from datetime import date

from django.db.models import Min
from django.views.generic import TemplateView

from finances.models import Entry, Income
from finances.services.projection import build_projection
from finances.views.mixins import HtmxLoginRequiredMixin

DEFAULT_MONTHS = 14
MAX_MONTHS = 36
MIN_MONTHS = 1


def _default_start(today: date) -> date:
    """First day of the previous month (the moving window starts at -1)."""
    first = today.replace(day=1)
    if first.month == 1:
        return date(first.year - 1, 12, 1)
    return date(first.year, first.month - 1, 1)


def _parse_start(request, today: date) -> date:
    sy, sm = request.GET.get("start_year"), request.GET.get("start_month")
    if sy and sm:
        try:
            return date(int(sy), int(sm), 1)
        except (ValueError, TypeError):
            pass
    raw = request.GET.get("start")
    if raw:
        try:
            year, month = (int(p) for p in raw.split("-")[:2])
            return date(year, month, 1)
        except (ValueError, TypeError):
            pass
    return _default_start(today)


def _data_anchor_year(user, today: date) -> int:
    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    return min(candidates).year if candidates else today.year


def _parse_months(raw: str | None) -> int:
    try:
        n = int(raw)
    except (ValueError, TypeError):
        return DEFAULT_MONTHS
    return max(MIN_MONTHS, min(n, MAX_MONTHS))


class ProjectionView(HtmxLoginRequiredMixin, TemplateView):
    """Read-only multi-month projection: months as columns, metrics as rows."""

    template_name = "projection/projection_page.html"
    htmx_template_name = "projection/_projection_table.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()

        start = _parse_start(self.request, today)
        months = _parse_months(self.request.GET.get("months"))

        first_year = min(_data_anchor_year(self.request.user, today), start.year)
        last_year = max(today.year, start.year)

        context["rows"] = build_projection(self.request.user, start, months, today=today)
        context["today_month"] = today.replace(day=1)
        context["start_year"] = start.year
        context["start_month"] = start.month
        context["year_options"] = list(range(first_year, last_year + 1))
        context["start_month_options"] = list(range(1, 13))
        context["months_value"] = months
        context["month_options"] = [6, 12, 14, 18, 24]
        return context
