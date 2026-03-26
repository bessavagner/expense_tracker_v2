from datetime import date

from finances.models.payment_method import PaymentType


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
