import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
if not DEBUG and SECRET_KEY == "development-only-change-me":
    raise ImproperlyConfigured(
        "Set a private SECRET_KEY before running with DEBUG=False."
    )
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cssms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "environment": "portal.jinja2.environment",
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "portal.context_processors.template_context",
            ],
        },
    },
]

WSGI_APPLICATION = "cssms.wsgi.application"

database_url = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
parsed_database_url = urlparse(database_url)
if parsed_database_url.scheme in {"mysql", "mysql+pymysql"}:
    import pymysql

    pymysql.install_as_MySQLdb()
    database_options = parse_qs(parsed_database_url.query)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": unquote(parsed_database_url.path.lstrip("/")),
            "USER": unquote(parsed_database_url.username or ""),
            "PASSWORD": unquote(parsed_database_url.password or ""),
            "HOST": parsed_database_url.hostname or "localhost",
            "PORT": parsed_database_url.port or "",
            "CONN_MAX_AGE": max(0, int(os.getenv("DB_CONN_MAX_AGE", "60"))),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": database_options.get("charset", ["utf8mb4"])[0],
            },
        }
    }
elif parsed_database_url.scheme == "sqlite":
    database_path = unquote(parsed_database_url.path.lstrip("/"))
    if not database_path:
        database_path = "db.sqlite3"
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / database_path,
        }
    }
else:
    raise ValueError("DATABASE_URL must use sqlite or mysql+pymysql.")

AUTH_USER_MODEL = "portal.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads")
MEDIA_URL = "uploads/"
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "false").lower() == "true"
)
SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "false").lower() == "true"
if os.getenv("TRUST_X_FORWARDED_PROTO", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MESSAGE_TAGS = {40: "danger"}
