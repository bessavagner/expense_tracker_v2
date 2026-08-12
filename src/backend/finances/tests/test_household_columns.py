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
    NOT NULL arrives in phase 4, once every write path sets it."""
    entry = baker.make("finances.Entry", user=user, household=None)

    assert entry.household_id is None
