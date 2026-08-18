"""The vision path is two-tier, and the two thresholds are independent."""

import importlib

from django.conf import settings


def test_the_vision_path_ships_the_mix_the_matrix_chose():
    """E09's decision, pinned: `docs/superpowers/evidence/eval/matrix-2026-08-15.md`.

    Neither model clears the bar alone — the cheap read scores 0.508 and
    reconciles 53% of receipts, and the escalation model misses the 3x cost gate
    at 2.48x. The PAIR scores 0.719 at 3.75x less. Changing one without the
    other ships half a decision.
    """
    assert settings.LLM_VISION_MODEL == "openai:gpt-5.6-luna"
    assert settings.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.4-mini"


def test_the_two_vision_tiers_are_different_models():
    """A tier that escalates to itself is the bug E09 replaced.

    The retry before E09 called the same model it had just called, so it could
    only survive a transient failure and could never improve a poor read.
    """
    assert settings.LLM_VISION_MODEL != settings.LLM_VISION_ESCALATION_MODEL


def test_the_escalation_threshold_is_independent_of_the_review_threshold(settings):
    """Tuning when we ASK the user must not retune when we PAY for a retry."""
    settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE = 0.9
    assert settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.6


def _reloaded():
    """Reload the module that actually *reads* these environment variables.

    Deliberately `config.settings.base` rather than `settings.SETTINGS_MODULE`.
    Since E16 split settings into a package, `SETTINGS_MODULE` is
    `config.settings.dev`, and reloading it re-runs `from .base import *` —
    which copies names out of the already-imported `base` module without
    re-executing it, so no `os.environ.get` call ever runs again and the
    override is invisible. Same reason `core/tests/test_email_config.py`
    reloads `base`.
    """
    import config.settings.base as module

    return importlib.reload(module)


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
    monkeypatch.setenv("LLM_VISION_MODEL", "")
    monkeypatch.setenv("LLM_VISION_ESCALATION_MODEL", "")
    monkeypatch.setenv("ASSISTANT_ESCALATE_MIN_CONFIDENCE", "")

    module = _reloaded()

    assert module.LLM_VISION_MODEL == "openai:gpt-5.6-luna"
    assert module.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.4-mini"
    assert module.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.6
