"""The seed migration's *rule*, tested against the live models.

Testing a historical migration by replaying it (django-test-migrations) is
heavier than this project needs. What matters is the invariant the rest of
E04 leans on, so assert the invariant and keep the helper the migration
calls in one place.
"""

import pytest
from django.contrib.auth import get_user_model
from model_bakery import baker

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


def test_seed_creates_one_household_and_an_owner_membership():
    user = baker.make(get_user_model(), username="bessavagner")

    seed_household_for_user(Household, Membership, user)

    membership = Membership.objects.get(user=user)
    assert membership.role == Role.OWNER
    assert membership.household.name == "Casa de bessavagner"


def test_seed_clips_a_household_name_that_would_not_fit():
    """A username may be 150 characters; Household.name holds 120. The name is
    a label, not an identifier, so it gets clipped rather than blowing up the
    insert with StringDataRightTruncation."""
    user = baker.make(get_user_model(), username="v" * 150)

    household = seed_household_for_user(Household, Membership, user)

    assert len(household.name) == 120
    assert household.name.startswith("Casa de vvv")


def test_seed_is_idempotent():
    """Re-running must not create a second household — migrations get replayed
    on a rebuilt database more often than anyone expects."""
    user = baker.make(get_user_model(), username="bessavagner")

    seed_household_for_user(Household, Membership, user)
    seed_household_for_user(Household, Membership, user)

    assert Membership.objects.filter(user=user).count() == 1
    assert Household.objects.count() == 1
