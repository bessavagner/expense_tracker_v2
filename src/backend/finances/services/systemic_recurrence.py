from finances.models import Entry
from finances.models.entry import EntryType
from finances.services.dates import add_months


def apply_systemic_recurrence(template, amount, start, end) -> int:
    """Upsert the monthly systemic Entry across ``[start, end]``, propagating
    only the ``amount``.

    Months already launched are updated; missing months are launched (from the
    template's category/payment_method). The template's ``default_amount`` is
    left untouched, and only this template's entries are affected. The window may
    extend backwards (``start`` before the current month). Returns the number of
    months touched.
    """
    start = start.replace(day=1)
    end = end.replace(day=1)
    if end < start:
        return 0
    touched = 0
    m = start
    while m <= end:
        entry = Entry.objects.filter(
            user=template.user,
            systemic_expense=template,
            entry_type=EntryType.SYSTEMIC,
            billing_month=m,
        ).first()
        if entry is not None:
            entry.amount = amount
            entry.save(update_fields=["amount", "updated_at"])
        else:
            template.create_monthly_entry(m, amount=amount)
        touched += 1
        m = add_months(m, 1)
    return touched
