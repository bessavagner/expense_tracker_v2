import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

from core.observability import init_sentry

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
    # Identity (E05, ADR-007). `allauth.mfa` is the second factor Task 15
    # requires of staff before admin will answer them.
    "allauth",
    "allauth.account",
    "allauth.mfa",
    # Local apps
    "core",
    "accounts",
    "finances",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Second on purpose: the ID must exist before anything can fail, so even a
    # 413 from the body-size guard immediately below carries one.
    "core.middleware.request_id_middleware",
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
    # Must sit after AuthenticationMiddleware: it reads request.user. Must sit
    # before the household resolver, because a request allauth rejects should
    # never have cost us a membership query.
    "allauth.account.middleware.AccountMiddleware",
    "accounts.middleware.active_household_middleware",
    # After the household resolver: the user and the household do not exist
    # until AuthenticationMiddleware and the resolver above have both run.
    "core.middleware.log_context_middleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Last on purpose, which is a security requirement and not a preference.
    # It reads request.user, so it has to follow AuthenticationMiddleware — but
    # being *innermost* is what makes its 404 indistinguishable from a routing
    # 404. A middleware's response travels back out through everything listed
    # above it and through nothing listed below; registered any higher, the
    # gate's 404 skipped XFrameOptionsMiddleware and came back without
    # `X-Frame-Options: DENY` while every genuine 404 carried it. One
    # `curl -sI` then confirmed the secret path.
    #
    # The cost is that a refused admin request has already run the household
    # resolver. That is one query on a path nobody legitimate takes.
    "core.admin_gate.admin_staff_only_middleware",
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
#
# Structured JSON on stdout: Cloud Run collects it and Cloud Logging parses each
# line into fields, which is what makes "every ERROR for this household" a query
# instead of a grep. Plain text in DEBUG, because JSON is unreadable in a
# terminal you are actively working in.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "core.log_formatting.JsonFormatter"},
        "plain": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain" if DEBUG else "json",
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# Error tracking (E06, ADR-005). No DSN -> no Sentry, which is the local and CI
# path: neither should transmit. The DSN comes from Secret Manager in production.
#
# init_sentry never raises. This runs at import time, so a DSN the SDK cannot
# parse would otherwise stop Django from starting -- one mistyped secret taking
# the service down is a far worse outcome than losing error tracking.
init_sentry(os.environ)

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

LOGIN_URL = "/accounts/login/"
# Signing in belongs on the dashboard, not on Django's admin index. Without
# this, Django's default sends people to /accounts/profile/, which does not
# exist here.
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"

# Brute-force protection lives in the authentication backend, not a view, so it
# applies to every door: the allauth login page and the admin's own form.
# Exactly one backend is registered on purpose — a second, lockout-free backend
# would silently answer the credential the first one refused.
AUTHENTICATION_BACKENDS = ["core.auth_backends.LockoutAuthenticationBackend"]
LOGIN_FAILURE_LIMIT = int(os.environ.get("LOGIN_FAILURE_LIMIT", "10"))
LOGIN_FAILURE_WINDOW_MINUTES = int(os.environ.get("LOGIN_FAILURE_WINDOW_MINUTES", "15"))

# --- Staff isolation (E05 S05-5) ----------------------------------------
# Admin holds every household's financial records and every user's raw chat,
# on a service deployed --allow-unauthenticated because the product needs to
# be. Two independent controls: an unguessable path so it is not enumerable,
# and `core.admin_gate` so guessing it correctly still yields a 404 to anyone
# who is not staff with a second factor.
#
# The path is an env var, never a literal in a committed file. The dev default
# is deliberately not "admin/" so that a missing env var is loud in tests
# rather than silently restoring the old front door.
ADMIN_URL_PATH = os.environ.get("ADMIN_URL_PATH", "gestao-dev/").strip("/") + "/"

