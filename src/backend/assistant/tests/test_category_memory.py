import pytest

from assistant.agents.tools import _apply_category_memory, propose_receipt
from assistant.models import MemoryRule, MemorySource, ReceiptDraft, ReceiptDraftStatus

pytestmark = pytest.mark.django_db


def _rule(user, trigger, value):

    return MemoryRule.objects.create(
        user=user,
        trigger=trigger,
        field="category",
        value=value,
        source=MemorySource.USER_CORRECTION,
    )


def test_apply_overrides_category_from_rule(seeded_user, seeded_scope):
    _rule(seeded_user, "energ", "Lanche")
    _rule(seeded_user, "refrig", "Lanche")
    items = [
        {"description": "ENERG MONSTER 473ML", "category": "Alimentação"},
        {"description": "REFRIG LARANJA SJ 350ML", "category": "Alimentação"},
        {"description": "BROCOLIS ESP KG", "category": "Alimentação"},
    ]
    _apply_category_memory(seeded_scope, items)
    assert items[0]["category"] == "Lanche"
    assert items[1]["category"] == "Lanche"
    assert items[2]["category"] == "Alimentação"  # no rule → unchanged


def test_apply_case_insensitive_and_uppercase_trigger(seeded_user, seeded_scope):
    # even if a trigger were stored uppercase, matching is case-insensitive
    MemoryRule.objects.create(
        user=seeded_user,
        trigger="MONSTER",
        field="category",
        value="Lanche",
        source=MemorySource.USER_CORRECTION,
    )
    items = [{"description": "energ monster 473ml", "category": "Alimentação"}]
    _apply_category_memory(seeded_scope, items)
    assert items[0]["category"] == "Lanche"


def test_apply_longest_trigger_wins(seeded_user, seeded_scope):
    _rule(seeded_user, "queijo", "Alimentação")
    _rule(seeded_user, "queijo coalho", "Lanche")
    items = [{"description": "QUEIJO COALHO ZERO LACTOSE", "category": "?"}]
    _apply_category_memory(seeded_scope, items)
    assert items[0]["category"] == "Lanche"


def test_apply_no_rules_is_noop(seeded_user, seeded_scope):
    items = [{"description": "ENERG MONSTER", "category": "Alimentação"}]
    _apply_category_memory(seeded_scope, items)
    assert items[0]["category"] == "Alimentação"


def test_propose_auto_path_applies_rules(seeded_user, seeded_scope):
    _rule(seeded_user, "energ", "Lanche")
    ReceiptDraft.objects.create(
        user=seeded_user,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos",
            "date": "2026-07-06",
            "amount_paid": "13.00",
            "payment_hint": "Pix",
            "items": [
                {
                    "description": "ENERG MONSTER 473ML",
                    "line_total": "10.00",
                    "category": "Alimentação",
                },
                {
                    "description": "BROCOLIS ESP KG",
                    "line_total": "3.00",
                    "category": "Alimentação",
                },
            ],
        },
    )
    propose_receipt(seeded_scope, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    cats = {ln["category_name"] for ln in plan["lines"]}
    assert cats == {"Lanche", "Alimentação"}


def test_propose_explicit_categories_not_overridden(seeded_user, seeded_scope):

    _rule(seeded_user, "energ", "Lanche")  # would move item 0 to Lanche in auto path
    ReceiptDraft.objects.create(
        user=seeded_user,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos",
            "date": "2026-07-06",
            "amount_paid": "13.00",
            "payment_hint": "Pix",
            "items": [
                {
                    "description": "ENERG MONSTER 473ML",
                    "line_total": "10.00",
                    "category": "Alimentação",
                },
                {
                    "description": "BROCOLIS ESP KG",
                    "line_total": "3.00",
                    "category": "Alimentação",
                },
            ],
        },
    )
    # user explicitly assigns BOTH items to Alimentação this turn
    propose_receipt(
        seeded_scope, items_by_category={"Alimentação": [0, 1]}, payment_method_name="Pix"
    )
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    cats = {ln["category_name"] for ln in plan["lines"]}
    assert cats == {"Alimentação"}  # rule NOT applied; explicit assignment won


def test_propose_preserves_commas_in_summary(seeded_user, seeded_scope):

    ReceiptDraft.objects.create(
        user=seeded_user,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos",
            "date": "2026-07-06",
            "amount_paid": "10.00",
            "payment_hint": "Pix",
            "items": [{"description": "X", "line_total": "10.00", "category": "Lanche"}],
        },
    )
    propose_receipt(
        seeded_scope,
        payment_method_name="Pix",
        summaries={"Lanche": "bolachas, energéticos e refrigerantes"},
    )
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    assert plan["lines"][0]["description"] == "Cosmos - bolachas, energéticos e refrigerantes"
