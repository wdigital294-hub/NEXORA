"""Regras de negócio que não pertencem a nenhuma rota em particular."""
import io
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import current_app

from db import execute, query

# --------------------------------------------------------------------------
# Tempo
# --------------------------------------------------------------------------
def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today():
    return datetime.now(timezone.utc).date()


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def add_days(days):
    return (today() + timedelta(days=days)).isoformat()


def fmt_date(value):
    d = parse_date(value)
    return d.strftime("%d/%m/%Y") if d else "—"


# --------------------------------------------------------------------------
# Dinheiro — sempre inteiros em cêntimos
# --------------------------------------------------------------------------
def to_cents(value):
    """Aceita '5.000', '5000,50', '5 000' e devolve cêntimos."""
    if value is None:
        return 0
    s = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        return 0
    # Se tiver vírgula, assume-se decimal europeu e ponto como milhar.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        inteiro, dec = s.split(".")
        if len(dec) == 3:  # "5.000" é cinco mil, não cinco
            s = inteiro + dec
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return 0


def fmt_money(cents, currency=None):
    cents = int(cents or 0)
    currency = currency or current_app.config["CURRENCY"]
    inteiro, resto = divmod(abs(cents), 100)
    milhares = f"{inteiro:,}".replace(",", ".")
    txt = milhares if resto == 0 else f"{milhares},{resto:02d}"
    sinal = "-" if cents < 0 else ""
    return f"{sinal}{txt} {currency}"


# --------------------------------------------------------------------------
# Slugs
# --------------------------------------------------------------------------
def slugify(text):
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text) or "empresa"


def unique_slug(base, exclude_id=None):
    slug = slugify(base)
    candidate, n = slug, 1
    while True:
        if exclude_id:
            row = query(
                "SELECT id FROM businesses WHERE slug = ? AND id != ?",
                (candidate, exclude_id),
                one=True,
            )
        else:
            row = query("SELECT id FROM businesses WHERE slug = ?", (candidate,), one=True)
        if row is None:
            return candidate
        n += 1
        candidate = f"{slug}-{n}"


