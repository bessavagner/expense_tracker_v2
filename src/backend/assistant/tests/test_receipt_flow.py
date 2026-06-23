from decimal import Decimal

import pytest

from assistant.agents.tools import (
    add_receipt_item,
    commit_receipt,
    discard_receipt,
    propose_receipt,
)
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
    amounts = sorted(Decimal(ln["amount"]) for ln in plan["lines"])
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
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="",
    )
    assert "forma de pagamento" in out.lower()
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert "plan" not in (draft.payload or {})


def test_commit_creates_entries_once_and_is_idempotent(seeded_user):
    _draft(seeded_user)
    propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
    )
    out = commit_receipt(seeded_user)
    assert Entry.objects.filter(user=seeded_user).count() == 2
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert draft.status == ReceiptDraftStatus.REGISTERED
    assert "Registrado" in out
    total = sorted(e.amount for e in Entry.objects.filter(user=seeded_user))
    assert total == [Decimal("40.00"), Decimal("60.00")]
    # second confirm must NOT duplicate
    out2 = commit_receipt(seeded_user)
    assert Entry.objects.filter(user=seeded_user).count() == 2
    assert "pendente" in out2.lower()


def test_commit_without_plan_writes_nothing(seeded_user):
    _draft(seeded_user)  # pending draft but no propose() => no plan
    out = commit_receipt(seeded_user)
    assert Entry.objects.count() == 0
    assert "pendente" in out.lower()


def test_discard_blocks_commit(seeded_user):
    _draft(seeded_user)
    propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
    )
    discard_receipt(seeded_user)
    out = commit_receipt(seeded_user)
    assert Entry.objects.count() == 0
    assert "pendente" in out.lower()


def test_assistant_agent_exposes_receipt_and_write_tools():
    from assistant.agents.assistant import assistant_agent

    names = set(assistant_agent._function_toolset.tools.keys())
    assert {"propose_receipt", "commit_receipt", "discard_receipt"} <= names
    assert {"register_entry", "add_receipt_item"} <= names
    assert "register_receipt" not in names


def _draft_categorized(user):
    return ReceiptDraft.objects.create(
        user=user,
        payload={
            "store": "MATEUS",
            "date": "2026-06-22",
            "discount": None,
            "amount_paid": "100.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "arroz", "line_total": "60.00", "category": "Alimentação"},
                {"description": "refri", "line_total": "40.00", "category": "Lanche"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )


def test_propose_auto_mode_groups_by_item_category(seeded_user):
    _draft_categorized(seeded_user)
    out = propose_receipt(seeded_user, payment_method_name="Pix")  # no items_by_category
    assert Entry.objects.count() == 0
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    amounts = sorted(Decimal(ln["amount"]) for ln in plan["lines"])
    assert amounts == [Decimal("40.00"), Decimal("60.00")]
    assert "Confirma" in out


def test_propose_auto_mode_errors_when_item_uncategorized(seeded_user):
    _draft(seeded_user)  # items have NO category
    out = propose_receipt(seeded_user, payment_method_name="Pix")
    assert "categor" in out.lower()  # asks for categorization
    assert "plan" not in (
        ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload or {}
    )


def test_description_uses_product_names_not_category(seeded_user):
    """Sem summaries explícitos, a descrição é montada dos NOMES dos produtos
    (não o nome da categoria). Regressão do recibo Mercado Livre."""
    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={
            "store": "Mercado Livre",
            "date": "2026-06-23",
            "discount": "0",
            "amount_paid": "100.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "arroz tipo 1", "line_total": "60.00", "category": "Alimentação"},
                {"description": "feijão preto", "line_total": "40.00", "category": "Alimentação"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )
    out = propose_receipt(seeded_user, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    desc = plan["lines"][0]["description"]
    assert "arroz tipo 1" in desc and "feijão preto" in desc
    assert desc.startswith("Mercado Livre -")
    assert desc != "Mercado Livre - Alimentação"  # not the bare category name
    # the proposal table shows the items so the user can verify before commit
    assert "arroz tipo 1" in out
    assert "Itens" in out


def test_explicit_summary_still_wins(seeded_user):
    _draft_categorized(seeded_user)
    propose_receipt(
        seeded_user,
        payment_method_name="Pix",
        summaries={"Alimentação": "grãos", "Lanche": "bebida"},
    )
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    descs = {ln["category_name"]: ln["description"] for ln in plan["lines"]}
    assert descs["Alimentação"] == "MATEUS - grãos"
    assert descs["Lanche"] == "MATEUS - bebida"


def test_store_name_override(seeded_user):
    _draft(seeded_user, store=None)  # no store → would fall back to "Recibo"
    out = propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
        store_name="Mercado Livre",
    )
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert draft.payload["store"] == "Mercado Livre"  # persisted for re-propose
    for ln in draft.payload["plan"]["lines"]:
        assert ln["description"].startswith("Mercado Livre -")
    assert "Mercado Livre" in out


def test_pending_directive_guides_compound_and_store(seeded_user):
    from assistant.agents.tools import build_pending_receipt_directive

    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={
            "store": "Recibo",
            "amount_paid": "100.00",
            "items": [{"description": "x", "line_total": "10.00", "category": "Alimentação"}],
        },
        status=ReceiptDraftStatus.PENDING,
    )
    out = build_pending_receipt_directive(seeded_user)
    assert "add_receipt_item" in out
    assert "store_name" in out
    assert "commit_receipt" in out
    assert "delegate_registro" not in out
    assert "uma vez" in out.lower()  # ask payment at most once


def test_add_receipt_item_then_propose_folds_frete(seeded_user):
    """O frete adicionado entra na categoria e na descrição ao re-propor."""
    _draft_categorized(seeded_user)  # arroz 60 Alimentação, refri 40 Lanche
    add_receipt_item(seeded_user, "frete", "39.97", "Alimentação")
    propose_receipt(seeded_user, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    ali = next(ln for ln in plan["lines"] if ln["category_name"] == "Alimentação")
    assert "frete" in ali["description"]
    assert Decimal(ali["amount"]) == Decimal("99.97")  # 60.00 + 39.97
