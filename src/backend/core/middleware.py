"""Reject oversized request bodies before Django parses them.

``DATA_UPLOAD_MAX_MEMORY_SIZE`` deliberately excludes file fields, so it caps
neither a five-image chat upload nor a large CSV. Cloud Run backs the container
filesystem with its 1Gi of RAM, which means the importer's
``tempfile.NamedTemporaryFile`` spends memory even though the code reads as
"write to disk". Checking the declared ``Content-Length`` stops the payload at
the door -- for requests this middleware actually gets to see.

This is the *second* line of defence, not the first. In production
(``gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker``,
see ``Dockerfile``), Django's ``ASGIHandler.read_body``
(``django/core/handlers/asgi.py``) reads the entire body into a
``SpooledTemporaryFile`` *before any Django middleware runs* -- including this
one -- and before Django's own ``DATA_UPLOAD_MAX_MEMORY_SIZE`` check, which
never trips for a request with no ``Content-Length`` (an absent header reads as
``int(None or 0) == 0``). ``core.asgi_body_limit`` wraps the ASGI application
itself, ahead of Django entirely, to close that gap; see its module docstring.
This middleware still earns its place below that: for a request whose declared
``Content-Length`` is already too large, it rejects before Django's multipart
parser or the importer's own temp-file copy ever run -- work the ASGI-layer
check alone does not save, since it only guards the *body read*, not the
parsing of a request its own ceiling let through.
"""

import sys

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import sync_and_async_middleware

IMPORT_PATH_PREFIX = "/import/"


def limit_for_path(path: str) -> int:
    """The byte ceiling that applies to ``path``.

    Shared with ``core.asgi_body_limit`` so the ASGI-layer guard (which runs
    earlier, before Django's ASGIHandler ever buffers a byte) and this
    Django-layer guard can never drift into two different limits.
    """
    return (
        settings.MAX_CSV_UPLOAD_BYTES
        if path.startswith(IMPORT_PATH_PREFIX)
        else settings.MAX_REQUEST_BODY_BYTES
    )


def oversized_response(limit: int) -> HttpResponse:
    """The pt-BR 413 body. Shared with ``core.asgi_body_limit`` for the same
    reason as ``limit_for_path`` -- one wording, not two that can drift apart.
    """
    return HttpResponse(
        f"Requisição grande demais (máximo {limit // (1024 * 1024)} MB).",
        status=413,
    )


def declared_content_length(raw: str | None) -> int | None:
    """Parse a (possibly comma-folded) ``Content-Length`` header value.

    Returns ``None`` when the header is genuinely absent -- a legitimate
    state for a chunked request, left for the caller to handle by counting
    bytes as they actually arrive (see ``core.asgi_body_limit``).

    ASGI folds repeated headers into one comma-joined value (see
    ``ASGIRequest.__init__`` in ``django/core/handlers/asgi.py``); a request
    that declares conflicting lengths is read as the *largest* of them --
    trusting the smaller number would let a client understate its own
    upload, and the cost of over-counting here is nothing worse than an
    early, correct rejection.

    A header that is present but not a valid, non-negative integer is
    treated as *oversized* rather than as absent: a garbled or negative
    ``Content-Length`` must not read as "no limit applies", which is what
    treating it as ``0`` (the previous behaviour) effectively did.
    """
    if raw is None or raw == "":
        return None
    try:
        parts = [int(part.strip()) for part in raw.split(",")]
    except ValueError:
        return sys.maxsize
    if any(part < 0 for part in parts):
        return sys.maxsize
    return max(parts)


def _too_large(request) -> HttpResponse | None:
    """A 413 when the declared body exceeds this path's ceiling, else ``None``.

    A missing ``Content-Length`` is not treated as oversized *here* -- it is
    the case ``core.asgi_body_limit`` exists to cover, by counting bytes as
    they stream in ahead of this middleware ever running.
    """
    length = declared_content_length(request.META.get("CONTENT_LENGTH"))
    if length is None:
        return None
    limit = limit_for_path(request.path)
    if length <= limit:
        return None
    return oversized_response(limit)


@sync_and_async_middleware
def max_request_body_middleware(get_response):
    """Dual-mode so the ASGI path stays async — chat streams through here."""
    if iscoroutinefunction(get_response):

        async def middleware(request):
            blocked = _too_large(request)
            return blocked if blocked is not None else await get_response(request)

    else:

        def middleware(request):
            blocked = _too_large(request)
            return blocked if blocked is not None else get_response(request)

    return middleware
