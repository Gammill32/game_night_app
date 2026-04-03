import os
from datetime import timedelta

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Base configuration."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-default")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-Mail Configuration
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")

    # Flask Session Configuration
    # NOTE: SESSION_TYPE defaults to "filesystem", which is not shared across
    # Gunicorn workers. For multi-worker production deployments set
    # SESSION_TYPE=redis and configure SESSION_REDIS.
    SESSION_TYPE = os.getenv("SESSION_TYPE", "filesystem")
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    SESSION_USE_SIGNER = True
    SESSION_COOKIE_PATH = "/"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_DEBUG", "0") != "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Flask Debug Settings
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # Timezone Configuration
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Chicago")
