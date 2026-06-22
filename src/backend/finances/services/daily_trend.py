"""Daily spend trend, smoothed by a rolling median + IQR band (robust to outliers)."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from finances.models import Entry
from finances.services.category_stats import ADJUSTMENT_CATEGORY_PATTERN

_CENTS = Decimal("0.01")

# Period (x-axis span, days) -> rolling window (days) for the median/IQR.
# The window stays well under the period so the smoothed series has real points.
ROLLING_BY_PERIOD = {7: 3, 15: 5, 30: 7, 90: 15}
_DEFAULT_PERIOD = 30


def _percentile(values: list[Decimal], q: Decimal) -> Decimal:
    """Linear-interpolation percentile. ``q`` in [0, 1]."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return Decimal("0")
    if n == 1:
        return xs[0].quantize(_CENTS, rounding=ROUND_HALF_UP)
    pos = q * (n - 1)
    lo = int(pos)
    if lo + 1 >= n:
        return xs[lo].quantize(_CENTS, rounding=ROUND_HALF_UP)
    frac = pos - lo
    return (xs[lo] + (xs[lo + 1] - xs[lo]) * frac).quantize(_CENTS, rounding=ROUND_HALF_UP)


def daily_spend_trend(user, period=30, as_of=None) -> list[dict]:
    """Rolling median + IQR (p25/p75) of daily spend over the last ``period`` days.

    Daily spend = Σ ``Entry.amount`` (>0, excluding #AJUSTE) grouped by the real
    ``date``; missing days count as 0. Each output point applies the rolling
    window (see ``ROLLING_BY_PERIOD``) ending on that day. Oldest first.
    """
    if period not in ROLLING_BY_PERIOD:
        period = _DEFAULT_PERIOD
    as_of = as_of or date.today()
    rolling = ROLLING_BY_PERIOD[period]

    start_display = as_of - timedelta(days=period - 1)
    start_fetch = start_display - timedelta(days=rolling - 1)

    rows = (
        Entry.objects.filter(
            user=user, amount__gt=0, date__gte=start_fetch, date__lte=as_of
        )
        .exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)
        .values("date")
        .annotate(total=Sum("amount"))
    )
    by_day = {r["date"]: r["total"] for r in rows}

    out = []
    for i in range(period):
        day = start_display + timedelta(days=i)
        window = [
            by_day.get(day - timedelta(days=k), Decimal("0")) for k in range(rolling)
        ]
        out.append(
            {
                "date": day,
                "median": _percentile(window, Decimal("0.5")),
                "p25": _percentile(window, Decimal("0.25")),
                "p75": _percentile(window, Decimal("0.75")),
            }
        )
    return out
