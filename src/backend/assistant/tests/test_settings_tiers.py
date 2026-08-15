"""The vision path is two-tier, and the two thresholds are independent."""

import importlib

from django.conf import settings


def test_the_vision_escalation_model_defaults_to_the_strong_model():
    """Until E09's matrix chooses, escalation must not degrade anything."""
    assert settings.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.4"


def test_the_escalation_threshold_is_independent_of_the_review_threshold(settings):
    """Tuning when we ASK the user must not retune when we PAY for a retry."""
    settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE = 0.9
    assert settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.6


def _reloaded():
    from django.conf import settings as django_settings

    return importlib.reload(importlib.import_module(django_settings.SETTINGS_MODULE))


def test_both_are_env_overridable(monkeypatch):
    """S09-5: every model in the mix changes by env var, without a deploy."""
    monkeypatch.setenv("LLM_VISION_ESCALATION_MODEL", "openai:gpt-5.6-sol")
    monkeypatch.setenv("ASSISTANT_ESCALATE_MIN_CONFIDENCE", "0.75")

    module = _reloaded()

    assert module.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.6-sol"
    assert module.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.75


def test_an_empty_env_var_falls_back_to_the_default(monkeypatch):
    """`.env.example` ships these keys PRESENT and EMPTY.

    `os.environ.get(key, default)` only falls back when the key is absent, so an
    empty value would hand `float("")` a ValueError at import and take the whole
    app down on a fresh `.env` — the exact trap `LLM_TIER_*` already documents.
    """
    monkeypatch.setenv("LLM_VISION_ESCALATION_MODEL", "")
    monkeypatch.setenv("ASSISTANT_ESCALATE_MIN_CONFIDENCE", "")

    module = _reloaded()

    assert module.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.4"
    assert module.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.6
