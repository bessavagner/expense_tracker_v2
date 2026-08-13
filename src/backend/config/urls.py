from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

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
    path("login/", AppLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="/login/"), name="logout"),
    # E05: allauth owns signup, verification, password reset and TOTP. Task 6
    # hands it the login page too; until then this coexists with /login/.
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("sw.js", ServiceWorkerView.as_view(), name="service-worker"),
    path("offline/", OfflineView.as_view(), name="offline"),
    path("", include("finances.urls")),
]
