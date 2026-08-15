"""Behavioural cases assert the LEDGER, never the prose.

The model's wording will vary between runs and between models; the entry it
creates must not. Every expectation in `BEHAVIOUR_CASES` is a row, an amount, a
billing month or the absence of a row.
"""

from datetime import date
from decimal import Decimal

import pytest

from assistant.eval.behaviour import (
    BEHAVIOUR_CASES,
    BehaviourCase,
    ExpectedEntry,
    LedgerRow,
    World,
    load_behaviour_cases,
    score_ledger,
)


def row(
    category,
    amount,
    *,
    billing_month=date(2026, 7, 1),
    payment_method="Credito C6",
    description="Loja - coisas",
):
    return LedgerRow(
        category=category,
        amount=Decimal(amount),
        billing_month=billing_month,
        payment_method=payment_method,
        description=description,
    )


def case(**overrides) -> BehaviourCase:
    data = {
        "id": "t",
        "why": "synthetic",
        "world": World(categories=("Roupa", "Lanche"), payment_methods=()),
        "opening": "text",
        "turns": ("oi",),
        "expected_entries": (
            ExpectedEntry(category="Roupa", amount=Decimal("9.13")),
            ExpectedEntry(category="Lanche", amount=Decimal("33.03")),
        ),
        "expected_total": Decimal("42.16"),
        "today": date(2026, 6, 20),
    }
    data.update(overrides)
    return BehaviourCase(**data)


def test_the_expected_ledger_passes():
    score = score_ledger(case(), [row("Roupa", "9.13"), row("Lanche", "33.03")])
    assert score.passed is True
    assert score.matched == 2 and score.extra == 0 and score.total_ok is True
    assert score.errors == ()


def test_row_order_does_not_matter():
    assert score_ledger(case(), [row("Lanche", "33.03"), row("Roupa", "9.13")]).passed


def test_the_americanas_failure_is_caught():
    """Roupa 42,16 / Lanche 0,00 — the real transcript in iteraction.txt."""
    score = score_ledger(case(), [row("Roupa", "42.16"), row("Lanche", "0.00")])
    assert score.passed is False
    assert score.matched == 0
    assert any("Roupa" in e for e in score.errors)


def test_a_missing_entry_fails():
    score = score_ledger(case(), [row("Roupa", "9.13")])
    assert score.passed is False
    assert score.matched == 1 and score.total_ok is False


def test_an_extra_entry_fails_even_when_every_expectation_matched():
    score = score_ledger(
        case(), [row("Roupa", "9.13"), row("Lanche", "33.03"), row("Roupa", "5.00")]
    )
    assert score.passed is False
    assert score.extra == 1


def test_amount_none_means_any_positive_amount():
    c = case(
        expected_entries=(
            ExpectedEntry(category="Roupa"),
            ExpectedEntry(category="Lanche"),
        )
    )
    assert score_ledger(c, [row("Roupa", "9.13"), row("Lanche", "33.03")]).passed
    assert not score_ledger(c, [row("Roupa", "42.16"), row("Lanche", "0.00")]).passed


def test_billing_month_is_asserted_when_declared():
    c = case(
        expected_entries=(
            ExpectedEntry(category="Roupa", amount=Decimal("9.13"), billing_month=date(2026, 8, 1)),
        ),
        expected_total=Decimal("9.13"),
    )
    ok = score_ledger(c, [row("Roupa", "9.13", billing_month=date(2026, 8, 1))])
    bad = score_ledger(c, [row("Roupa", "9.13", billing_month=date(2026, 7, 1))])
    assert ok.passed and not bad.passed
    assert any("billing_month" in e for e in bad.errors)


def test_payment_method_and_description_are_asserted_when_declared():
    c = case(
        expected_entries=(
            ExpectedEntry(
                category="Roupa",
                amount=Decimal("9.13"),
                payment_method="Pix",
                description_contains="Americanas",
            ),
        ),
        expected_total=Decimal("9.13"),
    )
    bad = score_ledger(c, [row("Roupa", "9.13", payment_method="Credito C6")])
    assert not bad.passed and any("payment_method" in e for e in bad.errors)


def test_expect_no_new_entries_passes_only_on_an_untouched_ledger():
    c = case(expected_entries=(), expected_total=None, expect_no_new_entries=True)
    assert score_ledger(c, []).passed is True
    assert score_ledger(c, [row("Roupa", "9.13")]).passed is False


