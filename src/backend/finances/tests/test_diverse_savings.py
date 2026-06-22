from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models import Entry
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.category_stats import diverse_savings_for_month

pytestmark = pytest.mark.django_db


def _mk(user, *, billing_month, amount, category, pm, entry_type=EntryType.REGULAR):
    return Entry.objects.create(
        user=user,
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
def cat(user):
    return baker.make("finances.Category", user=user, name="Mercado")


@pytest.fixture
def adj(user):
    return baker.make("finances.Category", user=user, name="Ajuste de saldo")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type=PaymentType.PIX)


def test_economia_positive_when_below_robust_baseline(user, cat, pix):
    # Prior 6 months: 1000 each -> median baseline 1000.
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    # Current month (julho): spent only 600.
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)

    out = diverse_savings_for_month(user, date(2025, 7, 1))

    assert out["baseline"] == Decimal("1000")
    assert out["actual"] == Decimal("600")
    assert out["economia"] == Decimal("400")
    assert out["has_baseline"] is True


def test_economia_negative_when_above_baseline(user, cat, pix):
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(user, billing_month=date(2025, 7, 1), amount="1500", category=cat, pm=pix)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["economia"] == Decimal("-500")


def test_outlier_month_does_not_break_baseline(user, cat, pix):
    # Five months at 1000, one wild outlier at 9000 -> median still 1000.
    for m in range(1, 6):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(user, billing_month=date(2025, 6, 1), amount="9000", category=cat, pm=pix)
    _mk(user, billing_month=date(2025, 7, 1), amount="1000", category=cat, pm=pix)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["baseline"] == Decimal("1000")


def test_adjustment_entries_excluded_from_actual(user, cat, adj, pix):
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pix)
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)
    # #AJUSTE-SALDO entry must NOT inflate actual.
    _mk(user, billing_month=date(2025, 7, 1), amount="5000", category=adj, pm=pix)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["actual"] == Decimal("600")


def test_no_history_has_baseline_false(user, cat, pix):
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pix)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["baseline"] == Decimal("0")
    assert out["has_baseline"] is False
    assert out["economia"] == Decimal("-600")
