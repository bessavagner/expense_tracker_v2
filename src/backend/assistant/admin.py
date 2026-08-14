from django.contrib import admin

from assistant.models import CreditPrice, MemoryRule, ModelPrice

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


@admin.register(ModelPrice)
class ModelPriceAdmin(admin.ModelAdmin):
    list_display = (
        "model_name",
        "input_per_mtok",
        "output_per_mtok",
        "effective_from",
        "checked_on",
    )
    list_filter = ("model_name",)
    search_fields = ("model_name",)


@admin.register(CreditPrice)
class CreditPriceAdmin(admin.ModelAdmin):
    """The (tier x kind) grid. Editable in the list so the beta's economics can
    be retuned from real cost data without a deploy (E07 spec D4)."""

    list_display = ("tier", "kind", "credits")
    list_editable = ("credits",)
    list_filter = ("tier", "kind")
