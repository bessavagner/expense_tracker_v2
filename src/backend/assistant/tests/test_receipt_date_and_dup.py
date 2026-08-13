"""Regressões do incidente PAGUE MENOS (06/07):

Bug 1 — a extração devolveu a data como 'dd/mm/aaaa HH:MM:SS' (formato BR + hora),
que ``date.fromisoformat`` não parseia; o recibo caía silenciosamente na data de
HOJE em vez da data do cupom.

Bug 2 — reenviar a MESMA foto (só para o bot identificar/corrigir) abria um novo
fluxo de recibo pendente; um "sim" seguinte era sequestrado pela diretiva de
recibo pendente e o recibo era REGISTRADO de novo (duplicata).
"""

import pytest

from assistant.agents.extraction import ReceiptExtraction, normalize_receipt_date
from assistant.agents.tools import (
    build_duplicate_receipt_directive,
    commit_receipt,
    find_registered_duplicate,
    propose_receipt,
)
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Entry

pytestmark = pytest.mark.django_db


# ── Bug 1: normalização/parse de data ───────────────────────────────────────


def test_normalize_brazilian_date_with_time():

    # o caso real do cupom PAGUE MENOS
    assert normalize_receipt_date("04/07/2026 12:09:32") == "2026-07-04"


def test_normalize_iso_passthrough():

    assert normalize_receipt_date("2026-07-04") == "2026-07-04"


def test_normalize_iso_datetime_drops_time():

    assert normalize_receipt_date("2026-07-04T12:09:32") == "2026-07-04"


def test_normalize_two_digit_year():

    assert normalize_receipt_date("04/07/26") == "2026-07-04"


def test_normalize_unparseable_returns_none():

    assert normalize_receipt_date("sem data") is None
    assert normalize_receipt_date(None) is None
    assert normalize_receipt_date("") is None


def test_extraction_model_normalizes_date_field():

    ext = ReceiptExtraction(date="04/07/2026 12:09:32")
    assert ext.date == "2026-07-04"


def test_propose_uses_cupom_date_not_today(seeded_user, seeded_scope):
    """Draft com data BR+hora → o plano/entry usa a data do cupom, não hoje."""
    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={
            "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
            "date": "04/07/2026 12:09:32",
            "amount_paid": "100.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "arroz", "line_total": "60.00", "category": "Alimentação"},
                {"description": "refri", "line_total": "40.00", "category": "Lanche"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )
    propose_receipt(seeded_scope, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    assert plan["date"] == "2026-07-04"
    commit_receipt(seeded_scope)
    for e in Entry.objects.filter(user=seeded_user):
        assert e.date.isoformat() == "2026-07-04"


# ── Bug 2: detecção de recibo já registrado (reenvio) ───────────────────────


def _registered(user, **over):

    payload = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "date": "2026-07-04",
        "amount_paid": "155.90",
        "items": [
            {"description": "lemont", "line_total": "135.98", "category": "Farmácia"},
            {"description": "barra", "line_total": "19.92", "category": "Alimentação"},
        ],
    }
    payload.update(over)
    return ReceiptDraft.objects.create(
        user=user, payload=payload, status=ReceiptDraftStatus.REGISTERED
    )


def test_find_duplicate_matches_store_and_paid(seeded_user, seeded_scope):
    _registered(seeded_user)
    incoming = {
        "store": "empreendimentos pague menos s/a",  # case-insensitive
        "amount_paid": "155.90",
        "items": [
            {"description": "x", "line_total": "135.98"},
            {"description": "y", "line_total": "19.92"},
        ],
    }
    assert find_registered_duplicate(seeded_scope, incoming) is not None


def test_find_duplicate_matches_by_items_when_paid_missing(seeded_user, seeded_scope):
    _registered(seeded_user, amount_paid=None)
    incoming = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "amount_paid": None,
        "items": [
            {"description": "x", "line_total": "135.98"},
            {"description": "y", "line_total": "19.92"},
        ],
    }
    assert find_registered_duplicate(seeded_scope, incoming) is not None


def test_find_duplicate_none_for_different_total(seeded_user, seeded_scope):
    _registered(seeded_user)
    incoming = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "amount_paid": "999.00",
        "items": [{"description": "x", "line_total": "999.00"}],
    }
    assert find_registered_duplicate(seeded_scope, incoming) is None


