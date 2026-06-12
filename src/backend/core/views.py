from django.db import connection
from django.http import JsonResponse
from django.views.generic import TemplateView


def health_check(request):
    """Health check endpoint for Cloud Run startup/liveness probes."""
    db_status = "ok"
    try:
        connection.ensure_connection()
    except Exception:
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    status_code = 200 if status == "ok" else 503

    return JsonResponse({"status": status, "database": db_status}, status=status_code)


class ManifestView(TemplateView):
    """Serve the web app manifest (template-rendered so {% static %} resolves
    hashed icon URLs under ManifestStaticFilesStorage in production)."""

    template_name = "manifest.webmanifest"
    content_type = "application/manifest+json"
