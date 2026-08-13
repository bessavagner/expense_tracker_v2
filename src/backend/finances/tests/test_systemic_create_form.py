from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from accounts.resolution import household_for_user
from finances.forms import SystemicExpenseCreateForm
from finances.models import Category, Entry, PaymentMethod, SystemicExpense
from finances.models.entry import EntryType


@pytest.fixture
def ctx(db):
    user = baker.make("core.CustomUser")
    household = household_for_user(user)
    cat = baker.make(Category, household=household)
    pm = baker.make(PaymentMethod, household=household, is_active=True)
    return user, household, cat, pm


def _data(cat, pm, **over):
    data = {
        "name": "Netflix",
        "category": cat.id,
        "payment_method": pm.id,
        "default_amount": "39.90",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_non_recurring_creates_template_only(ctx):
    user, household, cat, pm = ctx
    form = SystemicExpenseCreateForm(_data(cat, pm), household=household)
    assert form.is_valid(), form.errors
    systemic, launched = form.save_for_household(household, user)
    assert SystemicExpense.objects.for_household(household).count() == 1
    assert launched == 0
    assert Entry.objects.filter(systemic_expense=systemic).count() == 0


@pytest.mark.django_db
def test_recurring_launches_n_months(ctx):
    user, household, cat, pm = ctx
    form = SystemicExpenseCreateForm(
        _data(cat, pm, is_recurring="on", months="3", start_month="2026-06-01"),
        household=household,
    )
    assert form.is_valid(), form.errors
    systemic, launched = form.save_for_household(household, user)
    assert launched == 3
    months = sorted(
        Entry.objects.filter(systemic_expense=systemic, entry_type=EntryType.SYSTEMIC).values_list(
            "billing_month", flat=True
        )
    )
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    assert Entry.objects.get(billing_month=date(2026, 6, 1)).amount == Decimal("39.90")


@pytest.mark.django_db
def test_recurring_requires_payment_method(ctx):
    _user, household, cat, pm = ctx
    form = SystemicExpenseCreateForm(
        _data(cat, pm, payment_method="", is_recurring="on", months="2", start_month="2026-06-01"),
        household=household,
    )
    assert not form.is_valid()
    assert "payment_method" in form.errors
