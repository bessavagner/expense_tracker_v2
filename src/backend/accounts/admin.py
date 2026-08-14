from django.contrib import admin

from accounts.models import Plan

# Household, Membership and Invitation are deliberately not registered. They
# are tenant data, and an admin list view of them is a standing invitation to
# browse who lives with whom — the same reasoning that keeps ChatMessage out of
# assistant/admin.py (E05 S05-5). E17 owns the deliberate, consented, logged
# way to look at a customer's account.


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """Global product configuration, not tenant data — safe to edit here.

    `monthly_credits` is editable in the list so the beta grant can be retuned
    without a deploy, which is the whole point of it being a row (E07 spec D4).
    """

    list_display = ("name", "slug", "monthly_credits", "is_default")
    list_editable = ("monthly_credits",)
    prepopulated_fields = {"slug": ("name",)}
