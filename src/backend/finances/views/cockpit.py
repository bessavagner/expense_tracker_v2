import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from finances.forms import (
    CockpitIncomeForm,
    EntryForm,
    IncomeForm,
    InstallmentForm,
    SystemicEntryEditForm,
    SystemicExpenseForm,
)
from finances.models import Category, Entry, Income, PaymentMethod, SystemicExpense
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.models.payment_method_closing_day import PaymentMethodClosingDay
from finances.services.income_recurrence import apply_income_recurrence
from finances.services.installment_month import installment_rows_for_month
from finances.services.systemic_month import systemic_rows_for_month
from finances.views.mixins import HtmxLoginRequiredMixin


def _income_context(request, year, month):
    incomes = list(
        Income.objects.filter(
            user=request.user, month__year=year, month__month=month
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


class CockpitIncomeEditModalView(HtmxLoginRequiredMixin, View):
    """Edit a single Income inside the shared #entry-modal."""

    def _income(self, request, pk):
        inc = Income.objects.filter(user=request.user, pk=pk).first()
        if not inc:
            raise Http404
        return inc

    def _modal_context(self, year, month, inc, form):
        return {
            "form": form,
            "title": "Editar Renda",
            "post_url": reverse(
                "finances:cockpit_income_edit_modal", args=[year, month, inc.id]
            ),
            "swap_target": "#cockpit-income",
            "swap_mode": "outerHTML",
        }

    def get(self, request, year, month, pk):
        inc = self._income(request, pk)
        form = IncomeForm(instance=inc)
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, inc, form),
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, year, month, pk):
        inc = self._income(request, pk)
        form = IncomeForm(request.POST, instance=inc)
        if form.is_valid():
            inc = form.save()
            apply_income_recurrence(inc)
            html = render_to_string(
                "cockpit/_income_section.html",
                _income_context(request, int(year), int(month)),
                request=request,
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Renda atualizada!", "type": "success"},'
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, inc, form),
            request=request,
        )
        return HttpResponse(html)


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
            toast = f"{systemic.name} lançado!"
        elif amount is not None:
            entry.amount = _parse_amount(amount, entry.amount)
            entry.save(update_fields=["amount", "updated_at"])
            toast = f"{systemic.name} atualizado!"
        else:
            toast = None
        return _render_systemic_section(request, y, m, toast=toast)


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


class CockpitSystemicCreateView(HtmxLoginRequiredMixin, View):
    """Inline create a new SystemicExpense from the cockpit."""

    def post(self, request, year, month):
        y, m = int(year), int(month)
        form = SystemicExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            systemic = form.save(commit=False)
            systemic.user = request.user
            systemic.save()
            return _render_systemic_section(request, y, m, toast=f"{systemic.name} adicionado!")
        ctx = _systemic_context(request, y, m)
        ctx["systemic_form"] = form
        html = render_to_string("cockpit/_systemic_section.html", ctx, request=request)
        return HttpResponse(html)


def _patch_entry_querysets(form, entry):
    """Keep the entry's current category/payment_method as valid choices."""
    form.fields["category"].queryset = form.fields["category"].queryset | Category.objects.filter(
        pk=entry.category_id
    )
    form.fields["payment_method"].queryset = form.fields[
        "payment_method"
    ].queryset | PaymentMethod.objects.filter(pk=entry.payment_method_id)


class CockpitSystemicEditModalView(HtmxLoginRequiredMixin, View):
    """Edit this month's systemic Entry inside the shared #entry-modal.

    ``pk`` is the SystemicExpense id; the view resolves the month's lançado
    Entry. 404 when the systemic was not lançado this month.
    """

    def _entry(self, request, year, month, pk):
        entry = Entry.objects.filter(
            user=request.user,
            systemic_expense_id=pk,
            billing_month=date(int(year), int(month), 1),
        ).first()
        if not entry:
            raise Http404
        return entry

    def _modal_context(self, year, month, pk, form):
        return {
            "form": form,
            "title": "Editar Sistemático",
            "post_url": reverse(
                "finances:cockpit_systemic_edit_modal", args=[year, month, pk]
            ),
            "swap_target": "#cockpit-systemic",
            "swap_mode": "outerHTML",
        }

    def get(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = SystemicEntryEditForm(entry=entry, user=request.user)
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, pk, form),
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = SystemicEntryEditForm(request.POST, entry=entry, user=request.user)
        if form.is_valid():
            form.save()
            html = render_to_string(
                "cockpit/_systemic_section.html",
                _systemic_context(request, int(year), int(month)),
                request=request,
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Sistemático atualizado!", "type": "success"},'
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, pk, form),
            request=request,
        )
        return HttpResponse(html)


