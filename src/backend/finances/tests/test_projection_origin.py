"""The projection's origin is per household, because 'nothing before Nov 2025
counts' is one household's migration history, not a fact about money."""

from datetime import date

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

    def test_an_empty_household_falls_back_to_its_creation_month(self, household):
        expected = household.created_at.date().replace(day=1)

        assert projection_origin(household) == expected

    def test_no_household_at_all_does_not_raise(self):
        """Fail closed like every other household-less path in this codebase."""
        assert projection_origin(None) is not None


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
