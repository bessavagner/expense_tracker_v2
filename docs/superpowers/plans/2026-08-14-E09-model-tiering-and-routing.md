# E09 · Model tiering & routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run receipt extraction on a cheap model that escalates to a strong one only when a defined signal fires, cutting cost per interaction by at least 3× with no regression in the money invariant.

**Architecture:** Extraction becomes a two-attempt pipeline: a cheap vision model runs first, and a single bounded retry on a stronger model fires when extraction confidence is low, the items fail to reconcile, or the first call errored. The escalation decision is one pure function that both production and the eval harness call, so the harness scores the pipeline that actually ships rather than a lookalike. Every attempt already writes a `UsageRecord`; a new `escalation_reason` column makes the escalation rate and its causes queryable.

**Tech Stack:** Django 5, pydantic-ai 1.73, PostgreSQL + pgvector (port 5433), pytest + anyio, OpenAI and OpenRouter providers.

**Spec:** `docs/backlog/E09-model-tiering-and-routing.md`

## Global Constraints

- **Cost target (E09 open question 1, decided 2026-08-14): ≥3× reduction** in cost per interaction versus the `openai:gpt-5.4` baseline. A mix that does not clear 3× does not ship, regardless of how good it looks.
- **Regression threshold (E08 open question 2, decided 2026-08-14):** the escalating **pipeline** score must land within one measured spread of the baseline, and **`money_ok_rate` must not drop at all**. A cheaper model that misprorates a discount is not cheaper.
- **The pipeline's score is what ships**, not any individual model's — E09 spec S09-3.
- **Escalation is bounded to exactly one retry. Never a loop.**
- **Never name a model or a price from memory.** Read the provider's live pricing page, and seed a `ModelPrice` row in the same change. An unpriced model reports `0` USD, which reads as free. A model string pinned in this repo is a claim to verify, not evidence.
- **Never `git add` the receipt photos.** This repository is public and these are real household receipts. Images live in `$EVAL_FIXTURES_DIR` (`~/ledger-eval-fixtures/`); only the JSON ground truth is committed.
- **Prompt engineering is out of scope.** It would invalidate E08's baseline mid-epic (E09 spec, Out of scope).
- Every task ends green: `EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q`, `uv run ruff check src/backend/`, `uv run ruff format --check src/backend/`.
- No AI attribution in commit messages.

## Already delivered by E07 — do not re-implement

Two of E09's five stories are done. Verify, do not rebuild:

