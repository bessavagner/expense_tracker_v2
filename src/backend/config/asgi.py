"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

# Pay the URLconf/view import cost here rather than on the first request.
# See config/warmup.py -- this is what keeps Cloud Run cold starts short.
from config.warmup import warm_up  # noqa: E402 -- needs the app registry ready

warm_up()
