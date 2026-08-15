from django.urls import path

from core.tasks.views import task_dispatch_view

app_name = "tasks"

urlpatterns = [
    # The task name is a path segment because that is what Cloud Tasks routes
    # on: one queue can drive many handlers by URL alone, with no per-handler
    # queue to provision.
    path("<str:name>/", task_dispatch_view, name="dispatch"),
]