def test_the_suite_has_at_least_six_cases_and_unique_ids():
    assert len(BEHAVIOUR_CASES) >= 6
    assert len({c.id for c in BEHAVIOUR_CASES}) == len(BEHAVIOUR_CASES)


def test_every_case_asserts_something_about_the_ledger():
    for c in BEHAVIOUR_CASES:
        assert c.expected_entries or c.expect_no_new_entries, c.id


def test_every_case_pins_its_own_clock():
    """No time-bomb cases: billing-month judgment depends on today's date."""
    for c in BEHAVIOUR_CASES:
        assert isinstance(c.today, date), c.id


def test_every_case_declares_the_categories_and_methods_its_answer_needs():
    for c in BEHAVIOUR_CASES:
        names = {p.name for p in c.world.payment_methods}
        for exp in c.expected_entries:
            assert exp.category in c.world.categories, (c.id, exp.category)
            if exp.payment_method:
                assert exp.payment_method in names, (c.id, exp.payment_method)


def test_the_iteraction_failure_is_one_of_the_cases():
    assert any("americanas" in c.id for c in BEHAVIOUR_CASES)


def test_load_behaviour_cases_filters_by_id():
    (one,) = load_behaviour_cases([BEHAVIOUR_CASES[0].id])
    assert one is BEHAVIOUR_CASES[0]


# ── D01: a receipt case must be passable ────────────────────────────────────
#
# `hipermacional-six-categories-no-double-count` failed on every run of every
# model with `ledger total 0`. The world it opened in was not one production can
# produce: the payload's items carried no category, so the very first tool the
# photo turn asks for — `propose_receipt()` with no `items_by_category` — refused
# with "Itens sem categoria definida pela leitura" and the agent had nothing left
# to do but ask a question. These tests pin the two halves of the fix and cost
# nothing to run.

RECEIPT_CASE = "hipermacional-six-categories-no-double-count"


@pytest.mark.django_db
def test_a_receipt_opening_leaves_a_draft_its_tools_can_use(household, user):
    """The PENDING draft must exist AND its items must carry categories."""
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import build_pending_receipt_directive
    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.behaviour_runner import build_opening_prompt, build_world
    from assistant.models import ReceiptDraft, ReceiptDraftStatus

    (case,) = load_behaviour_cases([RECEIPT_CASE])
    build_world(case, household, user)
    scope = AgentScope(household=household, user=user)

    build_opening_prompt(case, scope)

    draft = (
        ReceiptDraft.objects.for_household(household)
        .filter(status=ReceiptDraftStatus.PENDING)
        .first()
    )
    assert draft is not None, "commit_receipt refuses without a PENDING draft"
    items = (draft.payload or {}).get("items") or []
    assert items and all(i.get("category") for i in items), (
        "propose_receipt() refuses a read whose items carry no category"
    )
    # Without this the directive forcing the receipt tools never reaches the agent.
    assert build_pending_receipt_directive(scope) != ""


@pytest.mark.django_db
def test_every_receipt_case_declares_the_categories_its_payload_uses(household, user):
    """A payload category the world never creates is an unpassable case."""
    from assistant.eval.behaviour import BEHAVIOUR_CASES

    for c in BEHAVIOUR_CASES:
        payload = c.world.receipt_payload or {}
        for item in payload.get("items") or []:
            category = item.get("category")
            if category:
                assert category in c.world.categories, (c.id, category)


@pytest.mark.django_db
def test_the_six_category_case_is_passable_without_calling_a_provider(household, user):
    """A stub that proposes and commits must produce exactly the expected rows.

    This is the guard that keeps D01 fixed. It walks the same two tools the agent
    is asked to call, so it fails the moment the fixture stops supporting them —
    and it costs nothing, so it runs in normal CI.
    """
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import commit_receipt, propose_receipt
    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.behaviour_runner import (
        build_opening_prompt,
        build_world,
        snapshot_ledger,
    )

    (case,) = load_behaviour_cases([RECEIPT_CASE])
    build_world(case, household, user)
    scope = AgentScope(household=household, user=user)
    build_opening_prompt(case, scope)

    proposed = propose_receipt(scope)
    assert "Erro" not in proposed and "sem categoria" not in proposed, proposed

    result = commit_receipt(scope)

    assert "Não há recibo pendente" not in result
    rows = snapshot_ledger(household, set())
    assert sum(r.amount for r in rows) == case.expected_total
    by_category = {r.category: r.amount for r in rows}
    for expected in case.expected_entries:
        assert by_category.get(expected.category) == expected.amount, (
            expected.category,
            by_category,
        )
