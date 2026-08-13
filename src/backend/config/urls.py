from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import (
    AppLoginView,
    AssetLinksView,
    ManifestView,
    OfflineView,
    ServiceWorkerView,
    health_check,
)

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
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
    path("admin/", admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("sw.js", ServiceWorkerView.as_view(), name="service-worker"),
    path("offline/", OfflineView.as_view(), name="offline"),
    path("", include("finances.urls")),
]
