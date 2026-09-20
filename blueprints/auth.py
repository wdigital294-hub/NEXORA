"""Login, logout e auto-registo de empresas."""
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)

from db import execute, query
from security import (
    ROLE_BUSINESS, ROLE_OWNER, hash_password, login_user, logout_user,
    verify_password,
)
from services import now_iso, today, unique_slug

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("auth.home_for_role"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

        # Mensagem única para email errado e password errada: dizer qual dos
        # dois falhou permite enumerar contas existentes.
        if user is None or not verify_password(user, password):
            flash("Email ou palavra-passe incorrectos.", "error")
            return render_template("auth/login.html", email=email), 401

        if user["status"] != "active":
            flash("Esta conta está desactivada. Contacte a NEXORA.", "error")
            return render_template("auth/login.html", email=email), 403

        login_user(user)
        destino = request.args.get("next")
        # Só aceitamos redireccionamentos internos.
        if destino and destino.startswith("/") and not destino.startswith("//"):
            return redirect(destino)
        return redirect(url_for("auth.home_for_role"))

    return render_template("auth/login.html", email="")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("Sessão terminada.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/ir")
def home_for_role():
    user = g.get("user")
    if user is None:
        return redirect(url_for("auth.login"))
    if user["role"] == ROLE_OWNER:
        return redirect(url_for("owner.dashboard"))
    return redirect(url_for("business.dashboard"))


@bp.route("/registar", methods=["GET", "POST"])
def register():
    """Auto-registo: cria a empresa e o seu primeiro gestor.

    A conta nasce com assinatura pendente — o catálogo público só abre
    depois de o proprietário da NEXORA aprovar um pagamento.
    """
    planos = query(
        "SELECT * FROM plans WHERE status = 'active' ORDER BY price_cents", ()
    )

    if request.method == "POST":
        nome_empresa = (request.form.get("business_name") or "").strip()
        nome = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        whatsapp = (request.form.get("whatsapp") or "").strip()
        plano_id = request.form.get("plan_id") or None

        erros = []
        if len(nome_empresa) < 2:
            erros.append("Indique o nome do negócio.")
        if len(nome) < 2:
            erros.append("Indique o seu nome.")
        if "@" not in email or "." not in email:
            erros.append("Email inválido.")
        if len(password) < 8:
            erros.append("A palavra-passe precisa de pelo menos 8 caracteres.")
        if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            erros.append("Já existe uma conta com este email.")

        if erros:
            for e in erros:
                flash(e, "error")
            return render_template("auth/register.html", planos=planos, form=request.form)

        slug = unique_slug(nome_empresa)
        business_id = execute(
            """INSERT INTO businesses (name, slug, whatsapp, status, created_at)
               VALUES (?, ?, ?, 'active', ?)""",
            (nome_empresa, slug, whatsapp, now_iso()),
        )
        execute(
            """INSERT INTO users (business_id, name, email, password_hash, role,
                                  status, created_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (business_id, nome, email, hash_password(password), ROLE_BUSINESS, now_iso()),
        )
        execute(
            """INSERT INTO subscriptions (business_id, plan_id, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (business_id, plano_id, now_iso()),
        )
        # Categoria inicial para o painel não abrir vazio e sem saída.
        execute(
            """INSERT INTO categories (business_id, name, position, created_at)
               VALUES (?, 'Geral', 0, ?)""",
            (business_id, now_iso()),
        )

        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        login_user(user)
        flash("Conta criada. Active a assinatura para publicar o catálogo.", "success")
        return redirect(url_for("business.subscription"))

    return render_template("auth/register.html", planos=planos, form={})
