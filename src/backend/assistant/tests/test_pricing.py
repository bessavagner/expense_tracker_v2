"""Cost arithmetic, and the ratchet that stops a new model metering at zero."""

from datetime import date
from decimal import Decimal

import pytest
from django.conf import settings

from assistant.models import ModelPrice
from assistant.pricing import clear_price_cache, cost_usd_for, price_for

pytestmark = pytest.mark.django_db


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_price_cache()
    yield
    clear_price_cache()


def _price(name="openai:test", inp="1.00", out="10.00", when=date(2020, 1, 1)):
    return ModelPrice.objects.create(
        model_name=name,
        input_per_mtok=Decimal(inp),
        output_per_mtok=Decimal(out),
        effective_from=when,
        source_url="https://example.test/pricing",
        checked_on=when,
    )


def test_cost_is_tokens_over_a_million_times_the_rate():
    _price(inp="1.00", out="10.00")
    # 500_000 in @ $1/Mtok = $0.50; 200_000 out @ $10/Mtok = $2.00
    assert cost_usd_for("openai:test", FakeUsage(500_000, 200_000)) == Decimal("2.500000")


def test_an_unpriced_model_costs_none_rather_than_zero():
    """Zero would silently understate spend and look like a real measurement."""
    assert cost_usd_for("openai:never-seen", FakeUsage(1000, 1000)) is None


def test_a_price_edit_landing_mid_lookup_does_not_lose_the_row(monkeypatch):
    """`clear_price_cache` runs from a `post_save` signal, in whatever thread
    saved the `ModelPrice` — so it can land between this function's cache write
    and a subsequent cache read. Re-reading the dict would raise `KeyError`,
    and the caller is `record_usage`, which reports rather than raises: the
    symptom would be a silently missing cost row, which is the exact failure
    this epic exists to prevent.

    The self-clearing dict makes that interleaving deterministic instead of
    waiting for an operator to edit a price during a chat turn.
    """
    from assistant import pricing

    class ClearsOnWrite(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            self.clear()  # the signal, firing at the worst possible moment

    _price(inp="3.00", out="4.00")
    monkeypatch.setattr(pricing, "_cache", ClearsOnWrite())

    row = price_for("openai:test")
    assert row is not None
    assert row.input_per_mtok == Decimal("3.00")


def test_the_most_recent_price_not_after_the_cutoff_wins():
    _price(inp="1.00", out="1.00", when=date(2020, 1, 1))
    _price(inp="2.00", out="2.00", when=date(2026, 1, 1))
    assert price_for("openai:test").input_per_mtok == Decimal("2.00")
    assert price_for("openai:test", on=date(2025, 6, 1)).input_per_mtok == Decimal("1.00")


def test_zero_tokens_costs_zero_not_none():
    _price()
    assert cost_usd_for("openai:test", FakeUsage(0, 0)) == Decimal("0.000000")


def test_missing_token_counts_are_treated_as_zero():
    """A provider that returns no usage must not crash the metering path."""
    _price()
    assert cost_usd_for("openai:test", FakeUsage(None, None)) == Decimal("0.000000")


@pytest.mark.parametrize(
    "setting_name",
    [
        "LLM_MODEL",
        "LLM_ASSISTANT_MODEL",
        "LLM_VISION_MODEL",
        "LLM_TIER_ADVANCED",
        "LLM_TIER_STANDARD",
        "LLM_TIER_ESSENTIAL",
        "LLM_TIER_ESSENTIAL_FALLBACK",
    ],
)
def test_every_configured_chat_model_has_a_seeded_price(setting_name):
    """The ratchet: adding a model to settings without pricing it fails here.

    Without this, a new model meters at cost=None forever and the operator
    report quietly under-reports. Transcription and embedding models are
    excluded deliberately — see `test_pricing_gaps_are_declared`.
    """
    name = getattr(settings, setting_name, "")
    if not name:
        pytest.skip(f"{setting_name} is not configured")
    assert price_for(name) is not None, (
        f"{setting_name}={name} has no ModelPrice row. Look up current pricing "
        f"online (spec D3 — never from memory) and add it to the seed migration."
    )


def test_the_embedding_model_is_priced():
    """`EMBEDDING_MODEL` is a module constant, not a setting, so it needs its
    own assertion — Task 9 meters it and an unpriced embedding reports null."""
    from assistant.services.embedding import EMBEDDING_MODEL

    assert price_for(EMBEDDING_MODEL) is not None


def test_pricing_gaps_are_declared():
    """Transcription is priced per MINUTE by the provider, not per token.

    `ModelPrice` models token pricing only, so transcription records carry
    tokens-if-available and cost=None. This is a known, bounded gap: E01
    established that a transcription is ~2 orders of magnitude cheaper than a
    vision call, so it does not move p50/p90/p99. Documented in the runbook.
    This test exists so the gap is a decision, not an oversight.
    """
    assert price_for(settings.LLM_TRANSCRIBE_MODEL) is None
    assert price_for(settings.LLM_TRANSCRIBE_FALLBACK_MODEL) is None
