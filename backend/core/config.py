"""Hypertrophy-X merkezi konfigürasyon ve ortam değişkenleri."""
import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# .env yükleme
try:
    from dotenv import load_dotenv

    env_path = os.path.join(BACKEND_DIR, ".env")
    legacy_env_path = os.path.join(BACKEND_DIR, "admin.env")
    requested_env = os.getenv("APP_ENV", "").strip().lower()
    if os.path.isfile(env_path):
        load_dotenv(dotenv_path=env_path, override=False)
    elif requested_env != "production" and os.path.isfile(legacy_env_path):
        load_dotenv(dotenv_path=legacy_env_path, override=False)
except ImportError:
    pass

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
if APP_ENV not in {"development", "test", "production"}:
    raise RuntimeError("APP_ENV yalnızca development, test veya production olabilir.")
IS_PRODUCTION = APP_ENV == "production"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_BACKEND = "postgresql" if DATABASE_URL else "sqlite"
DB_PATH = os.getenv("DB_PATH", os.path.join(BACKEND_DIR, "hypertrophy.db"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD_PLAIN = os.getenv("ADMIN_PASSWORD", "")
ADMIN_PASSWORD_HASH = None

SECRET_KEY = os.getenv("JWT_SECRET", "").strip()
if not SECRET_KEY and not IS_PRODUCTION:
    SECRET_KEY = secrets.token_urlsafe(48)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 saat

CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*").strip()
CORS_ORIGINS = [origin.strip().rstrip("/") for origin in CORS_ORIGIN.split(",") if origin.strip()]
if not CORS_ORIGINS:
    CORS_ORIGINS = ["*"]

ENABLE_HSTS = os.getenv("ENABLE_HSTS", "false").strip().lower() in {"1", "true", "yes"}
LOGIN_RATE_LIMIT_MAX = max(1, int(os.getenv("LOGIN_RATE_LIMIT_MAX", "10")))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")))
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes"}
BCRYPT_ROUNDS = 12

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").replace(" ", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@hypertrophyx.com")).strip()

import logging
log = logging.getLogger("hypertrophy-x")

try:
    import psycopg
except ImportError:
    psycopg = None


def validate_runtime_configuration() -> None:
    if not IS_PRODUCTION:
        return

    errors = []
    insecure_secrets = {"", "change-me", "changeme", "secret", "jwt_secret", "example", "test"}
    insecure_admin_passwords = {
        "", "admin", "admin123", "password", "password123", "123456",
        "12345678", "değiştirilmek-zorunda", "degistirilmek-zorunda",
    }

    if len(SECRET_KEY) < 32 or SECRET_KEY.lower() in insecure_secrets:
        errors.append("JWT_SECRET production için en az 32 karakterlik rastgele bir değer olmalıdır.")
    if len(ADMIN_PASSWORD_PLAIN) < 12 or ADMIN_PASSWORD_PLAIN.strip().lower() in insecure_admin_passwords:
        errors.append("ADMIN_PASSWORD production için varsayılan olmayan, en az 12 karakterlik güçlü bir değer olmalıdır.")
    if "*" in CORS_ORIGINS:
        errors.append("CORS_ORIGIN=*, production ortamında kullanılamaz.")
    if any(not origin.startswith("https://") for origin in CORS_ORIGINS):
        errors.append("CORS_ORIGIN production ortamında yalnızca https:// ile başlayan alan adları içermelidir.")
    if not DATABASE_URL:
        errors.append("DATABASE_URL production ortamında PostgreSQL bağlantısı için zorunludur.")
    if DATABASE_URL and psycopg is None:
        errors.append("psycopg paketi yüklü değil; PostgreSQL bağlantısı kurulamaz.")

    if errors:
        raise RuntimeError("Güvensiz production yapılandırması: " + " ".join(errors))

