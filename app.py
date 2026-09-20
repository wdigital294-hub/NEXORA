"""NEXORA — plataforma multiempresa de catálogos digitais.

Arranque:
    pip install -r requirements.txt
    python app.py init-db     # cria a base e os dados iniciais
    python app.py             # arranca em http://127.0.0.1:5000
"""
import os
import sys

from flask import Flask, g, render_template, request, session

import db as database
from config import Config
from security import (
    ROLE_BUSINESS, ROLE_OWNER, check_csrf, csrf_token, hash_password,
    load_logged_in_user,
)
from services import fmt_date, fmt_money, now_iso, to_cents


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)
    os.makedirs(app.config["UPLOAD_ROOT"], exist_ok=True)

    app.teardown_appcontext(database.close_db)

    # ---- Blueprints -----------------------------------------------------
    from blueprints.auth import bp as auth_bp
    from blueprints.business import bp as business_bp
    from blueprints.owner import bp as owner_bp
    from blueprints.public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(business_bp)
    app.register_blueprint(owner_bp)

    # ---- Hooks ----------------------------------------------------------
    @app.before_request
    def _before():
        load_logged_in_user()
        # CSRF em todos os POST de formulário de área autenticada.
        # O pedido público do catálogo é JSON de visitante anónimo e está
        # fora desta verificação por desenho: não há sessão a proteger.
        if request.method == "POST" and g.get("user") is not None:
            check_csrf()

    @app.context_processor
    def _inject():
        return {
            "csrf_token": csrf_token,
            "fmt_money": fmt_money,
            "fmt_date": fmt_date,
            "current_user": g.get("user"),
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_BUSINESS": ROLE_BUSINESS,
            "PLATFORM_NAME": app.config["PLATFORM_NAME"],
        }

    # ---- Erros ----------------------------------------------------------
    @app.errorhandler(400)
    def _400(e):
        return render_template("errors/error.html", codigo=400,
                               titulo="Pedido inválido",
                               detalhe=getattr(e, "description", "")), 400

    @app.errorhandler(403)
    def _403(e):
        return render_template("errors/error.html", codigo=403,
                               titulo="Sem acesso a esta área",
                               detalhe=getattr(e, "description", "")), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("errors/error.html", codigo=404,
                               titulo="Página não encontrada",
                               detalhe="Verifique o endereço ou o QR Code."), 404

    @app.errorhandler(413)
    def _413(e):
        return render_template("errors/error.html", codigo=413,
                               titulo="Ficheiro demasiado grande",
                               detalhe="O limite é 6 MB por imagem."), 413

    @app.errorhandler(500)
    def _500(e):
        return render_template("errors/error.html", codigo=500,
                               titulo="Erro no servidor",
                               detalhe="Tente de novo dentro de momentos."), 500

    # ---- CLI ------------------------------------------------------------
    @app.cli.command("init-db")
    def init_db_command():
        _init(app)

    return app


def _init(app):
    """Cria o esquema e os dados mínimos para a plataforma funcionar."""
    with app.app_context():
        database.init_db()
        conn = database.get_db()

        # Planos iniciais (o proprietário pode alterar preços no painel).
        if conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"] == 0:
            conn.executemany(
                """INSERT INTO plans (name, price_cents, duration_days, features,
                                      max_products, status)
                   VALUES (?, ?, ?, ?, ?, 'active')""",
                [
                    ("Básico", 500000, 30, "Catálogo digital\nQR Code\nPedidos por WhatsApp",
                     30),
                    ("Profissional", 1000000, 30,
                     "Tudo do Básico\nProdutos ilimitados\nMétodos de pagamento", 0),
                    ("Premium", 2000000, 30,
                     "Tudo do Profissional\nRelatórios\nApoio prioritário", 0),
                ],
            )

        # Conta do proprietário.
        if conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'owner'"
        ).fetchone()["n"] == 0:
            email = os.environ.get("NEXORA_OWNER_EMAIL", "admin@nexora.com")
            senha = os.environ.get("NEXORA_OWNER_PASSWORD", "nexora12345")
            conn.execute(
                """INSERT INTO users (business_id, name, email, password_hash, role,
                                      status, created_at)
                   VALUES (NULL, ?, ?, ?, 'owner', 'active', ?)""",
                ("Proprietário NEXORA", email, hash_password(senha), now_iso()),
            )
            print(f"  Conta do proprietário: {email} / {senha}")
            print("  Mude esta palavra-passe antes de pôr em produção.")

        if conn.execute(
            "SELECT COUNT(*) AS n FROM platform_settings"
        ).fetchone()["n"] == 0:
            conn.executemany(
                "INSERT INTO platform_settings (key, value) VALUES (?, ?)",
                [
                    ("payment_instructions",
                     "Transfira o valor do plano e envie o comprovativo por esta página."),
                    ("bank_name", "Banco — por configurar"),
                    ("bank_iban", "AO06 0000 0000 0000 0000 0000 0"),
                    ("bank_holder", "NEXORA"),
                    ("support_whatsapp", ""),
                ],
            )

        conn.commit()
        print("Base de dados pronta em:", app.config["DATABASE_PATH"])


app = create_app()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init-db":
        _init(app)
    elif len(sys.argv) > 1 and sys.argv[1] == "seed-demo":
        from seed import seed_demo

        _init(app)
        seed_demo(app)
    else:
        if not os.path.exists(app.config["DATABASE_PATH"]):
            _init(app)
        app.run(debug=True, host="0.0.0.0", port=5000)
