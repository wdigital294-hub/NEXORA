"""Painel do proprietário da NEXORA.

Separado do painel das empresas em URL, template e decorador. O papel
'owner' não tem business_id: ele não é um tenant, está acima deles.
"""
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for
)

from db import execute, query
from security import ROLE_BUSINESS, hash_password, owner_required
from services import (
    fmt_money, now_iso, renew_subscription, subscription_state, to_cents,
    unique_slug,
)

bp = Blueprint("owner", __name__, url_prefix="/plataforma")


@bp.before_request
@owner_required
def _guard():
    pass


@bp.route("/")
def dashboard():
    total = query("SELECT COUNT(*) AS n FROM businesses", (), one=True)["n"]
    empresas = query("SELECT * FROM businesses ORDER BY id DESC", ())

    activas = suspensas = expiradas = pendentes = 0
    for e in empresas:
        estado, _ = subscription_state(e["id"])
        if e["status"] != "active":
            suspensas += 1
        elif estado == "active":
            activas += 1
        elif estado == "expired":
            expiradas += 1
        else:
            pendentes += 1

    receita = query(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM payments WHERE status = 'approved'",
        (), one=True,
    )["t"]
    por_verificar = query(
        "SELECT COUNT(*) AS n FROM payments WHERE status = 'pending'", (), one=True
    )["n"]
    ultimos = query(
        """SELECT p.*, b.name AS business_name FROM payments p
             JOIN businesses b ON b.id = p.business_id
            ORDER BY p.id DESC LIMIT 8""",
        (),
    )
    return render_template(
        "owner/dashboard.html",
        total=total, activas=activas, suspensas=suspensas, expiradas=expiradas,
        pendentes=pendentes, receita=receita, por_verificar=por_verificar,
        ultimos=ultimos,
    )


# --------------------------------------------------------------------------
# Empresas
# --------------------------------------------------------------------------
@bp.route("/empresas")
def businesses():
    termo = (request.args.get("q") or "").strip()
    if termo:
        linhas = query(
            "SELECT * FROM businesses WHERE name LIKE ? OR slug LIKE ? ORDER BY name",
            (f"%{termo}%", f"%{termo}%"),
        )
    else:
        linhas = query("SELECT * FROM businesses ORDER BY name", ())

    dados = []
    for b in linhas:
        estado, dias = subscription_state(b["id"])
        sub = query(
            """SELECT s.*, p.name AS plan_name FROM subscriptions s
                 LEFT JOIN plans p ON p.id = s.plan_id
                WHERE s.business_id = ? ORDER BY s.id DESC LIMIT 1""",
            (b["id"],), one=True,
        )
        dados.append({"b": b, "estado": estado, "dias": dias, "sub": sub})
    return render_template("owner/businesses.html", dados=dados, termo=termo)


