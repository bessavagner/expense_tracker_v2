import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root (two levels above src/backend/config/)
load_dotenv(BASE_DIR.parent.parent / ".env")

# Environment
DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me-in-production")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "http://localhost:8000").split(",")

# TWA (Trusted Web Activity) — Digital Asset Links for the Android app.
# Fingerprint(s) come from the Bubblewrap signing key; set TWA_CERT_FINGERPRINT
# (comma-separated SHA-256, colon-delimited) in the environment once the key exists.
TWA_PACKAGE_NAME = os.environ.get("TWA_PACKAGE_NAME", "com.bessavagner.ledger")
TWA_CERT_FINGERPRINTS = [
    f.strip() for f in os.environ.get("TWA_CERT_FINGERPRINT", "").split(",") if f.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_tailwind_cli",
    "django_htmx",
    "rest_framework",
    # Local apps
    "core",
    "finances",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
# Served via ASGI in production (gunicorn + uvicorn worker) so the assistant's
# SSE streaming works correctly under async.
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "core.CustomUser"

# Database
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    DATABASES = {"default": dj_database_url.parse(_database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "expense_tracker"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

# Connection settings for serverless (Cloud Run)
if not DEBUG:
    DATABASES["default"]["CONN_MAX_AGE"] = 0
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# TailwindCSS v4 + DaisyUI
TAILWIND_CLI_USE_DAISY_UI = True
TAILWIND_CLI_SRC_CSS = "static/css/input.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"

# AI Assistant
LLM_MODEL = os.environ.get("LLM_MODEL", "openai:gpt-5.4-mini")
# Sistema de agentes (prompt 004): orquestrador/registrador usam um modelo leve e
# barato; analista/planejador usam um modelo mais capaz. Provider-agnóstico — por
# padrão herdam LLM_MODEL para não exigir configuração extra nem chaves novas.
LLM_ORCHESTRATOR_MODEL = os.environ.get("LLM_ORCHESTRATOR_MODEL", LLM_MODEL)
LLM_WORKER_MODEL = os.environ.get("LLM_WORKER_MODEL", LLM_MODEL)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
ASSISTANT_MAX_HISTORY = int(os.environ.get("ASSISTANT_MAX_HISTORY", "20"))
# Teto de requisições por delegação a um sub-agente (controle de custo multi-agente)
ASSISTANT_DELEGATION_REQUEST_LIMIT = int(
    os.environ.get("ASSISTANT_DELEGATION_REQUEST_LIMIT", "8")
)

# Multimodal (áudio + foto). Transcrição via API da OpenAI; sem chaves novas.
LLM_TRANSCRIBE_MODEL = os.environ.get("LLM_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
# Modelo usado para LER imagem (recibo). Default = modelo leve do registrador;
# escape hatch caso o modelo leve leia recibo mal.
LLM_VISION_MODEL = os.environ.get("LLM_VISION_MODEL", LLM_ORCHESTRATOR_MODEL)

ASSISTANT_MAX_IMAGE_MB = int(os.environ.get("ASSISTANT_MAX_IMAGE_MB", "10"))
ASSISTANT_MAX_AUDIO_MB = int(os.environ.get("ASSISTANT_MAX_AUDIO_MB", "25"))
ASSISTANT_ALLOWED_IMAGE_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
)
ASSISTANT_ALLOWED_AUDIO_TYPES = (
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
)

# Ensure OpenAI client can be instantiated (uses dummy key in dev/test; real key in prod)
if LLM_API_KEY and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = LLM_API_KEY
elif not os.environ.get("OPENAI_API_KEY"):
    os.environ.setdefault("OPENAI_API_KEY", "sk-not-set")

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Production security
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HTTP Strict Transport Security: tell browsers to only use HTTPS for a year,
    # including subdomains, and allow preload-list inclusion.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
