---
id: E08
title: AI evaluation harness
release: R2
status: ready
depends_on: [E02]
blocks: [E09]
wedge_critical: true
---

# E08 · AI evaluation harness

## Outcome

Receipt extraction and assistant behaviour are **scored** against real fixtures, per model, with cost recorded — so "can we ship on a cheaper model?" is answered with a number instead of an opinion.

## Why now

Decision **PD-4**. The wedge is AI capture (PD-1), which means **evaluation quality is product quality**. And decision PD-3 requires moving off `gpt-5.4` for both text and vision before an open beta, because the current configuration is not affordable at beta scale.

Today that migration is unfalsifiable. All assistant tests use `TestModel()`, which calls every tool with dummy data — they test **wiring, not judgment**. Swapping in a weaker model would pass the entire suite and produce wrong ledger entries in production.

This epic is **not greenfield.** The pattern already exists and works; this epic generalizes it.

## Evidence in the codebase

### What already exists — build on this, do not replace it

| What | Where |
|---|---|
| A real regression test anchored on real failures | `assistant/tests/test_image_extraction_regression.py` |
| Hand-written ground truth ("gabarito") with exact descriptions, amounts, categories | same file, `AMERICANAS_ITEMS` and the HIPERMACIONAL case |
| Real receipt fixtures | `assistant/tests/fixtures/receipt_americanas.jpg`, `receipt_hipermacional.jpg`, `receipt_mercadolivre_desconto.png` |
| Real-LLM tests already gated behind an env flag | same file — `RUN_LLM_TESTS=1`; these are the 2 skipped tests in the suite |
| Deterministic math assertions that always run | same file — each item counted once, sum matches amount paid |
| A consistency check the harness can score against | `assistant/agents/extraction.py` — `receipt_is_consistent` |
| The confidence threshold that already drives escalation | `config/settings.py:190-192` — `ASSISTANT_RECEIPT_MIN_CONFIDENCE` |

### Additional fixture material available, not yet used

| What | Where |
|---|---|
| 5 more real receipt photos | `docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/*.jpg` (untracked) |
| 2 more receipt photos | `docs/notas/*.jpg` (untracked) |
| A documented conversational failure transcript | `docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/iteraction.txt` — the Americanas case where the agent registered `Roupa R$42,16 / Lanche R$0,00` instead of splitting |

### Why the existing suite cannot answer the model question

```
assistant/tests/test_assistant.py:49       with agents_override(TestModel()):
assistant/tests/test_extraction.py:153     with extraction_agent.override(model=TestModel()):
assistant/tests/test_data_changed.py:64    # TestModel calls every tool ...
```

## Stories

### S08-1 · Curate the golden dataset

- **Given** 3 tracked fixtures and 7 untracked real receipt photos
- **When** the dataset is curated
- **Then** each case has an image plus ground truth: store, date, per-item description, per-item amount, expected category, payment method, total paid, and any discount
- **And** the dataset spans the hard cases deliberately — thermal print, rotated, low contrast, multi-category, discounted multi-unit lines (the marketplace quantity bug), and a receipt already registered (the duplicate-detection path)
- **And** the images are committed with a clear statement of provenance, and any personal data visible on them is considered before committing
- **And** the conversational failure in `iteraction.txt` becomes a scored case, not just a story

> Ground truth is the expensive part and the part that must be right. A wrong gabarito silently teaches the harness to prefer a worse model.

### S08-2 · Score extraction rather than pass/fail it

- **Given** binary assertions cannot compare two models that are both imperfect
- **When** scoring is implemented
- **Then** an extraction run produces a per-case score covering: item recall, item precision, amount accuracy, category accuracy, store and date correctness, and whether the total reconciles
- **And** an aggregate score summarises a model's performance across the dataset
- **And** the **money invariant is scored separately and weighted decisively** — a run whose items do not sum to the amount paid is a failure regardless of how good the rest looks
- **And** scoring is deterministic given the same model output, so runs are comparable

### S08-3 · Score assistant behaviour, not only extraction

- **Given** the wedge includes conversational capture, not just OCR
- **When** behavioural cases are added
- **Then** scenarios cover the judgments that matter: resolving a category from a loose phrase, choosing the right payment method, computing the correct billing month for a credit purchase, splitting a receipt across categories on request, and refusing to double-register a known receipt
- **And** each asserts the **resulting ledger state**, not the wording of the reply — the model's prose will vary, the entry it creates must not
- **And** the `iteraction.txt` failure is one of these cases

> This is where a cheap model will fail first. Extraction is a vision problem; category resolution and billing-month reasoning are judgment problems, and judgment is what degrades when you downgrade.

### S08-4 · Run the harness across a model matrix, with cost

