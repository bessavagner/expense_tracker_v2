"""Eagerly resolve the URLconf at boot instead of on the first request.

Django loads the root URLconf lazily, on the first request that needs routing.
That import pulls in every view module -- and through the assistant views, the
LLM SDKs -- which is expensive.

On Cloud Run that laziness is actively harmful: the platform routes the first
request as soon as the container's port is open, so the import cost landed
*after* the startup probe had already passed. A measured cold start spent 5s
booting and then a further ~14s importing views while the user's request sat
waiting.

Calling ``warm_up()`` from ``config.asgi`` moves that work into container
startup, where Cloud Run's startup CPU boost applies and (under
``gunicorn --preload``) the port does not open until it is done.
"""

from django.urls import get_resolver


def warm_up() -> None:
    """Import every view module and build the reverse-URL cache."""
    resolver = get_resolver()
    # Importing the root URLconf cascades into every include()d module.
    _ = resolver.url_patterns
    # Populates the {% url %} reverse cache the first template render would
    # otherwise have to build.
    _ = resolver.reverse_dict
