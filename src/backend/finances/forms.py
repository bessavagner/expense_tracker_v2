from datetime import date as _date

from django import forms
from django.core.validators import MinValueValidator

from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)
from finances.services.dates import add_months


class EntryForm(forms.ModelForm):
    class Meta:
        model = Entry
        fields = ["date", "amount", "description", "category", "payment_method"]
        labels = {
            "date": "Data",
            "amount": "Valor",
            "description": "Descrição",
            "category": "Categoria",
            "payment_method": "Forma de pagamento",
        }
        widgets = {
            "date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "amount": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "class": "input input-bordered input-sm w-full",
                    "placeholder": "R$ 0,00",
                }
            ),
            "description": forms.TextInput(
                attrs={"class": "input input-bordered input-sm w-full", "placeholder": "Descrição"}
            ),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(
                attrs={"class": "select select-bordered select-sm w-full"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )


class InstallmentForm(forms.ModelForm):
    class Meta:
        model = InstallmentPlan
        fields = [
            "date",
            "description",
            "category",
            "payment_method",
            "total_amount",
            "num_installments",
            "installment_amount",
        ]
        labels = {
            "date": "Data",
            "description": "Descrição",
            "category": "Categoria",
            "payment_method": "Forma de pagamento",
            "total_amount": "Valor total",
            "num_installments": "Parcelas",
            "installment_amount": "Valor da parcela",
        }
        widgets = {
            "date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "description": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(
                attrs={"class": "select select-bordered select-sm w-full"}
            ),
            "total_amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
            "num_installments": forms.NumberInput(
                attrs={"min": "1", "class": "input input-bordered input-sm w-full"}
            ),
            "installment_amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )
        self.fields["num_installments"].validators.append(MinValueValidator(1))


class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = ["name", "amount", "month", "is_recurring", "recurrence_start", "recurrence_end"]
        labels = {
            "name": "Nome",
            "amount": "Valor",
            "month": "Mês",
            "is_recurring": "Recorrente",
            "recurrence_start": "Início da recorrência",
            "recurrence_end": "Fim da recorrência",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
            "month": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "is_recurring": forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
            "recurrence_start": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "recurrence_end": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
        }

    def clean_month(self):
        return self.cleaned_data["month"].replace(day=1)


class CockpitIncomeForm(forms.ModelForm):
    repeat_until_december = forms.BooleanField(required=False)

    class Meta:
        model = Income
        fields = ["name", "amount", "month"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "input input-bordered input-sm w-full",
                    "placeholder": "Nome (ex.: Salário)",
                }
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "input input-bordered input-sm w-full",
                    "step": "0.01",
                    "placeholder": "Valor (R$)",
                }
            ),
            "month": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
        }

    def save_for_user(self, user):
        """Create one Income per target month; returns the created list."""
        base = self.cleaned_data
        start = base["month"].replace(day=1)
        if self.cleaned_data.get("repeat_until_december"):
            months = [_date(start.year, m, 1) for m in range(start.month, 13)]
        else:
            months = [start]
        created = []
        recurring = len(months) > 1
        for m in months:
            created.append(
                Income.objects.create(
                    user=user,
                    name=base["name"],
                    amount=base["amount"],
                    month=m,
                    is_recurring=recurring,
                    recurrence_start=months[0] if recurring else None,
                    recurrence_end=months[-1] if recurring else None,
                )
            )
        return created


class SystemicExpenseForm(forms.ModelForm):
    class Meta:
        model = SystemicExpense
        fields = ["name", "category", "payment_method", "default_amount"]
        labels = {
            "name": "Nome",
            "category": "Categoria",
            "payment_method": "Forma de pagamento",
            "default_amount": "Valor padrão",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(
                attrs={"class": "select select-bordered select-sm w-full"}
            ),
            "default_amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )
            self.fields["payment_method"].required = False


class SystemicEntryEditForm(forms.Form):
    """Edit a launched systemic: the template name + this month's entry fields."""

    name = forms.CharField(
        max_length=100,
        label="Nome",
        widget=forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
    )
    date = forms.DateField(
        label="Data",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
        ),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        label="Valor",
        widget=forms.NumberInput(
            attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
        ),
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        label="Categoria",
        widget=forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
    )
    payment_method = forms.ModelChoiceField(
        queryset=PaymentMethod.objects.none(),
        label="Forma de pagamento",
        widget=forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
    )

    def __init__(self, *args, entry=None, user=None, **kwargs):
        self.entry = entry
        super().__init__(*args, **kwargs)
        cats = Category.objects.filter(user=user)
        pms = PaymentMethod.objects.filter(user=user, is_active=True)
        if entry is not None:
            cats = cats | Category.objects.filter(pk=entry.category_id)
            pms = pms | PaymentMethod.objects.filter(pk=entry.payment_method_id)
        self.fields["category"].queryset = cats
        self.fields["payment_method"].queryset = pms
        if not self.is_bound and entry is not None:
            self.fields["name"].initial = entry.systemic_expense.name
            self.fields["date"].initial = entry.date
            self.fields["amount"].initial = entry.amount
            self.fields["category"].initial = entry.category_id
            self.fields["payment_method"].initial = entry.payment_method_id

    def save(self):
        cd = self.cleaned_data
        systemic = self.entry.systemic_expense
        systemic.name = cd["name"]
        systemic.save(update_fields=["name", "updated_at"])
        from finances.models import Entry
        Entry.objects.filter(systemic_expense=systemic).update(description=cd["name"])
        self.entry.date = cd["date"]
        self.entry.amount = cd["amount"]
        self.entry.category = cd["category"]
        self.entry.payment_method = cd["payment_method"]
        self.entry.description = cd["name"]
        self.entry.save()
        return self.entry


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "type", "closing_day"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "type": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "closing_day": forms.NumberInput(
                attrs={"min": "1", "max": "31", "class": "input input-bordered input-sm w-full"}
            ),
        }


class CategoryBudgetForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["budget_ceiling"]
        widgets = {
            "budget_ceiling": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
        }


class CategoryCreateForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "budget_ceiling"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "budget_ceiling": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
        }


class SystemicExpenseCreateForm(SystemicExpenseForm):
    """Create a systemic template; optionally launch N months immediately."""

    is_recurring = forms.BooleanField(
        required=False,
        label="Recorrente por N meses",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm", "x-model": "recurring"}),
    )
    months = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=60,
        label="Nº de meses",
        widget=forms.NumberInput(
            attrs={"min": "1", "class": "input input-bordered input-sm w-full"}
        ),
    )
    start_month = forms.DateField(
        required=False,
        label="Mês inicial",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
        ),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_recurring"):
            if not cleaned.get("months"):
                self.add_error("months", "Informe o número de meses.")
            if not cleaned.get("payment_method"):
                self.add_error(
                    "payment_method",
                    "Forma de pagamento é obrigatória para recorrência.",
                )
        return cleaned

    def save_for_user(self, user):
        systemic = self.save(commit=False)
        systemic.user = user
        systemic.save()
        launched = 0
        if self.cleaned_data.get("is_recurring"):
            n = self.cleaned_data.get("months") or 1
            start = (self.cleaned_data.get("start_month") or _date.today()).replace(day=1)
            for i in range(n):
                systemic.create_monthly_entry(add_months(start, i))
                launched += 1
        return systemic, launched
