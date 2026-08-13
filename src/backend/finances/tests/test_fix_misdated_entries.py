"""Correct year-typo dates: regular entries logged in 2025 months 1-9.

The user's records begin Oct/2025, so a regular entry dated Jan-Sep 2025 is an
impossible date — a data-entry typo where the year should be 2026 (the row
physically lives in a 2026 monthly import table). The app billed them to a
pre-origin month, so they vanished from the projection; this restores them.

Installments and systemics are never touched; legitimate Oct/2025 (pre-origin)
data is never touched.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from finances.models.entry import EntryType


def _entry(household, pm, d, *, entry_type=EntryType.REGULAR, amount="100"):
    return baker.make(
        "finances.Entry",
        household=household,
        date=d,
        amount=Decimal(amount),
        category=baker.make("finances.Category", household=household),
        payment_method=pm,
        entry_type=entry_type,
        billing_month=d.replace(day=1),
        billing_month_override=False,
    )


def _pix(household):
    return baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")


def _credit(household, closing_day=25):
    return baker.make(
        "finances.PaymentMethod",
        household=household,
        name="C6",
        type="credit_card",
        closing_day=closing_day,
    )


def _run(*args):
    out = StringIO()
    call_command("fix_misdated_entries", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestFixMisdatedEntries:
    def test_dry_run_reports_but_does_not_write(self, household):
        e = _entry(household, _pix(household), date(2025, 1, 5))

        out = _run()  # no --apply

        e.refresh_from_db()
        assert e.date == date(2025, 1, 5)
        assert "2025-01-05" in out and "2026-01-05" in out
        assert "DRY-RUN" in out.upper()

    def test_apply_shifts_year_and_recomputes_billing_pix(self, household):
        e = _entry(household, _pix(household), date(2025, 1, 5))

        _run("--apply")

        e.refresh_from_db()
        assert e.date == date(2026, 1, 5)
        assert e.billing_month == date(2026, 1, 1)  # pix bills in purchase month

    def test_apply_recomputes_billing_for_credit(self, household):
        # 05/01 on a card closing the 25th -> closes Jan -> billed Feb/2026.
        e = _entry(household, _credit(household, 25), date(2025, 1, 5))

        _run("--apply")

        e.refresh_from_db()
        assert e.date == date(2026, 1, 5)
        assert e.billing_month == date(2026, 2, 1)

    def test_ignores_october_2025_and_2026(self, household):
        pix = _pix(household)
        oct25 = _entry(household, pix, date(2025, 10, 15))  # legit pre-origin
        in26 = _entry(household, pix, date(2026, 1, 10))

        _run("--apply")

        oct25.refresh_from_db()
        in26.refresh_from_db()
        assert oct25.date == date(2025, 10, 15)
        assert in26.date == date(2026, 1, 10)

    def test_ignores_installment_and_systemic(self, household):
        pix = _pix(household)
        inst = _entry(household, pix, date(2025, 1, 5), entry_type=EntryType.INSTALLMENT)
        sysx = _entry(household, pix, date(2025, 1, 5), entry_type=EntryType.SYSTEMIC)

        _run("--apply")

        inst.refresh_from_db()
        sysx.refresh_from_db()
        assert inst.date == date(2025, 1, 5)
        assert sysx.date == date(2025, 1, 5)