def test_find_duplicate_ignores_pending_and_other_store(seeded_user, seeded_scope):
    # pending (não conta) e loja diferente (não conta)
    ReceiptDraft.objects.create(
        user=seeded_user,
        payload={"store": "PAGUE MENOS", "amount_paid": "155.90", "items": []},
        status=ReceiptDraftStatus.PENDING,
    )
    _registered(seeded_user, store="OUTRA LOJA")
    incoming = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "amount_paid": "155.90",
        "items": [{"description": "x", "line_total": "155.90"}],
    }
    assert find_registered_duplicate(seeded_scope, incoming) is None


def test_duplicate_directive_steers_to_edit_not_register(seeded_user, seeded_scope):

    dup = _registered(seeded_user)
    out = build_duplicate_receipt_directive(
        seeded_scope,
        {"store": "EMPREENDIMENTOS PAGUE MENOS S/A", "amount_paid": "155.90", "items": []},
        dup,
    )
    low = out.lower()
    assert "já" in low and "registrad" in low  # avisa que já foi registrado
    assert "list_recent_entries" in out and "update_entry" in out  # caminho de edição
    assert "não registre" in low or "nao registre" in low  # proíbe re-registro cego


# ── Evidence-based dedup: a registered receipt whose entries were DELETED must
#    NOT count as a duplicate (so the user can safely re-send the photo). ──────


def _plan_payload(**over):

    payload = {
        "store": "Drogasil",
        "date": "2026-07-04",
        "amount_paid": "118.86",
        "items": [
            {"description": "a", "line_total": "20.97", "category": "Alimentação"},
            {"description": "b", "line_total": "97.89", "category": "Saúde"},
        ],
        "plan": {
            "store": "Drogasil",
            "date": "2026-07-04",
            "payment_method_id": None,  # set per-test
            "lines": [
                {"category_name": "Alimentação", "description": "Drogasil - a", "amount": "20.97"},
                {"category_name": "Saúde", "description": "Drogasil - b", "amount": "97.89"},
            ],
            "total": "118.86",
        },
    }
    payload.update(over)
    return payload


def _incoming():

    return {
        "store": "Drogasil",
        "amount_paid": "118.86",
        "items": [
            {"description": "x", "line_total": "20.97"},
            {"description": "y", "line_total": "97.89"},
        ],
    }


def test_deleted_entries_not_a_duplicate(seeded_user, seeded_scope):
    """Registered draft WITH a plan but NO live entries → re-send is allowed."""
    from finances.models import PaymentMethod

    pm = PaymentMethod.objects.filter(user=seeded_user).first()
    payload = _plan_payload()
    payload["plan"]["payment_method_id"] = str(pm.id)
    ReceiptDraft.objects.create(
        user=seeded_user, payload=payload, status=ReceiptDraftStatus.REGISTERED
    )
    # No Entry rows created (they were "deleted").
    assert find_registered_duplicate(seeded_scope, _incoming()) is None


def test_live_entries_still_a_duplicate(seeded_user, seeded_scope):
    """Registered draft WITH a plan AND matching live entries → still a dup."""
    from datetime import date

    from finances.models import Category, PaymentMethod

    pm = PaymentMethod.objects.filter(user=seeded_user).first()
    cat = Category.objects.filter(user=seeded_user).first()
    payload = _plan_payload()
    payload["plan"]["payment_method_id"] = str(pm.id)
    ReceiptDraft.objects.create(
        user=seeded_user, payload=payload, status=ReceiptDraftStatus.REGISTERED
    )
    # One matching live entry (date + pm + amount) is enough.
    Entry.objects.create(
        user=seeded_user,
        date=date(2026, 7, 4),
        amount="20.97",
        description="Drogasil - a",
        category=cat,
        payment_method=pm,
    )
    assert find_registered_duplicate(seeded_scope, _incoming()) is not None


def test_legacy_draft_without_plan_still_duplicate(seeded_user, seeded_scope):
    """No 'plan' key (pre-plan drafts) → fallback keeps dup behavior."""
    _registered(seeded_user)  # helper payload has NO 'plan'
    incoming = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "amount_paid": "155.90",
        "items": [
            {"description": "x", "line_total": "135.98"},
            {"description": "y", "line_total": "19.92"},
        ],
    }
    assert find_registered_duplicate(seeded_scope, incoming) is not None
