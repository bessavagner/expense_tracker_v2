from datetime import date

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
