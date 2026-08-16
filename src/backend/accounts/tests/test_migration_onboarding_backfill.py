"""The onboarding backfill's *rule*, tested against the live models.

Same shape as `test_migration_seed.py`: replaying a historical migration is
heavier than this project needs, so the rule lives in `migrations_helpers`
and the invariant is asserted here.

The invariant: a household that existed before E11 shipped must never be
routed into the guided setup. It has years of entries; being asked to enter
its income for the first time reads as the product having lost the data.
"""

import pytest
from model_bakery import baker

from accounts.migrations_helpers import mark_existing_households_onboarded
from accounts.models import Household, OnboardingState, OnboardingStep

pytestmark = pytest.mark.django_db

ALL_STEPS = [step.value for step in OnboardingStep]


def test_a_household_that_predates_onboarding_is_marked_complete():
    household = baker.make(Household, name="Casa de bessavagner")

    mark_existing_households_onboarded(Household, OnboardingState, ALL_STEPS)

    assert OnboardingState.objects.get(household=household).is_complete


def test_the_backfill_does_not_invent_a_completion_timestamp():
    """`completed_at` is when a household *went through* setup. These never
    did, and E14's activation cohort reads that column — stamping it here
    would fill the cohort with households that predate the flow."""
    household = baker.make(Household, name="Casa de bessavagner")

    mark_existing_households_onboarded(Household, OnboardingState, ALL_STEPS)

    assert OnboardingState.objects.get(household=household).completed_at is None


def test_the_backfill_leaves_a_household_already_in_the_flow_alone():
    """Idempotent, and non-destructive: migrations get replayed on a rebuilt
    database, and a household halfway through setup must keep its place."""
    household = baker.make(Household, name="Casa nova")
    OnboardingState.objects.create(household=household, steps_done=[OnboardingStep.INCOME.value])

    mark_existing_households_onboarded(Household, OnboardingState, ALL_STEPS)

    state = OnboardingState.objects.get(household=household)
    assert state.steps_done == [OnboardingStep.INCOME.value]
    assert not state.is_complete
    assert OnboardingState.objects.count() == 1
