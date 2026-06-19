from datetime import date


def add_months(d: date, n: int) -> date:
    """Return the first day of the month `n` months after `d`."""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)
