from django.contrib import admin

from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "budget_ceiling", "is_system", "user")
    list_filter = ("is_system", "user")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "closing_day", "is_active", "user")
    list_filter = ("type", "is_active", "user")
    search_fields = ("name",)


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "month", "is_recurring", "user")
    list_filter = ("is_recurring", "user", "month")
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
