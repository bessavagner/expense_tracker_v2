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
    - No declared length (chunked transfer encoding): no buffering. Each
      message is forwarded to Django as it arrives; only a running byte
      total is kept. Once that total crosses the ceiling, a 413 is sent and
      Django is handed a synthetic ``http.disconnect`` instead of the real
      message -- Django's own ``read_body`` treats that exactly like a real
      client disconnect (closes its temp file and raises ``RequestAborted``),
      which ``ASGIHandler.handle`` catches and returns from without sending
      anything else. Memory cost is O(1) in body size and message count: at
      most one in-flight message plus a running integer, never a full copy
      of the body. (An earlier version of this wrapper buffered every
      message into a list before replaying it to Django -- correct in the
      bytes it counted, but each buffered message dict costs real memory
      independent of its payload size, so a client trickling the body in
      many tiny messages could grow that buffer far faster than the byte
      ceiling would suggest. Measured on that version: 100k 2-byte chunks
      totalling ~200 KB of real payload cost ~18 MiB of peak traced memory
      before this rewrite -- see ``core/tests/test_asgi_body_limit.py``'s
      ``TestChunkedBodyMemory``.)
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

        # Chunked: no declared length. Pass every message straight through,
        # counting bytes as they go -- see the docstring above for why this
        # replaced an earlier buffer-and-replay design.
        total = 0
        aborted = False

        async def counting_receive():
            nonlocal total, aborted
            if aborted:
                # Defensive: ASGIHandler.handle() never calls receive() again
                # once read_body has raised RequestAborted (it returns
                # immediately from the except clause), so this branch is not
                # expected to run in practice -- but if some other consumer
                # ever reuses this receive after an abort, keep reporting the
                # disconnect rather than resuming a request we already killed.
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.disconnect":
                return message
            total += len(message.get("body", b""))
            if total > limit:
                aborted = True
                await app.send_response(oversized_response(limit), send)
                return {"type": "http.disconnect"}
            return message

        await app(scope, counting_receive, send)

    return middleware
