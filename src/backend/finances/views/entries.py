import json
from datetime import date
from decimal import Decimal

from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, UpdateView

from finances.forms import EntryForm, InstallmentForm
from finances.models import Entry
from finances.models.entry import EntryType
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
            Entry.objects.filter(
                user=self.request.user,
                billing_month=billing_month,
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
                '{"showToast": {"message": "Entrada criada!", "type": "success"}}'
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
            '{"showToast": {"message": "Entrada atualizada!", "type": "success"}}'
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
            '{"showToast": {"message": "Entrada excluída!", "type": "success"}}'
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
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_edit_form.html",
            self._modal_context(entry, form),
            request=request,
        )
        return HttpResponse(html)


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
                    ' "entry-saved": true}'
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
