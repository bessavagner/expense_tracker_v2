import pytest

from assistant.agents.extraction import ReceiptExtraction, extraction_to_prompt
from assistant.agents.prompts import ASSISTANT_PROMPT
from assistant.agents.tools import build_pending_receipt_directive
from assistant.models import ReceiptDraft, ReceiptDraftStatus

pytestmark = pytest.mark.django_db


def test_extraction_prompt_asks_for_readable_summaries():

    ext = ReceiptExtraction(
        store="Cosmos",
        amount_paid="13.00",
        items=[{"description": "ENERG MONSTER", "line_total": "10.00", "category": "Lanche"}],
    )
    out = extraction_to_prompt(ext)
    low = out.lower()
    assert "summaries" in out
    assert "resumo" in low or "legível" in low or "legivel" in low


def test_pending_directive_asks_summaries_and_learns_category(seeded_user, seeded_scope, household):
    ReceiptDraft.objects.create(
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos",
            "amount_paid": "13.00",
            "items": [{"description": "ENERG MONSTER", "line_total": "10.00"}],
        },
    )
    out = build_pending_receipt_directive(seeded_scope)
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
        store="Cosmos",
        amount_paid="13.00",
        items=[{"description": "ENERG MONSTER", "line_total": "10.00", "category": "Lanche"}],
    )
    out = extraction_to_prompt(ext, needs_review=True)
    low = out.lower()
    assert "summaries" in out
    assert "não inclua o nome da loja" in low or "nome da loja" in low


def test_pending_directive_forbids_hand_typed_table(seeded_user, seeded_scope, household):
    """Bug real (Mercado Livre 2026-07-15): o modelo digitou uma tabela com
    categorias inventadas ("Vestuário", "Eletrônicos" — nomes que não existem
    nas categorias do usuário) e sem coluna de valor, em vez de mostrar o texto
    literal devolvido por propose_receipt(). A diretiva deve proibir isso
    explicitamente.
    """
    ReceiptDraft.objects.create(
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Mercado Livre",
            "amount_paid": None,
            "items": [{"description": "Bermuda", "line_total": "66.09"}],
        },
    )
    out = build_pending_receipt_directive(seeded_scope)
    low = out.lower()
    assert "nunca" in low and ("digite" in low or "monte" in low or "invente a tabela" in low)
    assert "literal" in low or "exatamente o texto" in low


def test_pending_directive_payment_method_is_sticky(seeded_user, seeded_scope, household):
    """Bug real: o bot perguntou a forma de pagamento 3 vezes no mesmo recibo,
    mesmo já resolvida (legenda da foto + resposta explícita do usuário)."""
    ReceiptDraft.objects.create(
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Mercado Livre",
            "amount_paid": None,
            "items": [{"description": "Bermuda", "line_total": "66.09"}],
        },
    )
    out = build_pending_receipt_directive(seeded_scope)
    low = out.lower()
    assert "já foi resolvida" in low or "já resolvida" in low or "já informou" in low
    assert "nunca pergunte de novo" in low or "não pergunte de novo" in low
