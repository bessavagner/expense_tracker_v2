"""How an entry was captured, recorded at the write path itself.

`first_ai_entry` fires once per household and therefore cannot count the second
receipt. `entry_created` is what the AI-versus-manual ratio (E14 S14-3) is built
on, so every path that writes an `Entry` has to emit one.

Its own module rather than appended to `test_receipt_billing_month.py`: that file
is about which invoice a receipt lands in, and this is about who typed it.
"""

import pytest

from assistant.agents.tools import commit_receipt, create_entry, propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from core.events import EventName
from core.models import ProductEvent

pytestmark = pytest.mark.django_db


def _sources(household):
    return [
        row.metadata.get("source")
        for row in ProductEvent.objects.filter(
            household=household, name=EventName.ENTRY_CREATED
        ).order_by("created_at")
    ]


def _pending_draft(household, when="2026-08-16"):
    return ReceiptDraft.objects.create(
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "MATEUS",
            "date": when,
            "discount": None,
            "amount_paid": "100.00",
            "payment_hint": "Pix",
            "items": [{"description": "arroz", "line_total": "100.00", "category": "Alimentação"}],
        },
    )


def test_committing_a_receipt_records_the_source(seeded_scope, household):
    _pending_draft(household)
    propose_receipt(seeded_scope, payment_method_name="Pix")

    commit_receipt(seeded_scope)

    assert _sources(household) == ["receipt"]


def test_a_second_receipt_is_counted_too(seeded_scope, household):
    """The reason this is not `emit_once`: a household's tenth receipt is exactly
    the evidence the wedge is landing, and a once-event throws it away."""
    for _ in range(2):
        _pending_draft(household)
        propose_receipt(seeded_scope, payment_method_name="Pix")
        commit_receipt(seeded_scope)

    assert _sources(household) == ["receipt", "receipt"]


def test_a_chat_entry_records_the_chat_source(seeded_scope, household):
    create_entry(
        seeded_scope,
        date_str="2026-08-16",
        amount_str="42.00",
        description="feira",
        category_name="Alimentação",
        payment_method_name="Pix",
    )

    assert _sources(household) == ["chat"]


def test_a_rejected_chat_entry_records_nothing(seeded_scope, household):
    """No row written, no event. A failed capture is not a capture."""
    create_entry(
        seeded_scope,
        date_str="2026-08-16",
        amount_str="42.00",
        description="feira",
        category_name="Categoria que não existe",
        payment_method_name="Pix",
    )

    assert _sources(household) == []
