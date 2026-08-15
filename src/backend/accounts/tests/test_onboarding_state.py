"""Guided setup must be resumable: a phone loses a session mid-signup constantly."""

import pytest

from accounts.models import OnboardingState, OnboardingStep


@pytest.mark.django_db
class TestOnboardingState:
    # These tests are about a fresh household's progress through the flow, so
    # they ask for `new_household` — the shared `household` fixture arrives
    # already onboarded (see conftest), which would make every assertion here
    # about "the first step" false.
    def test_a_fresh_household_starts_at_the_first_step(self, new_household):
        state = OnboardingState.for_household(new_household)

        assert state.next_step() == OnboardingStep.INCOME
        assert state.is_complete is False

    def test_for_household_is_idempotent(self, new_household):
        first = OnboardingState.for_household(new_household)
        second = OnboardingState.for_household(new_household)

        assert first.pk == second.pk
        assert OnboardingState.objects.filter(household=new_household).count() == 1

    def test_marking_a_step_advances_to_the_next(self, new_household):
        state = OnboardingState.for_household(new_household)

        state.mark(OnboardingStep.INCOME)

        assert state.next_step() == OnboardingStep.CARDS

    def test_marking_the_same_step_twice_does_not_skip_one(self, new_household):
        state = OnboardingState.for_household(new_household)

        state.mark(OnboardingStep.INCOME)
        state.mark(OnboardingStep.INCOME)

        assert state.next_step() == OnboardingStep.CARDS
        assert state.steps_done == [OnboardingStep.INCOME]

    def test_progress_survives_a_reload(self, new_household):
        OnboardingState.for_household(new_household).mark(OnboardingStep.INCOME)

        assert OnboardingState.for_household(new_household).next_step() == OnboardingStep.CARDS

    def test_marking_every_step_completes_it(self, new_household):
        state = OnboardingState.for_household(new_household)

        for step in OnboardingStep:
            state.mark(step)

        assert state.next_step() is None
        assert state.is_complete is True
        assert state.completed_at is not None

    def test_completion_timestamp_is_not_overwritten(self, new_household):
        state = OnboardingState.for_household(new_household)
        for step in OnboardingStep:
            state.mark(step)
        first_completion = state.completed_at

        state.mark(OnboardingStep.CAPTURE)

        assert state.completed_at == first_completion

    def test_the_flow_is_at_most_five_steps(self):
        """S11-3 and the industry standard it cites. A guard, not a formality."""
        assert len(OnboardingStep) <= 5

    def test_each_household_has_its_own_progress(self, new_household, other_user):
        from accounts.resolution import household_for_user

        OnboardingState.for_household(new_household).mark(OnboardingStep.INCOME)

        other_fresh_household = household_for_user(other_user)
        assert OnboardingState.for_household(other_fresh_household).next_step() == (
            OnboardingStep.INCOME
        )
