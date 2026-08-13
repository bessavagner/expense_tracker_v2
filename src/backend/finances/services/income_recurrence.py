from datetime import date

from finances.models import Income
from finances.services.dates import add_months


def apply_income_recurrence(income) -> int:
    """Upsert one Income row per month across the recurrence window.

    No-op unless ``income.is_recurring``. Window is
    ``[recurrence_start, recurrence_end]``; blanks default to
    ``income.month`` → December of that year. Existing same-name rows in the
    window are updated to match (amount + recurrence flags). Returns the number
    of months touched.
    """
    if not income.is_recurring:
        return 0
    start = (income.recurrence_start or income.month).replace(day=1)
    end = (income.recurrence_end or date(income.month.year, 12, 1)).replace(day=1)
    if end < start:
        return 0
    touched = 0
    m = start
    while m <= end:
        # Scoped from the row we were handed, not from its author: a recurrence
        # the other member set up is still the same household's income.
        qs = Income.objects.for_household(income.household).filter(name=income.name, month=m)
        if qs.exists():
            qs.update(
                amount=income.amount,
                is_recurring=True,
                recurrence_start=start,
                recurrence_end=end,
            )
        else:
            Income.objects.create(
                user=income.user,  # still NOT NULL until phase 4
                household=income.household,
                # Set explicitly, and not incidentally: the write bridge fills
                # `created_by` only when it also fills `household`, so setting
                # `household` here means the bridge returns early and the author
                # would otherwise be lost. The copies inherit the original's.
                created_by=income.created_by or income.user,
                name=income.name,
                month=m,
                amount=income.amount,
                is_recurring=True,
                recurrence_start=start,
                recurrence_end=end,
            )
        touched += 1
        m = add_months(m, 1)
    return touched
