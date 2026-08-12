"""Which household does a person write into, when there is no request?

The middleware answers that for a request (honouring the session-selected
household). Management commands, the back-fill and the phase-3 write bridge
have no request, so they need this. Keeping the rule here rather than in
`bridge.py` means phase 4 can delete the bridge without deleting the rule.
"""

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from accounts.resolution import household_for_user

pytestmark = pytest.mark.django_db


def test_none_user_has_no_household():
    assert household_for_user(None) is None


def test_returns_the_existing_membership_household(user):
    household = baker.make(Household, name="Casa de vagner")
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    assert household_for_user(user) == household


def test_creates_a_household_when_the_user_has_none(user):
    """Fail closed: a person with no membership writes into their own new
    ledger. Borrowing an existing household would be the leak."""
    resolved = household_for_user(user)

    assert resolved is not None
    assert Membership.objects.filter(user=user, household=resolved).exists()


def test_is_idempotent(user):
    assert household_for_user(user) == household_for_user(user)


def test_user_fixture_has_a_household(user, household):
    """From phase 3 on, every fixture user must resolve to a household —
    otherwise `for_request` returns none() and a view test passes vacuously."""
    assert household_for_user(user) == household


def test_other_user_is_a_different_household(household, other_household):
    assert household != other_household
