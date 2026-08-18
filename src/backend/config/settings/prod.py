"""Production settings — loaded by Cloud Run, in production and in staging alike.

Every hardening line below is unconditional. Review finding **H7** was that they
all sat inside a single ``if not DEBUG:``, so a stray ``DEBUG=True`` in the
environment disabled SSL redirect, secure cookies, HSTS and nosniff at once and
``check --deploy`` reported nothing. There is no environment variable in this
file. If you are reading it, you are hardened.

Staging loads this module too (E16 D7). Staging exists to exercise what
production runs, and a staging module that relaxed anything would make staging a
worse predictor of production than having no staging at all. The differences
between the two environments are all data — database, ``ALLOWED_HOSTS``,
``SENTRY_ENVIRONMENT`` — and all already environment variables read by base.py.
"""

from .base import *  # noqa: F403 — a settings module is a namespace, not an API

DEBUG = False

# --- Transport and cookies ----------------------------------------------
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

# --- Serverless database behaviour --------------------------------------
# Cloud Run kills idle instances, so a pooled connection outlives nothing and a
# dead one is worse than none. Health-check before reuse.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# --- Static files -------------------------------------------------------
# WhiteNoise's manifest storage: hashed filenames, so a deploy cannot serve a
# stale cached asset. A missing manifest entry is a hard error at render time,
# which is why the Dockerfile's collectstatic must not be allowed to fail.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# --- Logging ------------------------------------------------------------
# Structured JSON on stdout: Cloud Run collects it and Cloud Logging parses each
# line into fields, which is what makes "every ERROR for this household" a query
# instead of a grep.
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
