import json
from datetime import date
from decimal import Decimal

from django.db.models import Count, Min, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, UpdateView

from finances.forms import EntryForm, InstallmentForm
from finances.models import Entry, Income, PaymentMethod
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.billing import installment_billing_months
from finances.services.projection import build_projection
from finances.views.mixins import HtmxLoginRequiredMixin

# HX-Trigger fired after any entry mutation so the top totals refresh live.
ENTRIES_CHANGED = '"entries-changed": true'


def compute_entry_summary(user, year, month):
    """Totais do mês para o painel de Entradas.

    ``total_lancado`` é a soma das entradas REGULARES *lançadas* no mês (por
    ``date``) — as mesmas linhas que aparecem na tabela. ``total_gastos`` e os
    saldos vêm de :func:`build_projection`, ancorada no mês mais antigo com
    dado, para baterem 100% com a tela de Projeção (inclui sistemáticos e
    parcelas, por ``billing_month``).
    """
    target = date(year, month, 1)

    lanc = Entry.objects.filter(
        user=user, entry_type=EntryType.REGULAR, date__year=year, date__month=month
    ).aggregate(total=Sum("amount"), count=Count("id"))
    total_lancado = lanc["total"] or Decimal("0")
    entry_count = lanc["count"]

    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    anchor = min(candidates).replace(day=1) if candidates else target
    if anchor > target:
        anchor = target
    num_months = (year * 12 + month) - (anchor.year * 12 + anchor.month) + 1

    rows = build_projection(user, anchor, num_months, today=date.today())
    row = rows[-1]

    return {
        "total_lancado": total_lancado,
        "total_gastos": row["total"],
        "income": row["income"],
        "saldo_projetado": row["saldo_projetado"],
        "acumulado": row["acumulado"],
        "entry_count": entry_count,
    }


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
        return (
            Entry.objects.filter(
                user=self.request.user,
                date__year=year,
                date__month=month,
                entry_type=EntryType.REGULAR,
            )
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

        # Summary (aggregated across the whole month, not just this page)
        context["summary"] = compute_entry_summary(self.request.user, year, month)

        # Inline form
        context["form"] = EntryForm(user=self.request.user)

        return context


class EntriesSummaryView(HtmxLoginRequiredMixin, View):
    """Render just the top totals partial; refreshed live on `entries-changed`."""

    def get(self, request, year, month):
        year = int(year)
        month = int(month)
        html = render_to_string(
            "entries/_entries_summary.html",
            {
                "summary": compute_entry_summary(request.user, year, month),
                "current_year": year,
                "current_month": month,
            },
            request=request,
        )
        return HttpResponse(html)


class EntryCreateView(HtmxLoginRequiredMixin, View):
    """Create entry from inline form."""

    def post(self, request):
        form = EntryForm(request.POST, user=request.user)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            html = render_to_string("entries/_entry_row.html", {"entry": entry}, request=request)
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Entrada criada!", "type": "success"},'
                f" {ENTRIES_CHANGED}}}"
            )
            return response
        # Invalid form: return form with errors
        html = render_to_string("entries/_inline_entry_form.html", {"form": form}, request=request)
        return HttpResponse(html)


class EntryUpdateView(HtmxLoginRequiredMixin, UpdateView):
    """Edit entry inline."""

    model = Entry
    form_class = EntryForm
    template_name = "entries/_entry_edit_row.html"
    htmx_template_name = "entries/_entry_edit_row.html"

    def get_queryset(self):
        return Entry.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        entry = form.save()
        html = render_to_string("entries/_entry_row.html", {"entry": entry}, request=self.request)
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Entrada atualizada!", "type": "success"},'
            f" {ENTRIES_CHANGED}}}"
        )
        return response


class EntryDeleteView(HtmxLoginRequiredMixin, View):
    """Delete entry."""

    def delete(self, request, pk):
        entry = Entry.objects.filter(user=request.user, pk=pk).first()
        if not entry:
            raise Http404
        entry.delete()
        response = HttpResponse("")
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Entrada excluída!", "type": "success"},'
            f" {ENTRIES_CHANGED}}}"
        )
        return response


