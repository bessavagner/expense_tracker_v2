from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AdminAccessLog, CustomUser


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
