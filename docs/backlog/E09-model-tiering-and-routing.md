---
id: E09
title: Model tiering & routing
release: R2
status: blocked
depends_on: [E07, E08]
blocks: []
wedge_critical: true
---

# E09 · Model tiering & routing

## Outcome

Production runs on a mix of cheaper models chosen by measured evidence, with automatic escalation to a stronger model when confidence is low — cutting cost per interaction by a meaningful measured factor with no score regression beyond an agreed threshold.

## Why now

Decision **PD-4**, and your own framing: *"let's develop with cheap first, like using openrouter or cheap model, which might be weak and not work as the current development is with top tier models."*

That instinct is right and the risk is real. Both `LLM_ASSISTANT_MODEL` and `LLM_VISION_MODEL` default to `openai:gpt-5.4` (`config/settings.py:175, 187`). Running an open beta with a frontier model on **both** the text and vision paths is the single largest variable cost in the product, against a market where the incumbent charges ~R$10/month.

This epic depends on **E08** (the score) and **E07** (the cost baseline). With both, a model change becomes a two-number decision: how much cheaper, how much worse. Without them it is a guess with financial records at stake.

## Evidence in the codebase

### The abstraction already exists — this epic exploits it

| What | Where |
|---|---|
| Provider-agnostic agent framework | `pydantic-ai>=1.73.0` in `pyproject.toml` |
| Assistant model, env-overridable | `config/settings.py:175` — `LLM_ASSISTANT_MODEL` |
| Vision model, env-overridable | `config/settings.py:187` — `LLM_VISION_MODEL` |
| Transcription model + an existing fallback | `config/settings.py:180-183` — primary and `LLM_TRANSCRIBE_FALLBACK_MODEL` |
| Per-run model override already plumbed through | `assistant/views.py:76-96` — `_sse_response(..., model=...)`, passed to `agent.run_stream(..., model=model)` |

### The escalation pattern already exists — this epic generalizes it

| What | Where |
|---|---|
| Confidence threshold driving field-by-field confirmation | `config/settings.py:190-192` — `ASSISTANT_RECEIPT_MIN_CONFIDENCE` |
| Extraction retried with the vision model on failure | `assistant/views.py:327-330` |
| Consistency check available as an escalation signal | `assistant/agents/extraction.py` — `receipt_is_consistent` |
| Transcription already falls back between models | `config/settings.py:181-183` — whisper-1 fallback for browser webm/opus |

**The architecture is already tiered.** What is missing is a deliberate policy, measurement, and a cheap default.

## Stories

### S09-1 · Add OpenRouter as a provider

- **Given** OpenRouter exposes many models behind one API and one key
- **When** it is integrated
- **Then** models can be configured through OpenRouter without code changes, via the existing `LLM_*` environment variables
- **And** the OpenAI-direct path continues to work, so the provider is a choice rather than a migration
- **And** the key is in Secret Manager and `.env.example` documents the configuration
- **And** E07's price table covers OpenRouter-routed models, so cost attribution stays accurate

> OpenRouter also gives access to non-OpenAI vision models, which matters: receipt OCR is where the cost concentrates and where the model landscape is most competitive.

### S09-2 · Run the matrix and decide with evidence

- **Given** E08's harness and E07's cost baseline
- **When** candidate models are evaluated
- **Then** the matrix covers at least three candidates each for the text path and the vision path, including at least one substantially cheaper option per path
- **And** the results are recorded as a durable comparison table in the repo, not just read once
- **And** a model is chosen per path, with the score and cost that justified it written down
- **And** the agreed regression threshold from E08 open question 2 is stated explicitly and honoured

> Expect the answer to differ per path. Category resolution and billing-month reasoning are judgment tasks that degrade fast; receipt OCR may hold up well on a cheaper vision model, or may not. Measure both separately — a single "cheap model" decision across both paths is the mistake this epic exists to prevent.

### S09-3 · Confidence-based escalation

- **Given** a cheap model handles the common case and fails on hard ones
- **When** escalation is implemented
- **Then** the cheap model runs first, and a stronger model is invoked only when a defined signal fires
- **And** the signals are concrete and already available: extraction confidence below `ASSISTANT_RECEIPT_MIN_CONFIDENCE`, `receipt_is_consistent` returning false, or the total failing to reconcile
- **And** every escalation is recorded in `UsageRecord` (E07) so the escalation rate is measurable — an escalation rate near 100% means the cheap model is not actually cheap
- **And** escalation is bounded: one retry, never a loop
- **And** the harness scores the **escalating pipeline end to end**, not just the individual models — the pipeline's score is what ships

### S09-4 · Degrade instead of refusing at quota

- **Given** E07 open question 4
- **When** a household exhausts its allowance
- **Then** the decision is implemented deliberately: either a hard block or a fall back to the cheapest tier with a clear notice
- **And** whichever is chosen, the user is told plainly what changed and why, in pt-BR
- **And** the behaviour is asserted by test

### S09-5 · Make the model mix operable

- **Given** model pricing and availability change frequently
- **When** operations are considered
- **Then** every model in the mix is changeable by environment variable without a deploy
- **And** a documented rollback exists: how to return to the previous mix if quality complaints arrive
- **And** the production model mix is visible in traces (E06 S06-3), so a quality report can be tied to the model that produced it
- **And** `docs/runbook.md` documents the current mix, the evidence behind it, and how to change and roll it back

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# The pipeline scores acceptably on the chosen mix
RUN_LLM_TESTS=1 <E08 harness command, targeting the production mix>
```

Observable assertions:

- [ ] A comparison table in the repo covers ≥3 candidates per path with score and cost
- [ ] The chosen mix's cost per interaction is measurably lower than the `gpt-5.4` baseline, with the factor stated
- [ ] The escalating pipeline's aggregate score is within the agreed threshold of the baseline
- [ ] The money invariant score has **not** regressed at all — a cheaper model that misprorates a discount is not cheaper
- [ ] Escalation rate is measurable from `UsageRecord` and is materially below 100%
- [ ] Escalation is bounded to one retry, asserted by test
- [ ] The model mix is changeable by env var, proven by changing it against a deployed revision
- [ ] `docs/runbook.md` documents the mix, its evidence, and the rollback

## Out of scope

- Prompt engineering to recover a weak model's quality — legitimate work, but it invalidates E08's baseline. Do it as a follow-up epic with a re-scored baseline.
- Self-hosted or local models — operational cost exceeds the saving at this scale
- Caching model responses — a real cost lever, and a separate decision with correctness implications for a financial app
- Fine-tuning

## Open questions

1. **What cost reduction target justifies the quality risk?** Set it before running the matrix, so the decision is not rationalized after the fact.
2. **Does OpenRouter's added latency matter** for the streaming chat experience? Measure first-token latency in the matrix, not just cost.
3. **Is a non-OpenAI vision model acceptable** for receipts, given Brazilian thermal-print receipts and pt-BR text? This is an empirical question the harness answers.
4. **How is the escalation threshold tuned?** `ASSISTANT_RECEIPT_MIN_CONFIDENCE` currently defaults to 0.6 for a different purpose. Reusing it for escalation may need a separate, independently tunable value.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1 and 4 are policy decisions that shape the implementation
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion` — paste the comparison table and the escalating pipeline's score as evidence
8. `superpowers:finishing-a-development-branch`
