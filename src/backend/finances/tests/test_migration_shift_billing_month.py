import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps as global_apps
from model_bakery import baker

_migration = importlib.import_module(
    "finances.migrations.0008_shift_credit_card_billing_month"
)
_shift_month = _migration._shift_month
_shift_credit_entries = _migration._shift_credit_entries


class TestShiftMonthHelper:
    def test_forward_within_year(self):
        assert _shift_month(date(2026, 3, 1), 1) == date(2026, 4, 1)

    def test_forward_crosses_year(self):
        assert _shift_month(date(2025, 12, 1), 1) == date(2026, 1, 1)

    def test_backward_crosses_year(self):
        assert _shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)


@pytest.mark.django_db
class TestShiftCreditEntries:
    def _entry(self, user, pm, billing_month, entry_type="regular"):
        category = baker.make("finances.Category", user=user)
        return baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 10),
            amount=Decimal("10.00"),
            category=category,
            payment_method=pm,
            entry_type=entry_type,
            billing_month=billing_month,
            billing_month_override=True,
        )

    def test_credit_regular_shifts_forward_and_others_untouched(self, user):
        credit = baker.make(
            "finances.PaymentMethod", user=user, type="credit_card", closing_day=25
        )
        cash = baker.make("finances.PaymentMethod", user=user, type="cash")

        credit_entry = self._entry(user, credit, date(2026, 3, 1))
        cash_entry = self._entry(user, cash, date(2026, 3, 1))
        systemic_entry = self._entry(user, credit, date(2026, 3, 1), entry_type="systemic")

        _shift_credit_entries(global_apps, 1)

        credit_entry.refresh_from_db()
        cash_entry.refresh_from_db()
        systemic_entry.refresh_from_db()

        assert credit_entry.billing_month == date(2026, 4, 1)  # shifted
        assert cash_entry.billing_month == date(2026, 3, 1)  # untouched
        assert systemic_entry.billing_month == date(2026, 3, 1)  # untouched
