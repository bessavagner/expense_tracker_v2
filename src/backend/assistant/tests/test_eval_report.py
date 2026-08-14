"""The comparison table: one row per model, diffable over time."""

import json
from decimal import Decimal

import pytest
from pydantic_ai.models.test import TestModel

from assistant.eval.costing import CallCost
from assistant.eval.dataset import load_receipt_cases
from assistant.eval.extraction_runner import RawRun
from assistant.eval.report import (
    ModelReport,
    build_extraction_report,
    render_json,
    render_markdown,
)

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


@pytest.mark.django_db
def test_build_extraction_report_scores_and_prices_every_run():
    """Async runner, synchronous pricing — the split the command depends on.

    `build_extraction_report` reads `ModelPrice`, so it must NOT run inside an
    event loop; Django raises `SynchronousOnlyOperation` if it does. Driving the
    runner through `async_to_sync` here is the same shape `eval_models` uses.
    """
    from asgiref.sync import async_to_sync

    from assistant.eval.extraction_runner import run_extraction_case

    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = async_to_sync(run_extraction_case)(case, TestModel(custom_output_args=GOOD_READ))
    report = build_extraction_report("fake:model", [case], [run])
    assert report.model == "fake:model"
    assert report.suite == "extraction"
    assert report.n == 1
    assert report.overall == 1.0
    assert report.dimensions["money_ok_rate"] == 1.0
    assert report.totals.calls == 1


def test_a_run_that_errored_is_reported_as_a_failure_not_dropped():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = RawRun(case.id, None, None, 120, "RuntimeError: provider exploded")
    report = build_extraction_report("fake:model", [case], [run])
    assert report.n == 1
    assert report.overall == 0.0
    assert any("provider exploded" in f for f in report.failures)
    assert report.totals.unpriced_calls == 1


def sample_report(model="a", overall=0.9):
    from assistant.eval.costing import total

    return ModelReport(
        model=model,
        suite="extraction",
        n=2,
        overall=overall,
        dimensions={"money_ok_rate": 1.0, "item_recall": 0.95},
        totals=total([CallCost(model, 1000, 200, 4000, Decimal("0.010000"))]),
        failures=(),
    )


def test_markdown_has_one_row_per_model_with_cost_and_latency():
    md = render_markdown(
        [sample_report("openai:gpt-5.4", 0.97), sample_report("openrouter:cheap", 0.61)],
        generated_at="2026-08-14T10:00:00-03:00",
    )
    assert "openai:gpt-5.4" in md and "openrouter:cheap" in md
    assert "0.97" in md and "0.61" in md
    assert "USD" in md
    assert "2026-08-14T10:00:00-03:00" in md


def test_markdown_names_skipped_cases_rather_than_hiding_them():
    md = render_markdown([sample_report()], generated_at="t", skipped=["notas-2026-06-22"])
    assert "notas-2026-06-22" in md
    assert "skipped" in md.lower()


def test_json_round_trips_and_is_stable_key_order():
    payload = render_json([sample_report()], generated_at="t")
    data = json.loads(payload)
    assert data["generated_at"] == "t"
    assert data["reports"][0]["model"] == "a"
    assert data["reports"][0]["totals"]["cost_usd"] == "0.010000"
    assert render_json([sample_report()], generated_at="t") == payload


# ── The behaviour half ──────────────────────────────────────────────────────


def _behaviour_run(case_id, rows, usages, latency_ms=3000, error=""):
    from assistant.eval.behaviour_runner import BehaviourRun

    return BehaviourRun(
        case_id=case_id, rows=rows, usages=usages, latency_ms=latency_ms, error=error
    )


@pytest.mark.django_db
def test_a_behaviour_run_counts_one_call_per_turn_and_no_phantom_call():
    """Every ``calls`` in the table is a call somebody paid for.

    Recording the run's latency as an extra zero-token "call" (as an earlier
    draft did) permanently inflates ``unpriced_calls``, so the report warns
    "seed a price" even when every model is priced — and dilutes the latency
    average with calls that never happened.
    """
    from types import SimpleNamespace

    from model_bakery import baker

    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.report import build_behaviour_report

    baker.make(
        "assistant.ModelPrice",
        model_name="fake:priced",
        input_per_mtok=Decimal("1.000000"),
        output_per_mtok=Decimal("1.000000"),
        effective_from="2020-01-01",
    )
    (case,) = load_behaviour_cases(["refuses-to-double-register-a-known-receipt"])
    usages = [SimpleNamespace(input_tokens=100, output_tokens=10)] * 2
    report = build_behaviour_report("fake:priced", [case], [_behaviour_run(case.id, [], usages)])

    assert report.suite == "behaviour"
    assert report.n == 1
    assert report.overall == 1.0  # the refusal case wants an untouched ledger
    assert report.totals.calls == 2, "one cost row per turn, nothing invented"
    assert report.totals.unpriced_calls == 0
    assert report.totals.avg_latency_ms == 1500  # 3000ms over two turns


@pytest.mark.django_db
def test_a_behaviour_run_that_errored_scores_zero_and_is_named():
    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.report import build_behaviour_report

    (case,) = load_behaviour_cases(["billing-month-after-closing-day"])
    run = _behaviour_run(case.id, [], [], error="RuntimeError: rate limited")
    report = build_behaviour_report("fake:model", [case], [run])
    assert report.overall == 0.0
    assert any("rate limited" in f for f in report.failures)
    assert report.dimensions["cases_passed"] == 0.0
