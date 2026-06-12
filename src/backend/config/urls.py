from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from core.views import ManifestView, ServiceWorkerView, health_check

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("manifest.webmanifest", ManifestView.as_view(), name="manifest"),
    path("logout/", LogoutView.as_view(next_page="/admin/login/"), name="logout"),
    path("admin/", admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("sw.js", ServiceWorkerView.as_view(), name="service-worker"),
    path("", include("finances.urls")),
]
