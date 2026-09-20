"""Autenticação, autorização e isolamento entre empresas.

O ponto mais importante deste ficheiro é `current_business_id()`.
Nenhuma rota do painel da empresa deve receber o business_id do URL,
de um campo escondido ou de qualquer coisa enviada pelo navegador.
O business_id vem SEMPRE da sessão do utilizador autenticado.

É essa regra que impede que a Empresa A leia dados da Empresa B trocando
um número no endereço.
"""
import hmac
import secrets
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import query

ROLE_OWNER = "owner"
ROLE_BUSINESS = "business"


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
def login_user(user):
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["business_id"] = user["business_id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def logout_user():
    session.clear()


def load_logged_in_user():
    """Corre antes de cada request; popula g.user a partir da sessão."""
    uid = session.get("user_id")
    g.user = None
    if uid is None:
        return
    user = query(
        "SELECT * FROM users WHERE id = ? AND status = 'active'", (uid,), one=True
    )
    if user is None:
        session.clear()
        return
    g.user = user


def verify_password(user, password):
    return check_password_hash(user["password_hash"], password)


def hash_password(password):
    return generate_password_hash(password)


# --------------------------------------------------------------------------
# CSRF — implementação mínima, sem dependências externas
# --------------------------------------------------------------------------
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def check_csrf():
    """Chamado no before_request para todos os POST de área autenticada."""
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    real = session.get("csrf_token", "")
    if not real or not hmac.compare_digest(sent, real):
        abort(400, description="Sessão expirada. Recarregue a página e tente de novo.")


# --------------------------------------------------------------------------
# Decoradores de acesso
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Inicie sessão para continuar.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = g.get("user")
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        if user["role"] != ROLE_OWNER:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def business_required(view):
    """Exige um gestor de empresa com empresa associada e não bloqueada."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = g.get("user")
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        if user["role"] != ROLE_BUSINESS or not user["business_id"]:
            abort(403)
        biz = query(
            "SELECT * FROM businesses WHERE id = ?", (user["business_id"],), one=True
        )
        if biz is None:
            logout_user()
            abort(403)
        if biz["status"] == "blocked":
            abort(403, description="Esta conta está bloqueada. Contacte a NEXORA.")
        g.business = biz
        return view(*args, **kwargs)

    return wrapped


def current_business_id():
    """A única fonte de verdade para o tenant activo."""
    user = g.get("user")
    if not user or user["role"] != ROLE_BUSINESS:
        abort(403)
    return user["business_id"]
