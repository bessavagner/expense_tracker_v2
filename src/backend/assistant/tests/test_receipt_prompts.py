import pytest

from assistant.agents.extraction import ReceiptExtraction, extraction_to_prompt
from assistant.agents.prompts import ASSISTANT_PROMPT
from assistant.agents.tools import build_pending_receipt_directive
from assistant.models import ReceiptDraft, ReceiptDraftStatus

pytestmark = pytest.mark.django_db


def test_extraction_prompt_asks_for_readable_summaries():
    ext = ReceiptExtraction(
        store="Cosmos", amount_paid="13.00",
        items=[{"description": "ENERG MONSTER", "line_total": "10.00", "category": "Lanche"}],
    )
    out = extraction_to_prompt(ext)
    low = out.lower()
    assert "summaries" in out
    assert "resumo" in low or "legível" in low or "legivel" in low


def test_pending_directive_asks_summaries_and_learns_category(seeded_user):
    ReceiptDraft.objects.create(
        user=seeded_user, status=ReceiptDraftStatus.PENDING,
        payload={"store": "Cosmos", "amount_paid": "13.00",
                 "items": [{"description": "ENERG MONSTER", "line_total": "10.00"}]},
    )
    out = build_pending_receipt_directive(seeded_user)
    low = out.lower()
    # readable summaries requested
    assert "summaries" in out and ("resumo" in low or "legível" in low or "legivel" in low)
    # learn category on correction
    assert "save_memory_rule" in out
    assert "category" in out
    # trigger must be an NF token, not a colloquial word
    assert "trecho" in low or "aparece" in low or "nome do item" in low


def test_assistant_system_prompt_asks_for_summaries():
    assert "summaries" in ASSISTANT_PROMPT
    assert "não passe summaries" not in ASSISTANT_PROMPT


def test_extraction_needs_review_head_no_store_name():
    ext = ReceiptExtraction(
        store="Cosmos", amount_paid="13.00",
        items=[{"description": "ENERG MONSTER", "line_total": "10.00", "category": "Lanche"}],
    )
    out = extraction_to_prompt(ext, needs_review=True)
    low = out.lower()
    assert "summaries" in out
    assert "não inclua o nome da loja" in low or "nome da loja" in low