# ---------------------------------------------------------------------------
# Vencimentos section (credit-card closing day per month)
# ---------------------------------------------------------------------------


def _vencimentos_context(request, year, month):
    billing_month = date(year, month, 1)
    cards = PaymentMethod.objects.filter(
        user=request.user, type=PaymentType.CREDIT_CARD, is_active=True
    ).order_by("name")
    rows = []
    for pm in cards:
        override = PaymentMethodClosingDay.objects.filter(
            payment_method=pm, month=billing_month
        ).first()
        rows.append(
            {
                "pm": pm,
                "effective_day": override.closing_day if override else pm.closing_day,
                "is_override": override is not None,
            }
        )
    return {"current_year": year, "current_month": month, "venc_rows": rows}


def _render_vencimentos_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_vencimentos_section.html",
        _vencimentos_context(request, year, month),
        request=request,
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


class CockpitVencimentosSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_vencimentos_section(request, int(year), int(month))


class CockpitVencimentoSetView(HtmxLoginRequiredMixin, View):
    def post(self, request, year, month, pk):
        y, m = int(year), int(month)
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            raise Http404
        billing_month = date(y, m, 1)
        raw = (request.POST.get("closing_day") or "").strip()
        if raw == "":
            PaymentMethodClosingDay.objects.filter(
                payment_method=pm, month=billing_month
            ).delete()
            toast = f"{pm.name}: vencimento padrão"
        else:
            try:
                day = max(1, min(31, int(raw)))
            except ValueError:
                # Non-numeric input: no-op, leave any existing override untouched.
                return _render_vencimentos_section(request, y, m)
            PaymentMethodClosingDay.objects.update_or_create(
                payment_method=pm, month=billing_month, defaults={"closing_day": day}
            )
            toast = f"{pm.name}: fecha dia {day}"
        return _render_vencimentos_section(request, y, m, toast=toast)


# ---------------------------------------------------------------------------
# Parcelamentos section
# ---------------------------------------------------------------------------


class CockpitParcelamentosSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        y, m = int(year), int(month)
        ctx = {
            "current_year": y,
            "current_month": m,
            "parcelamento_rows": installment_rows_for_month(request.user, y, m),
        }
        html = render_to_string(
            "cockpit/_parcelamentos_section.html", ctx, request=request
        )
        return HttpResponse(html)


def _render_parcelamentos_section(request, year, month):
    ctx = {
        "current_year": year,
        "current_month": month,
        "parcelamento_rows": installment_rows_for_month(request.user, year, month),
    }
    return render_to_string("cockpit/_parcelamentos_section.html", ctx, request=request)


