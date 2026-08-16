"""Which invoice a receipt plan lands in, and how to say that to a person.

D05: filing a receipt under its own date is correct and is not what this module
changes. What it provides is the ability to *say* where the row went, before and
after it is written, using exactly the derivation `Entry.save()` uses — see
`finances/models/entry.py::save`. Two code paths computing this two ways would
put a month on the screen that the database disagrees with, which is a worse
defect than the one D05 describes.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

from finances.models import PaymentMethod
from finances.services.billing import compute_billing_month, resolve_closing_day

#: Month names in pt-BR, indexed by month number. Django's `date` filter would
#: need an active locale and a template; this is read by the assistant, which
#: renders strings, not templates.
_MONTHS_PT = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def month_label(when: date) -> str:
    """``junho/2023`` — how a Brazilian names an invoice."""
    return f"{_MONTHS_PT[when.month]}/{when.year}"


def dashboard_url_for(when: date) -> str:
    """The dashboard, showing that month.

    `finances/views/dashboard.py::DashboardView` reads `year` and `month` from
    the query string and falls back to today, so this is the whole contract.
    """
    return f"/?year={when.year}&month={when.month}"


def plan_entry_date(plan: dict) -> date:
    """The purchase date a plan will write, with the fallback commit has always had.

    Lifted out of `commit_receipt` so the proposal and the commit read the date
    the same way. A plan whose date is missing or malformed still writes rows —
    it writes them today — and the proposal must warn about the same day the
    commit will use.
    """
    try:
        return date.fromisoformat(plan["date"])
    except (ValueError, TypeError, KeyError):
        return timezone.localdate()


def prospective_billing_month(household, plan: dict) -> date | None:
    """First day of the invoice month this plan will land in, or ``None``.

    ``None`` when the plan's payment method cannot be resolved inside this
    household — a caller that cannot name the month must say nothing rather than
    guess, and a plan naming another household's card is exactly the case that
    must not silently borrow its closing day.
    """
    try:
        payment_method = (
            PaymentMethod.objects.for_household(household)
            .filter(pk=plan.get("payment_method_id"))
            .prefetch_related("monthly_closing_days")
            .first()
        )
    except (ValidationError, ValueError, TypeError):
        # A malformed id is the same answer as a missing one: we cannot name the
        # month, so we say nothing.
        return None
    if payment_method is None:
        return None
    entry_date = plan_entry_date(plan)
    return compute_billing_month(
        entry_date,
        payment_method.type,
        resolve_closing_day(payment_method, entry_date),
    )
