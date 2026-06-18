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
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"}
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
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"}
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
