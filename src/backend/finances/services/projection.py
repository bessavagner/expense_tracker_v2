"""Multi-month projection: one computed row per month.

Read-only. Every figure is derived from existing data (entries, incomes, active
systemic templates) — no manual per-cell estimates. See the spec at
docs/superpowers/specs/2026-06-18-projection-screen-design.md.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from finances.models import Entry, Income, SystemicExpense
from finances.models.entry import EntryType

ZERO = Decimal("0")


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def build_projection(user, start_month: date, num_months: int, today: date | None = None):
    """Return a list of ``num_months`` dicts, one per month from ``start_month``.

    Each dict holds: ``month``, ``systemic``, ``installments``, ``programmed``,
    ``diverse``, ``total``, ``income``, ``pct_income`` (Decimal|None),
    ``saldo_programado``, ``saldo_projetado``, ``acumulado``.

    ``today`` (defaults to ``date.today()``) decides the past/future split for the
    systemic row: months at or before the current month use the SYSTEMIC entries
    actually posted; strictly-future months project from active templates.
    """
    if today is None:
        today = date.today()
    current_month = today.replace(day=1)
    start_month = start_month.replace(day=1)
    num_months = max(int(num_months), 0)

    months = [_add_months(start_month, i) for i in range(num_months)]
    if not months:
        return []
    end_exclusive = _add_months(months[-1], 1)

    # --- one aggregated pass per source over the whole window ---
    entry_totals: dict[tuple[date, str], Decimal] = {}
    for r in (
        Entry.objects.filter(
            user=user, billing_month__gte=start_month, billing_month__lt=end_exclusive
        )
        .values("billing_month", "entry_type")
        .annotate(total=Sum("amount"))
    ):
        entry_totals[(r["billing_month"], r["entry_type"])] = r["total"] or ZERO

    income_totals: dict[date, Decimal] = {}
    for r in (
        Income.objects.filter(
            user=user, month__gte=start_month, month__lt=end_exclusive
        )
        .values("month")
        .annotate(total=Sum("amount"))
    ):
        income_totals[r["month"]] = r["total"] or ZERO

    active_systemic_total = (
        SystemicExpense.objects.filter(user=user, is_active=True).aggregate(
            total=Sum("default_amount")
        )["total"]
        or ZERO
    )

    rows = []
    acumulado = ZERO
    for m in months:
        if m > current_month:
            systemic = active_systemic_total
        else:
            systemic = entry_totals.get((m, EntryType.SYSTEMIC), ZERO)
        installments = entry_totals.get((m, EntryType.INSTALLMENT), ZERO)
        diverse = entry_totals.get((m, EntryType.REGULAR), ZERO)
        programmed = systemic + installments
        total = programmed + diverse
        income = income_totals.get(m, ZERO)

        pct_income = (total / income * 100) if income else None
        saldo_programado = income - programmed
        saldo_projetado = income - total
        acumulado += saldo_projetado

        rows.append(
            {
                "month": m,
                "systemic": systemic,
                "installments": installments,
                "programmed": programmed,
                "diverse": diverse,
                "total": total,
                "income": income,
                "pct_income": pct_income,
                "saldo_programado": saldo_programado,
                "saldo_projetado": saldo_projetado,
                "acumulado": acumulado,
            }
        )
    return rows
