"""Local development settings.

Everything that is *only* safe on a laptop lives here, so the production module
never has to ask whether it is in production.
"""

from .base import *  # noqa: F403 — a settings module is a namespace, not an API

DEBUG = True

# Persistent connections: there is no serverless cold-start cost locally, and a
# reconnect per request makes the dev server noticeably slower.
DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
