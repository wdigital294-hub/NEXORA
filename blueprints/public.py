"""Catálogo público. Não exige conta ao cliente final.

Toda a leitura é filtrada por business_id obtido a partir do slug do URL.
Um produto só entra na página se pertencer à empresa daquele slug — é o
que garante que o QR Code do Restaurante Kamba nunca mostra o Café Luanda.
"""
import os

from flask import (
    Blueprint, abort, current_app, jsonify, render_template, request,
    send_from_directory, url_for,
)

from db import execute, query
from services import (
    build_order_message, catalog_is_open, fmt_money, now_iso, order_code,
    subscription_state, whatsapp_url,
)

bp = Blueprint("public", __name__)


def _get_business_or_404(slug):
    biz = query("SELECT * FROM businesses WHERE slug = ?", (slug,), one=True)
    if biz is None:
        abort(404)
    return biz


@bp.route("/")
def landing():
    total = query("SELECT COUNT(*) AS n FROM businesses", (), one=True)["n"]
    return render_template("public/landing.html", total_empresas=total)


@bp.route("/menu/<slug>")
def menu(slug):
    biz = _get_business_or_404(slug)
    estado, _ = subscription_state(biz["id"])

    if not catalog_is_open(biz, estado):
        # 503: o recurso existe, está temporariamente indisponível.
        return render_template("public/unavailable.html", business=biz), 503

    categorias = query(
        """SELECT * FROM categories WHERE business_id = ?
           ORDER BY position, name""",
        (biz["id"],),
    )
    produtos = query(
        """SELECT * FROM products
            WHERE business_id = ? AND available = 1
            ORDER BY position, name""",
        (biz["id"],),
    )
    metodos = query(
        """SELECT * FROM payment_methods
            WHERE business_id = ? AND active = 1 ORDER BY id""",
        (biz["id"],),
    )

    por_categoria = {c["id"]: [] for c in categorias}
    sem_categoria = []
    for p in produtos:
        if p["category_id"] in por_categoria:
            por_categoria[p["category_id"]].append(p)
        else:
            sem_categoria.append(p)

    return render_template(
        "public/menu.html",
        business=biz,
        categorias=categorias,
        por_categoria=por_categoria,
        sem_categoria=sem_categoria,
        metodos=metodos,
        total_produtos=len(produtos),
    )


@bp.route("/menu/<slug>/pedido", methods=["POST"])
def create_order(slug):
    """Recebe o carrinho do navegador e cria o pedido.

    Nada de dinheiro vindo do cliente é aceite. O navegador envia apenas
    ids e quantidades; preços e total são lidos da base de dados e
    recalculados aqui. Caso contrário bastaria editar o JavaScript para
    comprar um hambúrguer por 1 Kz.
    """
    biz = _get_business_or_404(slug)
    estado, _ = subscription_state(biz["id"])
    if not catalog_is_open(biz, estado):
        return jsonify(ok=False, error="Este catálogo não está a aceitar pedidos."), 403

    dados = request.get_json(silent=True) or {}
    itens = dados.get("items") or []
    if not isinstance(itens, list) or not itens:
        return jsonify(ok=False, error="O carrinho está vazio."), 400
    if len(itens) > 60:
        return jsonify(ok=False, error="Pedido demasiado grande."), 400

    validados, total = [], 0
    for item in itens:
        try:
            pid = int(item.get("id"))
            qtd = int(item.get("qty"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Pedido inválido."), 400
        if qtd < 1 or qtd > 99:
            return jsonify(ok=False, error="Quantidade inválida."), 400

        # O filtro por business_id é o que impede pedir um produto de
        # outra empresa conhecendo apenas o seu id.
        prod = query(
            """SELECT * FROM products
                WHERE id = ? AND business_id = ? AND available = 1""",
            (pid, biz["id"]),
            one=True,
        )
        if prod is None:
            return jsonify(
                ok=False, error="Um dos produtos já não está disponível. Actualize a página."
            ), 409

        subtotal = prod["price_cents"] * qtd
        total += subtotal
        validados.append(
            {
                "product_id": prod["id"],
                "product_name": prod["name"],
                "quantity": qtd,
                "price_cents": prod["price_cents"],
                "subtotal_cents": subtotal,
            }
        )

    nome = (dados.get("customer_name") or "").strip()[:80]
    telefone = (dados.get("customer_phone") or "").strip()[:30]
    mesa = (dados.get("table_number") or "").strip()[:20]
    notas = (dados.get("notes") or "").strip()[:400]
    pagamento = (dados.get("payment_method") or "").strip()[:60]

    codigo = order_code()
    order_id = execute(
        """INSERT INTO orders (business_id, code, customer_name, customer_phone,
                               table_number, notes, payment_method, total_cents,
                               status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
        (biz["id"], codigo, nome, telefone, mesa, notas, pagamento, total, now_iso()),
    )
    for it in validados:
        execute(
            """INSERT INTO order_items (order_id, product_id, product_name,
                                        quantity, price_cents, subtotal_cents)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (order_id, it["product_id"], it["product_name"], it["quantity"],
             it["price_cents"], it["subtotal_cents"]),
        )

    pedido = query("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    mensagem = build_order_message(biz, pedido, validados)
    link = whatsapp_url(biz, mensagem)

    return jsonify(
        ok=True,
        code=codigo,
        total=fmt_money(total),
        whatsapp_url=link,
        message=mensagem if not link else None,
    )


@bp.route("/uploads/<path:rel_path>")
def uploaded_file(rel_path):
    """Serve imagens enviadas pelas empresas.

    Em produção isto deve ficar a cargo do Nginx/CDN; a rota existe para
    o sistema funcionar sem configuração extra em desenvolvimento.
    """
    if ".." in rel_path or rel_path.startswith("/"):
        abort(404)
    raiz = current_app.config["UPLOAD_ROOT"]
    caminho = os.path.join(raiz, rel_path)
    if not os.path.isfile(caminho):
        abort(404)
    pasta, ficheiro = os.path.split(caminho)
    return send_from_directory(pasta, ficheiro, max_age=60 * 60 * 24 * 30)


@bp.route("/manifest.webmanifest")
def manifest():
    return jsonify(
        {
            "name": "NEXORA",
            "short_name": "NEXORA",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#F4F7F8",
            "theme_color": "#0E6E5E",
            "icons": [
                {
                    "src": url_for("static", filename="img/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": url_for("static", filename="img/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                },
            ],
        }
    )
