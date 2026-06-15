"""Regressão de leitura de recibo, ancorada no caso real do prompt 006.

A foto ``fixtures/receipt_americanas.jpg`` é o cupom da Americanas que o bot
leu errado (jogou tudo em Lanche; depois Roupa R$42,16 / Lanche R$0,00). O
gabarito abaixo é a leitura correta. Os testes determinísticos (sempre on)
guardam a MATEMÁTICA do split contra exatamente esse caso. O teste de LLM real
é pulado por padrão (precisa de chave); rode com ``RUN_LLM_TESTS=1``.
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from assistant.agents.extraction import (
    ReceiptExtraction,
    ReceiptItem,
    receipt_is_consistent,
)

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_americanas.jpg"

# Gabarito do cupom real (Americanas, 12/06/2026).
GABARITO = {
    "store": "americanas sa - 1063",
    "date": "2026-06-12",
    "discount": Decimal("3.99"),
    "amount_paid": Decimal("42.16"),
    "items_by_category": {
        "Roupa": ["9.99"],  # SOUTIEN TOP B+ TAF21 BRANCO GG
        "Lanche": ["9.99", "9.99", "6.19", "9.99"],  # Baconzitos, Lays, Wafer, Pringles
    },
}


def _gabarito_extraction() -> ReceiptExtraction:
    items = []
    for values in GABARITO["items_by_category"].values():
        items += [ReceiptItem(description="item", line_total=Decimal(v)) for v in values]
    return ReceiptExtraction(
        store=GABARITO["store"],
        date=GABARITO["date"],
        items=items,
        total=sum((i.line_total for i in items), Decimal("0")),
        discount=GABARITO["discount"],
        amount_paid=GABARITO["amount_paid"],
        confidence=1.0,
    )


def test_fixture_exists_and_is_an_image():
    assert FIXTURE.exists()
    img = Image.open(FIXTURE)
    img.verify()


def test_gabarito_is_internally_consistent():
    assert receipt_is_consistent(_gabarito_extraction()) is True


@pytest.mark.django_db
def test_gabarito_split_sums_to_amount_paid(seeded_user):
    """O caso que falhou: o split de categorias DEVE somar 42,16, sem 0,00."""
    from django.db.models import Sum
    from model_bakery import baker

    from assistant.agents.tools import register_receipt
    from finances.models import Entry

    baker.make("finances.Category", user=seeded_user, name="Roupa")
    register_receipt(
        user=seeded_user,
        date_str=GABARITO["date"],
        store=GABARITO["store"],
        payment_method_name="Crédito C6",
        items_by_category=GABARITO["items_by_category"],
        discount=str(GABARITO["discount"]),
    )
    entries = Entry.objects.filter(user=seeded_user)
    assert entries.count() == 2
    assert entries.aggregate(s=Sum("amount"))["s"] == GABARITO["amount_paid"]
    # nenhuma categoria pode ficar zerada (o bug original)
    assert entries.get(category__name="Roupa").amount > 0
    assert entries.get(category__name="Lanche").amount > 0


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="LLM real: requer chave; rode com RUN_LLM_TESTS=1",
)
async def test_real_extraction_reads_americanas_receipt():
    from assistant.agents.extraction import extract_receipt

    data = FIXTURE.read_bytes()
    ext = await extract_receipt(data, "image/jpeg")
    assert ext.store is not None and "americ" in ext.store.lower()
    assert receipt_is_consistent(ext)
    assert ext.amount_paid == Decimal("42.16")