| Story | Where it landed |
|---|---|
| **S09-1** OpenRouter as a provider | `OPENROUTER_API_KEY` in `.env.example:53`; `LLM_TIER_ESSENTIAL` / `LLM_TIER_ESSENTIAL_FALLBACK` are env-configurable and OpenRouter-routed; `quota.model_for` degrades to STANDARD when the key is absent; OpenRouter models are priced in `ModelPrice`. |
| **S09-4** Degrade instead of refusing at quota | `quota.decide` returns a degraded tier plus a pt-BR notice; asserted by `test_a_household_out_of_credits_is_degraded_not_refused` and `test_a_household_out_of_credits_still_gets_an_answer`. |

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/assistant/eval/behaviour_runner.py` *(modify)* | Create the PENDING `ReceiptDraft` the receipt opening needs (D01) |
| `src/backend/assistant/eval/cases/*.json` *(create ~8)* | New ground truth, one file per receipt |
| `src/backend/assistant/agents/escalation.py` *(create)* | `should_escalate` — the single escalation decision, pure and shared |
| `src/backend/assistant/tests/test_escalation.py` *(create)* | Unit tests for the decision function |
| `src/backend/config/settings.py` *(modify)* | `LLM_VISION_ESCALATION_MODEL`, `ASSISTANT_ESCALATE_MIN_CONFIDENCE` |
| `src/backend/assistant/models.py` *(modify)* | `UsageRecord.escalation_reason` |
| `src/backend/assistant/migrations/0025_usagerecord_escalation_reason.py` *(create)* | The column |
| `src/backend/assistant/metering.py` *(modify)* | Thread `escalation_reason` into the record |
| `src/backend/assistant/agents/extraction.py` *(modify)* | `extract_receipt(..., escalation_reason=...)` |
| `src/backend/assistant/views.py` *(modify)* | `_handle_images`: cheap attempt → decide → one escalation |
| `src/backend/assistant/eval/extraction_runner.py` *(modify)* | `run_pipeline_case` — score the pipeline end to end |
| `src/backend/assistant/management/commands/eval_models.py` *(modify)* | `--pipeline cheap,strong` |
| `docs/superpowers/evidence/eval/matrix-<date>.md` *(create)* | The comparison table |
| `docs/runbook.md` *(modify)* | The mix, its evidence, how to change and roll back |

---

### Task 1: Fix D01 — the behaviour harness omits the `ReceiptDraft`

Every behavioural score is currently penalised by a case no model can pass. Fix it before any number is used to choose a model.

**Files:**
- Modify: `src/backend/assistant/eval/behaviour_runner.py:76-106`
- Test: `src/backend/assistant/tests/test_eval_behaviour.py`

**Interfaces:**
- Consumes: `assistant.models.ReceiptDraft`, `ReceiptDraftStatus`
- Produces: nothing new; `build_opening_prompt(case, scope)` keeps its signature

**Background:** `commit_receipt` (`agents/tools.py:593-603`) returns `"Não há recibo pendente para registrar."` unless a PENDING `ReceiptDraft` exists, and `build_pending_receipt_directive` (`agents/tools.py:829-846`) returns `""` without one. The harness builds prompt text and no draft, so the agent is asked to register a receipt with the registering tool disabled. See `docs/backlog/D01-behaviour-harness-omits-the-receipt-draft.md`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_a_receipt_opening_leaves_a_pending_draft(household, user):
    """Without the draft, `commit_receipt` refuses and the case cannot pass."""
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import build_pending_receipt_directive
    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.behaviour_runner import build_opening_prompt, build_world
    from assistant.models import ReceiptDraft, ReceiptDraftStatus

    (case,) = load_behaviour_cases(["hipermacional-six-categories-no-double-count"])
    build_world(case, household, user)
    scope = AgentScope(household=household, user=user)

    build_opening_prompt(case, scope)

    draft = ReceiptDraft.objects.for_household(household).filter(
        status=ReceiptDraftStatus.PENDING
    ).first()
    assert draft is not None
    assert (draft.payload or {}).get("plan"), "commit_receipt reads payload['plan']"
    assert build_pending_receipt_directive(scope) != ""
```

- [ ] **Step 2: Run it and watch it fail**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_behaviour.py::test_a_receipt_opening_leaves_a_pending_draft -q
```

Expected: FAIL, `assert None is not None`.

- [ ] **Step 3: Read how production builds the draft payload**

Read `assistant/views.py:430-475` (`_dispatch_extraction`) and `assistant/agents/tools.py:593-640` (`commit_receipt`). The payload is `extraction.model_dump(mode="json")` **plus** a `plan` key that `propose_receipt` writes. Reproduce that shape exactly; a payload without `plan` still makes `commit_receipt` refuse.

- [ ] **Step 4: Create the draft in the receipt branch**

In `build_opening_prompt`, replace the `case.opening == "receipt"` branch:

```python
    if case.opening == "receipt":
        from assistant.agents.tools import propose_receipt
        from assistant.models import ReceiptDraft

        ext = ReceiptExtraction(**case.world.receipt_payload)
        # Production persists the draft in `_dispatch_extraction` before it ever
        # prompts the agent, and BOTH `commit_receipt` and the pending-receipt
        # directive read that row. Rendering only the prompt text asks the agent
        # to register a receipt with the registering tool switched off, which is
        # how this case came to fail on every run for every model (D01).
        ReceiptDraft.objects.create(
            household=scope.household,
            created_by=scope.user,
            payload=ext.model_dump(mode="json"),
        )
        # `propose_receipt` computes and stores payload["plan"], which is the key
        # `commit_receipt` actually reads. Production reaches it through the
        # agent's own tool call; the harness calls it directly so the world is
        # identical before turn one.
        propose_receipt(scope)
        needs_review = receipt_needs_review(ext, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
        return extraction_to_prompt(ext, "", needs_review=needs_review)
```

If `propose_receipt` has a different name or arity, read `agents/tools.py` and call whatever writes `payload["plan"]`. The assertion in Step 1 is the contract.

- [ ] **Step 5: Run the test and the whole eval suite**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/ -q
```

Expected: PASS, no regressions.

- [ ] **Step 6: Prove the case is now passable without spending money**

```python
@pytest.mark.django_db
def test_the_six_category_case_is_passable_with_a_stub_that_commits(household, user):
    """A stub model that calls `commit_receipt` must produce the expected rows.

    This is the guard that keeps D01 fixed: it fails the moment the fixture goes
    missing again, and it costs nothing to run.
    """
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import commit_receipt
    from assistant.eval.behaviour import load_behaviour_cases
    from assistant.eval.behaviour_runner import build_opening_prompt, build_world, snapshot_ledger

    (case,) = load_behaviour_cases(["hipermacional-six-categories-no-double-count"])
    build_world(case, household, user)
    scope = AgentScope(household=household, user=user)
    build_opening_prompt(case, scope)

    result = commit_receipt(scope)

    assert "Não há recibo pendente" not in result
    rows = snapshot_ledger(household, None)
    assert sum(r.amount for r in rows) == case.expected_total
```

If `snapshot_ledger`'s signature differs, read `behaviour_runner.py` and match it.

- [ ] **Step 7: Run it**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_behaviour.py -q
```

Expected: PASS. If the totals disagree, the case's `expected_total` and the receipt payload disagree — fix the fixture, not the assertion.

- [ ] **Step 8: Commit**

```bash
git add src/backend/assistant/eval/behaviour_runner.py src/backend/assistant/tests/test_eval_behaviour.py
git commit -m "fix(eval): the receipt opening now leaves the draft its tools need

D01. commit_receipt refuses without a PENDING ReceiptDraft and the
pending-receipt directive returns empty without one, so a case that opened with
a receipt asked the agent to register it with the registering tool disabled.
Every model failed it identically, which read as a model defect and was a
missing fixture.

The stub test is the part that keeps it fixed: it proves the case is passable
without calling a provider, so the guard runs in normal CI."
```

---

### Task 2: Widen the golden dataset to 15 receipt cases

**This task contains operator work that cannot be delegated.** Ground truth is hand-written by the person who has the receipts.

**Files:**
- Create: `src/backend/assistant/eval/cases/<slug>.json` × ~8
- Modify: `docs/eval-dataset.md` (the shortfall section, the hard-case table)
- Test: `src/backend/assistant/tests/test_eval_dataset.py` (existing arithmetic + coverage tests pick new cases up automatically)

**Interfaces:**
- Consumes: `assistant.eval.dataset.ReceiptCase`, `TruthItem`, `PaymentMethodSpec`, `arithmetic_error`
- Produces: a dataset of ≥15 cases, which every later task measures on

**Why this is Task 2 and not later:** E08 measured a run-to-run score spread of **0.14** on seven cases, wider than the gap between serious candidates. One case is 14% of a seven-case score. At 15 cases it is 6.7%. Without this, the regression threshold in Global Constraints cannot be enforced and every number below is noise.

**Source material:** 79 photos in `.data/receipts/extracted/` (gitignored), unzipped from `.data/receipts/Photos-1-001.zip`. 5 are already in the fixture set by md5, leaving 74 candidates.

- [ ] **Step 1: Triage the candidates with the extraction model**

Write `scripts/triage_receipts.py` (a throwaway; do not commit it to `src/`):

```python
"""Classify candidate receipt photos so a human picks 8 instead of reading 74.

The model's read is a TRIAGE SIGNAL ONLY. Every number it reports is re-typed by
a human in Step 3 — a gabarito copied from the model under test would score that
model against its own output.
"""

import asyncio
import json
import pathlib
import sys

import django

django.setup()

from assistant.agents.extraction import extract_receipt  # noqa: E402

SRC = pathlib.Path(".data/receipts/extracted")
OUT = pathlib.Path(".data/receipts/triage.json")


async def main():
    results = []
    for path in sorted(SRC.glob("*.jpg")):
        try:
            ext = await extract_receipt([(path.read_bytes(), "image/jpeg")])
        except Exception as exc:  # noqa: BLE001
            results.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{path.name}: FAILED", file=sys.stderr)
            continue
        results.append(
            {
                "file": path.name,
                "store": ext.store,
                "date": ext.date,
                "amount_paid": str(ext.amount_paid) if ext.amount_paid is not None else None,
                "discount": str(ext.discount),
                "n_items": len(ext.items),
                "categories": sorted({i.category for i in ext.items if i.category}),
                "confidence": ext.confidence,
            }
        )
        print(f"{path.name}: {ext.store} {ext.amount_paid} ({len(ext.items)} items)")
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")


asyncio.run(main())
```

Run it:

```bash
POSTGRES_PORT=5433 DJANGO_SETTINGS_MODULE=config.settings PYTHONPATH=src/backend \
  uv run python scripts/triage_receipts.py
```

Cost: 74 vision calls, roughly **$2**. Output: `.data/receipts/triage.json`.

- [ ] **Step 2: Shortlist 8 by uncovered hard case**

`docs/eval-dataset.md` § *What the set deliberately covers* already covers thermal print, rotated, low contrast, multi-category, discount, multi-unit line, weighed item, repeated lines, long/multi-page, and no-printed-total/date. Adding more of those buys little.

Rank the triage output for these **uncovered** kinds, one case each where the photos allow:

| Wanted | Recognise it in `triage.json` by |
|---|---|
| `pharmacy-net-value` | drugstore store name; the DROGASIL "Valor Líquido" shape, where the discount is already embedded |
| `service-charge` | restaurant/bar; a ~10% line that is a **surcharge**, inverting reconciliation |
| `fuel` | posto/combustível; litres × price-per-litre |
| `handwritten` | low `confidence`, few items, odd store |
| `marketplace-non-ml` | an order screen that is not Mercado Livre |
| `many-lines` | highest `n_items` |
| `single-item` | `n_items == 1`, the trivial case nothing currently covers |
| `many-categories` | longest `categories` array |

**Present the shortlist to the operator with the model's read, and stop for confirmation.** Do not author ground truth from the model's numbers.

- [ ] **Step 3: Operator confirms each receipt (human step)**

For each shortlisted photo the operator confirms, reading the paper and not the screen: store, date, every line description and its `line_total`, the category for each line, the printed discount, and the amount paid.

- [ ] **Step 4: Copy the chosen images into the fixtures directory**

```bash
cp .data/receipts/extracted/<chosen>.jpg ~/ledger-eval-fixtures/
```

**Never `git add` these.** `image_source` is `"private"` for every one.

- [ ] **Step 5: Write one case file per receipt**

`src/backend/assistant/eval/cases/<slug>.json`, following the committed examples:

```json
{
 "id": "drogasil-2026-07-24",
 "images": ["IMG_20260724_185838348_HDR.jpg"],
 "image_source": "private",
 "media_type": "image/jpeg",
 "provenance": "Household receipt photographed 2026-07-24. Not committed: real personal data.",
 "hard_cases": ["pharmacy-net-value", "discount"],
 "categories": ["Saude", "Perfumaria"],
 "payment_methods": [{"name": "Credito C6", "type": "credit_card", "closing_day": 25}],
 "store": "Drogasil",
 "store_key": "drogasil",
 "date": "2026-07-24",
 "payment_hint": "credito",
 "discount": "4.30",
 "amount_paid": "58.60",
 "items": [
  {"description": "DIPIRONA 500MG 10CP", "line_total": "12.90", "category": "Saude"},
  {"description": "PROTETOR SOLAR FPS50 120ML", "line_total": "50.00", "category": "Perfumaria"}
 ]
}
```

The invariant `arithmetic_error` enforces: `items_total - discount == amount_paid`, **exactly**. Here `62.90 - 4.30 == 58.60`. If it does not balance, the typing is wrong — a one-cent slip is a typo, not rounding. If the receipt prints no total, set `amount_paid` to `null` and `discount` to `"0"`.

- [ ] **Step 6: Run the dataset tests**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_dataset.py -q
```

Expected: PASS. Failures name the case and the arithmetic that does not balance. Fix the JSON.

- [ ] **Step 7: Update the hard-case table and remove the shortfall**

In `docs/eval-dataset.md`, add a row per new `hard_cases` tag to *What the set deliberately covers*, and replace *Known shortfall: seven cases, not ten* with the real count. `test_the_set_covers_every_hard_case_it_claims_to` asserts the table, so it fails if you add a tag without documenting it.

- [ ] **Step 8: Tick E08's last DoD box**

In `docs/backlog/E08-ai-evaluation-harness.md`, the "≥10 receipt cases" box is now satisfiable. Tick it and note the new count.

- [ ] **Step 9: Commit**

```bash
git add src/backend/assistant/eval/cases/ docs/eval-dataset.md docs/backlog/E08-ai-evaluation-harness.md
git commit -m "feat(eval): widen the golden dataset to 15 receipts

Seven cases put one receipt at 14% of the score, and E08 measured a run-to-run
spread of 0.14 on that set: wider than the gap between the models E09 exists to
choose between. Fifteen cases put one receipt at 6.7%.

The eight new receipts were picked for failure modes the set did not cover
rather than at random: pharmacy net-value, a restaurant service charge (a
surcharge, which inverts reconciliation), fuel priced per litre, handwritten,
and a non-Mercado-Livre marketplace screen.

Ground truth is typed off the paper, not copied from a model's read. A gabarito
taken from the model under test scores that model against its own output.

Images stay out of the repository, as before."
```

---

### Task 3: Re-baseline on the wider set

The threshold in Global Constraints is "within one measured spread". That spread must be re-measured on 15 cases, or it is the old number describing a different dataset.

**Files:**
- Create: `docs/superpowers/evidence/eval/baseline-15-cases-<date>.md` and `.json` × 3
- Modify: `docs/superpowers/evidence/eval/baseline-2026-08-14.md` (point forward to the new baseline)

- [ ] **Step 1: Confirm every model you are about to run is priced**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from assistant.pricing import price_for
from django.conf import settings
for m in {settings.LLM_ASSISTANT_MODEL, settings.LLM_VISION_MODEL,
          settings.LLM_TIER_ESSENTIAL, settings.LLM_TIER_ESSENTIAL_FALLBACK}:
    print(m, '->', price_for(m))
"
```

Any `None` means that model's USD column will read zero. Seed a `ModelPrice` row from the provider's live page first.

- [ ] **Step 2: Run the extraction baseline three times**

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --models "openai:gpt-5.4" --suite extraction \
    --out docs/superpowers/evidence/eval/baseline-15-extraction-$i.md
done
```

- [ ] **Step 3: Run the behavioural baseline three times**

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --models "openai:gpt-5.4" --suite behaviour \
    --out docs/superpowers/evidence/eval/baseline-15-behaviour-$i.md
done
```

D01 is fixed, so `hipermacional-six-categories-no-double-count` should now pass or fail on substance. If it still reports `ledger total 0`, stop: Task 1 did not hold, and nothing downstream is trustworthy.

- [ ] **Step 4: Compute the mean and spread**

```bash
POSTGRES_PORT=5433 uv run python -c "
import json, glob, statistics as st
for suite in ('extraction', 'behaviour'):
    sc, usd = [], []
    for f in sorted(glob.glob(f'docs/superpowers/evidence/eval/baseline-15-{suite}-*.json')):
        for r in json.load(open(f))['reports']:
            sc.append(r['overall']); usd.append(float(r['totals']['cost_usd']))
    print(f'{suite}: mean={st.mean(sc):.3f} min={min(sc):.2f} max={max(sc):.2f} '
          f'spread={max(sc)-min(sc):.2f} usd={st.mean(usd):.4f}')
"
```

- [ ] **Step 5: Write the baseline document**

Create `docs/superpowers/evidence/eval/baseline-15-cases-<date>.md` stating, for each suite: mean, range, spread, `money_ok_rate`, cost per sweep. Then state the two gates this plan is measured against, with the numbers filled in:

> **Cost gate:** a candidate mix must cost ≤ (baseline cost ÷ 3) per sweep.
> **Quality gate:** the pipeline's score must be ≥ (baseline mean − spread), and its `money_ok_rate` must be ≥ the baseline's.

Add a line to `docs/superpowers/evidence/eval/baseline-2026-08-14.md` pointing to it: the seven-case numbers are superseded for decisions and kept as history.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/eval/
git commit -m "docs(eval): re-baseline gpt-5.4 on the fifteen-case set

The regression threshold E09 enforces is 'within one measured spread', and the
0.14 spread was measured on seven cases. Carrying it over to a different dataset
would be quoting a number about something else.

Also the first behavioural baseline where the six-category receipt is passable,
so this is the first behavioural figure that describes the model rather than the
fixture."
```

---

### Task 4: Tiered vision models and an independent escalation threshold

**Files:**
- Modify: `src/backend/config/settings.py:352-356`, `.env.example`
- Test: `src/backend/assistant/tests/test_settings_tiers.py` (create)

**Interfaces:**
- Produces: `settings.LLM_VISION_ESCALATION_MODEL: str`, `settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE: float`

**Decision on E09 open question 4:** the escalation threshold gets its **own** setting. `ASSISTANT_RECEIPT_MIN_CONFIDENCE` (0.6) decides whether to *ask the user field by field*; escalation decides whether to *spend money on a second model*. Reusing one number couples two decisions that will want to move in opposite directions, and tuning either would silently retune the other.

- [ ] **Step 1: Write the failing test**

```python
"""The vision path is two-tier, and the two thresholds are independent."""

from django.conf import settings


def test_the_vision_escalation_model_defaults_to_the_strong_model():
    """Until E09's matrix chooses, escalation must not degrade anything."""
    assert settings.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.4"


def test_the_escalation_threshold_is_independent_of_the_review_threshold(settings):
    """Tuning when we ASK the user must not retune when we PAY for a retry."""
    settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE = 0.9
    assert settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.6


def test_both_are_env_overridable(monkeypatch):
    """S09-5: every model in the mix changes by env var, without a deploy."""
    import importlib

    monkeypatch.setenv("LLM_VISION_ESCALATION_MODEL", "openai:gpt-5.6-sol")
    monkeypatch.setenv("ASSISTANT_ESCALATE_MIN_CONFIDENCE", "0.75")
    from config import settings as settings_module

    importlib.reload(settings_module)
    assert settings_module.LLM_VISION_ESCALATION_MODEL == "openai:gpt-5.6-sol"
    assert settings_module.ASSISTANT_ESCALATE_MIN_CONFIDENCE == 0.75
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_settings_tiers.py -q
```

Expected: FAIL, `AttributeError: 'Settings' object has no attribute 'LLM_VISION_ESCALATION_MODEL'`.

- [ ] **Step 3: Add the settings**

In `src/backend/config/settings.py`, immediately after `LLM_VISION_MODEL`:

```python
# The SECOND vision attempt. `LLM_VISION_MODEL` is the cheap first read; this is
# the model that gets a receipt the cheap one was not confident about (E09
# S09-3). It defaults to the current production model so that adding escalation
# changes nothing until the matrix has actually chosen a cheaper first attempt —
# a default that silently downgraded the only vision path would be a quality
# regression shipped as a refactor.
LLM_VISION_ESCALATION_MODEL = os.environ.get("LLM_VISION_ESCALATION_MODEL", "openai:gpt-5.4")

# When to spend money on that second attempt. Deliberately NOT
# ASSISTANT_RECEIPT_MIN_CONFIDENCE, which decides whether to ask the user field
# by field. The two answer different questions and will want to move in opposite
# directions: asking more often is cheap, retrying more often is not. Sharing one
# number means tuning either silently retunes the other (E09 open question 4).
ASSISTANT_ESCALATE_MIN_CONFIDENCE = float(
    os.environ.get("ASSISTANT_ESCALATE_MIN_CONFIDENCE", "0.6")
)
```

- [ ] **Step 4: Document them in `.env.example`**

```bash
# Vision: LLM_VISION_MODEL faz a PRIMEIRA leitura (barato); se a confiança ficar
# abaixo de ASSISTANT_ESCALATE_MIN_CONFIDENCE ou os itens não fecharem com o
# valor pago, UMA segunda tentativa roda em LLM_VISION_ESCALATION_MODEL.
# Trocar qualquer um deles é variável de ambiente, sem deploy.
LLM_VISION_ESCALATION_MODEL=
ASSISTANT_ESCALATE_MIN_CONFIDENCE=
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_settings_tiers.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backend/config/settings.py .env.example src/backend/assistant/tests/test_settings_tiers.py
git commit -m "feat(assistant): a second vision tier, with its own escalation threshold

Splits the vision path into a cheap first read and one stronger retry, and gives
the retry its own confidence threshold rather than borrowing
ASSISTANT_RECEIPT_MIN_CONFIDENCE.

That borrow was the tempting shortcut and it couples two unrelated decisions:
one governs whether to ask the user field by field, the other whether to spend
money on a second model call. Asking more often is cheap; retrying more often is
not, so they will want to move in opposite directions.

Both default to today's behaviour, so this commit changes no production
behaviour on its own."
```

---

### Task 5: Record why an attempt escalated

**Files:**
- Modify: `src/backend/assistant/models.py:317-324`, `src/backend/assistant/metering.py:41-80`, `src/backend/assistant/agents/extraction.py:240-261`
- Create: `src/backend/assistant/migrations/0025_usagerecord_escalation_reason.py`
- Test: `src/backend/assistant/tests/test_metering.py`

**Interfaces:**
- Produces: `UsageRecord.escalation_reason: str` (blank = not an escalation); `record_usage(..., escalation_reason: str = "")`; `extract_receipt(..., escalation_reason: str = "")`

**Why a column rather than deriving it:** two `EXTRACTION` records on one `interaction` could mean an escalation, or a retry after a transient 500. The DoD needs the escalation *rate*, and tuning the threshold needs the *reason*. Neither is recoverable from a count.

- [ ] **Step 1: Write the failing test**

```python
class TestEscalationIsRecorded:
    @pytest.mark.anyio
    async def test_a_normal_call_records_no_reason(self, household, user, priced):
        from assistant.metering import record_usage
        from assistant.models import UsageKind, UsageRecord

        await record_usage(
            household=household, user=user, kind=UsageKind.EXTRACTION,
            model="openai:gpt-5.4", usage=FakeUsage(), latency_ms=10, ok=True,
        )
        record = await UsageRecord.objects.aget()
        assert record.escalation_reason == ""

    @pytest.mark.anyio
    async def test_an_escalated_call_records_why(self, household, user, priced):
        from assistant.metering import record_usage
        from assistant.models import UsageKind, UsageRecord

        await record_usage(
            household=household, user=user, kind=UsageKind.EXTRACTION,
            model="openai:gpt-5.4", usage=FakeUsage(), latency_ms=10, ok=True,
            escalation_reason="low_confidence",
        )
        record = await UsageRecord.objects.aget()
        assert record.escalation_reason == "low_confidence"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -k Escalation -q
```

Expected: FAIL, `TypeError: record_usage() got an unexpected keyword argument`.

- [ ] **Step 3: Add the field**

In `assistant/models.py`, on `UsageRecord`, after `ok`:

```python
    # Blank means "not an escalation", never "unknown". Two EXTRACTION records on
    # one interaction could equally be a quality escalation or a retry after a
    # transient 500, and the DoD needs the escalation RATE; a count cannot tell
    # those apart. The reason is also what tunes
    # ASSISTANT_ESCALATE_MIN_CONFIDENCE — "we escalated 40% of the time" is not
    # actionable until you know whether it was confidence or reconciliation.
    escalation_reason = models.CharField(max_length=32, blank=True, default="")
```

- [ ] **Step 4: Generate and read the migration**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations assistant \
  --name usagerecord_escalation_reason
```

Read the generated file. It must be a single `AddField` with a non-null default. `UsageRecord` is append-only history, so there is no backfill: existing rows predate escalation and blank is the truthful value for them.

- [ ] **Step 5: Thread it through `record_usage`**

In `assistant/metering.py`, add the parameter and pass it:

```python
async def record_usage(
    *,
    household,
    kind: str,
    model: str,
    latency_ms: int,
    ok: bool,
    interaction=None,
    user=None,
    usage=None,
    escalation_reason: str = "",
) -> None:
```

and inside `UsageRecord.objects.acreate(...)`:

```python
            escalation_reason=escalation_reason,
```

- [ ] **Step 6: Thread it through the extraction meter**

In `assistant/agents/extraction.py`, change `_meter` and `extract_receipt`:

```python
async def _meter(
    scope, model: str, usage, latency_ms: int, *, ok: bool, escalation_reason: str = ""
) -> None:
```

passing `escalation_reason=escalation_reason` into `record_usage`, and add the same keyword-only parameter to `extract_receipt`:

```python
async def extract_receipt(
    images: list[tuple[bytes, str]],
    categories: list[str] | None = None,
    payment_methods: list[str] | None = None,
    model=None,
    *,
    scope=None,
    escalation_reason: str = "",
) -> ReceiptExtraction:
```

forwarding it to **both** `_meter` calls, the failure path and the success path. A failed escalation is still an escalation and still costs money.

- [ ] **Step 7: Run the tests and apply the migration**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/ -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/assistant/models.py src/backend/assistant/metering.py \
        src/backend/assistant/agents/extraction.py \
        src/backend/assistant/migrations/0025_usagerecord_escalation_reason.py \
        src/backend/assistant/tests/test_metering.py
git commit -m "feat(assistant): record why an extraction attempt escalated

E09's DoD requires the escalation rate to be measurable, and an escalation rate
near 100% means the cheap model is not actually cheap: it is the number that
tells you the routing failed.

A column rather than a derived count. Two EXTRACTION records sharing an
interaction could be a quality escalation or a retry after a transient 500, and
counting cannot separate them. The reason is also what makes the threshold
tunable — '40% escalation' is not actionable until you know whether it was
confidence or reconciliation that fired.

Blank means not an escalation, never unknown. Rows written before this column
predate escalation, so blank is true for them and no backfill is needed."
```

---

### Task 6: The escalation decision, as one shared function

**Files:**
- Create: `src/backend/assistant/agents/escalation.py`
- Test: `src/backend/assistant/tests/test_escalation.py`

**Interfaces:**
- Consumes: `ReceiptExtraction`, `receipt_is_consistent` from `assistant.agents.extraction`
- Produces: `should_escalate(extraction: ReceiptExtraction | None, *, min_confidence: float | None = None) -> str | None` — returns an escalation reason string, or `None` to accept the read. Reasons: `"error"`, `"no_items"`, `"low_confidence"`, `"inconsistent"`.

**Why pure and shared:** production and the harness must run the *same* pipeline. If the harness reimplements the rule, it scores a pipeline that does not ship, and the score is worthless. Everything here is decidable from the extraction alone: no I/O, no settings read at import, no database.

- [ ] **Step 1: Write the failing tests**

```python
"""When a cheap read is not good enough to keep."""

from decimal import Decimal

import pytest

from assistant.agents.escalation import should_escalate
from assistant.agents.extraction import ReceiptExtraction, ReceiptItem


def read(items, *, paid="10.00", confidence=0.9):
    return ReceiptExtraction(
        store="Loja",
        date="2026-06-12",
        discount=Decimal("0"),
        amount_paid=Decimal(paid) if paid is not None else None,
        confidence=confidence,
        items=items,
    )


ONE_ITEM = [ReceiptItem(description="X", line_total=Decimal("10.00"), category="Casa")]


class TestEscalates:
    def test_a_failed_call_escalates(self):
        assert should_escalate(None) == "error"

    def test_an_empty_read_escalates(self):
        assert should_escalate(read([])) == "no_items"

    def test_low_confidence_escalates(self):
        assert should_escalate(read(ONE_ITEM, confidence=0.4), min_confidence=0.6) == "low_confidence"

    def test_items_that_do_not_cover_the_total_escalate(self):
        """The money invariant is the gate the whole epic protects."""
        assert should_escalate(read(ONE_ITEM, paid="99.00")) == "inconsistent"


class TestAccepts:
    def test_a_confident_reconciling_read_is_kept(self):
        assert should_escalate(read(ONE_ITEM)) is None

    def test_a_receipt_with_no_printed_total_is_kept(self):
        """`amount_paid=None` is a correct read, not a failure to reconcile."""
        assert should_escalate(read(ONE_ITEM, paid=None)) is None

    def test_confidence_exactly_at_the_threshold_is_kept(self):
        """The threshold is a floor, not a wall — spending money on a tie is waste."""
        assert should_escalate(read(ONE_ITEM, confidence=0.6), min_confidence=0.6) is None


class TestPrecedence:
    def test_the_money_invariant_is_reported_over_confidence(self):
        """Both fire; the reported reason must be the one that tunes the threshold."""
        assert should_escalate(read(ONE_ITEM, paid="99.00", confidence=0.1)) == "inconsistent"
```

If `ReceiptItem` is not the item class's name, read `agents/extraction.py` and use the real one.

- [ ] **Step 2: Run and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_escalation.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'assistant.agents.escalation'`.

- [ ] **Step 3: Write the implementation**

```python
"""When a cheap vision read is not good enough to keep (E09 S09-3).

One function, called by BOTH production (`assistant/views.py`) and the eval
harness (`assistant/eval/extraction_runner.py`). That sharing is the point: the
harness scores the escalating pipeline end to end, and a harness that
reimplemented this rule would score a pipeline that does not ship.

Pure by construction — no I/O, no database, no settings read at import time — so
the decision is unit-testable without a provider and cannot drift between the
two callers.
"""

from assistant.agents.extraction import ReceiptExtraction, receipt_is_consistent

# Returned in priority order, most diagnostic first. When several signals fire at
# once the reported reason is the one that should drive tuning: "the money did
# not add up" tells you something the confidence score does not.
ERROR = "error"
NO_ITEMS = "no_items"
INCONSISTENT = "inconsistent"
LOW_CONFIDENCE = "low_confidence"


def should_escalate(
    extraction: ReceiptExtraction | None,
    *,
    min_confidence: float | None = None,
) -> str | None:
    """Why this read needs a stronger model, or ``None`` to keep it.

    ``extraction=None`` means the first attempt raised. ``min_confidence``
    defaults to ``ASSISTANT_ESCALATE_MIN_CONFIDENCE``, read lazily so importing
    this module never touches Django settings.
    """
    if extraction is None:
        return ERROR
    if not extraction.items:
        return NO_ITEMS
    # Before confidence: a model that is confidently wrong about money is the
    # exact failure this epic must not ship, and a reconciliation failure is a
    # fact where confidence is only an opinion.
    if not receipt_is_consistent(extraction):
        return INCONSISTENT
    if min_confidence is None:
        from django.conf import settings

        min_confidence = settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE
    if extraction.confidence < min_confidence:
        return LOW_CONFIDENCE
    return None
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_escalation.py -q
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/escalation.py src/backend/assistant/tests/test_escalation.py
git commit -m "feat(assistant): one shared rule for when a cheap read is not good enough

Production and the eval harness both call this. That is the whole design: E09's
spec says the pipeline's score is what ships, so a harness that reimplemented
the rule would score a pipeline nobody runs.

Reconciliation outranks confidence when both fire. A model that is confidently
wrong about money is precisely what this epic must not ship, and whether the
items cover the amount paid is a fact where confidence is an opinion.

A receipt printing no total is not a reconciliation failure. Marketplace order
screens print none, the prompt forbids inventing one, and escalating there would
pay twice to be told the same correct answer."
```

---

### Task 7: Route production through the escalation

**Files:**
- Modify: `src/backend/assistant/views.py:522-556`
- Test: `src/backend/assistant/tests/test_views.py`

**Interfaces:**
- Consumes: `should_escalate` (Task 6), `settings.LLM_VISION_ESCALATION_MODEL` (Task 4), `extract_receipt(..., escalation_reason=...)` (Task 5)

**What is there now:** attempt one calls `extract_receipt` with no `model=`, so the agent runs `LLM_VISION_MODEL`. The retry passes `model=settings.LLM_VISION_MODEL` — **the same model**. Today's "fallback" therefore only survives transient failures and can never improve a poor read, and it only fires on an exception, never on a bad-but-returned extraction.

- [ ] **Step 1: Write the failing tests**

```python
class TestVisionEscalation:
    @pytest.mark.django_db(transaction=True)
    def test_a_confident_read_never_calls_the_second_model(
        self, logged_client, household, settings
    ):
        """The saving IS the calls not made. This test is the cost gate."""
        settings.LLM_VISION_MODEL = "cheap:model"
        settings.LLM_VISION_ESCALATION_MODEL = "strong:model"
        calls = []

        async def fake_extract(images, **kwargs):
            calls.append(kwargs.get("model"))
            return GOOD_EXTRACTION

        with patch("assistant.views.extract_receipt", fake_extract):
            self._post_image(logged_client)

        assert calls == ["cheap:model"]

    @pytest.mark.django_db(transaction=True)
    def test_an_inconsistent_read_escalates_once(self, logged_client, household, settings):
        settings.LLM_VISION_MODEL = "cheap:model"
        settings.LLM_VISION_ESCALATION_MODEL = "strong:model"
        calls = []

        async def fake_extract(images, **kwargs):
            calls.append(kwargs.get("model"))
            return INCONSISTENT_EXTRACTION if len(calls) == 1 else GOOD_EXTRACTION

        with patch("assistant.views.extract_receipt", fake_extract):
            self._post_image(logged_client)

        assert calls == ["cheap:model", "strong:model"]

    @pytest.mark.django_db(transaction=True)
    def test_escalation_is_bounded_to_one_retry(self, logged_client, household, settings):
        """DoD: bounded to one retry, never a loop. Both reads are bad here."""
        settings.LLM_VISION_MODEL = "cheap:model"
        settings.LLM_VISION_ESCALATION_MODEL = "strong:model"
        calls = []

        async def fake_extract(images, **kwargs):
            calls.append(kwargs.get("model"))
            return INCONSISTENT_EXTRACTION

        with patch("assistant.views.extract_receipt", fake_extract):
            self._post_image(logged_client)

        assert len(calls) == 2

    @pytest.mark.django_db(transaction=True)
    def test_the_escalated_call_records_its_reason(
        self, logged_client, household, settings, priced
    ):
        settings.LLM_VISION_MODEL = "cheap:model"
        settings.LLM_VISION_ESCALATION_MODEL = "strong:model"
        calls = []

        async def fake_extract(images, **kwargs):
            calls.append(kwargs.get("escalation_reason", ""))
            return INCONSISTENT_EXTRACTION if len(calls) == 1 else GOOD_EXTRACTION

        with patch("assistant.views.extract_receipt", fake_extract):
            self._post_image(logged_client)

        assert calls == ["", "inconsistent"]
```

Define `GOOD_EXTRACTION` (confident, items summing to `amount_paid`) and `INCONSISTENT_EXTRACTION` (items well below `amount_paid`) as module constants beside the existing image-test fixtures. Reuse `self._post_image` from the existing image tests in this file.

- [ ] **Step 2: Run and watch them fail**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_views.py -k VisionEscalation -q
```

Expected: FAIL — the second model is never called, and no reason is recorded.

- [ ] **Step 3: Replace the retry block**

In `assistant/views.py`, replace lines 522-556 (from `# Fase 1: extração estruturada` through the `if extraction is None:` guard) with:

```python
    # Fase 1: leitura BARATA (combina todas as imagens num recibo).
    extraction = None
    try:
        extraction = await extract_receipt(
            prepared,
            categories=cats,
            payment_methods=pms,
            model=settings.LLM_VISION_MODEL,
            scope=scope,
        )
    except Exception:
        # No explicit capture_exception: Sentry's logging integration turns an
        # ERROR-level record into an event, and logger.exception is ERROR. Adding
        # one here would double-report.
        logger.exception("Leitura barata do recibo falhou; escalando.")

    # Fase 2: UMA escalação para o modelo forte, e só quando um sinal dispara.
    # Antes deste bloco a segunda tentativa reexecutava LLM_VISION_MODEL — o
    # mesmo modelo — então só sobrevivia a falha transitória e nunca melhorava
    # uma leitura ruim que tivesse RETORNADO.
    reason = should_escalate(extraction)
    if reason is not None:
        logger.info("Escalando leitura do recibo: %s", reason)
        try:
            escalated = await extract_receipt(
                prepared,
                categories=cats,
                payment_methods=pms,
                model=settings.LLM_VISION_ESCALATION_MODEL,
                scope=scope,
                escalation_reason=reason,
            )
        except Exception:
            logger.exception("Extração do recibo falhou mesmo no modelo forte.")
        else:
            # Fica com a leitura escalada mesmo que ela também não feche: é a do
            # modelo mais forte, e há exatamente UMA tentativa (DoD: nunca um
            # laço). `receipt_needs_review` a jusante ainda leva o usuário à
            # confirmação campo a campo quando não fecha.
            extraction = escalated

    if extraction is None:
```

Add the import at the top of the file, beside the other agent imports:

```python
from assistant.agents.escalation import should_escalate
```

- [ ] **Step 4: Run the tests**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_views.py -q
```

Expected: PASS. Existing image tests must stay green: with defaults, `LLM_VISION_MODEL` and `LLM_VISION_ESCALATION_MODEL` are both `openai:gpt-5.4`, so behaviour is unchanged until the matrix chooses.

- [ ] **Step 5: Run the full suite**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/tests/test_views.py
git commit -m "feat(assistant): read receipts cheap first, escalate once on a real signal

The retry this replaces called extract_receipt again with
model=settings.LLM_VISION_MODEL, which is the model the extraction agent was
already constructed with. It re-ran the same model, so it could only ever
survive a transient failure, and it fired only on an exception — a confidently
wrong read that RETURNED was accepted without a second look.

Now the cheap model reads first and one stronger attempt fires when
should_escalate names a reason. Bounded to one retry, asserted by test.

An escalated read is kept even when it also fails to reconcile: it came from the
stronger model, there is exactly one retry, and receipt_needs_review still routes
the user to field-by-field confirmation downstream.

Both settings default to today's model, so this ships as a no-op until E09's
matrix picks a cheaper first read."
```

---

### Task 8: Score the escalating pipeline end to end

**Files:**
- Modify: `src/backend/assistant/eval/extraction_runner.py`, `src/backend/assistant/management/commands/eval_models.py`
- Test: `src/backend/assistant/tests/test_eval_runners.py`

**Interfaces:**
- Consumes: `should_escalate` (Task 6), `RawRun`
- Produces: `run_pipeline_case(case, cheap, strong) -> RawRun`, `run_pipeline_suite(cases, cheap, strong) -> list[RawRun]`; `eval_models --pipeline "cheap,strong"`

**Why:** S09-3 says the pipeline's aggregate score is what ships. Scoring `cheap` alone understates it (escalation is what rescues the hard cases) and scoring `strong` alone is just the baseline. The `RawRun.usage` for a pipeline run must combine both attempts, or the cost column reports the cheap call and hides the retry — which would make every pipeline look free.

- [ ] **Step 1: Write the failing tests**

```python
class TestThePipelineRunner:
    @pytest.mark.anyio
    async def test_a_good_cheap_read_is_not_escalated(self):
        from assistant.eval.extraction_runner import run_pipeline_case

        (case,) = load_receipt_cases(["americanas-2026-06-12"])
        cheap = TestModel(custom_output_args=GOOD_READ)
        strong = TestModel(custom_output_args=GOOD_READ)

        run = await run_pipeline_case(case, cheap, strong)

        assert run.escalated is False
        assert run.error == ""

    @pytest.mark.anyio
    async def test_a_bad_cheap_read_is_rescued_by_the_strong_model(self):
        from assistant.eval.extraction_runner import run_pipeline_case

        (case,) = load_receipt_cases(["americanas-2026-06-12"])
        cheap = TestModel(custom_output_args=INCONSISTENT_READ)
        strong = TestModel(custom_output_args=GOOD_READ)

        run = await run_pipeline_case(case, cheap, strong)

        assert run.escalated is True
        assert run.extraction.amount_paid == Decimal(GOOD_READ["amount_paid"])

    @pytest.mark.anyio
    async def test_the_cost_of_both_attempts_is_counted(self):
        """A pipeline whose cost column hid the retry would look free."""
        from assistant.eval.extraction_runner import run_pipeline_case

        (case,) = load_receipt_cases(["americanas-2026-06-12"])
        cheap = TestModel(custom_output_args=INCONSISTENT_READ)
        strong = TestModel(custom_output_args=GOOD_READ)

        run = await run_pipeline_case(case, cheap, strong)

        assert run.usage.input_tokens > 0
        assert run.usage.output_tokens > 0
```

`GOOD_READ` and `INCONSISTENT_READ` follow the `GOOD_READ` dict already in `test_eval_report.py`; `INCONSISTENT_READ` keeps `amount_paid` but drops most items.

- [ ] **Step 2: Run and watch them fail**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_runners.py -k Pipeline -q
```

Expected: FAIL, `ImportError: cannot import name 'run_pipeline_case'`.

- [ ] **Step 3: Add `escalated` to `RawRun`**

```python
@dataclass(frozen=True)
class RawRun:
    """One model call: what came back, what it consumed, how long it took."""

    case_id: str
    extraction: ReceiptExtraction | None
    usage: object | None
    latency_ms: int
    error: str
    # True when a pipeline run needed its second attempt. Single-model runs are
    # always False, so the escalation rate is `mean(r.escalated)` over a suite.
    escalated: bool = False
```

- [ ] **Step 4: Write the pipeline runner**

Append to `assistant/eval/extraction_runner.py`:

```python
@dataclass(frozen=True)
class _SummedUsage:
    """Both attempts' tokens as one usage object.

    `cost_of` reads `input_tokens` / `output_tokens` by attribute, and a pipeline
    that reported only the cheap call's tokens would price the retry at zero —
    making every escalating pipeline look cheaper than the model it escalates to.
    """

    input_tokens: int
    output_tokens: int


def _sum_usage(*usages) -> _SummedUsage:
    return _SummedUsage(
        input_tokens=sum(getattr(u, "input_tokens", 0) or 0 for u in usages if u),
        output_tokens=sum(getattr(u, "output_tokens", 0) or 0 for u in usages if u),
    )


async def run_pipeline_case(case: ReceiptCase, cheap, strong) -> RawRun:
    """Read one receipt the way production does: cheap first, one escalation.

    Calls the SAME `should_escalate` production calls. A reimplementation here
    would score a pipeline that does not ship, which is the one thing this
    harness exists to prevent.
    """
    first = await run_extraction_case(case, cheap)
    reason = should_escalate(first.extraction)
    if reason is None:
        return first

    second = await run_extraction_case(case, strong)
    return RawRun(
        case_id=case.id,
        extraction=second.extraction,
        usage=_sum_usage(first.usage, second.usage),
        latency_ms=first.latency_ms + second.latency_ms,
        error=second.error,
        escalated=True,
    )


async def run_pipeline_suite(cases: Sequence[ReceiptCase], cheap, strong) -> list[RawRun]:
    """Every case through the pipeline, in order."""
    return [await run_pipeline_case(case, cheap, strong) for case in cases]
```

with `from assistant.agents.escalation import should_escalate` at the top.

- [ ] **Step 5: Run the tests**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_runners.py -q
```

Expected: PASS.

- [ ] **Step 6: Add the `--pipeline` flag**

In `eval_models.py`, add the argument:

```python
        parser.add_argument(
            "--pipeline",
            default="",
            help='Two model strings, "cheap,strong". Scores the escalating '
            "pipeline end to end instead of each model on its own.",
        )
```

and in `_run`, before the single-model extraction loop:

```python
        if suite in ("extraction", "both") and opts.get("pipeline"):
            parts = [m.strip() for m in opts["pipeline"].split(",") if m.strip()]
            if len(parts) != 2:
                raise CommandError('--pipeline needs exactly "cheap,strong".')
            cheap_name, strong_name = parts
            cases, skipped = available_receipt_cases(ids)
            label = f"pipeline({cheap_name} -> {strong_name})"
            self.stdout.write(f"{label} · {len(cases)} case(s)…")
            runs = async_to_sync(run_pipeline_suite)(
                cases, self._model_for(cheap_name, stub), self._model_for(strong_name, stub)
            )
            rate = (sum(r.escalated for r in runs) / len(runs)) if runs else 0.0
            self.stdout.write(f"escalation rate: {rate:.0%}")
            reports.append(build_extraction_report(label, cases, runs))
            return reports, skipped
```

Note the report is built with the pipeline label, so the comparison table shows the pipeline as its own row beside the individual models.

- [ ] **Step 7: Verify it for free against stubs**

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
uv run python src/backend/manage.py eval_models \
  --pipeline "openai:gpt-5.6-luna,openai:gpt-5.4" --suite extraction --stub
```

Expected: a report row labelled `pipeline(...)` and an escalation rate line, with no provider calls.

- [ ] **Step 8: Commit**

```bash
git add src/backend/assistant/eval/extraction_runner.py \
        src/backend/assistant/management/commands/eval_models.py \
        src/backend/assistant/tests/test_eval_runners.py
git commit -m "feat(eval): score the escalating pipeline, not just its parts

S09-3: the pipeline's aggregate score is what ships. Scoring the cheap model
alone understates it, because escalation exists to rescue exactly the cases it
fails; scoring the strong model alone just re-measures the baseline.

The runner calls the same should_escalate production calls, so the harness
cannot drift into scoring a pipeline nobody runs.

Both attempts' tokens are summed into one usage object. Reporting only the first
call would price every retry at zero and make an escalating pipeline look
cheaper than the model it escalates to, which is the exact number the cost gate
turns on."
```

---

### Task 9: Run the matrix

**Files:**
- Create: `docs/superpowers/evidence/eval/matrix-<date>.md` and the per-run JSON

**Interfaces:**
- Consumes: everything above

**Requirement:** ≥3 candidates per path, each run **3 times** (Task 3 established why one run does not rank). At least one substantially cheaper option per path.

- [ ] **Step 1: Choose candidates and verify each one is real and priced**

Do **not** take the model strings below on faith; they are examples, and this repository has already been wrong about a pinned model. For each candidate, fetch the provider's live pricing page, confirm the model ID exists, and seed a `ModelPrice` row with `source_url` and `checked_on` if one is missing.

Text path candidates: the baseline (`openai:gpt-5.4`), one mid-tier, one budget model. Vision path candidates: the baseline, one mid-tier, one budget vision-capable model. `openai:gpt-5.6-luna` already measured 0.656 at $0.023 per sweep on seven cases, which is the shape the cost gate wants.

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from assistant.pricing import price_for
for m in ['<candidate 1>', '<candidate 2>', '<candidate 3>']:
    p = price_for(m)
    print(m, '->', f'{p.input_per_mtok}/{p.output_per_mtok}' if p else '** UNPRICED **')
"
```

- [ ] **Step 2: Smoke-test each candidate on one case before paying for a sweep**

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
uv run python src/backend/manage.py eval_models \
  --models "<candidate>" --suite extraction --cases americanas-2026-06-12
```

Two of three models first pointed at this dataset returned HTTP 400 on every call. If this fails, add the provider quirk to `assistant/agents/model_compat.py` rather than at the call site, and record it in `docs/eval-dataset.md` § *Provider quirks*.

- [ ] **Step 3: Run the vision matrix, 3 runs per candidate**

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --models "<c1>,<c2>,<c3>" --suite extraction \
    --out docs/superpowers/evidence/eval/matrix-vision-$i.md
done
```

- [ ] **Step 4: Run the text matrix, 3 runs per candidate**

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --models "<c1>,<c2>,<c3>" --suite behaviour \
    --out docs/superpowers/evidence/eval/matrix-text-$i.md
done
```

- [ ] **Step 5: Run the winning pipeline, 3 runs**

Take the cheapest vision candidate that is not disqualified outright, paired with the baseline as its escalation:

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --pipeline "<cheap vision>,openai:gpt-5.4" --suite extraction \
    --out docs/superpowers/evidence/eval/matrix-pipeline-$i.md
done
```

Record the escalation rate printed by each run. **An escalation rate near 100% means the cheap model is not actually cheap** — it means paying twice per receipt, and the pipeline should be rejected however good its score.

- [ ] **Step 6: Sanity-check the safety contract**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from accounts.models import Household
print('eval households left behind:', Household.objects.filter(name__startswith='eval-').count())
"
```

Expected: `0`.

- [ ] **Step 7: Aggregate and write the matrix document**

Create `docs/superpowers/evidence/eval/matrix-<date>.md`: one row per candidate per path, with mean score, spread, `money_ok_rate`, cost per sweep, cost factor versus baseline, and first-token latency (E09 open question 2). Add the pipeline as its own row, with its escalation rate.

State plainly, for the pipeline row, whether it clears each Global Constraint gate:

| Gate | Required | Measured | Pass? |
|---|---|---|---|
| Cost | ≤ baseline ÷ 3 | | |
| Score | ≥ baseline mean − spread | | |
| `money_ok_rate` | ≥ baseline | | |
| Escalation rate | materially below 100% | | |

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/evidence/eval/
git commit -m "docs(eval): the E09 model matrix

Three candidates per path, three runs each, plus the escalating pipeline scored
end to end. Three runs because one does not rank: the same model scored 0.83 to
0.97 on identical inputs during E08, a swing wider than the gap between serious
candidates.

Every candidate was smoke-tested on a single case first. Two of the three models
first pointed at this dataset refused every call outright, and a full sweep
against a model that cannot answer buys a table of zeroes.

The gates were fixed before the matrix ran, so the decision in the next commit
is read off this table rather than argued backwards from it."
```

---

### Task 10: Decide, document, and close

**Files:**
- Modify: `src/backend/config/settings.py`, `.env.example`, `docs/runbook.md`, `docs/backlog/E09-model-tiering-and-routing.md`, `docs/backlog/INDEX.md`

- [ ] **Step 1: Apply the decision, or record that nothing cleared the bar**

If a mix cleared all four gates, set the defaults in `settings.py` with a comment naming the evidence file and the measured factor.

**If nothing cleared 3×, that is a valid and complete outcome.** Keep `gpt-5.4`, write the matrix up as the reason, and close the epic with the cost DoD box unticked and the finding recorded. E08 already showed that a model marketed as cheaper measured 51% more expensive per receipt; a matrix that finds no winner is evidence, not failure. Do not lower the gate to manufacture a pass.

- [ ] **Step 2: Run the full verification**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 \
  uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations --check --dry-run
```

- [ ] **Step 3: Write the runbook section**

Add to `docs/runbook.md`, after the E08 evaluation section:

````markdown
## The production model mix (E09)

| Path | Model | Why |
|---|---|---|
| Text (`LLM_TIER_ADVANCED` / `STANDARD`) | | score / cost from the matrix |
| Vision, first read (`LLM_VISION_MODEL`) | | |
| Vision, escalation (`LLM_VISION_ESCALATION_MODEL`) | | |

Evidence: `docs/superpowers/evidence/eval/matrix-<date>.md`.

### Changing a model

Every model is an environment variable, so this needs no deploy:

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --update-env-vars LLM_VISION_MODEL=<new model>
```

Use `--update-env-vars`, never `--set-env-vars`: the latter replaces the whole
env list and wipes `DATABASE_URL` and friends.

**Seed the `ModelPrice` row in the same change**, or the cost report reads zero
for every call to the new model, which looks like an answer.

### Rolling back

The same command with the previous value. The old `ModelPrice` rows are
deliberately kept, so historical `UsageRecord`s still price correctly.

### Is escalation working?

```sql
SELECT escalation_reason, count(*)
FROM assistant_usagerecord
WHERE kind = 'extraction' AND created_at > now() - interval '7 days'
GROUP BY escalation_reason;
```

Blank rows are first attempts. An escalation rate near 100% means the cheap
model is not cheap: it means paying for two calls per receipt, and the mix
should be rolled back.
````

- [ ] **Step 4: Close the epic honestly**

Tick each DoD box in `docs/backlog/E09-model-tiering-and-routing.md` that is genuinely met, annotating what proves it. Leave unmet boxes unticked with the reason inline. **Do not tick a box on autopilot** — E07 and E08 each closed with one open box for a real reason, and that is the pattern to follow.

Note in the epic that **S09-1 and S09-4 were delivered by E07** rather than by this work.

- [ ] **Step 5: Update the index**

In `docs/backlog/INDEX.md`, set E09 to `done` with the date and a footnote naming the chosen mix and its measured factor, or naming the reason nothing shipped. Mark **D01** done. Note that the R2 gate is now open, or what still blocks it.

- [ ] **Step 6: Commit**

```bash
git add src/backend/config/settings.py .env.example docs/runbook.md docs/backlog/
git commit -m "feat(assistant): the E09 production model mix

<Mix, with the measured cost factor and pipeline score.>

The gates were set before the matrix ran: 3x cost reduction, pipeline score
within one spread of the baseline, and no regression at all in the money
invariant. A cheaper model that misprorates a discount is not cheaper.

Every model is an environment variable, so changing or rolling back the mix is
one gcloud command and no deploy. The runbook has both, plus the query that says
whether escalation is firing too often to be worth it."
```

---

## Self-review

**Spec coverage.** S09-1 and S09-4 are delivered by E07 and are documented as such rather than re-planned. S09-2 is Tasks 9 and 10. S09-3 is Tasks 4-8. S09-5 is Task 4 (env-var configurability) plus Task 10 (runbook, rollback). Every DoD assertion maps to a task: comparison table → 9; cost factor → 9/10; pipeline score → 8/9; money invariant → 6/9; escalation rate measurable → 5/9; bounded to one retry → 7; env var changeable → 4/10; runbook → 10. Open questions: 1 and 2 fixed in Global Constraints; 3 is answered empirically by Task 9; 4 is decided in Task 4.

**Placeholders.** The `<candidate>` and `<date>` markers in Tasks 9 and 10 are deliberate: the candidates cannot be named in advance without violating the Global Constraint against naming a model from memory, and Step 1 of Task 9 says exactly how to choose and verify them. The runbook table in Task 10 Step 3 is intentionally blank because it records a decision the matrix has not yet produced.

**Type consistency.** `should_escalate(extraction, *, min_confidence=None) -> str | None` is used identically in Tasks 6, 7 and 8. `RawRun.escalated` is added in Task 8 Step 3 before its use in Step 4. `escalation_reason` threads consistently through `record_usage`, `_meter` and `extract_receipt` in Task 5 and is consumed in Task 7. `run_pipeline_suite` matches the signature the command calls in Task 8 Step 6.

**Known risk.** Task 2 depends on operator work that this plan cannot do. If the dataset stays at seven cases, Task 3's spread stays ~0.14 and the quality gate in Global Constraints is unenforceable — Task 10 would then have to record the threshold as unmet rather than pretend otherwise.
