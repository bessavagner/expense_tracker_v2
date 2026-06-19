from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView, View

from finances.forms import (
    CategoryBudgetForm,
    CategoryCreateForm,
    IncomeForm,
    PaymentMethodForm,
    SystemicExpenseForm,
)
from finances.models import Category, Income, PaymentMethod, SystemicExpense
from finances.services.income_recurrence import apply_income_recurrence
from finances.views.mixins import HtmxLoginRequiredMixin


class SettingsView(HtmxLoginRequiredMixin, TemplateView):
    """Settings page with tabs."""

    template_name = "settings/settings_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.request.GET.get("tab", "income")
        return context


# --- Income ---


def income_groups(user):
    """Group a user's incomes by name into one summary row each.

    Recurring incomes create one Income row per month; the Settings list groups
    them so the tab shows sources, not a wall of near-identical rows. Per-month
    values are edited in the monthly cockpit (Entradas).
    """
    groups: dict[str, dict] = {}
    for inc in Income.objects.filter(user=user).order_by("name", "month"):
        g = groups.get(inc.name)
        if g is None:
            g = groups[inc.name] = {
                "name": inc.name,
                "count": 0,
                "min_month": inc.month,
                "max_month": inc.month,
                "_amounts": set(),
                "is_recurring": False,
            }
        g["count"] += 1
        g["min_month"] = min(g["min_month"], inc.month)
        g["max_month"] = max(g["max_month"], inc.month)
        g["_amounts"].add(inc.amount)
        g["is_recurring"] = g["is_recurring"] or inc.is_recurring
    result = []
    for g in groups.values():
        amounts = g.pop("_amounts")
        g["amount"] = next(iter(amounts)) if len(amounts) == 1 else None
        result.append(g)
    result.sort(key=lambda x: x["name"])
    return result


def _income_tab_context(user):
    return {"income_groups": income_groups(user), "form": IncomeForm()}


class IncomeTabView(HtmxLoginRequiredMixin, TemplateView):
    """Income tab content (grouped summary)."""

    template_name = "settings/_income_tab.html"
    htmx_template_name = "settings/_income_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_income_tab_context(self.request.user))
        return context


class IncomeCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = IncomeForm(request.POST)
        if form.is_valid():
            income = form.save(commit=False)
            income.user = request.user
            income.save()
            apply_income_recurrence(income)
        return self._render_tab(request)

    def _render_tab(self, request):
        html = render_to_string(
            "settings/_income_tab.html", _income_tab_context(request.user), request=request
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Renda salva!", "type": "success"}}'
        return response


class IncomeGroupDeleteView(HtmxLoginRequiredMixin, View):
    """Delete every income row sharing a name (remove a whole income source)."""

    def post(self, request):
        name = request.POST.get("name", "")
        Income.objects.filter(user=request.user, name=name).delete()
        html = render_to_string(
            "settings/_income_tab.html", _income_tab_context(request.user), request=request
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Renda removida!", "type": "success"}}'
        return response


class IncomeUpdateView(HtmxLoginRequiredMixin, View):
    def get(self, request, pk):
        income = Income.objects.filter(user=request.user, pk=pk).first()
        if not income:
            raise Http404
        form = IncomeForm(instance=income)
        context = {"income": income, "edit_form": form}
        html = render_to_string("settings/_income_edit_form.html", context, request=request)
        return HttpResponse(html)

    def post(self, request, pk):
        income = Income.objects.filter(user=request.user, pk=pk).first()
        if not income:
            raise Http404
        form = IncomeForm(request.POST, instance=income)
        if form.is_valid():
            form.save()
            apply_income_recurrence(form.instance)
        html = render_to_string(
            "settings/_income_tab.html", _income_tab_context(request.user), request=request
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Renda atualizada!", "type": "success"}}'
        )
        return response


# --- Systemic Expenses ---


class SystemicsTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_systemics_tab.html"
    htmx_template_name = "settings/_systemics_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["systemics"] = SystemicExpense.objects.filter(
            user=self.request.user
        ).select_related("category", "payment_method")
        context["form"] = SystemicExpenseForm(user=self.request.user)
        return context


class SystemicCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = SystemicExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            systemic = form.save(commit=False)
            systemic.user = request.user
            systemic.save()
        return self._render_tab(request)

    def _render_tab(self, request):
        context = {
            "systemics": SystemicExpense.objects.filter(user=request.user).select_related(
                "category", "payment_method"
            ),
            "form": SystemicExpenseForm(user=request.user),
        }
        html = render_to_string("settings/_systemics_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Gasto sistemático salvo!", "type": "success"}}'
        )
        return response


class SystemicEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        form = SystemicExpenseForm(request.POST, instance=systemic, user=request.user)
        if form.is_valid():
            form.save()
        return SystemicCreateView()._render_tab(request)


class SystemicToggleView(HtmxLoginRequiredMixin, View):
    def patch(self, request, pk):
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        systemic.is_active = not systemic.is_active
        systemic.save()
        html = render_to_string(
            "settings/_systemics_tab.html",
            {
                "systemics": SystemicExpense.objects.filter(user=request.user).select_related(
                    "category", "payment_method"
                ),
                "form": SystemicExpenseForm(user=request.user),
            },
            request=request,
        )
        response = HttpResponse(html)
        status = "ativado" if systemic.is_active else "desativado"
        response["HX-Trigger"] = (
            f'{{"showToast": {{"message": "{systemic.name} {status}!", "type": "success"}}}}'
        )
        return response


# --- Payment Methods ---


class PaymentMethodsTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_payment_methods_tab.html"
    htmx_template_name = "settings/_payment_methods_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["payment_methods"] = PaymentMethod.objects.filter(user=self.request.user)
        context["form"] = PaymentMethodForm()
        return context


class PaymentMethodCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = PaymentMethodForm(request.POST)
        if form.is_valid():
            pm = form.save(commit=False)
            pm.user = request.user
            pm.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Forma de pagamento criada!", "type": "success"}}'
        )
        return response


class PaymentMethodEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            raise Http404
        form = PaymentMethodForm(request.POST, instance=pm)
        if form.is_valid():
            form.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Forma de pagamento atualizada!", "type": "success"}}'
        )
        return response


class PaymentMethodToggleView(HtmxLoginRequiredMixin, View):
    def patch(self, request, pk):
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            raise Http404
        pm.is_active = not pm.is_active
        pm.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        return response


# --- Categories ---


class CategoriesTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_categories_tab.html"
    htmx_template_name = "settings/_categories_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.filter(user=self.request.user)
        context["form"] = CategoryCreateForm()
        return context


class CategoryCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = CategoryCreateForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.user = request.user
            cat.save()
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Categoria criada!", "type": "success"}}'
        )
        return response


class CategoryEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        cat = Category.objects.filter(user=request.user, pk=pk).first()
        if not cat:
            raise Http404
        form = CategoryBudgetForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Teto atualizado!", "type": "success"}}'
        return response


class CategoryDeleteView(HtmxLoginRequiredMixin, View):
    def delete(self, request, pk):
        cat = Category.objects.filter(user=request.user, pk=pk).first()
        if not cat:
            raise Http404
        if cat.is_system:
            return HttpResponse(
                '{"error": "Categorias do sistema não podem ser excluídas."}',
                status=400,
                content_type="application/json",
            )
        try:
            cat.delete()
        except Exception:
            return HttpResponse(
                '{"error": "Categoria possui entradas vinculadas."}',
                status=400,
                content_type="application/json",
            )
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        return HttpResponse(html)
