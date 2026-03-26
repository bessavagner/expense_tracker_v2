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
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full", "placeholder": "R$ 0,00"}),
            "description": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full", "placeholder": "Descrição"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
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
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "description": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "total_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
            "num_installments": forms.NumberInput(attrs={"min": "1", "class": "input input-bordered input-sm w-full"}),
            "installment_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
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
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
            "month": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
            "recurrence_start": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "recurrence_end": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
        }


class SystemicExpenseForm(forms.ModelForm):
    class Meta:
        model = SystemicExpense
        fields = ["name", "category", "payment_method", "default_amount"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "default_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
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
            "closing_day": forms.NumberInput(attrs={"min": "1", "max": "31", "class": "input input-bordered input-sm w-full"}),
        }


class CategoryBudgetForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["budget_ceiling"]
        widgets = {
            "budget_ceiling": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }


class CategoryCreateForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "budget_ceiling"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "budget_ceiling": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }
