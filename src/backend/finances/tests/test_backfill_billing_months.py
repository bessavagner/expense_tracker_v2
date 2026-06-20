from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from finances.models import Entry
from finances.models.entry import EntryType


def _credit(user, closing_day=25):
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name=f"Cartao {closing_day}",
        type="credit_card",
        closing_day=closing_day,
    )


def _pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


def _entry(
    user, pm, d, billing_month, *, entry_type=EntryType.REGULAR, override=True, amount="100"
):
    return baker.make(
        "finances.Entry",
        user=user,
        date=d,
        amount=Decimal(amount),
        category=baker.make("finances.Category", user=user),
        payment_method=pm,
        entry_type=entry_type,
        billing_month=billing_month,
        billing_month_override=override,
    )


def _run(*args):
    out = StringIO()
    call_command("backfill_billing_months", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestBackfillBillingMonths:
    def test_dry_run_reports_but_does_not_write(self, user):
        pm = _credit(user, closing_day=25)
        # Bought 06/Dec on a card closing on the 25th -> closes Dec -> invoice
        # paid (billed) Jan. Stored wrongly at Dec via a spurious override.
        e = _entry(user, pm, date(2025, 12, 6), date(2025, 12, 1))

        out = _run()  # no --apply

        e.refresh_from_db()
        assert e.billing_month == date(2025, 12, 1)
        assert e.billing_month_override is True
        assert "2026-01" in out  # the corrected month is reported
        assert "DRY-RUN" in out.upper()

    def test_apply_fixes_billing_month_and_clears_override(self, user):
        pm = _credit(user, closing_day=25)
        e = _entry(user, pm, date(2025, 12, 6), date(2025, 12, 1))

        _run("--apply")

        e.refresh_from_db()
        assert e.billing_month == date(2026, 1, 1)
        assert e.billing_month_override is False

    def test_after_closing_day_rolls_to_following_invoice(self, user):
        pm = _credit(user, closing_day=25)
        # Bought 30/Dec, after the 25th -> closes Jan -> billed Feb.
        e = _entry(user, pm, date(2025, 12, 30), date(2025, 12, 1))

        _run("--apply")

        e.refresh_from_db()
        assert e.billing_month == date(2026, 2, 1)

    def test_does_not_touch_already_correct_entries(self, user):
        pm = _pix(user)
        # Pix bills in the purchase month; already correct, no override.
        e = _entry(user, pm, date(2025, 12, 10), date(2025, 12, 1), override=False)

        out = _run("--apply")

        e.refresh_from_db()
        assert e.billing_month == date(2025, 12, 1)
        assert e.billing_month_override is False
        assert "0" in out  # zero entries changed

    def test_ignores_installments_and_systemic(self, user):
        pm = _credit(user, closing_day=25)
        inst = _entry(
            user, pm, date(2025, 12, 6), date(2025, 12, 1), entry_type=EntryType.INSTALLMENT
        )
        sysx = _entry(
            user, pm, date(2025, 12, 6), date(2025, 12, 1), entry_type=EntryType.SYSTEMIC
        )

        _run("--apply")

        inst.refresh_from_db()
        sysx.refresh_from_db()
        assert inst.billing_month == date(2025, 12, 1)
        assert inst.billing_month_override is True
        assert sysx.billing_month == date(2025, 12, 1)
        assert sysx.billing_month_override is True

    def test_is_idempotent(self, user):
        pm = _credit(user, closing_day=25)
        _entry(user, pm, date(2025, 12, 6), date(2025, 12, 1))

        _run("--apply")
        out = _run("--apply")  # second pass

        assert Entry.objects.filter(billing_month_override=True).count() == 0
        assert "0" in out  # nothing left to change
