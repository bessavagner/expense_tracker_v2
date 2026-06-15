from datetime import date, timedelta

from finances.models.payment_method import PaymentType


def resolve_closing_day(payment_method, entry_date: date) -> int | None:
    """Resolve the closing day applicable to ``entry_date`` for a payment method.

    Looks up a per-month override (:class:`PaymentMethodClosingDay`) for the
    month of ``entry_date``; falls back to the payment method's default
    ``closing_day`` when there is no override.
    """
    month = entry_date.replace(day=1)
    override = payment_method.monthly_closing_days.filter(month=month).first()
    if override is not None:
        return override.closing_day
    return payment_method.closing_day


def compute_billing_month(
    entry_date: date,
    payment_type: str,
    closing_day: int | None,
) -> date:
    first_of_month = entry_date.replace(day=1)

    if payment_type != PaymentType.CREDIT_CARD or closing_day is None:
        return first_of_month

    if entry_date.day > closing_day:
        if entry_date.month == 12:
            return date(entry_date.year + 1, 1, 1)
        return date(entry_date.year, entry_date.month + 1, 1)

    return first_of_month


def _next_month(d: date) -> date:
    """First day of the month after ``d``."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def add_months(d: date, n: int) -> date:
    """Return ``d`` shifted by ``n`` months, clamping the day to month length."""
    total = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(total, 12)
    month += 1
    # Clamp day to the last valid day of the target month.
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def installment_billing_months(
    start_date: date,
    payment_method,
    num_installments: int,
) -> list[date]:
    """Billing month (first-of-month date) for each installment of a plan.

    The first installment is placed on the billing month that results from
    crossing ``start_date`` with the card's closing day (see
    :func:`compute_billing_month`); each subsequent installment falls on the
    following month. Single source of truth shared by
    ``InstallmentPlan.generate_entries`` and the modal preview.
    """
    first = compute_billing_month(
        start_date,
        payment_method.type,
        resolve_closing_day(payment_method, start_date),
    )
    months = [first]
    for _ in range(1, max(num_installments, 0)):
        months.append(_next_month(months[-1]))
    return months
