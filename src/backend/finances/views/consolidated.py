from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.views.generic import ListView, TemplateView

from finances.models import Entry, Income
from finances.models.entry import EntryType
from finances.views.mixins import HtmxLoginRequiredMixin


class ConsolidatedView(HtmxLoginRequiredMixin, TemplateView):
    """Month-scoped consolidated dashboard: category cards for the selected
    month with budget bars plus a Total/Renda/Saldo summary."""

    template_name = "consolidated/consolidated_page.html"
    htmx_template_name = "consolidated/_consolidated_table.html"
    entry_type_filter = None  # None = diverse (non-systemic), "systemic" = systemics only

    def get_entry_type_filter(self):
        return self.entry_type_filter

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        year = int(self.request.GET.get("year", today.year))
        month = int(self.request.GET.get("month", today.month))
        billing_month = date(year, month, 1)

        context["current_year"] = year
        context["current_month"] = month
        context["months"] = list(range(1, 13))
        context["year_range"] = range(2024, today.year + 2)
        context["tab"] = "systemics" if self.entry_type_filter == EntryType.SYSTEMIC else "diverse"

        entries_qs = Entry.objects.filter(user=self.request.user, billing_month=billing_month)
        if self.entry_type_filter == EntryType.SYSTEMIC:
            entries_qs = entries_qs.filter(entry_type=EntryType.SYSTEMIC)
        else:
            entries_qs = entries_qs.exclude(entry_type=EntryType.SYSTEMIC)

        aggregated = (
            entries_qs.values("category__id", "category__name", "category__budget_ceiling")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        cards = []
        for row in aggregated:
            total = row["total"] or Decimal("0")
            ceiling = row["category__budget_ceiling"]
            has_ceiling = bool(ceiling and ceiling > 0)
            pct = int((total / ceiling * 100).to_integral_value()) if has_ceiling else 0
            status = "success"
            if has_ceiling:
                if pct >= 100:
                    status = "error"
                elif pct >= 90:
                    status = "warning"
            cards.append(
                {
                    "id": row["category__id"],
                    "name": row["category__name"],
                    "total": total,
                    "budget_ceiling": ceiling,
                    "pct": pct,
                    "status": status,
                    "has_ceiling": has_ceiling,
                }
            )

        context["category_cards"] = cards
        context["month_total"] = sum((c["total"] for c in cards), Decimal("0"))
        context["income_total"] = sum(
            (
                inc.amount
                for inc in Income.objects.filter(user=self.request.user, month=billing_month)
            ),
            Decimal("0"),
        )
        context["saldo"] = context["income_total"] - context["month_total"]

        return context


class ConsolidatedSystemicsView(ConsolidatedView):
    """Consolidated view filtered to systemic entries only."""

    entry_type_filter = EntryType.SYSTEMIC


class CategoryDetailView(HtmxLoginRequiredMixin, ListView):
    """Expandable detail: individual entries for a category in a month."""

    model = Entry
    template_name = "consolidated/_category_entries.html"
    htmx_template_name = "consolidated/_category_entries.html"
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
