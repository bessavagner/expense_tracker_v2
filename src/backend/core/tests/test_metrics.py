"""Every metric, against a ledger whose answer is known by construction.

Frozen at 2026-08-16 midday UTC: every number here is a function of elapsed days,
so a test that reads the real clock would drift into passing for the wrong reason.
"""

from datetime import UTC, datetime, timedelta

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from core.events import EventName, emit, emit_once
from core.metrics import (
    excluded_shadow_households,
    funnel_counts,
    rolling_retention,
    signup_cohorts,
    wedge_ratio,
)

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


def _household(name):
    return baker.make(Household, name=name)


def _signed_up(household, days_ago):
    row = emit_once(EventName.SIGNUP, household=household)
    when = FROZEN_NOW - timedelta(days=days_ago)
    type(row).objects.filter(pk=row.pk).update(created_at=when)
    return household


def test_cohorts_are_keyed_by_the_monday_of_the_signup_week():
    _signed_up(_household("A"), days_ago=10)

    cohorts = signup_cohorts()

    (monday,) = cohorts.keys()
    assert monday.weekday() == 0


def test_a_household_active_on_day_nine_is_d7_retained():
    """The spec's exact edge case. Rolling retention: day 7 OR LATER counts."""
    household = _signed_up(_household("A"), days_ago=30)
    activity = emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})
    type(activity).objects.filter(pk=activity.pk).update(
        created_at=FROZEN_NOW - timedelta(days=21)  # 9 days after signup
    )

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) == 1.0


def test_a_household_that_never_came_back_is_not_retained():
    _signed_up(_household("A"), days_ago=30)
    # Its only activity is the signup event itself, on day 0.

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) == 0.0


def test_a_cohort_too_young_to_judge_is_excluded_not_counted_as_lost():
    """A household that signed up yesterday cannot have failed D7 yet. Counting
    it as unretained is how a growing beta reports collapsing retention."""
    _signed_up(_household("A"), days_ago=2)

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) is None


def test_the_wedge_ratio_counts_ai_against_manual():
    household = _household("A")
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "chat"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})

    assert wedge_ratio() == (2, 1)


def test_imports_are_excluded_from_the_ratio():
    """A CSV backfill is migration, not capture. Counting it would swamp the one
    number S14-3 calls the most important in the product."""
    household = _household("A")
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})
    emit(
        EventName.ENTRY_CREATED,
        household=household,
        metadata={"source": "import", "count": 2000},
    )

    assert wedge_ratio() == (1, 0)


def test_the_funnel_is_reported_in_order():
    household = _signed_up(_household("A"), days_ago=5)
    emit_once(EventName.ONBOARDING_DONE, household=household)

    steps = [name for name, _ in funnel_counts()]

    assert steps.index("signup") < steps.index("onboarding_done") < steps.index("activated")


def test_an_invited_members_shadow_household_is_excluded(django_user_model):
    """Every signup mints a household even when the user then joins another one.
    Counting those as failed signups understates activation for invited users —
    see docs/architecture/activation-event.md."""
    invitee = baker.make(django_user_model, username="convidado")
    shadow = _signed_up(_household("Casa de convidado"), days_ago=10)
    baker.make(Membership, household=shadow, user=invitee, role=Role.OWNER)
    shared = _household("Casa compartilhada")
    baker.make(Membership, household=shared, user=invitee, role=Role.MEMBER)

    assert shadow.id in excluded_shadow_households()
    assert shared.id not in excluded_shadow_households()


def test_an_activated_household_is_never_treated_as_a_shadow(django_user_model):
    """The guard on the exclusion. A household that reached the product's
    defining moment is a real household, whatever its membership shape."""
    user = baker.make(django_user_model, username="dono")
    house = _signed_up(_household("Casa própria"), days_ago=10)
    baker.make(Membership, household=house, user=user, role=Role.OWNER)
    other = _household("Casa da família")
    baker.make(Membership, household=other, user=user, role=Role.MEMBER)
    emit_once(EventName.ACTIVATED, household=house)

    assert house.id not in excluded_shadow_households()


def test_a_solo_household_is_not_excluded(django_user_model):
    """The other guard: one membership is the ordinary shape of this product."""
    user = baker.make(django_user_model, username="sozinho")
    house = _signed_up(_household("Casa sozinha"), days_ago=10)
    baker.make(Membership, household=house, user=user, role=Role.OWNER)

    assert house.id not in excluded_shadow_households()
