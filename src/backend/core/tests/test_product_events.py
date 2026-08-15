"""The product-event log: one row shape, one writer, and 'first' as a database fact."""

import pytest
from django.db import IntegrityError

from core.events import EventName, emit, emit_once
from core.models import ProductEvent


@pytest.mark.django_db
class TestEmit:
    def test_emit_writes_a_row_scoped_to_the_household(self, household, user):
        event = emit(
            EventName.ONBOARDING_STEP,
            household=household,
            user=user,
            metadata={"step": "income", "action": "done"},
        )

        assert event.household == household
        assert event.user == user
        assert event.name == EventName.ONBOARDING_STEP
        assert event.metadata == {"step": "income", "action": "done"}
        assert event.once is False

    def test_emit_is_repeatable(self, household, user):
        emit(EventName.ONBOARDING_STEP, household=household, user=user)
        emit(EventName.ONBOARDING_STEP, household=household, user=user)

        assert ProductEvent.objects.for_household(household).count() == 2

    def test_emit_without_a_household_is_a_no_op(self, user):
        """Fail closed like every scoped queryset: no tenant, no row, no crash."""
        assert emit(EventName.ACTIVATED, household=None, user=user) is None
        assert ProductEvent.objects.count() == 0


@pytest.mark.django_db
class TestEmitOnce:
    def test_first_call_returns_the_new_row(self, household, user):
        event = emit_once(EventName.ACTIVATED, household=household, user=user)

        assert event is not None
        assert event.once is True

    def test_second_call_returns_none_and_writes_nothing(self, household, user):
        emit_once(EventName.ACTIVATED, household=household, user=user)

        assert emit_once(EventName.ACTIVATED, household=household, user=user) is None
        assert (
            ProductEvent.objects.for_household(household).filter(name=EventName.ACTIVATED).count()
            == 1
        )

    def test_each_household_activates_independently(self, household, other_household, user):
        assert emit_once(EventName.ACTIVATED, household=household, user=user) is not None
        assert emit_once(EventName.ACTIVATED, household=other_household, user=user) is not None

    def test_the_database_refuses_a_duplicate_once_event(self, household, user):
        """Not merely a convention: two concurrent commits must not both 'activate'."""
        emit_once(EventName.ACTIVATED, household=household, user=user)

        with pytest.raises(IntegrityError):
            ProductEvent.objects.create(household=household, name=EventName.ACTIVATED, once=True)


@pytest.mark.django_db
class TestIsolation:
    def test_one_household_cannot_see_another_households_events(
        self, household, other_household, user
    ):
        emit(EventName.ACTIVATED, household=other_household, user=user)

        assert ProductEvent.objects.for_household(household).count() == 0
