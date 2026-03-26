
import pytest
from model_bakery import baker

from finances.forms import EntryForm, IncomeForm, InstallmentForm, SystemicExpenseForm


@pytest.mark.django_db
class TestEntryForm:
    def test_valid_entry(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "Test entry",
                "category": category.id,
                "payment_method": pm.id,
            },
            user=user,
        )
        assert form.is_valid(), form.errors

    def test_missing_required_fields(self, user):
        form = EntryForm(data={}, user=user)
        assert not form.is_valid()
        assert "date" in form.errors
        assert "amount" in form.errors
        assert "description" in form.errors

    def test_negative_amount_allowed(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "-50.00",
                "description": "Refund",
                "category": category.id,
                "payment_method": pm.id,
            },
            user=user,
        )
        assert form.is_valid()

    def test_filters_categories_by_user(self, user, other_user):
        cat_mine = baker.make("finances.Category", user=user, name="Mine")
        baker.make("finances.Category", user=other_user, name="Theirs")
        form = EntryForm(data={}, user=user)
        assert list(form.fields["category"].queryset) == [cat_mine]

    def test_filters_payment_methods_by_user(self, user, other_user):
        pm_mine = baker.make("finances.PaymentMethod", user=user, name="Mine")
        baker.make("finances.PaymentMethod", user=other_user, name="Theirs")
        form = EntryForm(data={}, user=user)
        assert list(form.fields["payment_method"].queryset) == [pm_mine]


@pytest.mark.django_db
class TestInstallmentForm:
    def test_valid_installment(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=25)
        form = InstallmentForm(
            data={
                "date": "2026-03-15",
                "description": "Notebook",
                "category": category.id,
                "payment_method": pm.id,
                "total_amount": "6699.00",
                "num_installments": "12",
                "installment_amount": "558.25",
            },
            user=user,
        )
        assert form.is_valid(), form.errors

    def test_num_installments_must_be_positive(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user)
        form = InstallmentForm(
            data={
                "date": "2026-03-15",
                "description": "Test",
                "category": category.id,
                "payment_method": pm.id,
                "total_amount": "100.00",
                "num_installments": "0",
                "installment_amount": "50.00",
            },
            user=user,
        )
        assert not form.is_valid()


@pytest.mark.django_db
class TestIncomeForm:
    def test_valid_income(self):
        form = IncomeForm(
            data={
                "name": "Salário",
                "amount": "7854.23",
                "month": "2026-03-01",
                "is_recurring": True,
            }
        )
        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestSystemicExpenseForm:
    def test_valid_systemic(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user)
        form = SystemicExpenseForm(
            data={
                "name": "Enel",
                "category": category.id,
                "payment_method": pm.id,
                "default_amount": "460.00",
            },
            user=user,
        )
        assert form.is_valid(), form.errors
