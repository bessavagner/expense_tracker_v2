from datetime import date

import pytest
from model_bakery import baker

from accounts.resolution import household_for_user
from finances.forms import EntryForm, IncomeForm, InstallmentForm, SystemicExpenseForm
from finances.models import Category, Entry, InstallmentPlan, PaymentMethod


@pytest.mark.django_db
class TestEntryForm:
    def test_valid_entry(self, user, household):
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "Test entry",
                "category": category.id,
                "payment_method": pm.id,
            },
            household=household,
        )
        assert form.is_valid(), form.errors

    def test_missing_required_fields(self, user, household):
        form = EntryForm(data={}, household=household)
        assert not form.is_valid()
        assert "date" in form.errors
        assert "amount" in form.errors
        assert "description" in form.errors

    def test_negative_amount_allowed(self, user, household):
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "-50.00",
                "description": "Refund",
                "category": category.id,
                "payment_method": pm.id,
            },
            household=household,
        )
        assert form.is_valid()

    def test_filters_categories_by_household(self, household, other_household):
        cat_mine = baker.make("finances.Category", household=household, name="Mine")
        baker.make("finances.Category", household=other_household, name="Theirs")
        form = EntryForm(data={}, household=household)
        assert list(form.fields["category"].queryset) == [cat_mine]

    def test_filters_payment_methods_by_household(self, household, other_household):
        pm_mine = baker.make("finances.PaymentMethod", household=household, name="Mine")
        baker.make("finances.PaymentMethod", household=other_household, name="Theirs")
        form = EntryForm(data={}, household=household)
        assert list(form.fields["payment_method"].queryset) == [pm_mine]


@pytest.mark.django_db
class TestInstallmentForm:
    def test_valid_installment(self, user, household):
        category = baker.make("finances.Category", household=household)
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=25
        )
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
            household=household,
        )
        assert form.is_valid(), form.errors

    def test_num_installments_must_be_positive(self, user, household):
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household)
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
            household=household,
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
    def test_valid_systemic(self, user, household):
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household)
        form = SystemicExpenseForm(
            data={
                "name": "Enel",
                "category": category.id,
                "payment_method": pm.id,
                "default_amount": "460.00",
            },
            household=household,
        )
        assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_entry_form_date_prefills_iso():
    user = baker.make("core.CustomUser")
    household = household_for_user(user)
    cat = baker.make(Category, household=household)
    pm = baker.make(PaymentMethod, household=household, is_active=True)
    entry = baker.make(
        Entry, household=household, category=cat, payment_method=pm, date=date(2026, 6, 19)
    )
    form = EntryForm(instance=entry, household=household)
    assert 'value="2026-06-19"' in str(form["date"])


@pytest.mark.django_db
def test_installment_form_date_prefills_iso():
    user = baker.make("core.CustomUser")
    household = household_for_user(user)
    cat = baker.make(Category, household=household)
    pm = baker.make(PaymentMethod, household=household, is_active=True)
    plan = baker.make(
        InstallmentPlan,
        household=household,
        category=cat,
        payment_method=pm,
        date=date(2026, 6, 19),
    )
    form = InstallmentForm(instance=plan, household=household)
    assert 'value="2026-06-19"' in str(form["date"])


@pytest.mark.django_db
def test_entry_form_choices_are_household_scoped(user, household, other_user, other_household):
    mine = baker.make("finances.Category", household=household, name="Minha")
    theirs = baker.make("finances.Category", household=other_household, name="Do vizinho")

    form = EntryForm(household=household)
    choices = list(form.fields["category"].queryset)

    assert mine in choices
    assert theirs not in choices


@pytest.mark.django_db
def test_entry_form_without_a_household_offers_nothing(user, household):
    """Fail closed, exactly as `for_household(None)` does — and strictly safer
    than the old `if user:` guard, which left the unfiltered default in place."""
    baker.make("finances.Category", household=household, name="Minha")

    form = EntryForm(household=None)

    assert list(form.fields["category"].queryset) == []
