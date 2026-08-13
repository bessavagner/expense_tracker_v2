"""The before/after fingerprint used to prove the E04 migration is lossless.

Alone among the converted test modules, these rows still carry `user=` as well
as `household=`. The command under test aggregates by user on purpose — it
fingerprints the ledger exactly as the pre-E04 code did, which is the only
reason its before/after comparison proves anything — and it is re-pointed at
household in the same commit that drops the column (phase 4, Task 13). The
`user=` kwargs below go with it.
"""

import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

pytestmark = pytest.mark.django_db


def test_dump_reports_per_user_totals_and_acumulado(user, household):
    category = baker.make("finances.Category", user=user, household=household, name="Alimentação")
    pix = baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )
    baker.make(
        "finances.Entry",
        user=user,
        household=household,
        date=date(2026, 3, 10),
        amount=Decimal("50.00"),
        description="Feira",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 3, 1),
    )
    baker.make(
        "finances.Income",
        user=user,
        household=household,
        amount=Decimal("100.00"),
        month=date(2026, 3, 1),
    )

    out = StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out)
    report = json.loads(out.getvalue())

    ledger = report["vagner"]
    assert ledger["entry_count"] == 1
    assert ledger["entry_sum"] == "50.00"
    assert ledger["income_sum"] == "100.00"
    assert any(month["acumulado"] == "50.00" for month in ledger["months"])


def test_window_stretches_to_the_last_billing_month(user, household):
    """``--months`` is a floor, not a cap.

    A fingerprint that stops short of the newest entry would report "identical"
    while never looking at the tail — the exact failure the rehearsal exists to
    catch. See E04 review finding C1.
    """
    category = baker.make("finances.Category", user=user, household=household, name="Alimentação")
    pix = baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )
    for billing_month in (date(2026, 3, 1), date(2027, 9, 1)):
        baker.make(
            "finances.Entry",
            user=user,
            household=household,
            date=billing_month,
            amount=Decimal("50.00"),
            description="Feira",
            category=category,
            payment_method=pix,
            billing_month=billing_month,
        )

    out = StringIO()
    call_command("dump_ledger_totals", "--json", "--months", "2", stdout=out)
    months = [m["month"] for m in json.loads(out.getvalue())["vagner"]["months"]]

    assert months[0] == "2026-03-01"
    assert "2027-09-01" in months


def test_window_stretches_to_the_last_income_month(user, household):
    baker.make(
        "finances.Income",
        user=user,
        household=household,
        amount=Decimal("100.00"),
        month=date(2027, 4, 1),
    )

    out = StringIO()
    call_command("dump_ledger_totals", "--json", "--months", "1", stdout=out)
    months = [m["month"] for m in json.loads(out.getvalue())["vagner"]["months"]]

    assert "2027-04-01" in months


def test_months_argument_still_sets_the_minimum_window(user):
    out = StringIO()
    call_command("dump_ledger_totals", "--json", "--months", "6", stdout=out)
    months = json.loads(out.getvalue())["vagner"]["months"]

    assert len(months) == 6


def test_dump_is_deterministic(user):
    out_a, out_b = StringIO(), StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out_a)
    call_command("dump_ledger_totals", "--json", stdout=out_b)

    assert out_a.getvalue() == out_b.getvalue()
