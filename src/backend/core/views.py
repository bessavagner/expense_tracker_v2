from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views import View
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


class ServiceWorkerView(TemplateView):
    """Serve the service worker from the site root so its scope is the whole app."""

    template_name = "sw.js"
    content_type = "application/javascript"

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Service-Worker-Allowed"] = "/"
        response["Cache-Control"] = "no-cache"
        return response


class OfflineView(TemplateView):
    """Offline fallback served by the service worker when a navigation fails.
    No DB, no auth — must render from cache."""

    template_name = "offline.html"


class AssetLinksView(View):
    """Digital Asset Links for the TWA (Android app) — served at
    /.well-known/assetlinks.json on the app host so Chrome verifies the app
    and opens it without the URL bar. Fingerprints come from settings."""

    def get(self, request, *args, **kwargs):
        statement = [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.TWA_PACKAGE_NAME,
                    "sha256_cert_fingerprints": settings.TWA_CERT_FINGERPRINTS,
                },
            }
        ]
        return JsonResponse(statement, safe=False)
