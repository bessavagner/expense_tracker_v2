from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models import Entry
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.category_stats import diverse_savings_for_month

pytestmark = pytest.mark.django_db


def _mk(household, *, billing_month, amount, category, pm, entry_type=EntryType.REGULAR):
    return Entry.objects.create(
        household=household,
        date=billing_month,
        amount=Decimal(amount),
        description="x",
        category=category,
        payment_method=pm,
        entry_type=entry_type,
        billing_month=billing_month,
        billing_month_override=True,
    )


@pytest.fixture
def cat(household):
    return baker.make("finances.Category", household=household, name="Mercado")


@pytest.fixture
def adj(household):
    return baker.make("finances.Category", household=household, name="Ajuste de saldo")


@pytest.fixture
def pix(household):
    return baker.make(
        "finances.PaymentMethod", household=household, name="Pix", type=PaymentType.PIX
    )


def test_economia_positive_when_below_robust_baseline(user, household, cat, pix):
    # Prior 6 months: 1000 each -> median baseline 1000.
    for m in range(1, 7):
        _mk(household, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    # Current month (julho): spent only 600.
    _mk(household, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)

    out = diverse_savings_for_month(household, date(2025, 7, 1))

    assert out["baseline"] == Decimal("1000")
    assert out["actual"] == Decimal("600")
    assert out["economia"] == Decimal("400")
    assert out["has_baseline"] is True


def test_economia_negative_when_above_baseline(user, household, cat, pix):
    for m in range(1, 7):
        _mk(household, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(household, billing_month=date(2025, 7, 1), amount="1500", category=cat, pm=pix)

    out = diverse_savings_for_month(household, date(2025, 7, 1))
    assert out["economia"] == Decimal("-500")


def test_outlier_month_does_not_break_baseline(user, household, cat, pix):
    # Five months at 1000, one wild outlier at 9000 -> median still 1000.
    for m in range(1, 6):
        _mk(household, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(household, billing_month=date(2025, 6, 1), amount="9000", category=cat, pm=pix)
    _mk(household, billing_month=date(2025, 7, 1), amount="1000", category=cat, pm=pix)

    out = diverse_savings_for_month(household, date(2025, 7, 1))
    assert out["baseline"] == Decimal("1000")


def test_adjustment_entries_excluded_from_actual(user, household, cat, adj, pix):
    for m in range(1, 7):
        _mk(household, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(household, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)
    # #AJUSTE-SALDO entry must NOT inflate actual.
    _mk(household, billing_month=date(2025, 7, 1), amount="5000", category=adj, pm=pix)

    out = diverse_savings_for_month(household, date(2025, 7, 1))
    assert out["actual"] == Decimal("600")


def test_no_history_has_baseline_false(user, household, cat, pix):
    _mk(household, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)

    out = diverse_savings_for_month(household, date(2025, 7, 1))
    assert out["baseline"] == Decimal("0")
    assert out["has_baseline"] is False
    assert out["economia"] == Decimal("-600")
