from decimal import Decimal

import pytest
from pydantic_ai.models.test import TestModel

from assistant.agents.extraction import (
    ReceiptExtraction,
    ReceiptItem,
    extract_receipt,
    extraction_agent,
    extraction_to_prompt,
    receipt_is_consistent,
    receipt_needs_review,
)


def _extraction(items, discount="0", amount_paid=None):
    items = [ReceiptItem(description=d, line_total=Decimal(v)) for d, v in items]
    total = sum((i.line_total for i in items), Decimal("0"))
    paid = Decimal(amount_paid) if amount_paid is not None else total - Decimal(discount)
    return ReceiptExtraction(
        store="Loja X",
        date="2026-06-12",
        items=items,
        total=total,
        discount=Decimal(discount),
        amount_paid=paid,
        confidence=0.9,
    )


def test_schema_holds_items_and_totals():
    ext = _extraction([("Soutien", "9.99"), ("Lays", "9.99")], discount="0")
    assert len(ext.items) == 2
    assert ext.items[0].description == "Soutien"
    assert ext.items[0].quantity == Decimal("1")  # default
    assert ext.total == Decimal("19.98")


def test_consistent_true_when_sum_matches_paid():
    ext = _extraction(
        [("a", "9.99"), ("b", "9.99"), ("c", "9.99"), ("d", "6.19"), ("e", "9.99")],
        discount="3.99",
        amount_paid="42.16",
    )
    assert receipt_is_consistent(ext) is True


def test_consistent_false_when_mismatch():
    ext = _extraction([("a", "10.00")], discount="0", amount_paid="42.16")
    assert receipt_is_consistent(ext) is False


def test_consistent_within_small_tolerance():
    ext = _extraction([("a", "10.00")], discount="0", amount_paid="10.03")
    assert receipt_is_consistent(ext) is True  # 0.03 <= 0.05


def test_needs_review_when_confidence_low():
    ext = _extraction([("a", "10.00")], discount="0", amount_paid="10.00")
    ext.confidence = 0.3
    assert receipt_needs_review(ext, min_confidence=0.6) is True


def test_needs_review_when_sum_does_not_close():
    ext = _extraction([("a", "10.00")], discount="0", amount_paid="42.16")
    ext.confidence = 0.99
    assert receipt_needs_review(ext, min_confidence=0.6) is True


def test_needs_review_when_no_items():
    ext = ReceiptExtraction(items=[], confidence=0.99, amount_paid=Decimal("0"))
    assert receipt_needs_review(ext, min_confidence=0.6) is True


def test_no_review_when_confident_and_consistent():
    ext = _extraction(
        [("a", "9.99"), ("b", "9.99"), ("c", "9.99"), ("d", "6.19"), ("e", "9.99")],
        discount="3.99",
        amount_paid="42.16",
    )
    ext.confidence = 0.9
    assert receipt_needs_review(ext, min_confidence=0.6) is False


def test_extraction_to_prompt_review_adds_caution():
    ext = _extraction([("a", "10.00")], discount="0")
    prompt = extraction_to_prompt(ext, needs_review=True)
    low = prompt.lower()
    assert "incerta" in low
    assert "confirm" in low
    assert "propose_receipt" in prompt


def test_extraction_to_prompt_lists_items_and_tool():
    ext = _extraction([("Soutien", "9.99"), ("Lays", "9.99")], discount="0")
    prompt = extraction_to_prompt(ext, caption="paguei no c6")
    assert "Soutien" in prompt and "Lays" in prompt
    assert "propose_receipt" in prompt
    assert "Loja X" in prompt
    assert "paguei no c6" in prompt


def test_extraction_to_prompt_instructs_hiding_internal_indices():
    """Os índices [0,1,...] são argumento de propose_receipt, NÃO devem ser
    exibidos ao usuário; o prompt precisa instruir isso explicitamente."""
    ext = _extraction([("a", "10.00"), ("b", "5.00")], discount="0")
    low = extraction_to_prompt(ext).lower()
    assert "índice" in low
    assert "nunca" in low  # "NUNCA exiba/mostre esses índices ao usuário"


def test_extraction_to_prompt_asks_to_confirm_exactly_once():
    """Evita o 'Confirma? Confirma?' — uma única pergunta de confirmação."""
    ext = _extraction([("a", "10.00")], discount="0")
    prompt = extraction_to_prompt(ext)
    assert prompt.count("Confirma?") == 1
    assert "uma única" in prompt.lower()


def test_extraction_to_prompt_brand_payment_routes_through_card_and_memory():
    """Bandeira (VISA/MASTER...) é genérica: usar dígitos do cartão + memória,
    e perguntar qual cartão quando não houver regra."""
    ext = _extraction([("a", "10.00")], discount="0")
    ext.payment_hint = "VISA CRÉDITO"
    ext.card_last4 = "4068"
    prompt = extraction_to_prompt(ext)
    low = prompt.lower()
    assert "4068" in prompt  # o final do cartão chega ao agente
    assert "check_memory" in low
    assert "save_memory_rule" in low
    assert "get_payment_methods" in low


def test_extraction_prompt_instructs_propose_not_write():
    ext = ReceiptExtraction(
        store="MATEUS",
        date="2026-06-22",
        items=[],
        amount_paid=Decimal("0"),
        discount=Decimal("0"),
    )
    for needs_review in (False, True):
        p = extraction_to_prompt(ext, "", needs_review=needs_review)
        assert "propose_receipt" in p
        assert "register_receipt" not in p
        assert "Confirma" in p


@pytest.mark.anyio
async def test_extract_receipt_returns_extraction():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    with extraction_agent.override(model=TestModel()):
        result = await extract_receipt([(png, "image/png")])
    assert isinstance(result, ReceiptExtraction)
    assert isinstance(result.confidence, float)


@pytest.mark.anyio
async def test_extract_receipt_sends_all_images_in_one_run(monkeypatch):
    """Várias imagens (páginas do mesmo recibo) vão num único run de visão."""
    captured = {}

    real_run = extraction_agent.run

    async def spy_run(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return await real_run(prompt, *args, **kwargs)

    monkeypatch.setattr(extraction_agent, "run", spy_run)

    images = [(b"img-a", "image/jpeg"), (b"img-b", "image/png")]
    with extraction_agent.override(model=TestModel()):
        await extract_receipt(images)

    prompt = captured["prompt"]
    from pydantic_ai import BinaryContent
    binaries = [p for p in prompt if isinstance(p, BinaryContent)]
    assert len(binaries) == 2
    assert binaries[0].data == b"img-a"
    assert binaries[1].media_type == "image/png"
