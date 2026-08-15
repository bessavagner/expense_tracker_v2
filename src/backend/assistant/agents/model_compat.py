"""Per-model settings needed to make tool calling work at all.

This is not tuning. Each entry here is a provider **refusing** a request that
the rest of the product assembles correctly, and every one was found by a live
400 rather than read off a changelog:

* `openai:gpt-5.6-*` — "Function tools with reasoning_effort are not supported
  for gpt-5.6-terra in /v1/chat/completions." pydantic-ai marks every `gpt-5*`
  model as always-thinking (`profiles/openai.py`, `thinking_always_enabled`), so
  it sends `reasoning_effort` on every request; our agents all use function
  tools, because `output_type=` is implemented as one. gpt-5.4 accepts the
  combination — the restriction arrived with the 5.6 family — so it is left
  untouched.

  The unified `thinking: False` does NOT fix this: it is documented as "silently
  ignored on always-on models", and measurement confirmed it still 400s. Only
  the provider-specific `openai_reasoning_effort` gets through.

* `openrouter:qwen/*` — "The tool_choice parameter does not support being set to
  required or object in thinking mode" (provider: Alibaba). Anything with an
  `output_type` forces `tool_choice: required`, so this hits the Essential
  tier's fallback (`LLM_TIER_ESSENTIAL_FALLBACK`) as well as the eval harness.
  OpenRouter carries reasoning in `extra_body['reasoning']`, so the switch is
  `openrouter_reasoning`, not `openai_reasoning_effort`.

Measured against the live providers on 2026-08-14. When a model string moves,
re-measure — do not assume the quirk moved with it.
"""

# Prefix → the settings that model needs. Longest match wins, so a more specific
# family can override a broader one later without reordering surprises.
_QUIRKS: tuple[tuple[str, dict], ...] = (
    ("openai:gpt-5.6", {"openai_reasoning_effort": "none"}),
    ("openrouter:qwen/", {"openrouter_reasoning": {"enabled": False}}),
)


def settings_for(model) -> dict | None:
    """The `model_settings` this model needs, or None when it needs nothing.

    Accepts whatever callers pass as `model`: a provider string, `None` (meaning
    "run the agent's configured model"), or a model *instance* such as the
    `TestModel` the suite injects. Only strings can be matched, and the rest are
    deliberately passed over rather than rejected — this sits on the hot path of
    every receipt read and must never be the thing that raises.
    """
    if not isinstance(model, str):
        return None
    match = max(
        (prefix for prefix, _ in _QUIRKS if model.startswith(prefix)),
        key=len,
        default=None,
    )
    if match is None:
        return None
    # Copied per call: callers merge into it, and a shared mutable default would
    # leak one run's settings into the next.
    return {k: dict(v) if isinstance(v, dict) else v for k, v in dict(_QUIRKS)[match].items()}
