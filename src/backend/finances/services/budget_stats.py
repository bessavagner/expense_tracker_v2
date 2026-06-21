# finances/services/budget_stats.py
"""Deterministic per-budget spend + planned-ceiling math."""

from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum

from finances.models import Budget, Category, Entry
from finances.services.category_stats import ADJUSTMENT_CATEGORY_PATTERN

ZERO = Decimal("0")


def _status(spent: Decimal, cap: Decimal) -> tuple[int, str]:
    if cap <= 0:
        return 0, "success"
    pct = int((spent / cap * 100).to_integral_value(rounding=ROUND_DOWN))
    if pct >= 100:
        return pct, "error"
    if pct >= 90:
        return pct, "warning"
    return pct, "success"


def _spend_by_category(user, billing_month: date) -> dict:
    rows = (
        Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
        .exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)
        .values("category_id")
        .annotate(total=Sum("amount"))
    )
    return {r["category_id"]: r["total"] or ZERO for r in rows}


def budget_spend_for_month(user, billing_month: date) -> list[dict]:
    spend = _spend_by_category(user, billing_month)
    out = []
    for b in Budget.objects.filter(user=user).prefetch_related("categories"):
        spent = sum((spend.get(c.id, ZERO) for c in b.categories.all()), ZERO)
        pct, status = _status(spent, b.amount)
        out.append(
            {"budget": b, "name": b.name, "amount": b.amount,
             "spent": spent, "pct": pct, "status": status}
        )
    return out


def orphan_category_spend_for_month(user, billing_month: date) -> list[dict]:
    spend = _spend_by_category(user, billing_month)
    out = []
    for c in Category.objects.filter(user=user, budget__isnull=True):
        if not c.budget_ceiling or c.budget_ceiling <= 0:
            continue
        spent = spend.get(c.id, ZERO)
        pct, status = _status(spent, c.budget_ceiling)
        out.append(
            {"name": c.name, "ceiling": c.budget_ceiling,
             "spent": spent, "pct": pct, "status": status}
        )
    return out


def total_diverse_ceiling(user) -> Decimal:
    budgets = Budget.objects.filter(user=user).aggregate(t=Sum("amount"))["t"] or ZERO
    orphans = (
        Category.objects.filter(user=user, budget__isnull=True)
        .aggregate(t=Sum("budget_ceiling"))["t"]
        or ZERO
    )
    return budgets + orphans


def seed_amount_from_ceilings(budget) -> Decimal:
    return budget.categories.aggregate(t=Sum("budget_ceiling"))["t"] or ZERO
