"""The invoice month a receipt plan will land in, named before it is written.

Frozen to 2026-08-16 because every assertion here is about a month being in the
past relative to "now" — the walkthrough's receipt is dated 2023-06-04, and the
whole defect is that three years is invisible on a dashboard showing August.
"""

from datetime import UTC, date, datetime

import pytest
from model_bakery import baker

from accounts.models import Household
from assistant.agents.receipt_billing import (
    dashboard_url_for,
    month_label,
    plan_entry_date,
    prospective_billing_month,
)
from assistant.agents.tools import commit_receipt, propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Entry, PaymentMethod
from finances.models.payment_method import PaymentType

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


def _plan(payment_method, when="2023-06-04"):
    return {
        "date": when,
        "payment_method_id": str(payment_method.id),
        "lines": [],
        "store": "HIPERMACIONAL",
        "payment_method_name": payment_method.name,
    }


def test_month_label_is_portuguese():
    assert month_label(date(2023, 6, 1)) == "junho/2023"


def test_dashboard_url_points_at_that_month():
    assert dashboard_url_for(date(2023, 6, 1)) == "/?year=2023&month=6"


def test_plan_entry_date_reads_the_plan():
    assert plan_entry_date({"date": "2023-06-04"}) == date(2023, 6, 4)


def test_plan_entry_date_falls_back_to_today_when_unusable():
    """Same fallback `commit_receipt` has always had — a plan with a broken date
    still writes rows, it just writes them today."""
    assert plan_entry_date({"date": "not-a-date"}) == date(2026, 8, 16)
    assert plan_entry_date({}) == date(2026, 8, 16)


def test_cash_lands_in_the_purchase_month(household):
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )

    assert prospective_billing_month(household, _plan(pix)) == date(2023, 6, 1)


def test_a_card_purchase_lands_on_the_invoice_that_pays_it(household):
    """Closing day 10, bought on the 4th: the invoice closes in June and is paid
    in July. This is the same arithmetic `Entry.save()` will do."""
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    assert prospective_billing_month(household, _plan(card)) == date(2023, 7, 1)


def test_a_card_purchase_after_closing_rolls_one_more_month(household):
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    plan = _plan(card, when="2023-06-20")

    assert prospective_billing_month(household, plan) == date(2023, 8, 1)


def test_an_unresolvable_payment_method_gives_no_answer(household):
    """Never guess. A caller that gets None says nothing rather than a wrong month."""
    plan = {"date": "2023-06-04", "payment_method_id": "00000000-0000-0000-0000-000000000000"}

    assert prospective_billing_month(household, plan) is None


def test_another_households_payment_method_is_not_visible(household):
    """The lookup is scoped. A plan naming someone else's card resolves to nothing,
    not to their closing day."""
    other = baker.make(Household, name="Casa alheia")
    card = baker.make(
        PaymentMethod,
        household=other,
        name="Crédito alheio",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    assert prospective_billing_month(household, _plan(card)) is None


# ---------------------------------------------------------------------------
# The proposal warns when the invoice is already behind us, and asks.
# ---------------------------------------------------------------------------


def _pending_draft(household, when="2023-06-04", payment_hint="Pix"):
    """A pending photo draft in the shape `propose_receipt` re-plans from.

    Deliberately the *raw* payload rather than a pre-baked plan: `propose_receipt`
    recomputes the plan from `items`, so a fixture that skipped straight to a plan
    would exercise nothing.
    """
    return ReceiptDraft.objects.create(
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "HIPERMACIONAL",
            "date": when,
            "discount": None,
            "amount_paid": "376.70",
            "payment_hint": payment_hint,
            "items": [
                {"description": "ARROZ 5KG", "line_total": "376.70", "category": "Alimentação"}
            ],
        },
    )


def test_a_past_invoice_is_named_and_asked_about(seeded_scope, household):
    _pending_draft(household)

    answer = propose_receipt(seeded_scope, payment_method_name="Pix")

    assert "junho/2023" in answer
    assert "Registrar nessa fatura?" in answer
    assert answer.endswith("Confirma?")


def test_a_receipt_from_this_month_is_not_second_guessed(seeded_scope, household):
    """No warning for the ordinary case. A prompt on every receipt is noise, and
    noise is what makes a real warning invisible."""
    _pending_draft(household, when="2026-08-16")

    answer = propose_receipt(seeded_scope, payment_method_name="Pix")

    assert "fatura" not in answer.lower()


def test_a_card_purchase_landing_in_the_future_is_not_warned_about(seeded_scope, household):
    """Bought today on a card that closes on the 25th: this lands in September and
    that is the product working. Warning here would fire on every card purchase."""
    _pending_draft(household, when="2026-08-16", payment_hint="Crédito C6")

    answer = propose_receipt(seeded_scope, payment_method_name="Crédito C6")

    assert "Registrar nessa fatura?" not in answer


# ---------------------------------------------------------------------------
# The confirmation says which invoice it landed in (SD05-1).
# ---------------------------------------------------------------------------


def _planned_draft(scope, household, when="2023-06-04", payment_hint="Pix"):
    """A draft carrying the saved plan `commit_receipt` reads.

    Produced by running the real proposal rather than by hand-writing a plan, so
    the two halves of the flow are exercised against the same object the product
    builds.
    """
    _pending_draft(household, when=when, payment_hint=payment_hint)
    propose_receipt(scope, payment_method_name=payment_hint)


def test_the_confirmation_names_the_invoice_and_links_to_it(seeded_scope, household):
    """The walkthrough, replayed. A stranger reading this reply knows where the
    money went and has one thing to tap — which is the whole defect."""
    _planned_draft(seeded_scope, household)

    answer = commit_receipt(seeded_scope)

    assert "junho/2023" in answer
    assert "/?year=2023&month=6" in answer
    # And the row really is where the reply claims it is.
    entry = Entry.objects.for_household(household).get()
    assert entry.billing_month == date(2023, 6, 1)


def test_a_receipt_in_the_current_month_says_nothing_extra(seeded_scope, household):
    _planned_draft(seeded_scope, household, when="2026-08-16")

    answer = commit_receipt(seeded_scope)

    assert "fatura" not in answer.lower()


def test_a_future_invoice_is_named_too(seeded_scope, household):
    """SD05-1 says "not the current month", not "in the past". A card purchase
    bought on the 16th against a card that closes on the 25th is paid in
    September, and September is just as invisible on today's dashboard."""
    _planned_draft(seeded_scope, household, when="2026-08-16", payment_hint="Crédito C6")

    answer = commit_receipt(seeded_scope)

    assert "setembro/2026" in answer


# ---------------------------------------------------------------------------
# The walkthrough, replayed end to end.
# ---------------------------------------------------------------------------


def test_the_walkthrough_receipt_end_to_end(seeded_scope, household):
    """The 2026-08-16 walkthrough, replayed: a real coupon dated 2023-06-04,
    proposed and then committed, on a dashboard showing August 2026.

    Asserts the property the defect is about rather than exact copy — a stranger
    must be told the month and be given one thing to tap, at both moments.
    """
    _pending_draft(household, when="2023-06-04")

    proposal = propose_receipt(seeded_scope, payment_method_name="Pix")
    confirmation = commit_receipt(seeded_scope)

    # Asked before writing...
    assert "junho/2023" in proposal
    assert proposal.rstrip().endswith("Confirma?")
    # ...and told after, with somewhere to go.
    assert "junho/2023" in confirmation
    assert "/?year=2023&month=6" in confirmation
    # And the rows are where both strings said they would be.
    assert (
        Entry.objects.for_household(household).filter(billing_month=date(2023, 6, 1)).count() == 1
    )
