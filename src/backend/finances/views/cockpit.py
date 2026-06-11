from datetime import date
from decimal import Decimal

from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views import View

from finances.forms import CockpitIncomeForm
from finances.models import Income
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
