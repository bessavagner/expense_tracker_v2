"""Multi-month projection: one computed row per month.

Read-only. Every figure is derived from existing data (entries, incomes, active
systemic templates) — no manual per-cell estimates. See the spec at
docs/superpowers/specs/2026-06-18-projection-screen-design.md.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Min, Sum

from finances.models import Entry, Income, SystemicExpense
from finances.models.entry import EntryType
from finances.services.category_stats import category_moving_averages

ZERO = Decimal("0")
DEFAULT_PROJECTION_ORIGIN = date(2025, 11, 1)


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _projection_origin() -> date:
    """First month that counts. Nothing earlier enters the projection at all.

    Configurable via ``settings.PROJECTION_ORIGIN_MONTH`` (a ``date`` or
    ``"YYYY-MM"`` string); defaults to Nov 2025. Pre-origin records are
    migration/seed noise and must never affect the running ``acumulado``.
    """
    raw = getattr(settings, "PROJECTION_ORIGIN_MONTH", None)
    if isinstance(raw, date):
        return raw.replace(day=1)
    if isinstance(raw, str) and raw.strip():
        try:
            year, month = (int(p) for p in raw.split("-")[:2])
            return date(year, month, 1)
        except (ValueError, TypeError):
            pass
    return DEFAULT_PROJECTION_ORIGIN


def projection_origin() -> date:
    """Public accessor for the first month the projection counts (see
    :func:`_projection_origin`). Lets callers detect months preceding the
    origin, where no projection rows exist."""
    return _projection_origin()


def build_projection(user, start_month: date, num_months: int, today: date | None = None,
                     overlay: dict | None = None):
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

    # Earliest month with any data — acumulado is anchored here, not at the
    # window start, so the accumulated balance for a month is fixed regardless
    # of the projection window the user picks.
    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    data_candidates = [d for d in (inc_min, ent_min) if d is not None]
    data_anchor = min(data_candidates).replace(day=1) if data_candidates else start_month
    # Floor at the projection origin: anything before it is excluded entirely, so
    # pre-origin records never leak into the running acumulado.
    origin = _projection_origin()
    agg_start = max(min(data_anchor, start_month), origin)

    # Every month from the anchor through the window end (drives the running total).
    span = (months[-1].year * 12 + months[-1].month) - (agg_start.year * 12 + agg_start.month) + 1
    all_months = [_add_months(agg_start, i) for i in range(span)]

    # --- one aggregated pass per source over the whole span ---
    entry_totals: dict[tuple[date, str], Decimal] = {}
    for r in (
        Entry.objects.filter(
            user=user, billing_month__gte=agg_start, billing_month__lt=end_exclusive
        )
        .values("billing_month", "entry_type")
        .annotate(total=Sum("amount"))
    ):
        entry_totals[(r["billing_month"], r["entry_type"])] = r["total"] or ZERO

    income_totals: dict[date, Decimal] = {}
    for r in (
        Income.objects.filter(
            user=user, month__gte=agg_start, month__lt=end_exclusive
        )
        .values("month")
        .annotate(total=Sum("amount"))
    ):
        income_totals[r["month"]] = r["total"] or ZERO

    # --- what-if overlay: hypothetical per-month deltas (Decimal) ---
    if overlay:
        for (m, kind), amount in overlay.items():
            if kind == "income":
                income_totals[m] = income_totals.get(m, ZERO) + amount
            else:
                key = (m, kind)
                entry_totals[key] = entry_totals.get(key, ZERO) + amount

    active_systemic_total = (
        SystemicExpense.objects.filter(user=user, is_active=True).aggregate(
            total=Sum("default_amount")
        )["total"]
        or ZERO
    )

    # --- estimated diversas (per-category regular moving average) ---
    reg_avg = category_moving_averages(user, window=3, as_of=today, entry_type="regular")
    est_future_diverse = sum(reg_avg.values(), ZERO)
    # current-month actual regular per category (for max(actual, avg))
    cur_actual = {
        r["category_id"]: (r["total"] or ZERO)
        for r in Entry.objects.filter(
            user=user, billing_month=current_month,
            entry_type=EntryType.REGULAR, amount__gt=0,
        ).values("category_id").annotate(total=Sum("amount"))
    }
    est_current_diverse = sum(
        (max(cur_actual.get(cid, ZERO), reg_avg.get(cid, ZERO))
         for cid in set(cur_actual) | set(reg_avg)),
        ZERO,
    )

    rows = []
    acumulado = ZERO
    acumulado_estimado = ZERO
    for m in all_months:
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

        if m < current_month:
            diverse_estimated = diverse
        elif m == current_month:
            diverse_estimated = est_current_diverse
        else:
            diverse_estimated = est_future_diverse
        total_estimated = programmed + diverse_estimated
        saldo_projetado_estimado = income - total_estimated
        acumulado_estimado += saldo_projetado_estimado

        if m < start_month:
            continue  # pre-window month: counted into acumulado, not displayed

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
                "diverse_estimated": diverse_estimated,
                "total_estimated": total_estimated,
                "saldo_projetado_estimado": saldo_projetado_estimado,
                "acumulado_estimado": acumulado_estimado,
            }
        )
    return rows
