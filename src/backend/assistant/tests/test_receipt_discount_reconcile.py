"""Regressão do recibo DROGASIL (04/07): desconto contado em dobro.

O cupom trazia os valores de LINHA já LÍQUIDOS (Valor Líquido, já com desconto):
6,99 + 57,99 + 6,99 + 39,90 + 6,99 = 118,86 = VALOR PAGO. Mas a extração também
lia ``discount=27,60`` (o total de descontos informado) e ``_prorate_discount``
subtraía esse valor DE NOVO, produzindo R$ 91,26 (118,86 − 27,60). O bot então
insistia no total errado e sinalizava falsa inconsistência.

Invariante correto: a soma das linhas gravadas tem de bater com o VALOR PAGO. O
desconto a ratear é DERIVADO como ``soma(linhas) − valor_pago`` (0 quando as
linhas já são líquidas), não o campo ``discount`` impresso.
"""

from decimal import Decimal

import pytest

from assistant.agents.extraction import ReceiptExtraction, ReceiptItem, receipt_is_consistent
from assistant.agents.tools import commit_receipt, propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Entry

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded_user(seeded_user):
    """Adiciona a categoria Farmácia (o recibo de drogaria usa saúde/farmácia)."""
    from model_bakery import baker

    baker.make("finances.Category", user=seeded_user, name="Farmácia")
    return seeded_user


def _drogasil_draft(user):
    """Linhas JÁ LÍQUIDAS que somam 118,86 = valor pago; discount impresso 27,60."""
    return ReceiptDraft.objects.create(
        user=user,
        payload={
            "store": "Drogasil",
            "date": "2026-07-04",
            "discount": "27.60",
            "total": "118.86",
            "amount_paid": "118.86",
            "payment_hint": "Pix",
            "items": [
                {
                    "description": "PIRACANJ WH CACAU250ML",
                    "line_total": "6.99",
                    "category": "Alimentação",
                },
                {
                    "description": "PROFU PURIANC CONT 150",
                    "line_total": "57.99",
                    "category": "Farmácia",
                },
                {
                    "description": "PIRACANJ WH CACAU250ML",
                    "line_total": "6.99",
                    "category": "Alimentação",
                },
                {
                    "description": "NASOAR REFIL 30 ENVEL",
                    "line_total": "39.90",
                    "category": "Farmácia",
                },
                {
                    "description": "PIRACANJ WH AMEND250ML",
                    "line_total": "6.99",
                    "category": "Alimentação",
                },
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )


def test_net_lines_do_not_double_subtract_discount(seeded_user, seeded_scope):
    """Linhas líquidas + discount impresso → plano bate com valor pago (118,86),
    NÃO 91,26."""
    _drogasil_draft(seeded_user)
    propose_receipt(seeded_scope, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    assert Decimal(plan["total"]) == Decimal("118.86")
    # Alimentação = 3×6,99 = 20,97 (não 16,10); Farmácia = 57,99+39,90 = 97,89
    by_cat = {ln["category_name"]: Decimal(ln["amount"]) for ln in plan["lines"]}
    assert by_cat["Alimentação"] == Decimal("20.97")
    assert by_cat["Farmácia"] == Decimal("97.89")


def test_net_lines_commit_totals_paid(seeded_user, seeded_scope):
    _drogasil_draft(seeded_user)
    propose_receipt(seeded_scope, payment_method_name="Pix")
    commit_receipt(seeded_scope)
    total = sum((e.amount for e in Entry.objects.filter(user=seeded_user)), Decimal("0"))
    assert total == Decimal("118.86")


def test_gross_lines_still_prorate_discount(seeded_user, seeded_scope):
    """Quando as linhas são BRUTAS e o desconto leva ao valor pago, o rateio
    continua válido (recibo PAGUE MENOS: 217,32 − 61,42 = 155,90)."""
    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={
            "store": "PAGUE MENOS",
            "date": "2026-07-04",
            "discount": "61.42",
            "total": "217.32",
            "amount_paid": "155.90",
            "payment_hint": "Pix",
            "items": [
                {"description": "item caro", "line_total": "160.00", "category": "Farmácia"},
                {"description": "item barato", "line_total": "57.32", "category": "Alimentação"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )
    propose_receipt(seeded_scope, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    assert Decimal(plan["total"]) == Decimal("155.90")


def test_no_amount_paid_falls_back_to_printed_discount(seeded_user, seeded_scope):
    """Sem valor pago, usa o desconto impresso (comportamento anterior)."""
    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={
            "store": "Loja",
            "discount": "10.00",
            "amount_paid": None,
            "payment_hint": "Pix",
            "items": [
                {"description": "a", "line_total": "60.00", "category": "Alimentação"},
                {"description": "b", "line_total": "40.00", "category": "Lanche"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )
    propose_receipt(seeded_scope, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    assert Decimal(plan["total"]) == Decimal("90.00")  # 100 - 10 printed discount


# ── consistência: recibo líquido NÃO é falso-inconsistente ──────────────────


def _ext(items, discount, paid):

    return ReceiptExtraction(
        items=[ReceiptItem(description="x", line_total=Decimal(v)) for v in items],
        discount=Decimal(discount) if discount is not None else None,
        amount_paid=Decimal(paid) if paid is not None else None,
    )


def test_consistency_net_receipt_is_consistent():

    # Drogasil: linhas líquidas somam o valor pago; discount impresso 27,60
    ext = _ext(["6.99", "57.99", "6.99", "39.90", "6.99"], "27.60", "118.86")
    assert receipt_is_consistent(ext) is True


def test_consistency_gross_receipt_is_consistent():

    # linhas brutas; a diferença bate com o desconto impresso
    ext = _ext(["160.00", "57.32"], "61.42", "155.90")
    assert receipt_is_consistent(ext) is True


def test_consistency_missing_item_flagged():

    # soma das linhas MENOR que o valor pago → leitura incompleta
    ext = _ext(["10.00", "20.00"], None, "118.86")
    assert receipt_is_consistent(ext) is False
