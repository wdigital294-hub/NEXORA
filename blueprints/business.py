"""Painel da empresa.

Regra de ouro: `current_business_id()` vem da sessão. Nenhuma query abaixo
aceita um business_id vindo do URL ou do formulário. Sempre que se lê ou
escreve um produto, categoria ou pedido, a cláusula WHERE inclui
`business_id = ?` com esse valor.
"""
from flask import (
    Blueprint, Response, abort, flash, g, redirect, render_template, request,
    url_for,
)

from db import execute, query
from security import business_required, current_business_id
from services import (
    delete_image, fmt_money, now_iso, qr_png_bytes, save_image,
    subscription_state, to_cents, unique_slug,
)

bp = Blueprint("business", __name__, url_prefix="/admin")

ESTADOS_PEDIDO = ["new", "confirmed", "preparing", "delivered", "cancelled"]


@bp.before_request
@business_required
def _guard():
    """Corre antes de qualquer rota deste blueprint.

    Se a assinatura não estiver activa, a empresa continua a poder entrar
    e ver os seus dados, mas só pode navegar para a área de assinatura.
    Nunca apagamos nada: os dados ficam intactos à espera do pagamento.
    """
    g.sub_state, g.sub_days = subscription_state(current_business_id())
    if g.sub_state != "active":
        permitidas = {"business.subscription", "business.dashboard", "business.send_proof"}
        if request.endpoint not in permitidas:
            flash("Active a assinatura para voltar a editar o catálogo.", "warning")
            return redirect(url_for("business.subscription"))


# --------------------------------------------------------------------------
# Painel
# --------------------------------------------------------------------------
@bp.route("/")
def dashboard():
    bid = current_business_id()
    stats = {
        "produtos": query(
            "SELECT COUNT(*) AS n FROM products WHERE business_id = ?", (bid,), one=True
        )["n"],
        "categorias": query(
            "SELECT COUNT(*) AS n FROM categories WHERE business_id = ?", (bid,), one=True
        )["n"],
        "pedidos_novos": query(
            "SELECT COUNT(*) AS n FROM orders WHERE business_id = ? AND status = 'new'",
            (bid,), one=True,
        )["n"],
        "pedidos_total": query(
            "SELECT COUNT(*) AS n FROM orders WHERE business_id = ?", (bid,), one=True
        )["n"],
    }
    receita = query(
        """SELECT COALESCE(SUM(total_cents), 0) AS t FROM orders
            WHERE business_id = ? AND status = 'delivered'""",
        (bid,), one=True,
    )["t"]
    recentes = query(
        "SELECT * FROM orders WHERE business_id = ? ORDER BY id DESC LIMIT 6", (bid,)
    )
    return render_template(
        "business/dashboard.html", stats=stats, receita=receita, recentes=recentes
    )


