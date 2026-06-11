from datetime import date

from finances.models import Entry, SystemicExpense
from finances.models.entry import EntryType


def systemic_rows_for_month(user, year, month):
    """Return [{"systemic": <template>, "entry": <Entry or None>}] for active templates."""
    billing_month = date(year, month, 1)
    templates = (
        SystemicExpense.objects.filter(user=user, is_active=True)
        .select_related("category", "payment_method")
        .order_by("name")
    )
    entries = {
        e.systemic_expense_id: e
        for e in Entry.objects.filter(
            user=user,
            entry_type=EntryType.SYSTEMIC,
            billing_month=billing_month,
            systemic_expense__isnull=False,
        )
    }
    return [{"systemic": t, "entry": entries.get(t.id)} for t in templates]
