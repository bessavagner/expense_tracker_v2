from datetime import date
from decimal import Decimal

from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from finances.forms import EntryForm
from finances.models import Entry
from finances.views.mixins import HtmxLoginRequiredMixin


class EntryRedirectView(HtmxLoginRequiredMixin, View):
    """Redirect /entries/ to current month."""

    def get(self, request, *args, **kwargs):
        today = date.today()
        return redirect("finances:entries_month", year=today.year, month=today.month)


class EntryListView(HtmxLoginRequiredMixin, ListView):
    """Display entries for a specific billing month."""

    model = Entry
    template_name = "entries/entries_page.html"
    htmx_template_name = "entries/_entries_table.html"
    context_object_name = "entries"
    paginate_by = 100

    def get_queryset(self):
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])
        billing_month = date(year, month, 1)
        return (
            Entry.objects.filter(user=self.request.user, billing_month=billing_month)
            .select_related("category", "payment_method")
            .order_by("-date", "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])

        context["current_year"] = year
        context["current_month"] = month
        context["months"] = list(range(1, 13))
        context["year_range"] = range(2024, date.today().year + 2)

        # Summary
        entries = context["entries"]
        expenses = sum(e.amount for e in entries if e.amount > 0) or Decimal("0")
        returns = sum(e.amount for e in entries if e.amount < 0) or Decimal("0")
        context["summary"] = {
            "total_expenses": expenses,
            "total_returns": abs(returns),
            "net": expenses + returns,
            "entry_count": len(entries),
        }

        # Inline form
        context["form"] = EntryForm(user=self.request.user)

        return context
