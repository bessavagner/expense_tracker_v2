"""Every write path sets `household` itself, with the bridge disconnected.

The bridge is a pre_save receiver that fills a missing household from the
writer's user. Task 12 deletes it, and at that moment any write site that was
leaning on it starts producing tenant-less rows — which the NOT NULL migration
in the same task turns into an IntegrityError in production.

Rather than wait for that, this disconnects the receiver and exercises the four
sites that were still leaning on it as of 2026-08-13.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db.models.signals import pre_save
from model_bakery import baker

from accounts.bridge import fill_household
from accounts.models import household_owned_models

pytestmark = pytest.mark.django_db


@pytest.fixture
def without_the_bridge():
    """Phase 4's end state, one task early."""
    for model in household_owned_models():
        pre_save.disconnect(
            fill_household,
            sender=model,
            dispatch_uid=f"e04_bridge_{model._meta.label_lower}",
        )
    yield
    from accounts.bridge import connect

    connect()


def test_a_systemic_expense_carries_its_household_into_its_entries(
    without_the_bridge, user, household
):
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


def test_seed_data_writes_into_a_household(without_the_bridge, user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).exists()
    assert not Category.objects.filter(household__isnull=True).exists()


def test_seed_data_is_idempotent_per_household(without_the_bridge, user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())
    before = Category.objects.for_household(household).count()
    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).count() == before