# --------------------------------------------------------------------------
# Categorias
# --------------------------------------------------------------------------
@bp.route("/categorias", methods=["GET", "POST"])
def categories():
    bid = current_business_id()
    if request.method == "POST":
        nome = (request.form.get("name") or "").strip()
        if not nome:
            flash("Dê um nome à categoria.", "error")
        else:
            execute(
                """INSERT INTO categories (business_id, name, description, position,
                                           created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (bid, nome, (request.form.get("description") or "").strip(),
                 int(request.form.get("position") or 0), now_iso()),
            )
            flash("Categoria criada.", "success")
        return redirect(url_for("business.categories"))

    cats = query(
        """SELECT c.*, (SELECT COUNT(*) FROM products p
                         WHERE p.category_id = c.id AND p.business_id = c.business_id)
                  AS n_produtos
             FROM categories c WHERE c.business_id = ?
            ORDER BY c.position, c.name""",
        (bid,),
    )
    return render_template("business/categories.html", categorias=cats)


@bp.route("/categorias/<int:cat_id>/editar", methods=["POST"])
def category_edit(cat_id):
    bid = current_business_id()
    cat = query(
        "SELECT * FROM categories WHERE id = ? AND business_id = ?", (cat_id, bid), one=True
    )
    if cat is None:
        abort(404)
    execute(
        "UPDATE categories SET name = ?, position = ? WHERE id = ? AND business_id = ?",
        ((request.form.get("name") or cat["name"]).strip(),
         int(request.form.get("position") or 0), cat_id, bid),
    )
    flash("Categoria actualizada.", "success")
    return redirect(url_for("business.categories"))


@bp.route("/categorias/<int:cat_id>/eliminar", methods=["POST"])
def category_delete(cat_id):
    bid = current_business_id()
    cat = query(
        "SELECT * FROM categories WHERE id = ? AND business_id = ?", (cat_id, bid), one=True
    )
    if cat is None:
        abort(404)
    # Os produtos não são apagados — ficam sem categoria, visíveis em "Outros".
    execute(
        "UPDATE products SET category_id = NULL WHERE category_id = ? AND business_id = ?",
        (cat_id, bid),
    )
    execute("DELETE FROM categories WHERE id = ? AND business_id = ?", (cat_id, bid))
    flash("Categoria eliminada. Os produtos ficaram sem categoria.", "success")
    return redirect(url_for("business.categories"))


# --------------------------------------------------------------------------
# Produtos
# --------------------------------------------------------------------------
@bp.route("/produtos")
def products():
    bid = current_business_id()
    termo = (request.args.get("q") or "").strip()
    if termo:
        prods = query(
            """SELECT p.*, c.name AS category_name FROM products p
                 LEFT JOIN categories c ON c.id = p.category_id
                WHERE p.business_id = ? AND p.name LIKE ?
                ORDER BY p.position, p.name""",
            (bid, f"%{termo}%"),
        )
    else:
        prods = query(
            """SELECT p.*, c.name AS category_name FROM products p
                 LEFT JOIN categories c ON c.id = p.category_id
                WHERE p.business_id = ? ORDER BY p.position, p.name""",
            (bid,),
        )
    return render_template("business/products.html", produtos=prods, termo=termo)


@bp.route("/produtos/novo", methods=["GET", "POST"])
@bp.route("/produtos/<int:prod_id>", methods=["GET", "POST"])
def product_form(prod_id=None):
    bid = current_business_id()
    produto = None
    if prod_id:
        produto = query(
            "SELECT * FROM products WHERE id = ? AND business_id = ?", (prod_id, bid),
            one=True,
        )
        if produto is None:
            abort(404)

    cats = query(
        "SELECT * FROM categories WHERE business_id = ? ORDER BY position, name", (bid,)
    )

    if request.method == "POST":
        nome = (request.form.get("name") or "").strip()
        if not nome:
            flash("O produto precisa de um nome.", "error")
            return render_template(
                "business/product_form.html", produto=produto, categorias=cats
            )

        preco = to_cents(request.form.get("price"))
        cat_id = request.form.get("category_id") or None
        if cat_id:
            # Impede associar o produto a uma categoria de outra empresa.
            valida = query(
                "SELECT id FROM categories WHERE id = ? AND business_id = ?",
                (cat_id, bid), one=True,
            )
            cat_id = valida["id"] if valida else None

        descricao = (request.form.get("description") or "").strip()
        disponivel = 1 if request.form.get("available") else 0
        posicao = int(request.form.get("position") or 0)

        imagem = produto["image"] if produto else None
        ficheiro = request.files.get("image")
        if ficheiro and ficheiro.filename:
            try:
                nova = save_image(ficheiro, bid, kind="produto")
                if nova:
                    if imagem:
                        delete_image(imagem)
                    imagem = nova
            except ValueError as e:
                flash(str(e), "error")
                return render_template(
                    "business/product_form.html", produto=produto, categorias=cats
                )

        if produto:
            execute(
                """UPDATE products SET category_id = ?, name = ?, description = ?,
                       price_cents = ?, image = ?, available = ?, position = ?,
                       updated_at = ?
                     WHERE id = ? AND business_id = ?""",
                (cat_id, nome, descricao, preco, imagem, disponivel, posicao,
                 now_iso(), prod_id, bid),
            )
            flash("Produto actualizado.", "success")
        else:
            limite = _limite_produtos(bid)
            if limite:
                flash(limite, "error")
                return redirect(url_for("business.subscription"))
            execute(
                """INSERT INTO products (business_id, category_id, name, description,
                        price_cents, image, available, position, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (bid, cat_id, nome, descricao, preco, imagem, disponivel, posicao,
                 now_iso(), now_iso()),
            )
            flash("Produto adicionado.", "success")
        return redirect(url_for("business.products"))

    return render_template("business/product_form.html", produto=produto, categorias=cats)


def _limite_produtos(bid):
    """Devolve uma mensagem se o plano já não permite mais produtos."""
    from services import current_subscription

    sub = current_subscription(bid)
    if not sub or not sub["max_products"]:
        return None
    n = query(
        "SELECT COUNT(*) AS n FROM products WHERE business_id = ?", (bid,), one=True
    )["n"]
    if n >= sub["max_products"]:
        return (
            f"O plano {sub['plan_name']} permite {sub['max_products']} produtos. "
            "Mude de plano para adicionar mais."
        )
    return None


@bp.route("/produtos/<int:prod_id>/disponibilidade", methods=["POST"])
def product_toggle(prod_id):
    bid = current_business_id()
    prod = query(
        "SELECT * FROM products WHERE id = ? AND business_id = ?", (prod_id, bid), one=True
    )
    if prod is None:
        abort(404)
    execute(
        "UPDATE products SET available = ?, updated_at = ? WHERE id = ? AND business_id = ?",
        (0 if prod["available"] else 1, now_iso(), prod_id, bid),
    )
    return redirect(request.referrer or url_for("business.products"))


@bp.route("/produtos/<int:prod_id>/eliminar", methods=["POST"])
def product_delete(prod_id):
    bid = current_business_id()
    prod = query(
        "SELECT * FROM products WHERE id = ? AND business_id = ?", (prod_id, bid), one=True
    )
    if prod is None:
        abort(404)
    delete_image(prod["image"])
    execute("DELETE FROM products WHERE id = ? AND business_id = ?", (prod_id, bid))
    flash("Produto eliminado.", "success")
    return redirect(url_for("business.products"))


# --------------------------------------------------------------------------
# Pedidos
# --------------------------------------------------------------------------
@bp.route("/pedidos")
def orders():
    bid = current_business_id()
    estado = request.args.get("estado") or ""
    if estado in ESTADOS_PEDIDO:
        pedidos = query(
            """SELECT * FROM orders WHERE business_id = ? AND status = ?
                ORDER BY id DESC LIMIT 200""",
            (bid, estado),
        )
    else:
        pedidos = query(
            "SELECT * FROM orders WHERE business_id = ? ORDER BY id DESC LIMIT 200", (bid,)
        )
    return render_template("business/orders.html", pedidos=pedidos, estado=estado)


@bp.route("/pedidos/<int:order_id>")
def order_detail(order_id):
    bid = current_business_id()
    pedido = query(
        "SELECT * FROM orders WHERE id = ? AND business_id = ?", (order_id, bid), one=True
    )
    if pedido is None:
        abort(404)
    itens = query("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
    return render_template("business/order_detail.html", pedido=pedido, itens=itens)


@bp.route("/pedidos/<int:order_id>/estado", methods=["POST"])
def order_status(order_id):
    bid = current_business_id()
    novo = request.form.get("status")
    if novo not in ESTADOS_PEDIDO:
        abort(400)
    pedido = query(
        "SELECT id FROM orders WHERE id = ? AND business_id = ?", (order_id, bid), one=True
    )
    if pedido is None:
        abort(404)
    execute(
        "UPDATE orders SET status = ? WHERE id = ? AND business_id = ?",
        (novo, order_id, bid),
    )
    flash("Estado do pedido actualizado.", "success")
    return redirect(request.referrer or url_for("business.orders"))


# --------------------------------------------------------------------------
# Definições
# --------------------------------------------------------------------------
@bp.route("/definicoes", methods=["GET", "POST"])
def settings():
    bid = current_business_id()
    biz = query("SELECT * FROM businesses WHERE id = ?", (bid,), one=True)

    if request.method == "POST":
        nome = (request.form.get("name") or biz["name"]).strip()
        novo_slug = request.form.get("slug", "").strip()
        slug = unique_slug(novo_slug or biz["slug"], exclude_id=bid)

        logo, cover = biz["logo"], biz["cover"]
        try:
            f_logo = request.files.get("logo")
            if f_logo and f_logo.filename:
                nova = save_image(f_logo, bid, kind="logo")
                if nova:
                    delete_image(logo)
                    logo = nova
            f_cover = request.files.get("cover")
            if f_cover and f_cover.filename:
                nova = save_image(f_cover, bid, kind="capa")
                if nova:
                    delete_image(cover)
                    cover = nova
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("business.settings"))

        execute(
            """UPDATE businesses SET name = ?, slug = ?, description = ?, phone = ?,
                   whatsapp = ?, address = ?, opening_hours = ?, logo = ?, cover = ?
                 WHERE id = ?""",
            (nome, slug, (request.form.get("description") or "").strip(),
             (request.form.get("phone") or "").strip(),
             (request.form.get("whatsapp") or "").strip(),
             (request.form.get("address") or "").strip(),
             (request.form.get("opening_hours") or "").strip(), logo, cover, bid),
        )
        if slug != biz["slug"]:
            flash(
                "O endereço do catálogo mudou. Gere e reimprima o QR Code — "
                "os códigos antigos deixam de funcionar.",
                "warning",
            )
        flash("Definições guardadas.", "success")
        return redirect(url_for("business.settings"))

    metodos = query(
        "SELECT * FROM payment_methods WHERE business_id = ? ORDER BY id", (bid,)
    )
    return render_template("business/settings.html", business=biz, metodos=metodos)


@bp.route("/pagamentos/metodos", methods=["POST"])
def payment_method_add():
    bid = current_business_id()
    nome = (request.form.get("name") or "").strip()
    if not nome:
        flash("Indique o nome do método de pagamento.", "error")
    else:
        execute(
            """INSERT INTO payment_methods (business_id, name, details, active)
               VALUES (?, ?, ?, 1)""",
            (bid, nome, (request.form.get("details") or "").strip()),
        )
        flash("Método de pagamento adicionado.", "success")
    return redirect(url_for("business.settings"))


@bp.route("/pagamentos/metodos/<int:pm_id>/eliminar", methods=["POST"])
def payment_method_delete(pm_id):
    bid = current_business_id()
    execute("DELETE FROM payment_methods WHERE id = ? AND business_id = ?", (pm_id, bid))
    flash("Método removido.", "success")
    return redirect(url_for("business.settings"))


# --------------------------------------------------------------------------
# QR Code
# --------------------------------------------------------------------------
@bp.route("/qrcode")
def qrcode_page():
    biz = g.business
    link = url_for("public.menu", slug=biz["slug"], _external=True)
    disponivel = qr_png_bytes("teste") is not None
    return render_template(
        "business/qrcode.html", business=biz, link=link, qr_disponivel=disponivel
    )


@bp.route("/qrcode.png")
def qrcode_png():
    biz = g.business
    link = url_for("public.menu", slug=biz["slug"], _external=True)
    png = qr_png_bytes(link)
    if png is None:
        abort(503, description="Instale a biblioteca qrcode: pip install qrcode[pil]")
    return Response(
        png,
        mimetype="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="qrcode-{biz["slug"]}.png"'
        },
    )