# --- Identity (E05 / ADR-007) -------------------------------------------
# Email is the login identifier. `username` stays on CustomUser because ten
# models and every historical migration reference it, but allauth derives it
# from the email at signup and no screen ever shows it.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "email2*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
# Mandatory rather than optional: a half-verified account is a state every
# downstream feature would have to reason about, and E11's activation funnel
# would inherit the ambiguity. Decided with E11, per the epic's question 3.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Do not confirm or deny that an address has an account — applies to signup
# and to password reset alike.
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
# No custom adapter. Marking an invited address verified has to happen
# before `perform_login` decides whether the signup may proceed, and the
# adapter's send-the-mail hooks all run after that decision — see
# `accounts.signals.verify_invited_email`.
ACCOUNT_ADAPTER = "allauth.account.adapter.DefaultAccountAdapter"
# allauth ships its own login throttle (`10/m/ip, 5/300s/key`, cache-backed).
# It is switched off because E01's lockout already answers this question, and
# two throttles with different windows is worse than either alone: allauth's is
# the stricter of the two, so it would fire first, show its own generic error,
# and the login page's "muitas tentativas, espere N minutos" — the whole point
# of explaining a lockout rather than letting people keep guessing — would
# never be reached. E01's also covers Django's admin form, which allauth's
# documentation is explicit about not covering. Every OTHER allauth rate limit
# (password reset, email management, reauthentication) stays on: those guard
# endpoints the lockout does not.
ACCOUNT_RATE_LIMITS = {"login_failed": None}

# The second factor Task 15 demands of staff. Recovery codes are on by
# default and stay on: losing a phone must not lock the only operator out of
# their own admin.
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]

# --- Transactional email (E05 S05-2) ------------------------------------
# Resend over plain SMTP, deliberately: an API-key-in-a-header SDK would be a
# dependency and a code path, and Django already speaks SMTP. Switching
# provider is then an environment change, not a deploy.
#
# The absent-EMAIL_HOST branch is the important one. Django's default is an
# SMTP backend pointed at localhost:25 — mail vanishes with no exception, so a
# developer sees "e-mail enviado" and an empty inbox. Console backend instead.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
# Resend's SMTP username is the literal string "resend"; the password is the
# API key, which lives in Secret Manager and never in this repo.
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "resend")
EMAIL_HOST_PASSWORD = os.environ.get("RESEND_API_KEY", "")
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Ledger <nao-responda@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# AI Assistant
#
# These stay on `gpt-5.4`, and that is a measured decision rather than inertia.
# `gpt-5.6-terra` is a newer generation and cheaper per token ($2.00/$12.00 per
# Mtok vs $2.50/$15.00), and on that basis it was briefly made the default. The
# E08 harness then scored both against real receipts: terra cost **51% more per
# receipt**, because it consumes ~2.6x the input tokens on the same images, and
# it showed no quality gain — the score gap was narrower than either model's own
# run-to-run spread. See docs/superpowers/evidence/eval/baseline-2026-08-14.md.
#
# So: a cheaper per-token price is not a cheaper model, and the only way to know
# is to run the harness. Never edit these strings from memory — re-check the
# provider's live pricing page, re-run the eval, and update the `ModelPrice` rows
# in the same change, or every cost figure the product reports silently becomes
# fiction.
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

# Model tiers (E07 spec D2). ADVANCED and STANDARD deliberately ship pointing
# at the SAME model as today: PD-4 forbids a model swap without an E08
# evaluation score, and E09 owns making them different. Shipping them equal
# means the tier machinery is live and provably changes nothing yet.
#
# `or` rather than a get() default: `.env.example` ships these keys present but
# EMPTY, and `os.environ.get(key, default)` only falls back when the key is
# ABSENT. Copying the example file therefore pointed both paid tiers at "" —
# no model at all — which surfaces as a broken chat rather than as a config
# error. An empty value must mean "unset", not "the empty model".
LLM_TIER_ADVANCED = os.environ.get("LLM_TIER_ADVANCED") or LLM_ASSISTANT_MODEL
LLM_TIER_STANDARD = os.environ.get("LLM_TIER_STANDARD") or LLM_ASSISTANT_MODEL
# ESSENTIAL is where a household lands when its credits run out. Its baseline
# is a 429 and no answer at all, not gpt-5.4 — which is why naming a model here
# is not the unscored swap PD-4 forbids (E07 spec D2).
#
# Free OpenRouter model first, cheapest paid model as the fallback. Both were
# read off openrouter.ai's live catalogue on 2026-08-14 and priced in
# assistant/migrations/0019_seed_model_prices.py — never fill these from
# memory (E07 spec D3), and re-check the catalogue when you change them,
# because free endpoints are retired without notice.
#
# Both are chosen for TOOL support: the assistant is tool-heavy, and a free
# model that cannot call tools is broken rather than cheap.
#
# Named by default rather than left empty, so the "every configured model is
# priced" ratchet in test_pricing.py actually binds. Running without an
# OPENROUTER_API_KEY is handled at resolution time instead — see
# assistant.quota.model_for, which degrades to STANDARD rather than crashing.
LLM_TIER_ESSENTIAL = (
    os.environ.get("LLM_TIER_ESSENTIAL") or "openrouter:nvidia/nemotron-3-super-120b-a12b:free"
)
LLM_TIER_ESSENTIAL_FALLBACK = (
    os.environ.get("LLM_TIER_ESSENTIAL_FALLBACK") or "openrouter:qwen/qwen3.7-flash"
)
# Read once here rather than at each call so that a test can override it via
# the `settings` fixture. PydanticAI reads the variable from the environment
# itself; this copy exists only so `model_for` can tell whether the degrade
# path is actually usable.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# Abaixo deste nível de confiança (ou se a soma do recibo não fecha), o bot
# confirma campo a campo antes de gravar, em vez de auto-registrar.
ASSISTANT_RECEIPT_MIN_CONFIDENCE = float(os.environ.get("ASSISTANT_RECEIPT_MIN_CONFIDENCE", "0.6"))

