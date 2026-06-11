from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views import View

from finances.forms import CockpitIncomeForm
from finances.models import Entry, Income, SystemicExpense
from finances.services.systemic_month import systemic_rows_for_month
from finances.views.mixins import HtmxLoginRequiredMixin


def _income_context(request, year, month):
    incomes = list(
        Income.objects.filter(
            user=request.user, month=date(year, month, 1)
        ).order_by("name")
    )
    income_month_total = sum((i.amount for i in incomes), Decimal("0"))
    return {
        "current_year": year,
        "current_month": month,
        "incomes": incomes,
        "income_month_total": income_month_total,
        "income_form": CockpitIncomeForm(initial={"month": date(year, month, 1)}),
    }


def _render_income_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_income_section.html", _income_context(request, year, month), request=request
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


class CockpitIncomeSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_income_section(request, int(year), int(month))


class CockpitIncomeCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request, year, month):
        form = CockpitIncomeForm(request.POST)
        if form.is_valid():
            form.save_for_user(request.user)
            return _render_income_section(request, int(year), int(month), toast="Renda salva!")
        ctx = _income_context(request, int(year), int(month))
        ctx["income_form"] = form
        return HttpResponse(render_to_string("cockpit/_income_section.html", ctx, request=request))


class CockpitIncomeDeleteView(HtmxLoginRequiredMixin, View):
    def delete(self, request, year, month, pk):
        inc = Income.objects.filter(user=request.user, pk=pk).first()
        if not inc:
            raise Http404
        inc.delete()
        return _render_income_section(request, int(year), int(month), toast="Renda excluída!")


# ---------------------------------------------------------------------------
# Systemic section
# ---------------------------------------------------------------------------


def _systemic_context(request, year, month):
    return {
        "current_year": year,
        "current_month": month,
        "systemic_rows": systemic_rows_for_month(request.user, year, month),
    }


def _render_systemic_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_systemic_section.html",
        _systemic_context(request, year, month),
        request=request,
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


def _parse_amount(raw, fallback):
    try:
        return Decimal(str(raw)) if raw not in (None, "") else fallback
    except (InvalidOperation, TypeError):
        return fallback


class CockpitSystemicSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_systemic_section(request, int(year), int(month))


class CockpitSystemicPostView(HtmxLoginRequiredMixin, View):
    """Create the month entry (lançar) or update its amount."""

    def post(self, request, year, month, pk):
        y, m = int(year), int(month)
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        billing_month = date(y, m, 1)
        entry = Entry.objects.filter(
            user=request.user, systemic_expense=systemic, billing_month=billing_month
        ).first()
        amount = request.POST.get("amount")
        if entry is None:
            value = _parse_amount(amount, systemic.default_amount)
            systemic.create_monthly_entry(billing_month, amount=value)
        elif amount is not None:
            entry.amount = _parse_amount(amount, entry.amount)
            entry.save(update_fields=["amount", "updated_at"])
        return _render_systemic_section(request, y, m, toast=f"{systemic.name} lançado!")


class CockpitSystemicDeleteView(HtmxLoginRequiredMixin, View):
    """'Não ocorreu' — remove the month entry."""

    def delete(self, request, year, month, pk):
        y, m = int(year), int(month)
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        Entry.objects.filter(
            user=request.user, systemic_expense=systemic, billing_month=date(y, m, 1)
        ).delete()
        return _render_systemic_section(request, y, m, toast=f"{systemic.name}: não ocorreu")
