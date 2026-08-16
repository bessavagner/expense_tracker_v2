from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.feedback import FeedbackView
from core.views import (
    AppLoginView,
    AssetLinksView,
    ManifestView,
    OfflineView,
    ServiceWorkerView,
    health_check,
)
from core.views_metrics import MetricsDashboardView

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    # Staff-only product metrics (E14 S14-4). Deliberately NOT under
    # `ADMIN_URL_PATH`: that path is a secret whose 404 must stay
    # indistinguishable from a wrong guess (`core.admin_gate`), and this page is
    # gated by identity instead. Staff are already exempt from the onboarding
    # redirect by identity, so this needs no `_ONBOARDING_EXEMPT_PREFIXES` entry.
    path("metricas/", MetricsDashboardView.as_view(), name="metrics_dashboard"),
    # Beta feedback (E14 S14-5). The one place the product stores user-authored
    # text on purpose — see `core.models.Feedback`.
    path("feedback/", FeedbackView.as_view(), name="feedback_submit"),
    # Cloud Tasks dispatch (E10). Public by necessity — the service is deployed
    # --allow-unauthenticated — so `core.tasks.auth` verifies the OIDC token
    # in-app on every request.
    path("tasks/", include("core.tasks.urls")),
    path("manifest.webmanifest", ManifestView.as_view(), name="manifest"),
    path(".well-known/assetlinks.json", AssetLinksView.as_view(), name="assetlinks"),
    # The installed Android TWA and the PWA shortcut both point at these two
    # paths. They are permanent redirects rather than deletions because there
    # is no way to push a URL change to a phone that already has the app.
    # Note a 301 cannot carry a POST body, so `/logout/` lands on allauth's
    # confirmation page rather than ending the session; the navbar posts to
    # `account_logout` directly, which does.
    path(
        "login/",
        RedirectView.as_view(url="/accounts/login/", permanent=True, query_string=True),
        name="login",
    ),
    path(
        "logout/",
        RedirectView.as_view(url="/accounts/logout/", permanent=True),
        name="logout",
    ),
    # Declared *before* allauth's include so this one wins the `account_login`
    # name — reverse() resolves to the first pattern registered under a name,
    # and resolution matches in order too, so allauth's own view never gets a
    # chance.
    path("accounts/login/", AppLoginView.as_view(), name="account_login"),
    path("accounts/", include("allauth.urls")),
    # Not "admin/". The path is an environment variable and the middleware
    # above 404s anyone who is not staff with a second factor — two
    # independent controls, because this service is public by necessity.
    #
    # The unslashed form is registered on purpose, and it is a security
    # control rather than a convenience. CommonMiddleware's APPEND_SLASH
    # rewrites a 404 into a 301 whenever the unslashed URL does *not* resolve
    # and the slashed one does — so `/gestao-xxxx` answered 301 while every
    # wrong guess answered 404, confirming the secret path to anyone who tried
    # it. Registering it makes it resolve, which is precisely what stops
    # APPEND_SLASH touching it; the gate above still 404s the request first
    # for anyone who is not staff, and this redirect only ever runs for
    # someone already allowed in.
    path(
        settings.ADMIN_URL_PATH.rstrip("/"),
        RedirectView.as_view(url="/" + settings.ADMIN_URL_PATH, permanent=False),
    ),
    path(settings.ADMIN_URL_PATH, admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("sw.js", ServiceWorkerView.as_view(), name="service-worker"),
    path("offline/", OfflineView.as_view(), name="offline"),
    path("casa/", include("accounts.urls")),
    path("", include("finances.urls")),
]