# E08 evaluation fixtures. The golden dataset's ground truth is committed; the
# receipt PHOTOS are not — this repository is public and they are real household
# receipts carrying CNPJ, card last-4 digits and a purchase history. Point this
# at a private directory holding the images named in `assistant/eval/cases/*.json`.
# Unset is fine: those cases are skipped with a warning, never a failure.
EVAL_FIXTURES_DIR = os.environ.get("EVAL_FIXTURES_DIR", "")

# Agent tracing (E06, ADR-005). No token -> no Logfire, which is the local and
# CI path. The token comes from Secret Manager in production.
LOGFIRE_TOKEN = os.environ.get("LOGFIRE_TOKEN", "")
LOGFIRE_ENVIRONMENT = os.environ.get("LOGFIRE_ENVIRONMENT", "development")
# Full prompts and completions ARE captured — an explicit operator decision
# (2026-08-14, E06 open question 2), taken so that debugging a bad extraction
# does not require reproducing it from scratch. The flag exists so it can be
# turned off without a deploy; it defaults to on because that is the decision.
#
# CONSEQUENCE: Logfire then holds chat content and receipt descriptions, which
# makes Pydantic a data sub-processor of personal financial data. E13's privacy
# notice must name it.
LOGFIRE_CAPTURE_CONTENT = os.environ.get("LOGFIRE_CAPTURE_CONTENT", "1") == "1"
# Binary content is a SEPARATE decision and defaults OFF. The decision above was
# about text; this flag governs whether every receipt PHOTO is uploaded to a
# third party, which is a materially larger exposure and a large trace cost.
LOGFIRE_CAPTURE_BINARY = os.environ.get("LOGFIRE_CAPTURE_BINARY", "0") == "1"

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

# The abuse ceiling (E07 S07-3). These were E01's ASSISTANT_THROTTLE_* limits;
# they are renamed, not weakened, because their JOB changed. E01 used them as
# the quota. E07's quota is credits, and these are now purely the anti-abuse
# rail: the thing that keeps R0's release gate true — "an authenticated
# stranger cannot generate unbounded LLM spend" — now that the ESSENTIAL tier
# has no plan quota at all.
#
# Sizing is unchanged from E01: the single production account peaked at 5
# turns/day and 3 turns/hour, of which 3 were image turns. These sit ~20x above
# that peak, so ordinary daily use never meets them, while a runaway client loop
# or a stolen session is capped within the hour.
# Audio counts against the TEXT budget: transcription is ~100x cheaper per turn
# than a vision call, so only the image path needs its own ceiling.
#
# Read from settings on every call, so the `settings` fixture can override them
# in tests and an env change takes effect on the next deploy without a code
# change.
ASSISTANT_ABUSE_TEXT_PER_HOUR = int(os.environ.get("ASSISTANT_ABUSE_TEXT_PER_HOUR", "60"))
ASSISTANT_ABUSE_TEXT_PER_DAY = int(os.environ.get("ASSISTANT_ABUSE_TEXT_PER_DAY", "300"))
ASSISTANT_ABUSE_IMAGE_PER_HOUR = int(os.environ.get("ASSISTANT_ABUSE_IMAGE_PER_HOUR", "15"))
ASSISTANT_ABUSE_IMAGE_PER_DAY = int(os.environ.get("ASSISTANT_ABUSE_IMAGE_PER_DAY", "50"))

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
