"""ASGI-layer enforcement of the request-body ceiling.

Ahead of Django entirely: ``ASGIHandler.read_body`` (``django/core/handlers/asgi.py``)
reads the whole HTTP body into a ``SpooledTemporaryFile`` before any Django
middleware runs -- including ``core.middleware.max_request_body_middleware`` --
and before Django's own ``DATA_UPLOAD_MAX_MEMORY_SIZE`` check, which only fires
from a numeric ``Content-Length``: an absent header reads as
``int(None or 0) == 0``, so the check never trips for a chunked body. On this
container's RAM-backed filesystem that means an unbounded, unauthenticated POST
-- this wraps every request before routing or auth exist -- was bounded by
nothing at all before this module.

Registered in ``config/asgi.py``, wrapping the ``ASGIHandler`` instance itself
(not a generic ASGI3 callable) so the 413 it sends is encoded by Django's own
``send_response`` -- the exact same encoding the Django-level middleware's
``HttpResponse`` would get if it reached ``ASGIHandler.send_response`` normally.
Sharing ``core.middleware``'s settings lookups and message text means the two
enforcement layers use one limit and one wording, not two that can drift apart.
"""

from django.core.handlers.asgi import ASGIHandler

from core.middleware import declared_content_length, limit_for_path, oversized_response


def _decode_header(scope, name: bytes) -> str | None:
    """Fold repeated ASGI headers the same way Django's ``ASGIRequest`` does."""
    values = [value.decode("latin1") for key, value in scope.get("headers", []) if key == name]
    return ",".join(values) if values else None


def request_body_ceiling_asgi(app: ASGIHandler):
    """Wrap ``app`` so an oversized body never reaches Django's ``ASGIHandler``.

    Two enforcement paths, matching the two ways a body's size can be known
    ahead of time:

    - A declared ``Content-Length`` already over the ceiling: rejected with a
      413 without ever calling ``receive()`` -- nothing is read from the
      client at all.
    - No declared length (chunked transfer encoding): the body is read and
      buffered here, one ASGI message at a time, until either it completes
      under the ceiling (and is replayed to Django exactly as received, so
      Django's own ``read_body`` behaves identically to today) or the
      running total crosses the ceiling, at which point a 413 is sent and no
      further body is read. Buffering here is bounded by the ceiling itself
      -- the guarantee this module exists to provide -- unlike Django's own
      ``read_body``, which buffers without any such limit.
    """

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        limit = limit_for_path(scope["path"])
        declared = declared_content_length(_decode_header(scope, b"content-length"))

        if declared is not None:
            if declared > limit:
                await app.send_response(oversized_response(limit), send)
                return
            await app(scope, receive, send)
            return

        # Chunked: no declared length. Pre-read ourselves, bounded by the
        # ceiling, then replay the buffered messages to Django.
        buffered = []
        total = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] == "http.disconnect":
                break
            total += len(message.get("body", b""))
            if total > limit:
                await app.send_response(oversized_response(limit), send)
                return
            if not message.get("more_body", False):
                break

        buffered_iter = iter(buffered)

        async def replay_receive():
            try:
                return next(buffered_iter)
            except StopIteration:
                return await receive()

        await app(scope, replay_receive, send)

    return middleware
