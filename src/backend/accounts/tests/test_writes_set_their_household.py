"""Every write path sets `household` itself.

Written in Task 10 against a still-present bridge, which these tests had to
disconnect by hand to prove anything. The bridge is gone, so they now exercise
the real thing rather than a simulation of it.

Keep them: these are the four sites that were leaning on it, and the ones a
future refactor is most likely to break. A regression here is an IntegrityError
in production, because `household` is NOT NULL from phase 4 on.
"""

from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db


def test_a_systemic_expense_carries_its_household_into_its_entries(user, household):
    category = baker.make("finances.Category", household=household, name="Casa")
    pm = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    template = baker.make(
        "finances.SystemicExpense",
        household=household,
        created_by=user,
        category=category,
        payment_method=pm,
        default_amount=Decimal("100.00"),
    )

    entry = template.create_monthly_entry(date(2026, 3, 1))

    assert entry.household == household
    assert entry.created_by == user


def test_seed_data_writes_into_a_household(user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).exists()


def test_seed_data_is_idempotent_per_household(user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())
    before = Category.objects.for_household(household).count()
    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).count() == before