class EntryEditModalView(HtmxLoginRequiredMixin, View):
    """Edit a regular entry inside the shared #entry-modal."""

    def _get_entry(self, request, pk):
        entry = Entry.objects.filter(user=request.user, pk=pk).first()
        if not entry:
            raise Http404
        return entry

    def _modal_context(self, entry, form):
        return {
            "form": form,
            "title": "Editar Entrada",
            "post_url": reverse("finances:entry_edit_modal", args=[entry.id]),
            "swap_target": f"#entry-{entry.id}",
            "swap_mode": "outerHTML",
        }

    def get(self, request, pk):
        entry = self._get_entry(request, pk)
        form = EntryForm(instance=entry, user=request.user)
        self._patch_form_querysets(form, entry)
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(entry, form),
            request=request,
        )
        return HttpResponse(html)

    def _patch_form_querysets(self, form, entry):
        """Ensure the entry's existing category/pm are always valid choices."""
        from finances.models import Category, PaymentMethod

        cat_qs = form.fields["category"].queryset
        form.fields["category"].queryset = cat_qs | Category.objects.filter(
            pk=entry.category_id
        )
        pm_qs = form.fields["payment_method"].queryset
        form.fields["payment_method"].queryset = pm_qs | PaymentMethod.objects.filter(
            pk=entry.payment_method_id
        )

    def post(self, request, pk):
        entry = self._get_entry(request, pk)
        form = EntryForm(request.POST, instance=entry, user=request.user)
        self._patch_form_querysets(form, entry)
        if form.is_valid():
            entry = form.save()
            html = render_to_string(
                "entries/_entry_row.html", {"entry": entry}, request=request
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Entrada atualizada!", "type": "success"},'
                ' "entry-saved": true, "entries-changed": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(entry, form),
            request=request,
        )
        return HttpResponse(html)


class InstallmentPreviewView(HtmxLoginRequiredMixin, View):
    """Return the billing month of each installment for live preview in the modal.

    Lets the user see immediately in which invoice (fatura) each parcela will
    land — making the effect of the card's closing day transparent. Uses the
    same rule as ``InstallmentPlan.generate_entries``.
    """

    def get(self, request):
        date_str = request.GET.get("date", "")
        pm_id = request.GET.get("payment_method", "")
        try:
            num = int(request.GET.get("num_installments", "0"))
        except (TypeError, ValueError):
            num = 0
        try:
            start = date.fromisoformat(date_str)
        except ValueError:
            return JsonResponse({"months": [], "note": ""})

        pm = PaymentMethod.objects.filter(user=request.user, pk=pm_id).first()
        if pm is None or num < 1 or num > 60:
            return JsonResponse({"months": [], "note": ""})

        months = installment_billing_months(start, pm, num)
        labels = [f"{m.month:02d}/{m.year}" for m in months]
        note = ""
        if pm.type != PaymentType.CREDIT_CARD or pm.closing_day is None:
            note = (
                "Esta forma de pagamento não usa fechamento de fatura; "
                "a 1ª parcela cai no mês da compra."
            )
        return JsonResponse({"months": labels, "note": note})


class EntryModalView(HtmxLoginRequiredMixin, View):
    """Serve modal form and handle both regular and installment creation."""

    def get(self, request):
        context = {
            "entry_form": EntryForm(user=request.user),
            "installment_form": InstallmentForm(user=request.user),
        }
        html = render_to_string("partials/_modal_entry_form.html", context, request=request)
        return HttpResponse(html)

    def post(self, request):
        entry_mode = request.POST.get("entry_mode", "regular")

        if entry_mode == "installment":
            form = InstallmentForm(request.POST, user=request.user)
            if form.is_valid():
                plan = form.save(commit=False)
                plan.user = request.user
                plan.save()
                plan.generate_entries()
                response = HttpResponse("")
                trigger = json.dumps(
                    {
                        "showToast": {
                            "message": (
                                f"Parcelamento criado com {plan.num_installments} parcelas!"
                            ),
                            "type": "success",
                        },
                        "entry-saved": True,
                        "entries-changed": True,
                    }
                )
                response["HX-Trigger"] = trigger
                return response
        else:
            form = EntryForm(request.POST, user=request.user)
            if form.is_valid():
                entry = form.save(commit=False)
                entry.user = request.user
                entry.save()
                response = HttpResponse("")
                response["HX-Trigger"] = (
                    '{"showToast": {"message": "Entrada criada!", "type": "success"},'
                    ' "entry-saved": true, "entries-changed": true}'
                )
                return response

        context = {
            "entry_form": (EntryForm(user=request.user) if entry_mode == "installment" else form),
            "installment_form": (
                form if entry_mode == "installment" else InstallmentForm(user=request.user)
            ),
            "errors": True,
        }
        html = render_to_string("partials/_modal_entry_form.html", context, request=request)
        return HttpResponse(html)
