from django.conf import settings
from django.contrib.auth.views import LoginView
from django.db import connection
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from core.security import client_ip, is_locked


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


class AppLoginView(LoginView):
    """The family's front door — the E05 login page ``core.auth_backends`` was
    written in anticipation of.

    Before this, ``LOGIN_URL`` pointed at ``/admin/login/``: the app opened on a
    Django admin screen, signing in landed on ``/admin/`` rather than the
    dashboard, and ``/login`` 404'd. ``/admin/login/`` still works; it is just
    the maintainer's door now, not everyone's.

    The lockout itself stays where E01 put it, in the authentication backend —
    this view only *explains* it. Naming the lockout leaks nothing, because a
    failed attempt is recorded for any username, existing or not, so the message
    does not tell an attacker that an account exists.
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lockout_minutes"] = settings.LOGIN_FAILURE_WINDOW_MINUTES
        # Preserved by hand: the form posts to an explicit action, so ?next=
        # would otherwise be dropped on a re-render after a failed attempt.
        context["next_url"] = self.get_redirect_url()
        context["locked_out"] = False
        return context

    def form_invalid(self, form):
        """Say *why* it failed when the reason is the lockout, not the password.

        The backend refuses a locked-out credential without checking it, so the
        form comes back with the ordinary "invalid credentials" error and the
        user has no way to tell a lockout from a typo — which is exactly the
        situation that makes someone keep trying.
        """
        response = super().form_invalid(form)
        username = form.data.get("username", "")
        if is_locked(username, client_ip(self.request)):
            response.context_data["locked_out"] = True
        return response


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
