"""Configuração da NEXORA.

Tudo o que muda entre ambientes (dev / produção) vive aqui.
Nunca colocar segredos reais neste ficheiro: use variáveis de ambiente.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # --- Segurança -------------------------------------------------------
    # Em produção é OBRIGATÓRIO definir NEXORA_SECRET_KEY no ambiente.
    SECRET_KEY = os.environ.get("NEXORA_SECRET_KEY", "dev-only-mudar-em-producao")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Ligar a True assim que o domínio tiver HTTPS.
    SESSION_COOKIE_SECURE = os.environ.get("NEXORA_HTTPS", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 horas

    # --- Base de dados ---------------------------------------------------
    DATABASE_PATH = os.environ.get(
        "NEXORA_DB", os.path.join(BASE_DIR, "database", "nexora.db")
    )

    # --- Uploads ---------------------------------------------------------
    UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads", "businesses")
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6 MB por request
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    IMAGE_MAX_SIDE = 1400  # px — imagens maiores são redimensionadas
    THUMB_MAX_SIDE = 600

    # --- Plataforma ------------------------------------------------------
    PLATFORM_NAME = "NEXORA"
    CURRENCY = "Kz"
    # Dias de tolerância depois do vencimento antes de bloquear o catálogo.
    GRACE_DAYS = 3
