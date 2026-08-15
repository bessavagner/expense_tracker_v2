"""The projection's origin is per household, because 'nothing before Nov 2025
counts' is one household's migration history, not a fact about money."""

from datetime import UTC, date, datetime

import pytest
from model_bakery import baker

from finances.services.projection import projection_origin


@pytest.mark.django_db
class TestOrigin:
    def test_an_explicit_origin_wins(self, household):
        household.projection_origin_month = date(2025, 11, 1)
        household.save(update_fields=["projection_origin_month"])

        assert projection_origin(household) == date(2025, 11, 1)

    def test_without_one_it_is_the_first_month_with_data(self, household, user):
        baker.make(
            "finances.Income",
            household=household,
            created_by=user,
            month=date(2026, 3, 1),
            amount=1000,
        )

        assert projection_origin(household) == date(2026, 3, 1)

    def test_an_entry_counts_as_data_too(self, household, user):
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make(
            "finances.PaymentMethod", household=household, created_by=user, type="pix"
        )
        baker.make(
            "finances.Entry",
            household=household,
            created_by=user,
            category=category,
            payment_method=payment,
            date=date(2026, 2, 10),
            amount=10,
        )

        assert projection_origin(household) == date(2026, 2, 1)

    def test_the_earliest_of_the_two_wins(self, household, user):
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make(
            "finances.PaymentMethod", household=household, created_by=user, type="pix"
        )
        baker.make(
            "finances.Entry",
            household=household,
            created_by=user,
            category=category,
            payment_method=payment,
            date=date(2026, 2, 10),
            amount=10,
        )
        baker.make(
            "finances.Income",
            household=household,
            created_by=user,
            month=date(2026, 1, 1),
            amount=1000,
        )

        assert projection_origin(household) == date(2026, 1, 1)

    def test_no_household_at_all_does_not_raise(self):
        """Fail closed like every other household-less path in this codebase."""
        assert projection_origin(None) is not None


@pytest.mark.django_db
class TestEmptyHouseholdFallback:
    """Split out so the clock can be frozen (global constraint 10: no
    date-sensitive test may read the unfrozen wall clock). Frozen at midday
    UTC — the documented default — specifically so the local and UTC
    calendar day agree: this test is about the creation-month fallback
    itself, not the UTC/America-Sao_Paulo day boundary that
    `TestOriginTimezoneBoundary` below exists to cover. An unfrozen or
    midnight-frozen clock would make this test's own two sides of the
    assertion (`household.created_at.date()` vs. `projection_origin`'s
    localtime result) disagree whenever the run happens to land in that
    boundary window.
    """

    FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(self.FROZEN_NOW, tick=False)

    def test_an_empty_household_falls_back_to_its_creation_month(self, household):
        expected = household.created_at.date().replace(day=1)

        assert projection_origin(household) == expected


@pytest.mark.django_db
class TestOriginTimezoneBoundary:
    """`created_at` is UTC-aware; naively taking `.date()` on it misdates a
    household created late in the evening in the app's own timezone.

    Frozen right at the boundary that makes the requirement observable:
    01:00 UTC on Feb 1st is 22:00 on Jan 31st in America/Sao_Paulo (fixed
    UTC-3, no DST since 2019). Raw UTC `.date()` would say Feb; the
    household's own calendar day is still Jan 31st.
    """

    FROZEN_NOW = datetime(2026, 2, 1, 1, 0, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(self.FROZEN_NOW, tick=False)

    def test_creation_month_uses_the_app_timezone_not_utc(self, household):
        assert projection_origin(household) == date(2026, 1, 1)


@pytest.mark.django_db
class TestImportedHistory:
    def test_history_older_than_the_old_global_floor_is_kept(self, household, user):
        """A CSV import of 2024 must not be silently discarded, which is exactly
        what a global 2025-11 floor did."""
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make(
            "finances.PaymentMethod", household=household, created_by=user, type="pix"
        )
        baker.make(
            "finances.Entry",
            household=household,
            created_by=user,
            category=category,
            payment_method=payment,
            date=date(2024, 5, 3),
            amount=10,
        )

        assert projection_origin(household) == date(2024, 5, 1)
