from django.contrib import admin
from django.urls import include, path

from core.views import health_check

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("", include("finances.urls")),
]
