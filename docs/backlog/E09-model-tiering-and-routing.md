---
id: E09
title: Model tiering & routing
release: R2
status: done
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

- [x] A comparison table in the repo covers ≥3 candidates per path with score and cost
      — `docs/superpowers/evidence/eval/matrix-2026-08-15.md`. Vision: 4
      candidates plus the pipeline. Text: 3 candidates. Three runs each.
- [x] The chosen mix's cost per interaction is measurably lower than the
      `gpt-5.4` baseline, with the factor stated
      — **3.75×** ($0.0942 against $0.3530 per 15-receipt sweep).
- [x] The escalating pipeline's aggregate score is within the agreed threshold
      of the baseline — it is **above** it: **0.719** against 0.699, where the
      gate was ≥ 0.631.
- [x] The money invariant score has **not** regressed at all
      — it **improved**: `money_ok_rate` **0.756** against the baseline's 0.711.
- [x] Escalation rate is measurable from `UsageRecord` and is materially below
      100% — `UsageRecord.escalation_reason` (migration 0025) records the cause
      of every second attempt, and the harness measured **33%** (27–40% across
      three sweeps). The operator query is in `docs/runbook.md`. Not yet
      exercised on production traffic, because the mix has not been deployed.
- [x] Escalation is bounded to one retry, asserted by test
      — `test_escalation_is_bounded_to_one_retry`: both reads are bad and the
      call count is exactly 2.
- [ ] The model mix is changeable by env var, proven by changing it against a
      deployed revision — **NOT MET.** Every model is env-configurable and
      tested (`test_settings_tiers.py`, including the empty-value trap), and the
      `gcloud` command is in the runbook. But nothing was deployed in this epic,
      so the *proof against a deployed revision* is outstanding. Do it with the
      next deploy and tick then.
- [x] `docs/runbook.md` documents the mix, its evidence, and the rollback
      — § *The production model mix (E09)*, including the escalation-rate query
      and what each reason means.

### Delivered by E07, not by this epic

**S09-1** (OpenRouter as a provider) and **S09-4** (degrade instead of refusing
at quota) were already shipped by E07 and were verified rather than rebuilt.
`OPENROUTER_API_KEY` is in `.env.example`, the ESSENTIAL tier is
OpenRouter-routed and degrades when the key is absent, and
`test_a_household_out_of_credits_is_degraded_not_refused` asserts the quota
behaviour.

### Two defects found on the way, both fixed

Neither was planned work. Both were found because the harness measured something
that could not be true.

- **D01** — the six-category behavioural case was unpassable by any model: the
  fixture's items carried no category, so `propose_receipt` refused the very
  tool the photo turn instructs the agent to call.
- **D02** — `_resolve_by_name` was accent-**sensitive**, so a model writing
  `Crédito C6` could not find a row stored `Credito C6`. A production bug on the
  main path, not only a harness artefact.

Together they were the whole of the behavioural deficit: with both fixed,
`gpt-5.4` scores **1.000 (7/7)** where E08 measured 0.810. **That number was
never about the model.** A cheaper candidate scored against 0.810 could have
looked adequate while genuinely regressing.

A third defect was in this epic's own code: `should_escalate` asked
`receipt_is_consistent`, which is deliberately one-sided and therefore blind to
the failure that dominates the dataset — an already-net line total reported next
to the receipt's printed discount. It kept a read that would post R$20 for a
R$40 purchase. Fixing it moved escalation 22% → 33% and the mix from failing the
money gate to beating the baseline on it.

## Out of scope

- Prompt engineering to recover a weak model's quality — legitimate work, but it invalidates E08's baseline. Do it as a follow-up epic with a re-scored baseline.
- Self-hosted or local models — operational cost exceeds the saving at this scale
- Caching model responses — a real cost lever, and a separate decision with correctness implications for a financial app
- Fine-tuning

## Open questions

1. **What cost reduction target justifies the quality risk?** — **ANSWERED,
   2026-08-14, before the matrix ran: ≥3×**, with no drop at all in the money
   invariant. Recorded in the plan's Global Constraints and in
   `baseline-15-cases-2026-08-15.md`. The shipped mix measured 3.75×.
2. **Does OpenRouter's added latency matter?** — **Moot for the shipped mix**,
   which is OpenAI-direct on both vision tiers. Latency was measured anyway and
   the mix is *faster* than the baseline: 7.0 s per call against 7.8 s. The
   OpenRouter models that were measured are slow — `qwen3.7-flash` averaged
   26.7 s in E08 — so if the ESSENTIAL tier is ever promoted beyond quota
   degradation, latency needs its own look.
3. **Is a non-OpenAI vision model acceptable for receipts?** — **Not answered,
   and not needed.** Every candidate that cleared the gates was OpenAI-direct.
   The one OpenRouter vision model measured (`qwen3.7-flash`, E08) answered one
   receipt in seven. The question stays open for whenever OpenAI pricing moves.
4. **How is the escalation threshold tuned?** — **ANSWERED: its own setting.**
   `ASSISTANT_ESCALATE_MIN_CONFIDENCE` is separate from
   `ASSISTANT_RECEIPT_MIN_CONFIDENCE`. They answer different questions and want
   to move in opposite directions: asking the user field by field is cheap,
   paying for a second model call is not. Sharing one number means tuning either
   silently retunes the other.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1 and 4 are policy decisions that shape the implementation
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion` — paste the comparison table and the escalating pipeline's score as evidence
8. `superpowers:finishing-a-development-branch`
