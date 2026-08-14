"""The runners, driven by TestModel — no provider, no money, no network."""

from decimal import Decimal

import pytest
from pydantic_ai.models.test import TestModel

from assistant.eval.dataset import load_receipt_cases
from assistant.eval.extraction_runner import run_extraction_case, run_extraction_suite

GOOD_READ = {
    "store": "Lojas Americanas",
    "date": "2026-06-12",
    "discount": "3.99",
    "amount_paid": "42.16",
    "confidence": 0.9,
    "items": [
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "9.99",
            "category": "Roupa",
        },
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99", "category": "Lanche"},
        {
            "description": "LAYS CLASSICA B&G ELMA CHIPS M",
            "line_total": "9.99",
            "category": "Lanche",
        },
        {
            "description": "WAFER MAIS AMENDOIM 102G HERSHEYS",
            "line_total": "6.19",
            "category": "Lanche",
        },
        {
            "description": "BATATA PRINGLES CREME E CEBOLA 109G",
            "line_total": "9.99",
            "category": "Lanche",
        },
    ],
}


def test_the_prompt_builder_produces_the_same_instruction_extract_receipt_uses():
    from assistant.agents.extraction import EXTRACTION_INSTRUCTION, build_extraction_prompt

    prompt = build_extraction_prompt([(b"x", "image/jpeg")])
    assert prompt[0] == EXTRACTION_INSTRUCTION
    assert len(prompt) == 2  # instruction + one BinaryContent


def test_the_prompt_builder_appends_categories_and_methods_verbatim():
    from assistant.agents.extraction import build_extraction_prompt

    prompt = build_extraction_prompt(
        [(b"x", "image/jpeg")], categories=["Roupa", "Lanche"], payment_methods=["Pix"]
    )
    assert "Roupa, Lanche" in prompt[0]
    assert "Pix" in prompt[0]


@pytest.mark.anyio
async def test_run_extraction_case_returns_output_usage_and_latency():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = await run_extraction_case(case, TestModel(custom_output_args=GOOD_READ))
    assert run.case_id == case.id
    assert run.error == ""
    assert run.extraction.amount_paid == Decimal("42.16")
    assert run.usage.input_tokens > 0
    assert run.latency_ms >= 0


@pytest.mark.anyio
async def test_a_failing_model_is_recorded_not_raised():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])

    class Boom(TestModel):
        async def request(self, *args, **kwargs):
            raise RuntimeError("provider exploded")

    run = await run_extraction_case(case, Boom())
    assert run.extraction is None
    assert "provider exploded" in run.error
    assert run.usage is None


@pytest.mark.anyio
async def test_run_extraction_suite_runs_every_case_in_order():
    cases = load_receipt_cases(["americanas-2026-06-12", "hipermacional-2026-06-15"])
    runs = await run_extraction_suite(cases, TestModel(custom_output_args=GOOD_READ))
    assert [r.case_id for r in runs] == [c.id for c in cases]


# ── Behavioural runner ──────────────────────────────────────────────────────

from datetime import date  # noqa: E402

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from assistant.eval.behaviour import (  # noqa: E402
    BehaviourCase,
    ExpectedEntry,
    World,
    load_behaviour_cases,
    score_ledger,
)
from assistant.eval.behaviour_runner import (  # noqa: E402
    build_opening_prompt,
    build_world,
    run_behaviour_case,
)
from assistant.eval.dataset import PaymentMethodSpec  # noqa: E402


def scripted(*responses):
    """A FunctionModel that returns the given responses in order, then stops."""
    calls = {"n": 0}

    def fn(messages, info):
        i = calls["n"]
        calls["n"] += 1
        return responses[i] if i < len(responses) else ModelResponse(parts=[TextPart("ok")])

    return FunctionModel(fn)


SIMPLE_CASE = BehaviourCase(
    id="simple",
    why="runner smoke test",
    world=World(
        categories=("Alimentacao",),
        payment_methods=(PaymentMethodSpec(name="Pix", type="pix"),),
    ),
    opening="text",
    turns=("Gastei 10 reais no mercado hoje, no pix.",),
    today=date(2026, 6, 12),
    expected_entries=(ExpectedEntry(category="Alimentacao", amount=Decimal("10.00")),),
    expected_total=Decimal("10.00"),
)


@pytest.mark.django_db
def test_build_world_seeds_exactly_the_declared_catalogue(household, user):
    from finances.models import Category, PaymentMethod

    build_world(SIMPLE_CASE, household, user)
    assert list(Category.objects.for_household(household).values_list("name", flat=True)) == [
        "Alimentacao"
    ]
    assert list(PaymentMethod.objects.for_household(household).values_list("name", flat=True)) == [
        "Pix"
    ]


@pytest.mark.django_db
def test_build_world_seeds_no_memory_rules(household, user):
    """Plan decision D-B — a personalised score is not a baseline."""
    from assistant.models import MemoryRule

    for case in load_behaviour_cases():
        build_world(case, household, user)
    assert MemoryRule.objects.for_household(household).count() == 0


@pytest.mark.django_db
def test_a_receipt_opening_uses_the_production_prompt(household, user):
    from assistant.agents.scope import AgentScope

    (case,) = load_behaviour_cases(["americanas-split-on-request"])
    build_world(case, household, user)
    prompt = build_opening_prompt(case, AgentScope(household=household, user=user))
    assert "propose_receipt" in prompt
    assert "SOUTIEN TOP B+ TAF21 BRANCO GG" in prompt


@pytest.mark.django_db
def test_a_duplicate_opening_uses_the_production_directive(household, user):
    from assistant.agents.scope import AgentScope

    (case,) = load_behaviour_cases(["refuses-to-double-register-a-known-receipt"])
    build_world(case, household, user)
    prompt = build_opening_prompt(case, AgentScope(household=household, user=user))
    assert "JÁ REGISTRADO" in prompt


@pytest.mark.django_db(transaction=True)
def test_run_behaviour_case_returns_only_the_rows_the_run_created(household, user):
    from asgiref.sync import async_to_sync

    build_world(SIMPLE_CASE, household, user)
    model = scripted(
        ModelResponse(
            parts=[
                ToolCallPart(
                    "register_entry",
                    {
                        "date": "2026-06-12",
                        "amount": "10.00",
                        "description": "Mercado",
                        "category_name": "Alimentacao",
                        "payment_method_name": "Pix",
                    },
                )
            ]
        ),
        ModelResponse(parts=[TextPart("Registrei.")]),
    )
    run = async_to_sync(run_behaviour_case)(SIMPLE_CASE, model, household, user)
    assert run.error == ""
    assert len(run.rows) == 1
    assert run.rows[0].amount == Decimal("10.00")
    assert run.rows[0].category == "Alimentacao"
    assert score_ledger(SIMPLE_CASE, run.rows).passed is True


@pytest.mark.django_db(transaction=True)
def test_pre_existing_entries_are_excluded_from_the_snapshot(household, user):
    """The duplicate case seeds an entry BEFORE the turn.

    Scoring it as 'created by this run' would make the refusal case impossible
    to pass.
    """
    from asgiref.sync import async_to_sync

    (case,) = load_behaviour_cases(["refuses-to-double-register-a-known-receipt"])
    build_world(case, household, user)
    run = async_to_sync(run_behaviour_case)(
        case, scripted(ModelResponse(parts=[TextPart("Ja registrado.")])), household, user
    )
    assert run.rows == []
    assert score_ledger(case, run.rows).passed is True
