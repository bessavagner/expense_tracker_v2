"""Multi-month projection: one computed row per month.

Read-only. Every figure is derived from existing data (entries, incomes, active
systemic templates) — no manual per-cell estimates. See the spec at
docs/superpowers/specs/2026-06-18-projection-screen-design.md.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Min, Sum
from django.utils import timezone

from finances.models import Entry, Income, SystemicExpense
from finances.models.entry import EntryType
from finances.services.category_stats import (
    monthly_diverse_total_ceiling,
    monthly_diverse_total_median,
)

ZERO = Decimal("0")
DEFAULT_PROJECTION_ORIGIN = date(2025, 11, 1)


def _add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def projection_origin(household) -> date:
    """First month that counts for ``household``. Nothing earlier enters at all.

    Per household rather than global (E11). The old
    ``settings.PROJECTION_ORIGIN_MONTH`` recorded one fact about one ledger —
    that everything before Nov 2025 was migration and seed noise — and applying
    it to a stranger produced a projection anchored two years before they had
    heard of the product. Worse, it silently discarded imported history: a CSV
    of 2024 landed below the floor and vanished from the ``acumulado``.

    Resolution order:

    1. ``household.projection_origin_month`` when set. The data migration set
       it for every household that existed when E11 shipped, so their numbers
       did not move.
    2. The earliest month with any income or entry.
    3. The household's own creation month, for a household with no data yet.
    """
    if household is None:
        return DEFAULT_PROJECTION_ORIGIN

    explicit = getattr(household, "projection_origin_month", None)
    if explicit:
        return explicit.replace(day=1)

    inc_min = Income.objects.for_household(household).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.for_household(household).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    if candidates:
        return min(candidates).replace(day=1)

    created = getattr(household, "created_at", None)
    if created is not None:
        # `created_at` is UTC-aware; converting to the app's local timezone
        # before taking `.date()` matters right at a month boundary — a
        # household created after 21:00 America/Sao_Paulo on the last day of
        # a month is still UTC-stamped into the next month.
        return timezone.localtime(created).date().replace(day=1)
    return DEFAULT_PROJECTION_ORIGIN


def build_projection(
    household,
    start_month: date,
    num_months: int,
    today: date | None = None,
    overlay: dict | None = None,
    diverse_estimator: str = "median",
):
    """The projection of ``household``'s ledger: one dict per month from ``start_month``.

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
    inc_min = Income.objects.for_household(household).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.for_household(household).aggregate(m=Min("billing_month"))["m"]
    data_candidates = [d for d in (inc_min, ent_min) if d is not None]
    data_anchor = min(data_candidates).replace(day=1) if data_candidates else start_month
    # Floor at the projection origin: anything before it is excluded entirely, so
    # pre-origin records never leak into the running acumulado.
    origin = projection_origin(household)
    agg_start = max(min(data_anchor, start_month), origin)

    # Every month from the anchor through the window end (drives the running total).
    span = (months[-1].year * 12 + months[-1].month) - (agg_start.year * 12 + agg_start.month) + 1
    all_months = [_add_months(agg_start, i) for i in range(span)]

    # --- one aggregated pass per source over the whole span ---
    entry_totals: dict[tuple[date, str], Decimal] = {}
    for r in (
        Entry.objects.for_household(household)
        .filter(billing_month__gte=agg_start, billing_month__lt=end_exclusive)
        .values("billing_month", "entry_type")
        .annotate(total=Sum("amount"))
    ):
        entry_totals[(r["billing_month"], r["entry_type"])] = r["total"] or ZERO

    income_totals: dict[date, Decimal] = {}
    for r in (
        Income.objects.for_household(household)
        .filter(month__gte=agg_start, month__lt=end_exclusive)
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
        SystemicExpense.objects.for_household(household)
        .filter(is_active=True)
        .aggregate(total=Sum("default_amount"))["total"]
        or ZERO
    )

    # --- estimated diversas: a "typical month" estimate for future months.
    # "ceiling": planned cap = sum of budget amounts + ceilings of un-budgeted
    #   categories (monthly_diverse_total_ceiling).
    # default ("median"/anything else): robust median of recent monthly totals
    #   (window=6), excluding reconciliation entries, so a one-off reform/big
    #   purchase can't poison the forward projection. ---
    if diverse_estimator == "ceiling":
        est_typical_diverse = monthly_diverse_total_ceiling(household)
    else:
        est_typical_diverse = monthly_diverse_total_median(household, window=6, as_of=today)

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
            # don't project below what's already posted this month
            diverse_estimated = max(diverse, est_typical_diverse)
        else:
            diverse_estimated = est_typical_diverse
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
