import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps as global_apps
from model_bakery import baker

_migration = importlib.import_module("finances.migrations.0008_freeze_credit_card_billing_month")
freeze_credit_entries = _migration.freeze_credit_entries


@pytest.mark.django_db
class TestFreezeCreditEntries:
    def _entry(self, household, pm, billing_month, entry_type="regular", override=False):
        category = baker.make("finances.Category", household=household)
        return baker.make(
            "finances.Entry",
            household=household,
            date=date(2026, 3, 10),
            amount=Decimal("10.00"),
            category=category,
            payment_method=pm,
            entry_type=entry_type,
            billing_month=billing_month,
            # Pin so model_bakery's save() doesn't recompute before we test.
            billing_month_override=override or True,
        )

    def test_credit_entries_frozen_without_changing_month(self, household):
        credit = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=25
        )
        cash = baker.make("finances.PaymentMethod", household=household, type="cash")

        # Simulate historical rows that were NOT yet frozen.
        from finances.models import Entry

        credit_entry = self._entry(household, credit, date(2026, 3, 1))
        cash_entry = self._entry(household, cash, date(2026, 3, 1))
        Entry.objects.filter(pk__in=[credit_entry.pk, cash_entry.pk]).update(
            billing_month_override=False
        )

        freeze_credit_entries(global_apps, None)

        credit_entry.refresh_from_db()
        cash_entry.refresh_from_db()

        # Month is never touched, for either.
        assert credit_entry.billing_month == date(2026, 3, 1)
        assert cash_entry.billing_month == date(2026, 3, 1)
        # Only the credit-card entry gets frozen.
        assert credit_entry.billing_month_override is True
        assert cash_entry.billing_month_override is False

    def test_already_frozen_entries_left_as_is(self, household):
        credit = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=25
        )
        # An installment-style entry already frozen with a hand-picked month.
        entry = self._entry(
            household, credit, date(2026, 5, 1), entry_type="installment", override=True
        )

        freeze_credit_entries(global_apps, None)

        entry.refresh_from_db()
        assert entry.billing_month == date(2026, 5, 1)
        assert entry.billing_month_override is True
