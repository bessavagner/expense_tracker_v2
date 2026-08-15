"""Cost accounting for a harness run.

Same rule as the operator report (E07 S07-5): an unpriced call is COUNTED, never
summed as zero. A comparison table that quietly treats "we don't know what this
model costs" as "free" would recommend the unpriced model every time.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from model_bakery import baker

from assistant.eval.costing import CallCost, cost_of, total


def usage(inp, out, cached=0):
    return SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_tokens=cached)


@pytest.mark.django_db
def test_cost_of_prices_a_call_from_the_model_price_row():
    baker.make(
        "assistant.ModelPrice",
        model_name="fake:cheap",
        input_per_mtok=Decimal("1.000000"),
        output_per_mtok=Decimal("2.000000"),
        effective_from="2020-01-01",
    )
    call = cost_of("fake:cheap", usage(1_000_000, 500_000), latency_ms=1234)
    assert call.input_tokens == 1_000_000
    assert call.output_tokens == 500_000
    assert call.latency_ms == 1234
    assert call.cost_usd == Decimal("2.000000")


@pytest.mark.django_db
def test_an_unpriced_model_costs_none_not_zero():
    assert cost_of("fake:unpriced", usage(10, 10), latency_ms=5).cost_usd is None


@pytest.mark.django_db
def test_usage_none_records_the_attempt_with_zero_tokens_and_no_cost():
    call = cost_of("fake:unpriced", None, latency_ms=77)
    assert call.input_tokens == 0 and call.output_tokens == 0
    assert call.cost_usd is None
    assert call.latency_ms == 77


def test_total_sums_priced_calls_and_counts_unpriced_ones_separately():
    costs = [
        CallCost("m", 100, 50, 1000, Decimal("0.001000")),
        CallCost("m", 200, 60, 3000, Decimal("0.002000")),
        CallCost("m", 300, 70, 2000, None),
    ]
    t = total(costs)
    assert t.calls == 3
    assert t.input_tokens == 600 and t.output_tokens == 180
    assert t.cost_usd == Decimal("0.003000")
    assert t.unpriced_calls == 1
    assert t.avg_latency_ms == 2000


def test_total_of_nothing_is_zero_not_a_crash():
    t = total([])
    assert t.calls == 0 and t.cost_usd == Decimal("0") and t.avg_latency_ms == 0


@pytest.mark.django_db
def test_cost_of_prices_the_cached_half_at_the_cached_rate():
    """The harness and the operator report must agree to the cent — same
    function, same arithmetic. D03."""
    baker.make(
        "assistant.ModelPrice",
        model_name="fake:cheap",
        input_per_mtok=Decimal("1.000000"),
        cached_input_per_mtok=Decimal("0.100000"),
        output_per_mtok=Decimal("2.000000"),
        effective_from="2020-01-01",
    )
    call = cost_of("fake:cheap", usage(1_000_000, 500_000, cached=500_000), latency_ms=1)
    assert call.cache_read_tokens == 500_000
    # 500k fresh @ $1 = $0.50; 500k cached @ $0.10 = $0.05; 500k out @ $2 = $1.00
    assert call.cost_usd == Decimal("1.550000")


@pytest.mark.django_db
def test_usage_none_records_zero_cache_reads():
    assert cost_of("fake:unpriced", None, latency_ms=1).cache_read_tokens == 0


def test_total_sums_cache_reads():
    costs = [
        CallCost("m", 100, 50, 1000, Decimal("0.001000"), 40),
        CallCost("m", 200, 60, 3000, Decimal("0.002000"), 60),
    ]
    assert total(costs).cache_read_tokens == 100
