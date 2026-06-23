from decimal import Decimal

import pytest

from assistant.agents.tools import propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Entry

pytestmark = pytest.mark.django_db


def _draft(user, **over):
    payload = {
        "store": "MATEUS",
        "date": "2026-06-22",
        "discount": "0",
        "amount_paid": "100.00",
        "payment_hint": "Pix",
        "items": [
            {"description": "arroz", "line_total": "60.00"},
            {"description": "refri", "line_total": "40.00"},
        ],
    }
    payload.update(over)
    return ReceiptDraft.objects.create(
        user=user, payload=payload, status=ReceiptDraftStatus.PENDING
    )


def test_propose_stores_plan_and_writes_nothing(seeded_user):
    _draft(seeded_user)
    out = propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
        summaries={"Alimentação": "grãos", "Lanche": "bebida"},
    )
    assert Entry.objects.count() == 0  # nothing written
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert draft.status == ReceiptDraftStatus.PENDING
    plan = (draft.payload or {}).get("plan")
    assert plan is not None
    amounts = sorted(Decimal(l["amount"]) for l in plan["lines"])
    assert amounts == [Decimal("40.00"), Decimal("60.00")]
    assert plan["payment_method_name"] == "Pix"
    assert "Confirma" in out


def test_propose_rejects_incomplete_coverage(seeded_user):
    _draft(seeded_user)
    out = propose_receipt(seeded_user, items_by_category={"Alimentação": [0]})
    assert "exatamente UMA" in out  # item 1 missing
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert "plan" not in (draft.payload or {})


def test_propose_ambiguous_payment_asks(seeded_user):
    _draft(seeded_user, payment_hint="")
    out = propose_receipt(
        seeded_user, items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="",
    )
    assert "forma de pagamento" in out.lower()
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert "plan" not in (draft.payload or {})
