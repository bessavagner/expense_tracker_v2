"""E04 phase 2: the finances domain models carry a household.

Deliberately narrow. This phase adds columns and does not change a single
read path, so these tests assert the columns exist, default to NULL, and route
through the scoped manager — nothing about views or services.
"""

import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


def test_entry_carries_household_and_created_by(user):
    household = baker.make(Household, name="Casa Bessa")
    entry = baker.make("finances.Entry", user=user, household=household, created_by=user)

    assert entry.household == household
    assert entry.created_by == user


def test_entry_scopes_through_the_household_manager(user):
    from finances.models import Entry

    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make("finances.Entry", user=user, household=ours)
    baker.make("finances.Entry", user=user, household=theirs)

    assert Entry.objects.for_household(ours).count() == 1
    assert Entry.objects.for_household(None).count() == 0


def test_entry_household_may_be_null_during_the_transition(user):
    """Phases 2 and 3 run with both columns and a partially-converted app.
    NOT NULL arrives in phase 4, once every write path sets it.

    The write goes through a queryset ``.update()`` because the phase 2 bridge
    refills any household a normal save leaves empty — so the only way to ask
    the database whether the column still accepts NULL is to bypass signals.
    """
    from finances.models import Entry

    entry = baker.make("finances.Entry", user=user)
    Entry.objects.filter(pk=entry.pk).update(household=None)
    entry.refresh_from_db()

    assert entry.household_id is None


FINANCES_HOUSEHOLD_MODELS = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
]


@pytest.mark.parametrize("label", FINANCES_HOUSEHOLD_MODELS)
def test_model_carries_household_and_created_by(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    household = baker.make(Household)
    row = baker.make(model, user=user, household=household, created_by=user)

    assert row.household == household
    assert row.created_by == user


@pytest.mark.parametrize("label", FINANCES_HOUSEHOLD_MODELS)
def test_model_scopes_through_the_household_manager(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household)
    theirs = baker.make(Household)
    baker.make(model, user=user, household=ours)
    baker.make(model, user=user, household=theirs)

    assert model.objects.for_household(ours).count() == 1


def test_closing_day_is_scoped_through_its_payment_method_only(user):
    """Decision 4, asserted rather than assumed: PaymentMethodClosingDay has
    no household of its own, and must reach one only via its parent."""
    from finances.models import PaymentMethodClosingDay

    field_names = {f.name for f in PaymentMethodClosingDay._meta.get_fields()}
    assert "household" not in field_names
    assert "payment_method" in field_names
