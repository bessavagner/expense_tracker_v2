"""Tier vocabulary and the settings that back each tier with a model."""

from django.conf import settings

from core.tiers import TIER_ORDER, Tier


def test_the_three_tiers_use_the_same_english_word_as_the_product():
    """E07 spec D2: code English == product English. No translation layer."""
    assert Tier.ADVANCED == "advanced"
    assert Tier.STANDARD == "standard"
    assert Tier.ESSENTIAL == "essential"


def test_display_labels_are_pt_br():
    assert Tier.ADVANCED.label == "Avançado"
    assert Tier.STANDARD.label == "Padrão"
    assert Tier.ESSENTIAL.label == "Essencial"


def test_tier_order_runs_most_expensive_first():
    """The cascade walks this list, so its direction is load-bearing."""
    assert TIER_ORDER == (Tier.ADVANCED, Tier.STANDARD, Tier.ESSENTIAL)


def test_advanced_and_standard_ship_pointing_at_todays_model():
    """PD-4: no unscored model swap. E09 owns moving these, with an E08 score."""
    assert settings.LLM_TIER_ADVANCED == settings.LLM_ASSISTANT_MODEL
    assert settings.LLM_TIER_STANDARD == settings.LLM_ASSISTANT_MODEL


def test_essential_names_a_different_model_than_the_paid_tiers():
    """Spec D2 is explicit that ESSENTIAL is the one tier allowed a new model:
    its baseline is a 429 and no answer, not today's model, so 'not worse' is
    trivially true and PD-4's no-unscored-swap rule does not bite."""
    assert settings.LLM_TIER_ESSENTIAL
    assert settings.LLM_TIER_ESSENTIAL != settings.LLM_TIER_STANDARD


# `model_for`'s resolution rules — including the fallback to STANDARD when
# ESSENTIAL is unconfigured or its API key is absent — are tested in
# `assistant/tests/test_quota.py`, next to the function itself.
