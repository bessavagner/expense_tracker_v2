"""The back-fill's *rule*, tested against the live models.

Same approach as phase 1's test_migration_seed: replaying a historical
migration is heavier than this project needs. What matters is that every
pre-existing row lands in its author's household with its author recorded,
and that re-running changes nothing.
"""

import pytest
from django.apps import apps as django_apps
from model_bakery import baker

from accounts.backfill import backfill_household_columns
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def owned_household(user):
    household = baker.make(Household, name="Casa de vagner")
    baker.make(Membership, user=user, household=household, role=Role.OWNER)
    return household


def _run():
    return backfill_household_columns(
        Membership,
        {"finances.Entry": django_apps.get_model("finances.Entry")},
    )


def _make_unfilled_entry(user):
    """A row as it exists in production before the back-fill: the bridge is a
    phase 2 invention, so pre-E04 rows have no household at all.

    A queryset ``.update()`` bypasses signals, which is exactly why it is the
    right tool here — ``baker.make(household=None)`` would just be refilled by
    the bridge before it ever reached the database.
    """
    from finances.models import Entry

    entry = baker.make("finances.Entry", user=user)
    Entry.objects.filter(pk=entry.pk).update(household=None, created_by=None)
    entry.refresh_from_db()
    return entry


def test_backfill_sets_household_from_the_owner_membership(user, owned_household):
    entry = _make_unfilled_entry(user)

    _run()

    entry.refresh_from_db()
    assert entry.household == owned_household
    assert entry.created_by == user


def test_backfill_leaves_already_filled_rows_alone(user, owned_household):
    """Idempotence, and the safety property that matters: a row already
    assigned to a household must never be moved to another one."""
    other = baker.make(Household, name="Outra")
    entry = baker.make("finances.Entry", user=user, household=other)

    _run()
    _run()

    entry.refresh_from_db()
    assert entry.household == other


def test_backfill_skips_a_user_with_no_membership(user):
    """Fails closed. A user with no household leaves their rows NULL rather
    than borrowing somebody's ledger — phase 4's NOT NULL will surface it."""
    entry = _make_unfilled_entry(user)
    # The bridge gave the writer a membership on the way in. Take it away
    # again: the state this test is about is a *pre-E04* row whose user the
    # seed migration never covered.
    Membership.objects.filter(user=user).delete()

    _run()

    entry.refresh_from_db()
    assert entry.household_id is None


def test_backfill_reports_what_it_touched(user, owned_household):
    for _ in range(3):
        _make_unfilled_entry(user)

    counts = _run()

    assert counts["finances.Entry"] == 3