@bp.route("/empresas/nova", methods=["GET", "POST"])
def business_new():
    planos = query("SELECT * FROM plans WHERE status = 'active' ORDER BY price_cents", ())
    if request.method == "POST":
        nome = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if len(nome) < 2 or "@" not in email or len(password) < 8:
            flash("Preencha nome, email válido e palavra-passe com 8+ caracteres.", "error")
            return render_template("owner/business_form.html", planos=planos)
        if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            flash("Já existe uma conta com este email.", "error")
            return render_template("owner/business_form.html", planos=planos)

        slug = unique_slug(request.form.get("slug") or nome)
        bid = execute(
            """INSERT INTO businesses (name, slug, whatsapp, phone, status, created_at)
               VALUES (?, ?, ?, ?, 'active', ?)""",
            (nome, slug, (request.form.get("whatsapp") or "").strip(),
             (request.form.get("phone") or "").strip(), now_iso()),
        )
        execute(
            """INSERT INTO users (business_id, name, email, password_hash, role,
                                  status, created_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (bid, (request.form.get("manager") or nome).strip(), email,
             hash_password(password), ROLE_BUSINESS, now_iso()),
        )
        execute(
            """INSERT INTO categories (business_id, name, position, created_at)
               VALUES (?, 'Geral', 0, ?)""",
            (bid, now_iso()),
        )
        plano_id = request.form.get("plan_id")
        if plano_id:
            plano = query("SELECT * FROM plans WHERE id = ?", (plano_id,), one=True)
            if plano:
                renew_subscription(bid, plano["id"], plano["duration_days"])
        else:
            execute(
                """INSERT INTO subscriptions (business_id, status, created_at)
                   VALUES (?, 'pending', ?)""",
                (bid, now_iso()),
            )
        flash(f"Empresa criada. Catálogo em /menu/{slug}", "success")
        return redirect(url_for("owner.businesses"))

    return render_template("owner/business_form.html", planos=planos)


@bp.route("/empresas/<int:bid>/estado", methods=["POST"])
def business_status(bid):
    novo = request.form.get("status")
    if novo not in ("active", "suspended", "blocked"):
        abort(400)
    biz = query("SELECT id FROM businesses WHERE id = ?", (bid,), one=True)
    if biz is None:
        abort(404)
    execute("UPDATE businesses SET status = ? WHERE id = ?", (novo, bid))
    flash("Estado da empresa actualizado.", "success")
    return redirect(request.referrer or url_for("owner.businesses"))


@bp.route("/empresas/<int:bid>")
def business_detail(bid):
    biz = query("SELECT * FROM businesses WHERE id = ?", (bid,), one=True)
    if biz is None:
        abort(404)
    estado, dias = subscription_state(bid)
    subs = query(
        """SELECT s.*, p.name AS plan_name FROM subscriptions s
             LEFT JOIN plans p ON p.id = s.plan_id
            WHERE s.business_id = ? ORDER BY s.id DESC""",
        (bid,),
    )
    pagamentos = query(
        "SELECT * FROM payments WHERE business_id = ? ORDER BY id DESC", (bid,)
    )
    gestores = query(
        "SELECT id, name, email, status FROM users WHERE business_id = ?", (bid,)
    )
    n_produtos = query(
        "SELECT COUNT(*) AS n FROM products WHERE business_id = ?", (bid,), one=True
    )["n"]
    n_pedidos = query(
        "SELECT COUNT(*) AS n FROM orders WHERE business_id = ?", (bid,), one=True
    )["n"]
    planos = query("SELECT * FROM plans WHERE status = 'active' ORDER BY price_cents", ())
    return render_template(
        "owner/business_detail.html", b=biz, estado=estado, dias=dias, subs=subs,
        pagamentos=pagamentos, gestores=gestores, n_produtos=n_produtos,
        n_pedidos=n_pedidos, planos=planos,
    )


@bp.route("/empresas/<int:bid>/plano", methods=["POST"])
def business_set_plan(bid):
    """Activa ou renova manualmente, sem passar por comprovativo."""
    plano = query(
        "SELECT * FROM plans WHERE id = ?", (request.form.get("plan_id"),), one=True
    )
    if plano is None:
        abort(400)
    fim = renew_subscription(bid, plano["id"], plano["duration_days"])
    flash(f"Assinatura activa até {fim.strftime('%d/%m/%Y')}.", "success")
    return redirect(url_for("owner.business_detail", bid=bid))


# --------------------------------------------------------------------------
# Pagamentos
# --------------------------------------------------------------------------
@bp.route("/pagamentos")
def payments():
    estado = request.args.get("estado") or "pending"
    if estado not in ("pending", "approved", "rejected", "todos"):
        estado = "pending"
    if estado == "todos":
        linhas = query(
            """SELECT p.*, b.name AS business_name, pl.name AS plan_name
                 FROM payments p
                 JOIN businesses b ON b.id = p.business_id
                 LEFT JOIN plans pl ON pl.id = p.plan_id
                ORDER BY p.id DESC LIMIT 200""",
            (),
        )
    else:
        linhas = query(
            """SELECT p.*, b.name AS business_name, pl.name AS plan_name
                 FROM payments p
                 JOIN businesses b ON b.id = p.business_id
                 LEFT JOIN plans pl ON pl.id = p.plan_id
                WHERE p.status = ? ORDER BY p.id DESC LIMIT 200""",
            (estado,),
        )
    return render_template("owner/payments.html", pagamentos=linhas, estado=estado)


@bp.route("/pagamentos/<int:pid>/decidir", methods=["POST"])
def payment_decide(pid):
    pag = query("SELECT * FROM payments WHERE id = ?", (pid,), one=True)
    if pag is None:
        abort(404)
    if pag["status"] != "pending":
        flash("Este pagamento já foi decidido.", "warning")
        return redirect(url_for("owner.payments"))

    decisao = request.form.get("decisao")
    nota = (request.form.get("notes") or "").strip()

    if decisao == "aprovar":
        plano = query("SELECT * FROM plans WHERE id = ?", (pag["plan_id"],), one=True)
        dias = plano["duration_days"] if plano else 30
        fim = renew_subscription(pag["business_id"], pag["plan_id"], dias)
        execute(
            """UPDATE payments SET status = 'approved', verified_at = ?, notes = ?
                 WHERE id = ?""",
            (now_iso(), nota, pid),
        )
        flash(f"Pagamento aprovado. Assinatura activa até {fim.strftime('%d/%m/%Y')}.",
              "success")
    elif decisao == "rejeitar":
        execute(
            """UPDATE payments SET status = 'rejected', verified_at = ?, notes = ?
                 WHERE id = ?""",
            (now_iso(), nota, pid),
        )
        flash("Pagamento rejeitado.", "success")
    else:
        abort(400)
    return redirect(request.referrer or url_for("owner.payments"))


# --------------------------------------------------------------------------
# Planos
# --------------------------------------------------------------------------
@bp.route("/planos", methods=["GET", "POST"])
def plans():
    if request.method == "POST":
        nome = (request.form.get("name") or "").strip()
        if not nome:
            flash("Dê um nome ao plano.", "error")
        else:
            execute(
                """INSERT INTO plans (name, price_cents, duration_days, features,
                                      max_products, status)
                   VALUES (?, ?, ?, ?, ?, 'active')""",
                (nome, to_cents(request.form.get("price")),
                 int(request.form.get("duration_days") or 30),
                 (request.form.get("features") or "").strip(),
                 int(request.form.get("max_products") or 0)),
            )
            flash("Plano criado.", "success")
        return redirect(url_for("owner.plans"))

    linhas = query("SELECT * FROM plans ORDER BY price_cents", ())
    return render_template("owner/plans.html", planos=linhas)


@bp.route("/planos/<int:plan_id>/editar", methods=["POST"])
def plan_edit(plan_id):
    plano = query("SELECT * FROM plans WHERE id = ?", (plan_id,), one=True)
    if plano is None:
        abort(404)
    execute(
        """UPDATE plans SET name = ?, price_cents = ?, duration_days = ?,
               features = ?, max_products = ?, status = ? WHERE id = ?""",
        ((request.form.get("name") or plano["name"]).strip(),
         to_cents(request.form.get("price")),
         int(request.form.get("duration_days") or 30),
         (request.form.get("features") or "").strip(),
         int(request.form.get("max_products") or 0),
         request.form.get("status") or "active", plan_id),
    )
    flash("Plano actualizado.", "success")
    return redirect(url_for("owner.plans"))


# --------------------------------------------------------------------------
# Definições da plataforma e relatórios
# --------------------------------------------------------------------------
@bp.route("/definicoes", methods=["GET", "POST"])
def settings():
    chaves = ["payment_instructions", "bank_name", "bank_iban", "bank_holder",
              "support_whatsapp"]
    if request.method == "POST":
        for chave in chaves:
            valor = (request.form.get(chave) or "").strip()
            execute(
                """INSERT INTO platform_settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (chave, valor),
            )
        flash("Definições da plataforma guardadas.", "success")
        return redirect(url_for("owner.settings"))

    valores = {r["key"]: r["value"] for r in query("SELECT * FROM platform_settings", ())}
    return render_template("owner/settings.html", valores=valores, chaves=chaves)


@bp.route("/relatorios")
def reports():
    por_mes = query(
        """SELECT substr(verified_at, 1, 7) AS mes,
                  COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total
             FROM payments WHERE status = 'approved' AND verified_at IS NOT NULL
            GROUP BY mes ORDER BY mes DESC LIMIT 12""",
        (),
    )
    por_empresa = query(
        """SELECT b.name, COALESCE(SUM(p.amount_cents), 0) AS total, COUNT(p.id) AS n
             FROM businesses b
             LEFT JOIN payments p ON p.business_id = b.id AND p.status = 'approved'
            GROUP BY b.id ORDER BY total DESC""",
        (),
    )
    pedidos = query(
        """SELECT b.name, COUNT(o.id) AS n,
                  COALESCE(SUM(o.total_cents), 0) AS volume
             FROM businesses b LEFT JOIN orders o ON o.business_id = b.id
            GROUP BY b.id ORDER BY n DESC""",
        (),
    )
    return render_template(
        "owner/reports.html", por_mes=por_mes, por_empresa=por_empresa, pedidos=pedidos
    )
