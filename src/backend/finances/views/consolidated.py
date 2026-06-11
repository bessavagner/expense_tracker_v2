from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.views.generic import ListView, TemplateView

from finances.models import Entry
from finances.models.entry import EntryType
from finances.views.mixins import HtmxLoginRequiredMixin


class ConsolidatedView(HtmxLoginRequiredMixin, TemplateView):
    """Consolidated view of expenses by category, one column per month."""

    template_name = "consolidated/consolidated_page.html"
    htmx_template_name = "consolidated/_consolidated_table.html"
    entry_type_filter = None  # None = diverse (non-systemic), "systemic" = systemics only

    def get_entry_type_filter(self):
        return self.entry_type_filter

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.request.GET.get("year", date.today().year))
        context["current_year"] = year
        context["tab"] = "systemics" if self.entry_type_filter == EntryType.SYSTEMIC else "diverse"
        context["year_range"] = range(2024, date.today().year + 2)

        # Get all entries for the year, grouped by category and month
        entries_qs = Entry.objects.filter(
            user=self.request.user,
            billing_month__year=year,
        )
        if self.entry_type_filter == EntryType.SYSTEMIC:
            entries_qs = entries_qs.filter(entry_type=EntryType.SYSTEMIC)
        else:
            entries_qs = entries_qs.exclude(entry_type=EntryType.SYSTEMIC)

        # Aggregate by category and month
        aggregated = (
            entries_qs.values(
                "category__id", "category__name", "category__budget_ceiling", "billing_month__month"
            )
            .annotate(total=Sum("amount"))
            .order_by("category__name", "billing_month__month")
        )

        # Build rows: one per category with monthly totals
        categories = {}
        for row in aggregated:
            cat_name = row["category__name"]
            if cat_name not in categories:
                categories[cat_name] = {
                    "category__name": cat_name,
                    "category__id": row["category__id"],
                    "budget_ceiling": row["category__budget_ceiling"],
                    "months": {m: Decimal("0") for m in range(1, 13)},
                    "budget_status": dict.fromkeys(range(1, 13), "ok"),
                }
            categories[cat_name]["months"][row["billing_month__month"]] = row["total"]

        # Compute budget status
        for cat in categories.values():
            ceiling = cat["budget_ceiling"]
            if ceiling and ceiling > 0:
                for m in range(1, 13):
                    ratio = cat["months"][m] / ceiling
                    if ratio >= 1:
                        cat["budget_status"][m] = "danger"
                    elif ratio >= Decimal("0.9"):
                        cat["budget_status"][m] = "warning"

        context["aggregation"] = sorted(categories.values(), key=lambda c: c["category__name"])
        context["months"] = list(range(1, 13))

        # Column totals
        context["column_totals"] = {
            m: sum(c["months"][m] for c in categories.values()) for m in range(1, 13)
        }

        return context


class ConsolidatedSystemicsView(ConsolidatedView):
    """Consolidated view filtered to systemic entries only."""

    entry_type_filter = EntryType.SYSTEMIC


class CategoryDetailView(HtmxLoginRequiredMixin, ListView):
    """Expandable detail: individual entries for a category in a month."""

    model = Entry
    template_name = "consolidated/_category_detail.html"
    htmx_template_name = "consolidated/_category_detail.html"
    context_object_name = "entries"

    def get_queryset(self):
        qs = Entry.objects.filter(
            user=self.request.user,
            category_id=self.kwargs["category_id"],
            billing_month=date(int(self.kwargs["year"]), int(self.kwargs["month"]), 1),
        )
        # Mirror the parent table's filter: systemic tab shows only systemic
        # entries; the diverse tab excludes them.
        if self.request.GET.get("type") == "systemic":
            qs = qs.filter(entry_type=EntryType.SYSTEMIC)
        else:
            qs = qs.exclude(entry_type=EntryType.SYSTEMIC)
        return qs.select_related("payment_method").order_by("-date")
