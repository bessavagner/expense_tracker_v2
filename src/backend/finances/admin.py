from django.contrib import admin

from finances.models import (
    Budget,
    Category,
    Entry,
    ImportJob,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "household", "created_by")
    list_filter = ("household",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "budget_ceiling", "is_system", "household", "created_by")
    list_filter = ("is_system", "household")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "closing_day", "is_active", "household", "created_by")
    list_filter = ("type", "is_active", "household")
    search_fields = ("name",)


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "month", "is_recurring", "household", "created_by")
    list_filter = ("is_recurring", "household", "month")
    search_fields = ("name",)
    ordering = ("-month",)


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "description",
        "amount",
        "category",
        "payment_method",
        "entry_type",
        "billing_month",
    )
    list_filter = ("entry_type", "category", "payment_method", "billing_month")
    search_fields = ("description",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "total_amount",
        "num_installments",
        "installment_amount",
        "payment_method",
        "date",
    )
    list_filter = ("payment_method", "category")
    search_fields = ("description",)
    ordering = ("-date",)


@admin.register(SystemicExpense)
class SystemicExpenseAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_amount", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    """Read-only on purpose: this is the record of what an import did, and an
    editable count is a record that can be made to lie."""

    list_display = (
        "id",
        "household",
        "status",
        "import_type",
        "created_count",
        "error_count",
        "created_at",
    )
    list_filter = ("status", "import_type")
    search_fields = ("id", "original_filename")
    readonly_fields = [field.name for field in ImportJob._meta.fields]

    def has_add_permission(self, request):
        return False
