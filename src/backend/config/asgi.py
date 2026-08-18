"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

django_application = get_asgi_application()

# Pay the URLconf/view import cost here rather than on the first request.
# See config/warmup.py -- this is what keeps Cloud Run cold starts short.
from config.warmup import warm_up  # noqa: E402 -- needs the app registry ready

warm_up()

# Wrapped ahead of Django itself (E01 Task 6, fix round 1): Django's
# ASGIHandler.read_body buffers the entire request body before any Django
# middleware runs -- including core.middleware.max_request_body_middleware --
# and before Django's own DATA_UPLOAD_MAX_MEMORY_SIZE check, which never trips
# for a request with no Content-Length. See core/asgi_body_limit.py for why
# the ceiling has to be enforced here, not only in Django middleware.
from core.asgi_body_limit import request_body_ceiling_asgi  # noqa: E402 -- needs settings ready

application = request_body_ceiling_asgi(django_application)