# --------------------------------------------------------------------------
# Assinatura
# --------------------------------------------------------------------------
@bp.route("/assinatura")
def subscription():
    from services import current_subscription

    bid = current_business_id()
    sub = current_subscription(bid)
    planos = query(
        "SELECT * FROM plans WHERE status = 'active' ORDER BY price_cents", ()
    )
    pagamentos = query(
        "SELECT * FROM payments WHERE business_id = ? ORDER BY id DESC LIMIT 20", (bid,)
    )
    dados_nexora = {
        r["key"]: r["value"]
        for r in query("SELECT * FROM platform_settings", ())
    }
    return render_template(
        "business/subscription.html", sub=sub, planos=planos, pagamentos=pagamentos,
        dados_nexora=dados_nexora, estado=g.sub_state, dias=g.sub_days,
    )


@bp.route("/assinatura/comprovativo", methods=["POST"])
def send_proof():
    """A empresa escolhe um plano e envia o comprovativo de transferência."""
    from services import current_subscription

    bid = current_business_id()
    plano_id = request.form.get("plan_id")
    plano = query(
        "SELECT * FROM plans WHERE id = ? AND status = 'active'", (plano_id,), one=True
    )
    if plano is None:
        flash("Escolha um plano válido.", "error")
        return redirect(url_for("business.subscription"))

    ficheiro = request.files.get("proof")
    caminho = None
    if ficheiro and ficheiro.filename:
        try:
            caminho = save_image(ficheiro, bid, kind="comprovativo")
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("business.subscription"))

    sub = current_subscription(bid)
    execute(
        """INSERT INTO payments (business_id, subscription_id, plan_id, amount_cents,
                method, proof_image, status, reference, paid_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (bid, sub["id"] if sub else None, plano["id"], plano["price_cents"],
         (request.form.get("method") or "").strip(), caminho,
         (request.form.get("reference") or "").strip(), now_iso(), now_iso()),
    )
    flash(
        "Comprovativo enviado. A NEXORA vai verificar e activar a sua assinatura.",
        "success",
    )
    return redirect(url_for("business.subscription"))
