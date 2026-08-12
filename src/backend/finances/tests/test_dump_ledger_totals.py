"""The before/after fingerprint used to prove the E04 migration is lossless."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

pytestmark = pytest.mark.django_db


def test_dump_reports_per_user_totals_and_acumulado(user):
    category = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 10),
        amount=Decimal("50.00"),
        description="Feira",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 3, 1),
    )
    baker.make("finances.Income", user=user, amount=Decimal("100.00"), month=date(2026, 3, 1))

    out = StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out)
    report = json.loads(out.getvalue())

    ledger = report["vagner"]
    assert ledger["entry_count"] == 1
    assert ledger["entry_sum"] == "50.00"
    assert ledger["income_sum"] == "100.00"
    assert any(month["acumulado"] == "50.00" for month in ledger["months"])


def test_dump_is_deterministic(user):
    out_a, out_b = StringIO(), StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out_a)
    call_command("dump_ledger_totals", "--json", stdout=out_b)

    assert out_a.getvalue() == out_b.getvalue()