class CockpitParcelamentoEditModalView(HtmxLoginRequiredMixin, View):
    """Edit this month's installment Entry inside the shared #entry-modal.

    ``entry_pk`` is the installment Entry id. Editing the parent plan's
    structure (total / number of parcels) is out of scope.
    """

    def _entry(self, request, entry_pk):
        entry = Entry.objects.filter(
            user=request.user, pk=entry_pk, entry_type=EntryType.INSTALLMENT
        ).first()
        if not entry:
            raise Http404
        return entry

    def _modal_context(self, year, month, entry, form):
        return {
            "form": form,
            "title": "Editar Parcelamento",
            "post_url": reverse(
                "finances:cockpit_parcelamento_edit_modal", args=[year, month, entry.id]
            ),
            "swap_target": "#cockpit-parcelamentos",
            "swap_mode": "outerHTML",
        }

    def get(self, request, year, month, entry_pk):
        entry = self._entry(request, entry_pk)
        form = EntryForm(instance=entry, user=request.user)
        _patch_entry_querysets(form, entry)
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, entry, form),
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, year, month, entry_pk):
        entry = self._entry(request, entry_pk)
        form = EntryForm(request.POST, instance=entry, user=request.user)
        _patch_entry_querysets(form, entry)
        if form.is_valid():
            form.save()
            response = HttpResponse(
                _render_parcelamentos_section(request, int(year), int(month))
            )
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Parcelamento atualizado!", "type": "success"},'
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(year, month, entry, form),
            request=request,
        )
        return HttpResponse(html)


class CockpitParcelamentoManageView(HtmxLoginRequiredMixin, View):
    """Manage a whole installment plan from the cockpit row.

    Provides, in one modal: edit the plan fields (regenerating all parcels),
    shift every parcel by N months, delete the whole plan, and edit just this
    month's parcela (delegated to the existing per-entry edit endpoint).
    """

    def _entry(self, request, entry_pk):
        entry = (
            Entry.objects.filter(
                user=request.user, pk=entry_pk, entry_type=EntryType.INSTALLMENT
            )
            .select_related("installment_plan")
            .first()
        )
        if not entry or entry.installment_plan is None:
            raise Http404
        return entry

    def _patch_plan_querysets(self, form, plan):
        form.fields["category"].queryset = form.fields[
            "category"
        ].queryset | Category.objects.filter(pk=plan.category_id)
        form.fields["payment_method"].queryset = form.fields[
            "payment_method"
        ].queryset | PaymentMethod.objects.filter(pk=plan.payment_method_id)

    def _modal(self, request, year, month, entry, plan_form=None, entry_form=None):
        plan = entry.installment_plan
        if plan_form is None:
            plan_form = InstallmentForm(instance=plan, user=request.user)
            self._patch_plan_querysets(plan_form, plan)
        if entry_form is None:
            entry_form = EntryForm(instance=entry, user=request.user)
            _patch_entry_querysets(entry_form, entry)
        ctx = {
            "plan": plan,
            "plan_form": plan_form,
            "entry_form": entry_form,
            "manage_url": reverse(
                "finances:cockpit_parcelamento_manage_modal", args=[year, month, entry.id]
            ),
            "parcela_url": reverse(
                "finances:cockpit_parcelamento_edit_modal", args=[year, month, entry.id]
            ),
        }
        return render_to_string(
            "cockpit/_modal_parcelamento_manage.html", ctx, request=request
        )

    def _section_response(self, request, year, month, message):
        response = HttpResponse(
            _render_parcelamentos_section(request, int(year), int(month))
        )
        response["HX-Trigger"] = json.dumps(
            {"showToast": {"message": message, "type": "success"}, "entry-saved": True}
        )
        return response

    def get(self, request, year, month, entry_pk):
        entry = self._entry(request, entry_pk)
        return HttpResponse(self._modal(request, year, month, entry))

    def post(self, request, year, month, entry_pk):
        entry = self._entry(request, entry_pk)
        plan = entry.installment_plan
        action = request.POST.get("action")

        if action == "delete":
            plan.delete()
            return self._section_response(request, year, month, "Parcelamento excluído!")

        if action == "shift":
            try:
                n = int(request.POST.get("months", "0"))
            except (TypeError, ValueError):
                n = 0
            if n != 0:
                plan.shift_months(n)
            return self._section_response(request, year, month, "Parcelas deslocadas!")

        if action == "edit_plan":
            form = InstallmentForm(request.POST, instance=plan, user=request.user)
            self._patch_plan_querysets(form, plan)
            if form.is_valid():
                form.save()
                plan.regenerate_entries()
                return self._section_response(
                    request, year, month, "Parcelamento atualizado!"
                )
            return HttpResponse(
                self._modal(request, year, month, entry, plan_form=form)
            )

        raise Http404
