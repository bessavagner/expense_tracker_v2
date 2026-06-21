import uuid
from datetime import date
from decimal import Decimal

from django.db.models import Min
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView, View

from finances.models import Entry, Income
from finances.services.projection import build_projection
from finances.services.whatif import HypotheticalItem, HypoType, expand_hypotheticals
from finances.views.mixins import HtmxLoginRequiredMixin

SESSION_KEY = "projection_whatif"
ESTIMATE_SESSION_KEY = "projection_estimate"

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


def _parse_month_field(raw):  # "YYYY-MM" -> date(first)
    y, m = (int(p) for p in raw.split("-")[:2])
    return date(y, m, 1)


def _session_items(request):
    return [HypotheticalItem(**d) for d in request.session.get(SESSION_KEY, [])]


def _parse_estimate(request) -> str:
    """'teto' or 'median'. GET wins; otherwise last session choice; default median."""
    raw = request.GET.get("estimate")
    if raw in ("teto", "median"):
        request.session[ESTIMATE_SESSION_KEY] = raw
        return raw
    return request.session.get(ESTIMATE_SESSION_KEY, "median")


def _overlay_simulation(rows, overlay):
    """Project the what-if ``overlay`` on top of the ESTIMATED track.

    The simulated line branches from the estimated trajectory (the realistic
    forward curve), not the posted one: for each month the hypothetical net
    (income − expenses) is added to ``saldo_projetado_estimado`` and accumulated
    onto ``acumulado_estimado``. Mutates each row, adding ``saldo_projetado_sim``
    and ``acumulado_sim``.
    """
    cum = Decimal("0")
    for r in rows:
        m = r["month"]
        net = (
            overlay.get((m, "income"), Decimal("0"))
            - overlay.get((m, "regular"), Decimal("0"))
            - overlay.get((m, "installment"), Decimal("0"))
            - overlay.get((m, "systemic"), Decimal("0"))
        )
        cum += net
        r["saldo_projetado_sim"] = r["saldo_projetado_estimado"] + net
        r["acumulado_sim"] = r["acumulado_estimado"] + cum


def build_projection_context(request):
    """Shared context for the projection screen and the what-if fragment renders.

    Builds the baseline projection once; when the session holds hypotheticals it
    also builds the simulated projection and zips ``*_sim`` figures onto each row.
    """
    today = date.today()
    start = _parse_start(request, today)
    months = _parse_months(request.GET.get("months"))

    first_year = min(_data_anchor_year(request.user, today), start.year)
    last_year = max(today.year, start.year)

    estimate = _parse_estimate(request)
    estimator = "ceiling" if estimate == "teto" else "median"

    items = _session_items(request)
    rows = build_projection(request.user, start, months, today=today, diverse_estimator=estimator)
    if items:
        span = [r["month"] for r in rows]
        overlay, _ = expand_hypotheticals(items, span)
        _overlay_simulation(rows, overlay)

    return {
        "rows": rows,
        "today_month": today.replace(day=1),
        "start_year": start.year,
        "start_month": start.month,
        "year_options": list(range(first_year, last_year + 1)),
        "start_month_options": list(range(1, 13)),
        "months_value": months,
        "month_options": [6, 12, 14, 18, 24],
        "whatif_items": items,
        "has_whatif": bool(items),
        "estimate": estimate,
    }


def _render_projection(request):
    ctx = build_projection_context(request)
    return HttpResponse(
        render_to_string("projection/_projection_body.html", ctx, request=request)
    )


class ProjectionView(HtmxLoginRequiredMixin, TemplateView):
    """Read-only multi-month projection: months as columns, metrics as rows."""

    template_name = "projection/projection_page.html"
    htmx_template_name = "projection/_projection_body.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(build_projection_context(self.request))
        return context


class ProjectionWhatifAddView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        items = request.session.get(SESSION_KEY, [])
        item = HypotheticalItem(
            id=uuid.uuid4().hex[:8],
            type=HypoType(request.POST["type"]),
            label=request.POST.get("label", ""),
            amount=request.POST["amount"],
            month=_parse_month_field(request.POST["month"]),
            end_month=(_parse_month_field(request.POST["end_month"])
                       if request.POST.get("end_month") else None),
            n_installments=(int(request.POST["n_installments"])
                            if request.POST.get("n_installments") else None),
            installment_amount=(request.POST["installment_amount"]
                                if request.POST.get("installment_amount") else None),
        )
        items.append(item.model_dump(mode="json"))
        request.session[SESSION_KEY] = items
        return _render_projection(request)


class ProjectionWhatifRemoveView(HtmxLoginRequiredMixin, View):
    def post(self, request, item_id):
        items = [d for d in request.session.get(SESSION_KEY, []) if d["id"] != item_id]
        request.session[SESSION_KEY] = items
        return _render_projection(request)


class ProjectionWhatifClearView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        request.session[SESSION_KEY] = []
        return _render_projection(request)
