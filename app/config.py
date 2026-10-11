import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # If SECRET_KEY is not set, a random key is used: sessions/carts reset on every restart.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    INSTANCE_DIR = str(BASE_DIR / "instance")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///" + str(BASE_DIR / "instance" / "store.db")

    STORE_NAME = os.environ.get("STORE_NAME", "Threadline")
    CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "R")
    SHIPPING_FLAT = int(os.environ.get("SHIPPING_FLAT", "8000"))
    FREE_SHIPPING_OVER = int(os.environ.get("FREE_SHIPPING_OVER", "100000"))
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:5000").rstrip("/")

    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024

    ENABLE_COD = _flag("ENABLE_COD")
    EFT_DETAILS = os.environ.get("EFT_DETAILS", "")
    PAYFAST_MERCHANT_ID = os.environ.get("PAYFAST_MERCHANT_ID", "")
    PAYFAST_MERCHANT_KEY = os.environ.get("PAYFAST_MERCHANT_KEY", "")
    PAYFAST_PASSPHRASE = os.environ.get("PAYFAST_PASSPHRASE", "")
    PAYFAST_SANDBOX = _flag("PAYFAST_SANDBOX", "1")
    WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
