"""Reject oversized request bodies before Django parses them.

``DATA_UPLOAD_MAX_MEMORY_SIZE`` deliberately excludes file fields, so it caps
neither a five-image chat upload nor a large CSV. Cloud Run backs the container
filesystem with its 1Gi of RAM, which means the importer's
``tempfile.NamedTemporaryFile`` spends memory even though the code reads as
"write to disk". Checking the declared ``Content-Length`` stops the payload at
the door.
"""

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import sync_and_async_middleware

IMPORT_PATH_PREFIX = "/import/"


def _too_large(request) -> HttpResponse | None:
    """A 413 when the declared body exceeds this path's ceiling, else ``None``.

    A missing or unparseable ``Content-Length`` is not treated as an attack: the
    ceiling is a cheap first line, and Django's own parser limits still apply
    behind it.
    """
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return None
    limit = (
        settings.MAX_CSV_UPLOAD_BYTES
        if request.path.startswith(IMPORT_PATH_PREFIX)
        else settings.MAX_REQUEST_BODY_BYTES
    )
    if length <= limit:
        return None
    return HttpResponse(
        f"Requisição grande demais (máximo {limit // (1024 * 1024)} MB).",
        status=413,
    )


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
