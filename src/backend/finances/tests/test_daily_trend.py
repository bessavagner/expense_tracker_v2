from datetime import date, timedelta
from decimal import Decimal

import pytest

from finances.models import Category, Entry, PaymentMethod
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.daily_trend import ROLLING_BY_PERIOD, daily_spend_trend

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    cat = Category.objects.create(user=user, name="Mercado")
    adj = Category.objects.create(user=user, name="Ajuste de saldo")
    pm = PaymentMethod.objects.create(user=user, name="Pix", type=PaymentType.PIX)
    return user, cat, adj, pm


def _mk(user, *, d, amount, category, pm):
    return Entry.objects.create(
        user=user,
        date=d,
        amount=Decimal(amount),
        description="x",
        category=category,
        payment_method=pm,
        entry_type=EntryType.REGULAR,
        billing_month=d.replace(day=1),
        billing_month_override=True,
    )


def test_series_length_and_order(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    series = daily_spend_trend(user, period=30, as_of=as_of)
    assert len(series) == 30
    assert series[0]["date"] == date(2025, 7, 1)
    assert series[-1]["date"] == as_of


def test_days_without_spend_count_as_zero(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    # No entries at all -> every rolling stat is 0.
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert all(p["median"] == Decimal("0") for p in series)
    assert all(p["p75"] == Decimal("0") for p in series)


def test_groups_by_real_date(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    # 100 on each of the last 3 days -> rolling(7d period -> window 3) median 100 at as_of.
    for k in range(3):
        _mk(user, d=as_of - timedelta(days=k), amount="100", category=cat, pm=pm)
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert series[-1]["median"] == Decimal("100")


def test_robust_to_single_outlier(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    # period 30 -> rolling 7. Put 50 on each of last 7 days, one of them 5000.
    for k in range(7):
        amount = "5000" if k == 3 else "50"
        _mk(user, d=as_of - timedelta(days=k), amount=amount, category=cat, pm=pm)
    series = daily_spend_trend(user, period=30, as_of=as_of)
    # Median of [50,50,50,5000,50,50,50] is 50 — outlier does not move the line.
    assert series[-1]["median"] == Decimal("50")
    # The band's upper edge (p75) is also 50.00 here — linear interpolation at
    # position 0.75*6=4.5 between two 50s yields 50.00.
    assert series[-1]["p75"] == Decimal("50.00")


def test_iqr_band(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    # window of 3 (period 7): values 10, 20, 30 over last 3 days.
    _mk(user, d=as_of, amount="30", category=cat, pm=pm)
    _mk(user, d=as_of - timedelta(days=1), amount="20", category=cat, pm=pm)
    _mk(user, d=as_of - timedelta(days=2), amount="10", category=cat, pm=pm)
    series = daily_spend_trend(user, period=7, as_of=as_of)
    last = series[-1]
    # sorted [10,20,30]: median=20, p25=15, p75=25 (linear interpolation).
    assert last["median"] == Decimal("20")
    assert last["p25"] == Decimal("15.00")
    assert last["p75"] == Decimal("25.00")


def test_adjustment_excluded(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    _mk(user, d=as_of, amount="5000", category=adj, pm=pm)  # #AJUSTE
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert series[-1]["median"] == Decimal("0")


def test_invalid_period_clamps_to_30(setup):
    user, cat, adj, pm = setup
    series = daily_spend_trend(user, period=999, as_of=date(2025, 7, 30))
    assert len(series) == 30


def test_rolling_map():
    assert ROLLING_BY_PERIOD == {7: 3, 15: 5, 30: 7, 90: 15}