# --------------------------------------------------------------------------
# Uploads de imagem
# --------------------------------------------------------------------------
def _business_dir(business_id):
    path = os.path.join(current_app.config["UPLOAD_ROOT"], str(business_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_image(file_storage, business_id, kind="product"):
    """Valida, redimensiona e grava. Devolve o caminho relativo ou None.

    Validação em três camadas, porque a extensão do ficheiro mente:
      1. extensão na whitelist;
      2. o Pillow tem de conseguir abrir e verificar o conteúdo;
      3. o ficheiro é reescrito pelo Pillow, o que remove qualquer
         payload escondido (um .jpg com PHP lá dentro não sobrevive).
    O nome final é aleatório, nunca o nome enviado pelo utilizador.
    """
    if not file_storage or not file_storage.filename:
        return None

    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        raise ValueError("Formato não aceite. Use JPG, PNG ou WEBP.")

    raw = file_storage.read()
    if len(raw) > current_app.config["MAX_CONTENT_LENGTH"]:
        raise ValueError("Imagem demasiado grande. Máximo 6 MB.")

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        raise ValueError("Pillow não está instalado. Corra: pip install Pillow")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # deteta ficheiros corrompidos ou falsos
        img = Image.open(io.BytesIO(raw))  # verify() invalida o objeto
    except Exception:
        raise ValueError("Não foi possível ler esta imagem.")

    if img.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    else:
        img = img.convert("RGB")

    lado = current_app.config["IMAGE_MAX_SIDE" if kind != "thumb" else "THUMB_MAX_SIDE"]
    img.thumbnail((lado, lado))

    nome = f"{kind}-{secrets.token_hex(8)}.jpg"
    destino = os.path.join(_business_dir(business_id), nome)
    img.save(destino, "JPEG", quality=82, optimize=True)
    return f"{business_id}/{nome}"


def delete_image(rel_path):
    if not rel_path:
        return
    # Impede travessia de caminho (../../etc/passwd).
    if ".." in rel_path or rel_path.startswith("/"):
        return
    caminho = os.path.join(current_app.config["UPLOAD_ROOT"], rel_path)
    if os.path.isfile(caminho):
        try:
            os.remove(caminho)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Assinaturas
# --------------------------------------------------------------------------
def current_subscription(business_id):
    return query(
        """SELECT s.*, p.name AS plan_name, p.price_cents AS plan_price,
                  p.max_products
             FROM subscriptions s
             LEFT JOIN plans p ON p.id = s.plan_id
            WHERE s.business_id = ?
            ORDER BY s.id DESC LIMIT 1""",
        (business_id,),
        one=True,
    )


def subscription_state(business_id):
    """Estado efetivo, já considerando a data de vencimento.

    Devolve (estado, dias_restantes). O estado guardado na tabela pode estar
    desatualizado — um registo 'active' com end_date no passado está, na
    prática, expirado. Calculamos em vez de confiar na coluna.
    """
    sub = current_subscription(business_id)
    if sub is None:
        return "pending", None
    if sub["status"] in ("suspended", "cancelled", "pending"):
        return sub["status"], None
    fim = parse_date(sub["end_date"])
    if fim is None:
        return sub["status"], None
    restantes = (fim - today()).days
    if restantes < 0:
        return "expired", restantes
    return "active", restantes


def catalog_is_open(business, state):
    """O catálogo público fica visível?"""
    if business["status"] in ("blocked", "suspended"):
        return False
    return state == "active"


def renew_subscription(business_id, plan_id, duration_days):
    """Renova a partir do fim actual se ainda válido, senão a partir de hoje.

    Renovar cedo não deve custar dias ao cliente.
    """
    sub = current_subscription(business_id)
    inicio = today()
    if sub and sub["end_date"]:
        fim_atual = parse_date(sub["end_date"])
        if fim_atual and fim_atual > inicio:
            inicio = fim_atual
    fim = inicio + timedelta(days=duration_days)
    execute(
        """INSERT INTO subscriptions
               (business_id, plan_id, status, start_date, end_date, created_at)
           VALUES (?, ?, 'active', ?, ?, ?)""",
        (business_id, plan_id, today().isoformat(), fim.isoformat(), now_iso()),
    )
    return fim


# --------------------------------------------------------------------------
# WhatsApp
# --------------------------------------------------------------------------
def normalize_whatsapp(numero):
    """Deixa apenas dígitos. Sem '+', que a API wa.me não aceita."""
    if not numero:
        return ""
    return re.sub(r"\D", "", str(numero))


def build_order_message(business, order, items):
    linhas = [f"*Pedido {order['code']} — {business['name']}*", ""]
    if order["customer_name"]:
        linhas.append(f"Cliente: {order['customer_name']}")
    if order["table_number"]:
        linhas.append(f"Mesa: {order['table_number']}")
    if order["customer_phone"]:
        linhas.append(f"Telefone: {order['customer_phone']}")
    linhas.append("")
    for it in items:
        linhas.append(
            f"{it['quantity']}x {it['product_name']} — {fmt_money(it['subtotal_cents'])}"
        )
    linhas.append("")
    linhas.append(f"*TOTAL: {fmt_money(order['total_cents'])}*")
    if order["payment_method"]:
        linhas.append(f"Pagamento: {order['payment_method']}")
    if order["notes"]:
        linhas.append("")
        linhas.append(f"Observação: {order['notes']}")
    return "\n".join(linhas)


def whatsapp_url(business, message):
    numero = normalize_whatsapp(business["whatsapp"])
    if not numero:
        return None
    return f"https://wa.me/{numero}?text={quote(message)}"


def order_code():
    return datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(2).upper()


# --------------------------------------------------------------------------
# QR Code
# --------------------------------------------------------------------------
def qr_png_bytes(url):
    """Devolve PNG do QR Code, ou None se a biblioteca não estiver instalada."""
    try:
        import qrcode
        from qrcode.image.pil import PilImage
    except ImportError:
        return None
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage, fill_color="#17222B", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