- **Given** the goal is a model decision
- **When** the harness runs
- **Then** it accepts a list of models and produces a comparison table: model, aggregate score, per-dimension scores, total tokens, estimated cost, and latency
- **And** results are written to a file so runs are diffable over time
- **And** it works for both the extraction path and the behavioural path
- **And** running it is a single documented command

### S08-5 · Keep it out of the default suite, but not out of reach

- **Given** real-model runs cost money and are non-deterministic
- **When** the harness is wired into the project
- **Then** it stays behind the existing `RUN_LLM_TESTS=1` convention and never runs in normal CI
- **And** an optional, manually-triggered CI workflow can run it against a chosen model
- **And** the deterministic parts — scoring logic, math invariants, fixtures loading — **are** covered by the normal suite
- **And** `docs/runbook.md` documents how to run it, what it costs, and how to read the output

## Definition of Done

```bash
# Normal suite unaffected and green
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# The harness runs for real and produces a comparison
RUN_LLM_TESTS=1 <documented harness command>
```

Observable assertions:

- [ ] The golden dataset has at least 10 receipt cases with complete ground truth
      — **NOT MET: 7 cases.** Only 7 distinct receipts exist; two of the
      candidate photos are byte-identical to fixtures already committed and two
      more are pages of one receipt. Shipped as 7 with the shortfall recorded
      rather than padded with synthesised filler. See `docs/eval-dataset.md`
      § *Known shortfall*. Closing it is now the cheapest way to reduce the
      run-to-run spread documented in the baseline.
- [x] At least 6 behavioural cases exist, each asserting resulting ledger state
      — 7 cases, scored on the rows the agent actually wrote.
- [x] A comparison table exists for the **current production models** — this is the baseline every future model is judged against
      — `docs/superpowers/evidence/eval/baseline-2026-08-14.md`. `openai:gpt-5.4`:
      extraction **0.886** (n=5), behaviour **0.810** (n=3), with per-run JSON.
- [x] The money invariant is scored and weighted decisively
- [x] Scoring logic is unit-tested deterministically without calling a model
- [x] The `iteraction.txt` Americanas failure is a scored case
      — `americanas-split-on-request`.
- [x] Normal CI runtime is unchanged — the harness is gated on `RUN_LLM_TESTS=1`
      and never runs in normal CI; suite is 1559 passed / 3 skipped in ~90s.
- [x] `docs/runbook.md` documents the command, its cost, and how to interpret results
      — plus the two ways it misleads: models that refuse the request outright,
      and scores that move between identical runs.

**Found while establishing the baseline, still open:**

- Behavioural case `hipermacional-six-categories-no-double-count` fails on
  **every** run — `ledger total 0 != expected 376.70`, the agent registers
  nothing for a six-category receipt, on the model production runs today. It
  reproduces, so it is a product defect rather than eval noise. Not an E08
  deliverable; needs its own ticket.
- The gpt-5.6 swap staged mid-epic was **reverted** on the evidence: cheaper per
  token, 51% more expensive per receipt, no measured quality gain. This restores
  the epic's own scope line — E08 measures, E09 decides.

## Out of scope

- **Changing which model production uses → E09.** This epic measures; E09 decides. Do not swap a model here.
- Fine-tuning or training
- Prompt optimization — tempting, and it invalidates the baseline mid-epic. Improve prompts *after* the baseline exists, and re-score.
- Automated evaluation of every PR — cost-prohibitive; manual trigger is correct at this stage

## Open questions

1. **How are the untracked receipt photos handled for privacy?** They are real receipts from a real household. Decide whether to commit as-is, redact, or keep in a private location referenced by path. This blocks S08-1.
2. **What aggregate score threshold counts as "good enough to ship"?** Cannot be answered before the baseline exists. Establish the baseline, then set the threshold in E09.
3. **Does category accuracy depend on the user's own categories?** It does — memory rules personalize it. Decide whether the harness fixes a standard category set or exercises the memory path too.
4. **LLM-as-judge for behavioural cases?** Recommendation: no. Assert ledger state deterministically. A judge model adds cost, variance, and a second thing to trust.

## Skill pipeline

1. `pm-ai-shipping:derive-tests` — before planning: derive the behavioural case list systematically from the product's actual claims rather than from memory
2. `superpowers:brainstorming` — open questions 1 and 3 shape the dataset and must be settled first
3. `superpowers:writing-plans`
4. `superpowers:using-git-worktrees`
5. `superpowers:test-driven-development` — for the deterministic scoring logic
6. `superpowers:subagent-driven-development`
7. `superpowers:requesting-code-review`
8. `superpowers:verification-before-completion` — paste the baseline comparison table as evidence
9. `superpowers:finishing-a-development-branch`
