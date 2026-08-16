from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AdminAccessLog, CustomUser, Feedback, ProductEvent, TaskRun


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    pass


@admin.register(AdminAccessLog)
class AdminAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "method", "path", "ip")
    list_filter = ("method", "created_at")
    search_fields = ("path", "actor__email")
    readonly_fields = ("actor", "path", "method", "ip", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        """An audit log a staff member can delete is not an audit log."""
        return False


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    """Where a dead-lettered task becomes visible.

    Read-only throughout: the way to act on a failed task is `replay_task`,
    which leaves the failure on the record. Editing `status` by hand would
    erase the evidence and enqueue nothing.
    """

    list_display = ("name", "status", "attempts", "max_attempts", "created_at")
    list_filter = ("status", "name")
    search_fields = ("id", "idempotency_key", "request_id")
    readonly_fields = (
        "id",
        "name",
        "idempotency_key",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "request_id",
        "last_error",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProductEvent)
class ProductEventAdmin(admin.ModelAdmin):
    """Read-only: these rows are measurements. An editable measurement is a lie."""

    list_display = ("name", "household", "user", "created_at")
    list_filter = ("name", "once")
    date_hierarchy = "created_at"
    readonly_fields = ("household", "name", "user", "once", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    """Read-only, newest first: this list IS the reading queue.

    Read-only because what someone wrote is a record of what they said, and an
    editable record of what someone said is worth nothing. The runbook says the
    queue is reviewed weekly — the confirmation the user sees promises it will
    be read, so the process has to keep that promise.
    """

    list_display = ("created_at", "household", "user", "message")
    list_filter = ("created_at",)
    search_fields = ("message",)
    date_hierarchy = "created_at"
    readonly_fields = ("household", "user", "message", "context", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
