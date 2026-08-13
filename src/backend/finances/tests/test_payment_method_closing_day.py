from datetime import date

import pytest
from model_bakery import baker

from finances.models import PaymentMethodClosingDay
from finances.services.billing import resolve_closing_day


@pytest.mark.django_db
class TestPaymentMethodClosingDay:
    def test_create_per_month_closing_day(self, household):
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=30
        )
        cd = PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 1, 1), closing_day=28
        )
        assert cd.payment_method == pm
        assert cd.month == date(2026, 1, 1)
        assert cd.closing_day == 28

    def test_unique_per_payment_method_and_month(self, household):
        from django.db import IntegrityError

        pm = baker.make("finances.PaymentMethod", household=household, type="credit_card")
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 1, 1), closing_day=28
        )
        with pytest.raises(IntegrityError):
            PaymentMethodClosingDay.objects.create(
                payment_method=pm, month=date(2026, 1, 1), closing_day=25
            )


@pytest.mark.django_db
class TestResolveClosingDay:
    def test_uses_per_month_override_when_present(self, household):
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=30
        )
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 1, 1), closing_day=28
        )
        assert resolve_closing_day(pm, date(2026, 1, 15)) == 28

    def test_falls_back_to_default_closing_day(self, household):
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=30
        )
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 1, 1), closing_day=28
        )
        # February has no override -> default
        assert resolve_closing_day(pm, date(2026, 2, 10)) == 30

    def test_falls_back_when_no_overrides_at_all(self, household):
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=25
        )
        assert resolve_closing_day(pm, date(2026, 5, 3)) == 25

    def test_returns_none_for_non_credit(self, household):
        pm = baker.make("finances.PaymentMethod", household=household, type="pix", closing_day=None)
        assert resolve_closing_day(pm, date(2026, 5, 3)) is None


@pytest.mark.django_db
class TestEntryUsesPerMonthClosingDay:
    def test_entry_billing_month_respects_per_month_override(self, household):
        pm = baker.make(
            "finances.PaymentMethod",
            household=household,
            name="Crédito C6",
            type="credit_card",
            closing_day=25,
        )
        # January override: closing day 23 -> a Jan 24 purchase is after closing,
        # so its invoice closes in February and is paid in March.
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 1, 1), closing_day=23
        )
        category = baker.make("finances.Category", household=household)
        entry = baker.make(
            "finances.Entry",
            household=household,
            date=date(2026, 1, 24),
            category=category,
            payment_method=pm,
            billing_month_override=False,
        )
        entry.refresh_from_db()
        assert entry.billing_month == date(2026, 3, 1)
