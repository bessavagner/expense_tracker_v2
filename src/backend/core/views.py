from allauth.account.views import LoginView
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from core.auth_backends import identifier_from
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
    """The family's front door.

    Subclasses allauth's login view rather than Django's: from E05 the
    identifier is an email address, and allauth owns that resolution along
    with signup, verification and reset. What this class adds is the one thing
    allauth does not know about — E01's lockout, which lives in
    `core.auth_backends` and refuses a locked credential without checking it.

    Naming the lockout leaks nothing: a failed attempt is recorded for any
    identifier, existing or not, so the message cannot tell an attacker that an
    account exists.
    """

    template_name = "account/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lockout_minutes"] = settings.LOGIN_FAILURE_WINDOW_MINUTES
        # Preserved by hand: the form posts to an explicit action, so ?next=
        # would otherwise be dropped on a re-render after a failed attempt.
        context["next_url"] = self.get_success_url() if self.request.GET.get("next") else ""
        context.setdefault("locked_out", False)
        return context

    def form_invalid(self, form):
        """Say *why* it failed when the reason is the lockout, not the password.

        The backend refuses a locked-out credential without checking it, so the
        form comes back with the ordinary "invalid credentials" error and the
        user has no way to tell a lockout from a typo — which is exactly the
        situation that makes someone keep trying.
        """
        response = super().form_invalid(form)
        # Through `identifier_from` rather than read raw: allauth's field is
        # `login`, and the rows were written case-folded, so a submission with
        # a capital in it would not match its own failures and the page would
        # go back to blaming the password.
        identifier = identifier_from({"login": form.data.get("login", "")})
        if is_locked(identifier, client_ip(self.request)):
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
