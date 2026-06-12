from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from core.views import health_check

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("logout/", LogoutView.as_view(next_page="/admin/login/"), name="logout"),
    path("admin/", admin.site.urls),
    path("api/assistant/", include("assistant.urls")),
    path("", include("finances.urls")),
]
