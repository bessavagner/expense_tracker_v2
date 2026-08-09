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

# Stated rather than inherited. Lax is correct here — the React widget and the
# Android TWA are both same-origin — but a setting that is only correct by
# default breaks silently when the default changes.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

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
    # Required by pgvector's HnswIndex on MemoryEmbedding: the index class is
    # validated by a django.contrib.postgres check, which errors (postgres.E005)
    # if the app is absent.
    "django.contrib.postgres",
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
    # Before anything reads the body: an oversized upload must not reach the
    # parser, the session store, or Cloud Run's RAM-backed filesystem.
    "core.middleware.max_request_body_middleware",
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
    # O pooler de runtime da Supabase (porta 6543) é pgbouncer em transaction
    # mode, que roteia cada transação para um backend Postgres diferente.
    # 1) Server-side cursors (cursores nomeados, usados ao iterar querysets —
    #    ex.: os ModelChoiceField do form do cockpit) somem quando a próxima
    #    transação cai em outro backend: "InvalidCursorName: cursor ... does not
    #    exist" (500 intermitente sob concorrência). Django manda desligá-los
    #    em transaction pooling.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    # 2) psycopg3 auto-prepara statements; pelo mesmo motivo eles "somem" entre
    #    backends. Desligar prepared statements evita a variante desse erro.
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None
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

# Logging: por padrão o Django só manda erros 500 (django.request) para
# mail_admins quando DEBUG=False — sem backend de e-mail, o traceback some.
# Em Cloud Run, stdout/stderr é coletado, então enviamos para o console.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

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
# Pinned: without this, django-tailwind-cli resolves "latest" from GitHub at build
# time, so two machines on different days emit different CSS and the committed
# static/css/tailwind.css cannot be reproduced. 2.8.3 is the tailwind-cli-extra
# release bundling tailwindcss 4.2.2 — the version that built the committed file.
# Bumping this is a deliberate act: bump, rebuild with --force, eyeball the site,
# commit the new CSS in the same commit.
TAILWIND_CLI_VERSION = "2.8.3"
TAILWIND_CLI_USE_DAISY_UI = True
TAILWIND_CLI_SRC_CSS = "static/css/input.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"

# Brute-force protection lives in the authentication backend, not a view, so it
# keeps working when E05 replaces /admin/login/ with a real login page.
AUTHENTICATION_BACKENDS = ["core.auth_backends.LockoutModelBackend"]
LOGIN_FAILURE_LIMIT = int(os.environ.get("LOGIN_FAILURE_LIMIT", "10"))
LOGIN_FAILURE_WINDOW_MINUTES = int(os.environ.get("LOGIN_FAILURE_WINDOW_MINUTES", "15"))

# AI Assistant
LLM_MODEL = os.environ.get("LLM_MODEL", "openai:gpt-5.4")
# Agente único (prompt 009): um assistente forte com todas as ferramentas.
# Provider-agnóstico — por padrão herda LLM_MODEL; defina LLM_ASSISTANT_MODEL no
# ambiente (ex.: Cloud Run) para trocar o modelo sem mexer no código.
LLM_ASSISTANT_MODEL = os.environ.get("LLM_ASSISTANT_MODEL", "openai:gpt-5.4")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
ASSISTANT_MAX_HISTORY = int(os.environ.get("ASSISTANT_MAX_HISTORY", "20"))

# Multimodal (áudio + foto). Transcrição via API da OpenAI; sem chaves novas.
LLM_TRANSCRIBE_MODEL = os.environ.get("LLM_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
# Fallback de transcrição: whisper-1 é mais tolerante ao webm/opus de navegador
# (que o modelo primário às vezes rejeita como "corrupted or unsupported").
LLM_TRANSCRIBE_FALLBACK_MODEL = os.environ.get("LLM_TRANSCRIBE_FALLBACK_MODEL", "whisper-1")
# Modelo usado para LER imagem (recibo). Default = modelo de visão capaz (recibo
# térmico/girado/baixo contraste vai mal no modelo leve). Herda a mesma
# LLM_API_KEY OpenAI; override por env para trocar de provider/modelo.
LLM_VISION_MODEL = os.environ.get("LLM_VISION_MODEL", "openai:gpt-5.4")
# Abaixo deste nível de confiança (ou se a soma do recibo não fecha), o bot
# confirma campo a campo antes de gravar, em vez de auto-registrar.
ASSISTANT_RECEIPT_MIN_CONFIDENCE = float(os.environ.get("ASSISTANT_RECEIPT_MIN_CONFIDENCE", "0.6"))

# Projeção: mês de origem (YYYY-MM). Nada antes disso entra no acumulado — dados
# anteriores são migração/seed e não contam na conta. Default: nov/2025.
PROJECTION_ORIGIN_MONTH = os.environ.get("PROJECTION_ORIGIN_MONTH", "2025-11")

ASSISTANT_MAX_IMAGE_MB = int(os.environ.get("ASSISTANT_MAX_IMAGE_MB", "10"))
ASSISTANT_MAX_IMAGES = int(os.environ.get("ASSISTANT_MAX_IMAGES", "5"))
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

# Request body ceilings (E01). The container is 1 vCPU / 1Gi with a RAM-backed
# filesystem, so "written to a temp file" still costs memory.
# 60MB covers the widest legitimate chat payload — ASSISTANT_MAX_IMAGES (5) at
# ASSISTANT_MAX_IMAGE_MB (10) each, plus multipart overhead. Raise both together
# or this becomes the thing that rejects a valid upload.
MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(60 * 1024 * 1024)))
# The CSV importer never legitimately needs more than a few MB.
MAX_CSV_UPLOAD_BYTES = int(os.environ.get("MAX_CSV_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# Django's default is 100 files per request; nothing here wants more than the
# assistant's five images plus slack.
DATA_UPLOAD_MAX_NUMBER_FILES = 10

# Assistant throttling — a crude per-account ceiling, deliberately blunt (E01).
# Sized from measured usage: the single production account peaked at 5 turns/day
# and 3 turns/hour, of which 3 were image turns. These defaults sit ~20x above
# that peak, so ordinary daily use never meets them, while a runaway client loop
# or a stolen session is capped within the hour.
# Audio counts against the TEXT budget: transcription is ~100x cheaper per turn
# than a vision call, so only the image path needs its own ceiling.
ASSISTANT_THROTTLE_TEXT_PER_HOUR = int(os.environ.get("ASSISTANT_THROTTLE_TEXT_PER_HOUR", "60"))
ASSISTANT_THROTTLE_TEXT_PER_DAY = int(os.environ.get("ASSISTANT_THROTTLE_TEXT_PER_DAY", "300"))
ASSISTANT_THROTTLE_IMAGE_PER_HOUR = int(os.environ.get("ASSISTANT_THROTTLE_IMAGE_PER_HOUR", "15"))
ASSISTANT_THROTTLE_IMAGE_PER_DAY = int(os.environ.get("ASSISTANT_THROTTLE_IMAGE_PER_DAY", "50"))

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
