"""Regressão de leitura/registro de recibo, ancorada nos casos reais.

- Americanas (prompt 006): split Roupa/Lanche que virou R$42,16 / R$0,00.
- HIPERMACIONAL (este bug): supermercado com 6 categorias que registrou Pets em
  DOBRO (no próprio item e dentro de Alimentação) e no cartão errado.

Os testes determinísticos (sempre on) registram a partir de um ``ReceiptDraft``
(como em produção) e guardam a MATEMÁTICA: cada item conta UMA vez e a soma bate
com o valor pago. O teste de LLM real é pulado por padrão (rode com
``RUN_LLM_TESTS=1``).
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

FIXTURES = Path(__file__).parent / "fixtures"
AMERICANAS_FIXTURE = FIXTURES / "receipt_americanas.jpg"
HIPERMACIONAL_FIXTURE = FIXTURES / "receipt_hipermacional.jpg"

# Gabarito Americanas (12/06/2026): (descrição, valor, categoria).
AMERICANAS_ITEMS = [
    ("SOUTIEN TOP B+ TAF21 BRANCO GG", "9.99", "Roupa"),
    ("BACONZITOS B&G ELMA CHIPS M", "9.99", "Lanche"),
    ("LAYS CLASSICA B&G ELMA CHIPS M", "9.99", "Lanche"),
    ("WAFER MAIS AMENDOIM 102G HERSHEYS", "6.19", "Lanche"),
    ("BATATA PRINGLES CREME E CEBOLA 109G", "9.99", "Lanche"),
]

# Gabarito HIPERMACIONAL (15/06/2026): 6 categorias, sem desconto, total 376,70.
HIPERMACIONAL_ITEMS = [
    ("MASSA RAINHA PASTEL 1kg", "9.95", "Alimentação"),
    ("LINGUICA CHURRASCO 500G BACON", "18.95", "Alimentação"),
    ("LINGUICA CHURRASCO 500G BIQUINHO", "18.95", "Alimentação"),
    ("QUEIJO ISIS COAL Z LAC kg", "32.73", "Alimentação"),
    ("FILE PEITO REGINA 1kg", "24.75", "Alimentação"),
    ("FILEZINHO REGINA MILANESA 700G", "23.75", "Alimentação"),
    ("BATATA EASYCHEF PRE FRITA 2kg", "24.85", "Alimentação"),
    ("QUEIJO ITAMBE ZERO LAC 150G", "24.90", "Alimentação"),
    ("LEITE UHT PIRACANJU 1L", "10.99", "Alimentação"),
    ("IOG BETANIA YO BEM 170G PAPAIA", "8.30", "Alimentação"),
    ("IOG BETANIA YO BEM 170G MORANGO", "8.30", "Alimentação"),
    ("ALHO kg", "2.62", "Alimentação"),
    ("CEBOLA AMARELA kg", "3.32", "Alimentação"),
    ("EMP LEMON PEPPER kg", "4.55", "Alimentação"),
    ("EMP PAPRIC DEFUMADA kg", "2.58", "Alimentação"),
    ("EMP GERGELIM MIX kg", "4.62", "Alimentação"),
    ("PIMENTAO kg", "1.18", "Alimentação"),
    ("CR LEITE PIRACANJU ZERO LACT 200G", "12.50", "Alimentação"),
    ("OVOS CAIP TIJUCA 10UN", "9.95", "Alimentação"),
    ("BATAT PALH ELMA CHIPS 190G", "22.99", "Alimentação"),
    ("BISC TODDY WAFER 94G CHOC", "3.15", "Alimentação"),
    ("ENERG EXTR POWER 473ML MANGO", "14.50", "Lanche"),
    ("RACAO CHAMP ADULTO 85G FRANGO", "9.45", "Pets"),
    ("RACAO CHAMP ADULTO 85G CARNE", "9.45", "Pets"),
    ("TOALHA PAPEL C 2 SCALA", "5.49", "Casa"),
    ("AMAC DOWNY 1L BRISA", "29.99", "Limpeza"),
    ("DESOD MONANGE AERO 150ML", "9.95", "Perfumaria"),
    ("ESPUMA GILLETTE 155ML", "23.99", "Perfumaria"),
]


def _extraction(flat, *, store, date, discount="0", amount_paid):
    items = [ReceiptItem(description=d, line_total=Decimal(v)) for d, v, _ in flat]
    return ReceiptExtraction(
        store=store,
        date=date,
        items=items,
        total=sum((i.line_total for i in items), Decimal("0")),
        discount=Decimal(discount),
        amount_paid=Decimal(amount_paid),
        confidence=1.0,
    )


def _make_draft(
    user, flat, *, store, date, amount_paid, discount="0", payment_hint="Cartão Crédito"
):
    """Cria um ReceiptDraft pendente e o mapa categoria→[índices] do gabarito."""
    from assistant.models import ReceiptDraft

    payload = {
        "store": store,
        "date": date,
        "discount": discount,
        "amount_paid": amount_paid,
        "payment_hint": payment_hint,
        "items": [{"description": d, "line_total": v} for d, v, _ in flat],
    }
    draft = ReceiptDraft.objects.create(user=user, payload=payload)
    mapping: dict[str, list[int]] = {}
    for idx, (_, _, cat) in enumerate(flat):
        mapping.setdefault(cat, []).append(idx)
    return draft, mapping


def test_fixtures_exist_and_are_images():
    for f in (AMERICANAS_FIXTURE, HIPERMACIONAL_FIXTURE):
        assert f.exists()
        Image.open(f).verify()


def test_americanas_gabarito_is_internally_consistent():
    ext = _extraction(
        AMERICANAS_ITEMS, store="americanas sa - 1063", date="2026-06-12",
        discount="3.99", amount_paid="42.16",
    )
    assert receipt_is_consistent(ext) is True


@pytest.mark.django_db
def test_americanas_split_sums_to_amount_paid(seeded_user):
    from django.db.models import Sum
    from model_bakery import baker

    from assistant.agents.tools import register_receipt
    from finances.models import Entry

    baker.make("finances.Category", user=seeded_user, name="Roupa")
    _make_draft(
        seeded_user, AMERICANAS_ITEMS, store="americanas sa - 1063",
        date="2026-06-12", discount="3.99", amount_paid="42.16",
    )
    register_receipt(
        user=seeded_user,
        items_by_category={"Roupa": [0], "Lanche": [1, 2, 3, 4]},
        payment_method_name="Crédito C6",
    )
    entries = Entry.objects.filter(user=seeded_user)
    assert entries.count() == 2
    assert entries.aggregate(s=Sum("amount"))["s"] == Decimal("42.16")
    assert entries.get(category__name="Roupa").amount > 0
    assert entries.get(category__name="Lanche").amount > 0


@pytest.mark.django_db
def test_hipermacional_no_double_count_and_correct_total(seeded_user):
    """O bug: Pets entrou em dobro e Lanche foi fundido em Alimentação."""
    from django.db.models import Sum
    from model_bakery import baker

    from assistant.agents.tools import register_receipt
    from finances.models import Entry

    for cat in ("Pets", "Casa", "Limpeza", "Perfumaria"):
        baker.make("finances.Category", user=seeded_user, name=cat)
    _, mapping = _make_draft(
        seeded_user, HIPERMACIONAL_ITEMS, store="HIPERMACIONAL LTDA",
        date="2026-06-15", discount="0", amount_paid="376.70",
    )
    msg = register_receipt(
        user=seeded_user,
        items_by_category=mapping,
        payment_method_name="Crédito C6",  # cartão resolvível no seeded_user
        summaries={"Alimentação": "mercearia, carnes e laticínios"},
    )
    assert "✅" in msg
    entries = Entry.objects.filter(user=seeded_user)
    assert entries.count() == 6
    # total correto (não 395,60)
    assert entries.aggregate(s=Sum("amount"))["s"] == Decimal("376.70")
    # Pets contado UMA vez (não 18,90 também dentro de Alimentação)
    assert entries.get(category__name="Pets").amount == Decimal("18.90")
    assert entries.get(category__name="Alimentação").amount == Decimal("273.88")
    # Lanche existe como sua própria linha (não fundido em Alimentação)
    assert entries.get(category__name="Lanche").amount == Decimal("14.50")
    # descrição começa pelo estabelecimento + resumo
    assert entries.get(category__name="Alimentação").description.startswith(
        "HIPERMACIONAL LTDA - "
    )


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="LLM real: requer chave; rode com RUN_LLM_TESTS=1",
)
async def test_real_extraction_reads_hipermacional_receipt():
    from assistant.agents.extraction import extract_receipt

    data = HIPERMACIONAL_FIXTURE.read_bytes()
    ext = await extract_receipt(data, "image/jpeg")
    assert ext.store is not None and "hiper" in ext.store.lower()
    assert receipt_is_consistent(ext)
    assert ext.amount_paid == Decimal("376.70")
