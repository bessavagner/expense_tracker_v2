from django.contrib import admin

from assistant.models import MemoryRule

# ChatMessage is deliberately not registered (E05 S05-5). It holds every
# user's raw conversation with the assistant — receipts, salaries, arguments
# about money — and an admin list view of it is a standing invitation to read
# them. E17 owns the deliberate, consented, logged way to look at a customer's
# account.


@admin.register(MemoryRule)
class MemoryRuleAdmin(admin.ModelAdmin):
    list_display = (
        "household",
        "created_by",
        "trigger",
        "field",
        "value",
        "confidence",
        "source",
        "last_used_at",
    )
    list_filter = ("source", "field")
    search_fields = ("trigger", "value")
    readonly_fields = ("created_at", "last_used_at")
