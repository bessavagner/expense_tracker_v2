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
