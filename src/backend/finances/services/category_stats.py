"""Per-category moving-average spend. Deterministic, computed live."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from finances.models import Category, Entry
from finances.services.whatif import add_months

_CENTS = Decimal("0.01")


def _window_months(as_of: date, window: int) -> list[date]:
    current = as_of.replace(day=1)
    return [add_months(current, -i) for i in range(1, window + 1)]


def category_moving_averages(user, window=3, as_of=None, entry_type=None) -> dict:
    as_of = as_of or date.today()
    months = _window_months(as_of, window)
    qs = Entry.objects.filter(
        user=user, amount__gt=0, billing_month__in=months
    )
    if entry_type is not None:
        qs = qs.filter(entry_type=entry_type)
    rows = qs.values("category_id", "billing_month").annotate(total=Sum("amount"))

    totals: dict = {}
    counts: dict = {}
    for r in rows:
        cid = r["category_id"]
        totals[cid] = totals.get(cid, Decimal("0")) + (r["total"] or Decimal("0"))
        counts[cid] = counts.get(cid, 0) + 1

    return {
        cid: (totals[cid] / counts[cid]).quantize(_CENTS, rounding=ROUND_HALF_UP)
        for cid in totals
    }


def category_moving_averages_named(user, window=3, as_of=None, entry_type=None) -> list:
    as_of = as_of or date.today()
    months = _window_months(as_of, window)
    avgs = category_moving_averages(user, window, as_of, entry_type)
    qs = Entry.objects.filter(user=user, amount__gt=0, billing_month__in=months)
    if entry_type is not None:
        qs = qs.filter(entry_type=entry_type)
    names = dict(Category.objects.filter(user=user).values_list("id", "name"))
    out = [
        {
            "id": cid,
            "name": names.get(cid, "?"),
            "avg": avg,
            "months_used": qs.filter(category_id=cid).values("billing_month").distinct().count(),
        }
        for cid, avg in avgs.items()
    ]
    out.sort(key=lambda x: x["avg"], reverse=True)
    return out
