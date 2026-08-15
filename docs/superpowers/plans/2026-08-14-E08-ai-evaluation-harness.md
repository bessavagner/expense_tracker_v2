# E08 · AI Evaluation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score receipt extraction and assistant behaviour against a curated golden dataset, per model, with token counts and USD cost recorded — so "can we ship on a cheaper model?" is answered with a number.

**Architecture:** A new dev-only package `src/backend/assistant/eval/` with a hard split between **deterministic** code (dataset loading, scoring, cost accounting, report rendering — all unit-tested in the normal suite, no model calls) and **live** code (two async runners that call a real model, reachable only through one management command gated on `RUN_LLM_TESTS=1`). The behavioural runner drives the *real* `assistant_agent` against a throwaway household inside a transaction that is always rolled back, and scores the **resulting ledger rows**, never the prose. Ground truth is committed JSON; receipt images stay outside the repo.

**Tech Stack:** Django 6 (async), PydanticAI 1.73, PostgreSQL 17 + pgvector, pytest + pytest-django + anyio, `model_bakery` for test fixtures, `uv` for Python deps. No new runtime dependency.

**Spec:** [`docs/backlog/E08-ai-evaluation-harness.md`](../../backlog/E08-ai-evaluation-harness.md) — read it in full before Task 1, including *Out of scope* and *Open questions*.

---

## Global Constraints

Copied verbatim from [`docs/backlog/INDEX.md`](../../backlog/INDEX.md) §7. Violating any of these fails review regardless of whether the DoD passes. Every task's requirements implicitly include this section.

1. **TDD.** Test first, always. Project convention, not a preference.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number**. No epic may move arithmetic into a prompt.
4. **Tenant scoping is centralized.** After E04, no epic may write `filter(user=...)` on a domain model. Use the household-scoped manager.
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
8. **pt-BR in the product UI, English in code, comments, and docs.** Existing convention.
9. **Migrations are reversible** or the epic states explicitly why not. *(This epic adds no migration.)*
10. **No time-bomb tests.** Any date-sensitive test freezes the clock. See E02.

Plus, binding decisions specific to this epic:

11. **E08 measures; E09 decides (PD-4).** No task in this plan may change `LLM_ASSISTANT_MODEL`, `LLM_VISION_MODEL`, `LLM_TIER_*`, or any production default. If a run shows a cheaper model wins, record the number and stop.
12. **No prompt optimization.** `EXTRACTION_PROMPT`, `EXTRACTION_INSTRUCTION`, `ASSISTANT_PROMPT` and `extraction_to_prompt` are frozen for the duration of this epic. Improving a prompt mid-epic invalidates the baseline. The one permitted change to `extraction.py` is the pure refactor in Task 5, which must not alter a single character of prompt text.
13. **DECISION D-A — receipt images stay out of the repo.** `bessavagner/expense_tracker_v2` is a **public** GitHub repository. The 3 fixtures already tracked under `assistant/tests/fixtures/` stay where they are (already public, no point retracting). The 7 additional real receipts are **not committed**. They live in a private directory pointed at by the `EVAL_FIXTURES_DIR` env var. Ground truth JSON **is** committed. A case whose image cannot be resolved is *skipped with a printed warning*, never a failure — a fresh clone and CI must both stay green.
14. **DECISION D-B — fixed taxonomy, no memory rules.** Each eval case declares its own category list and payment methods in its ground-truth JSON, and the harness seeds exactly those. No `MemoryRule` is ever seeded by the harness. Rationale: a score that moves when the operator's personal rules change is not a baseline. Memory-driven resolution stays covered by the existing deterministic tests (`test_category_memory.py`, `test_memory_tools.py`).
15. **Never name a model or a price from memory** (E07 spec D3). Any model string typed into a matrix, and any `ModelPrice` row, comes from the provider's live pricing page with the URL and date recorded.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# Coverage gate
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80

# Lint + format
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# No missing migrations (this epic must add none)
uv run python src/backend/manage.py makemigrations --check --dry-run
```

---

## Orientation — read this before Task 1

You are working in a Django project at `src/backend/`. Apps: `core` (users, middleware, observability), `accounts` (tenancy: `Household`, `Membership`, `Plan`), `finances` (the ledger: `Entry`, `Category`, `PaymentMethod`), `assistant` (the LLM surface).

**Seven things about this codebase that will bite you:**

1. **`extract_receipt()` throws away token usage.** It returns `result.output` only. Task 5 adds the seam the harness needs — a pure prompt-builder — without changing the prompt text or the existing signature.

2. **`ReceiptExtraction.date` has a `mode="before"` validator** (`normalize_receipt_date`) that silently turns an unparseable date into `None`. Ground truth dates are always ISO `YYYY-MM-DD`.

3. **`receipt_is_consistent()` deliberately does NOT subtract the printed discount.** It only asks whether `sum(line_totals) + 0.05 >= amount_paid`. The harness's money invariant is **stricter and different** — see Task 2. Do not reuse `receipt_is_consistent` as the score.

4. **The discount is re-derived at commit time, not read from the receipt.** `_effective_discount()` returns `sum(lines) − amount_paid` when `amount_paid` is known, and `_prorate_discount()` splits it across categories rounding each share HALF_UP with the residue absorbed by the *largest* category. This is why the Americanas expectation in Task 6 is `Roupa 9.13 / Lanche 33.03` and not `9.13 / 33.02`.

5. **`Entry.billing_month` is computed in `Entry.save()`**, via `compute_billing_month(date, payment_type, closing_day)`. For a credit card: purchase on/before the closing day → month **M+1**; after the closing day → **M+2**. Cash/Pix → the purchase month. Never set `billing_month` by hand in a harness expectation; derive it from the rule and assert it.

6. **Async + the ORM + a transaction do not mix through `asyncio.run`.** `sync_to_async(thread_sensitive=True)` (Django's default, used by every tool wrapper in `agents/assistant.py`) only runs on the *calling* thread when the event loop was started by `asgiref.sync.async_to_sync`. Start the loop with `asyncio.run` and the ORM work lands on a different thread with a different connection, which cannot see the uncommitted transaction. **The management command must use `async_to_sync`.** This is written down because it fails as "my seeded categories don't exist", not as an obvious error.

7. **`pydantic_ai.models.ALLOW_MODEL_REQUESTS` is forced to `False`** in `assistant/tests/conftest.py` unless `RUN_LLM_TESTS=1`, and `conftest.py` at the repo root patches embeddings the same way. Every deterministic test in this plan uses `TestModel` or `FunctionModel`, which are unaffected by that flag.

**Two verified API facts you will need** (checked against the installed `pydantic_ai==1.73.0`):

```python
# Forcing a structured output without a provider call:
from pydantic_ai.models.test import TestModel
result = await extraction_agent.run(["..."], model=TestModel(custom_output_args={...}))
# result.output is a ReceiptExtraction; result.usage() -> RunUsage(input_tokens=..., output_tokens=...)

# Scripting an exact sequence of tool calls:
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
def script(messages, info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart("register_entry", {"date": "2026-06-12", ...})])
result = await assistant_agent.run("...", deps=scope, model=FunctionModel(script))
```

---

## File Structure

**New package — `src/backend/assistant/eval/`** (dev-only; nothing in `assistant/views.py`, `agents/`, or `models.py` imports it):

| File | Responsibility |
|---|---|
| `__init__.py` | Empty. |
| `dataset.py` | Ground-truth schema (`ReceiptCase`), JSON loading, image-path resolution, arithmetic self-check. |
| `scoring.py` | `ExtractionScore`, `score_extraction`, `aggregate_extraction`. Pure functions, no I/O. |
| `costing.py` | `CallCost`, `CostTotals`, `cost_of`, `total`. Wraps `assistant.pricing.cost_usd_for`. |
| `behaviour.py` | `World`, `BehaviourCase`, `ExpectedEntry`, `BEHAVIOUR_CASES`, `build_world`, `build_opening_prompt`, `score_ledger`. |
| `extraction_runner.py` | Async: one model × N receipt cases → raw runs. No DB, no scoring. |
| `behaviour_runner.py` | Async: one model × N behavioural cases → raw runs + ledger snapshots. |
| `report.py` | `ModelReport`, `build_extraction_report`, `build_behaviour_report`, `render_markdown`, `render_json`. |
| `cases/*.json` | Committed ground truth, one file per receipt case. |

**Modified:**

| File | Change |
|---|---|
| `src/backend/config/settings.py` | Add `EVAL_FIXTURES_DIR`. |
| `src/backend/assistant/agents/extraction.py` | Extract `build_extraction_prompt()` (pure refactor, Task 5). |
| `src/backend/assistant/management/commands/eval_models.py` | New command (Task 8). |
| `.env.example` | Document `EVAL_FIXTURES_DIR`. |
| `.gitignore` | Ignore `docs/superpowers/evidence/eval/*.json` scratch, keep the committed baseline. |
| `.github/workflows/eval.yml` | New, `workflow_dispatch` only (Task 10). |
| `docs/runbook.md` | New `## Evaluating a model (E08)` section (Task 11). |
| `docs/eval-dataset.md` | New: provenance, privacy, how to add a case (Task 9). |

**Tests** (all in the normal suite, all deterministic):
`assistant/tests/test_eval_dataset.py`, `test_eval_scoring.py`, `test_eval_costing.py`, `test_eval_behaviour.py`, `test_eval_runners.py`, `test_eval_report.py`, `test_eval_command.py`.

---

## Task 1: The ground-truth schema and dataset loader

**Files:**
- Create: `src/backend/assistant/eval/__init__.py`
- Create: `src/backend/assistant/eval/dataset.py`
- Create: `src/backend/assistant/eval/cases/americanas-2026-06-12.json`
- Create: `src/backend/assistant/eval/cases/hipermacional-2026-06-15.json`
- Modify: `src/backend/config/settings.py` (add `EVAL_FIXTURES_DIR` after `ASSISTANT_RECEIPT_MIN_CONFIDENCE`, around line 391)
- Modify: `.env.example`
- Test: `src/backend/assistant/tests/test_eval_dataset.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ReceiptCase` (pydantic model) with fields `id: str`, `image: str`, `image_source: Literal["tracked","private"]`, `media_type: str`, `provenance: str`, `hard_cases: list[str]`, `categories: list[str]`, `payment_methods: list[PaymentMethodSpec]`, `store: str`, `store_key: str`, `date: str`, `payment_hint: str | None`, `discount: Decimal`, `amount_paid: Decimal`, `items: list[TruthItem]`
  - `TruthItem` with `description: str`, `line_total: Decimal`, `category: str`, `quantity: Decimal = Decimal("1")`
  - `PaymentMethodSpec` with `name: str`, `type: str`, `closing_day: int | None`
  - `ReceiptCase.items_total -> Decimal`, `ReceiptCase.image_path() -> Path | None`, `ReceiptCase.read_image() -> tuple[bytes, str]`
  - `load_receipt_cases(ids: list[str] | None = None) -> list[ReceiptCase]`
  - `available_receipt_cases(ids=None) -> tuple[list[ReceiptCase], list[str]]` → (loadable cases, ids skipped for a missing image)
  - `arithmetic_error(case: ReceiptCase) -> str | None`
  - `DatasetError(Exception)`

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_dataset.py`:

```python
"""The golden dataset loads, and its arithmetic is self-consistent.

A wrong gabarito silently teaches the harness to prefer a worse model, so the
arithmetic check runs over EVERY committed case in the normal suite — it is the
only automatic defence against a transcription slip.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from assistant.eval.dataset import (
    DatasetError,
    ReceiptCase,
    arithmetic_error,
    available_receipt_cases,
    load_receipt_cases,
)


def test_every_committed_case_loads():
    cases = load_receipt_cases()
    assert len(cases) >= 2
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"


def test_every_committed_case_is_arithmetically_consistent():
    for case in load_receipt_cases():
        assert arithmetic_error(case) is None, f"{case.id}: {arithmetic_error(case)}"


def test_americanas_case_matches_the_known_gabarito():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    assert case.store_key == "americanas"
    assert case.date == "2026-06-12"
    assert case.amount_paid == Decimal("42.16")
    assert case.items_total == Decimal("46.15")
    assert len(case.items) == 5
    assert [i.category for i in case.items] == ["Roupa", "Lanche", "Lanche", "Lanche", "Lanche"]


def test_hipermacional_case_matches_the_known_gabarito():
    (case,) = load_receipt_cases(["hipermacional-2026-06-15"])
    assert case.amount_paid == Decimal("376.70")
    assert case.items_total == Decimal("376.70")
    assert len(case.items) == 28
    assert len({i.category for i in case.items}) == 6


def test_arithmetic_error_catches_a_wrong_total():
    case = ReceiptCase(
        id="broken",
        image="x.jpg",
        image_source="tracked",
        media_type="image/jpeg",
        provenance="synthetic",
        categories=["Lanche"],
        payment_methods=[{"name": "Pix", "type": "pix"}],
        store="Loja",
        store_key="loja",
        date="2026-06-12",
        discount="0",
        amount_paid="10.00",
        items=[{"description": "a", "line_total": "9.00", "category": "Lanche"}],
    )
    assert "9.00" in arithmetic_error(case)


def test_unknown_case_id_raises():
    with pytest.raises(DatasetError):
        load_receipt_cases(["does-not-exist"])


def test_tracked_images_resolve_inside_the_repo():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    path = case.image_path()
    assert path is not None and path.exists()
    assert path.parts[-2:] == ("fixtures", "receipt_americanas.jpg")


def test_private_case_without_the_env_var_is_skipped_not_failed(settings, tmp_path):
    settings.EVAL_FIXTURES_DIR = str(tmp_path / "nowhere")
    cases, skipped = available_receipt_cases()
    assert all(c.image_path() is not None for c in cases)
    assert isinstance(skipped, list)


def test_read_image_returns_bytes_and_media_type():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    data, media_type = case.read_image()
    assert isinstance(data, bytes) and len(data) > 1000
    assert media_type == "image/jpeg"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'assistant.eval'`.

- [ ] **Step 3: Add the setting**

In `src/backend/config/settings.py`, immediately after the `ASSISTANT_RECEIPT_MIN_CONFIDENCE` line:

```python
# E08 evaluation fixtures. The golden dataset's ground truth is committed; the
# receipt PHOTOS are not — this repository is public and they are real household
# receipts carrying CNPJ, card last-4 digits and a purchase history. Point this
# at a private directory holding the images named in `assistant/eval/cases/*.json`.
# Unset is fine: those cases are skipped with a warning, never a failure.
EVAL_FIXTURES_DIR = os.environ.get("EVAL_FIXTURES_DIR", "")
```

In `.env.example`, under a new `# E08 — model evaluation` heading:

```
# Private directory holding the eval receipt photos (see docs/eval-dataset.md).
# Leave empty to run the harness on the tracked fixtures only.
EVAL_FIXTURES_DIR=
```

- [ ] **Step 4: Write the loader**

Create `src/backend/assistant/eval/__init__.py` (empty file).

Create `src/backend/assistant/eval/dataset.py`:

```python
"""The golden dataset: real receipts plus hand-written ground truth.

Ground truth is the expensive part and the part that must be right — a wrong
gabarito silently teaches the harness to prefer a worse model. So it is
committed JSON, reviewed like code, and every case is arithmetic-checked by the
normal test suite.

The IMAGES are deliberately not committed (plan decision D-A): this repository
is public and these are real household receipts. `image_source="private"`
resolves under ``settings.EVAL_FIXTURES_DIR``; a case whose image is missing is
SKIPPED, so a fresh clone and CI both stay green.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from django.conf import settings
from pydantic import BaseModel

CASES_DIR = Path(__file__).parent / "cases"
TRACKED_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


class DatasetError(Exception):
    """A case file is missing, unparseable, or asked for by an unknown id."""


class TruthItem(BaseModel):
    """One line of the receipt, as a human read it off the paper."""

    description: str
    line_total: Decimal
    category: str
    quantity: Decimal = Decimal("1")


class PaymentMethodSpec(BaseModel):
    """A payment method the harness seeds for this case (plan decision D-B)."""

    name: str
    type: str  # "cash" | "pix" | "credit_card"
    closing_day: int | None = None


class ReceiptCase(BaseModel):
    """One scored receipt: an image plus everything a correct read produces."""

    id: str
    image: str
    image_source: Literal["tracked", "private"]
    media_type: str
    provenance: str
    hard_cases: list[str] = []
    categories: list[str]
    payment_methods: list[PaymentMethodSpec]
    store: str
    # A lowercase substring a correct read must contain. The header says
    # "americanas sa - 1063" and a model may answer "Lojas Americanas"; both are
    # right, and only a substring rule scores them that way.
    store_key: str
    date: str  # ISO YYYY-MM-DD
    payment_hint: str | None = None
    discount: Decimal = Decimal("0")
    amount_paid: Decimal
    items: list[TruthItem]

    @property
    def items_total(self) -> Decimal:
        return sum((i.line_total for i in self.items), Decimal("0"))

    def image_path(self) -> Path | None:
        """Where the photo lives, or ``None`` when it cannot be resolved."""
        if self.image_source == "tracked":
            path = TRACKED_FIXTURES_DIR / self.image
        else:
            root = (settings.EVAL_FIXTURES_DIR or "").strip()
            if not root:
                return None
            path = Path(root) / self.image
        return path if path.exists() else None

    def read_image(self) -> tuple[bytes, str]:
        """``(data, media_type)``, shaped for ``extract_receipt``."""
        path = self.image_path()
        if path is None:
            raise DatasetError(f"{self.id}: image {self.image!r} not found")
        return path.read_bytes(), self.media_type


def arithmetic_error(case: ReceiptCase) -> str | None:
    """``None`` when the ground truth adds up, else a message saying how it does not.

    The rule is exact, not tolerant: these numbers were typed by a person off a
    piece of paper, and a one-cent slip is a typo, not a rounding artefact.
    """
    expected = case.items_total - case.discount
    if expected != case.amount_paid:
        return (
            f"items ({case.items_total}) - discount ({case.discount}) = {expected}, "
            f"but amount_paid is {case.amount_paid}"
        )
    unknown = sorted({i.category for i in case.items} - set(case.categories))
    if unknown:
        return f"items use categories not declared in `categories`: {unknown}"
    return None


def load_receipt_cases(ids: list[str] | None = None) -> list[ReceiptCase]:
    """Every committed case, or just the ids asked for, ordered by id."""
    cases: dict[str, ReceiptCase] = {}
    for path in sorted(CASES_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path.name}: {exc}") from exc
        case = ReceiptCase(**raw)
        if case.id in cases:
            raise DatasetError(f"duplicate case id {case.id!r} in {path.name}")
        cases[case.id] = case
    if ids is None:
        return list(cases.values())
    missing = [i for i in ids if i not in cases]
    if missing:
        raise DatasetError(f"unknown case id(s): {', '.join(missing)}")
    return [cases[i] for i in ids]


def available_receipt_cases(
    ids: list[str] | None = None,
) -> tuple[list[ReceiptCase], list[str]]:
    """Split the dataset into runnable cases and ids skipped for a missing image."""
    runnable: list[ReceiptCase] = []
    skipped: list[str] = []
    for case in load_receipt_cases(ids):
        if case.image_path() is None:
            skipped.append(case.id)
        else:
            runnable.append(case)
    return runnable, skipped
```

- [ ] **Step 5: Write the two known ground-truth cases**

Create `src/backend/assistant/eval/cases/americanas-2026-06-12.json`. Every value here is transcribed from `assistant/tests/test_image_extraction_regression.py::AMERICANAS_ITEMS`, which was hand-checked against the photo:

```json
{
  "id": "americanas-2026-06-12",
  "image": "receipt_americanas.jpg",
  "image_source": "tracked",
  "media_type": "image/jpeg",
  "provenance": "Real household receipt, already tracked in the repository since the prompt-006 regression work. Kept public; retracting it would not un-publish it.",
  "hard_cases": ["multi-category", "discount", "thermal-print"],
  "categories": ["Roupa", "Lanche", "Alimentacao"],
  "payment_methods": [
    {"name": "Credito C6", "type": "credit_card", "closing_day": 25},
    {"name": "Pix", "type": "pix"}
  ],
  "store": "americanas sa - 1063",
  "store_key": "americanas",
  "date": "2026-06-12",
  "payment_hint": "CREDITO",
  "discount": "3.99",
  "amount_paid": "42.16",
  "items": [
    {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "9.99", "category": "Roupa"},
    {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99", "category": "Lanche"},
    {"description": "LAYS CLASSICA B&G ELMA CHIPS M", "line_total": "9.99", "category": "Lanche"},
    {"description": "WAFER MAIS AMENDOIM 102G HERSHEYS", "line_total": "6.19", "category": "Lanche"},
    {"description": "BATATA PRINGLES CREME E CEBOLA 109G", "line_total": "9.99", "category": "Lanche"}
  ]
}
```

Create `src/backend/assistant/eval/cases/hipermacional-2026-06-15.json`, transcribed from `HIPERMACIONAL_ITEMS`:

```json
{
  "id": "hipermacional-2026-06-15",
  "image": "receipt_hipermacional.jpg",
  "image_source": "tracked",
  "media_type": "image/jpeg",
  "provenance": "Real household receipt, already tracked in the repository. The double-count regression case.",
  "hard_cases": ["multi-category", "long-receipt", "thermal-print"],
  "categories": ["Alimentacao", "Lanche", "Pets", "Casa", "Limpeza", "Perfumaria"],
  "payment_methods": [
    {"name": "Credito C6", "type": "credit_card", "closing_day": 25},
    {"name": "Pix", "type": "pix"}
  ],
  "store": "HIPERMACIONAL LTDA",
  "store_key": "hipermacional",
  "date": "2026-06-15",
  "payment_hint": "CREDITO",
  "discount": "0",
  "amount_paid": "376.70",
  "items": [
    {"description": "MASSA RAINHA PASTEL 1kg", "line_total": "9.95", "category": "Alimentacao"},
    {"description": "LINGUICA CHURRASCO 500G BACON", "line_total": "18.95", "category": "Alimentacao"},
    {"description": "LINGUICA CHURRASCO 500G BIQUINHO", "line_total": "18.95", "category": "Alimentacao"},
    {"description": "QUEIJO ISIS COAL Z LAC kg", "line_total": "32.73", "category": "Alimentacao"},
    {"description": "FILE PEITO REGINA 1kg", "line_total": "24.75", "category": "Alimentacao"},
    {"description": "FILEZINHO REGINA MILANESA 700G", "line_total": "23.75", "category": "Alimentacao"},
    {"description": "BATATA EASYCHEF PRE FRITA 2kg", "line_total": "24.85", "category": "Alimentacao"},
    {"description": "QUEIJO ITAMBE ZERO LAC 150G", "line_total": "24.90", "category": "Alimentacao"},
    {"description": "LEITE UHT PIRACANJU 1L", "line_total": "10.99", "category": "Alimentacao"},
    {"description": "IOG BETANIA YO BEM 170G PAPAIA", "line_total": "8.30", "category": "Alimentacao"},
    {"description": "IOG BETANIA YO BEM 170G MORANGO", "line_total": "8.30", "category": "Alimentacao"},
    {"description": "ALHO kg", "line_total": "2.62", "category": "Alimentacao"},
    {"description": "CEBOLA AMARELA kg", "line_total": "3.32", "category": "Alimentacao"},
    {"description": "EMP LEMON PEPPER kg", "line_total": "4.55", "category": "Alimentacao"},
    {"description": "EMP PAPRIC DEFUMADA kg", "line_total": "2.58", "category": "Alimentacao"},
    {"description": "EMP GERGELIM MIX kg", "line_total": "4.62", "category": "Alimentacao"},
    {"description": "PIMENTAO kg", "line_total": "1.18", "category": "Alimentacao"},
    {"description": "CR LEITE PIRACANJU ZERO LACT 200G", "line_total": "12.50", "category": "Alimentacao"},
    {"description": "OVOS CAIP TIJUCA 10UN", "line_total": "9.95", "category": "Alimentacao"},
    {"description": "BATAT PALH ELMA CHIPS 190G", "line_total": "22.99", "category": "Alimentacao"},
    {"description": "BISC TODDY WAFER 94G CHOC", "line_total": "3.15", "category": "Alimentacao"},
    {"description": "ENERG EXTR POWER 473ML MANGO", "line_total": "14.50", "category": "Lanche"},
    {"description": "RACAO CHAMP ADULTO 85G FRANGO", "line_total": "9.45", "category": "Pets"},
    {"description": "RACAO CHAMP ADULTO 85G CARNE", "line_total": "9.45", "category": "Pets"},
    {"description": "TOALHA PAPEL C 2 SCALA", "line_total": "5.49", "category": "Casa"},
    {"description": "AMAC DOWNY 1L BRISA", "line_total": "29.99", "category": "Limpeza"},
    {"description": "DESOD MONANGE AERO 150ML", "line_total": "9.95", "category": "Perfumaria"},
    {"description": "ESPUMA GILLETTE 155ML", "line_total": "23.99", "category": "Perfumaria"}
  ]
}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q
uv run ruff check src/backend/assistant/eval/ && uv run ruff format src/backend/assistant/eval/
```

Expected: 8 passed.

- [ ] **Step 7: Add a drift guard against the existing regression test**

Append to `src/backend/assistant/tests/test_eval_dataset.py`:

```python
def test_dataset_ground_truth_matches_the_regression_test_constants():
    """The two sources of gabarito must never drift apart.

    `test_image_extraction_regression.py` keeps its own literals because it is
    the record of two real production failures. This test is the ratchet that
    stops the dataset and the regression test from disagreeing about what the
    photo says.
    """
    from assistant.tests.test_image_extraction_regression import (
        AMERICANAS_ITEMS,
        HIPERMACIONAL_ITEMS,
    )

    pairs = [
        ("americanas-2026-06-12", AMERICANAS_ITEMS),
        ("hipermacional-2026-06-15", HIPERMACIONAL_ITEMS),
    ]
    for case_id, flat in pairs:
        (case,) = load_receipt_cases([case_id])
        assert len(case.items) == len(flat), case_id
        for item, (desc, value, cat) in zip(case.items, flat, strict=True):
            assert item.description == desc, case_id
            assert item.line_total == Decimal(value), case_id
            # The dataset writes category names without accents so a JSON file
            # stays diffable in any terminal; the regression test uses the
            # product's real names.
            assert item.category.lower()[:5] == cat.lower()[:5], (case_id, desc)
```

- [ ] **Step 8: Run it and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q
git add src/backend/assistant/eval/ src/backend/assistant/tests/test_eval_dataset.py \
        src/backend/config/settings.py .env.example
git commit -m "feat(eval): golden dataset schema, loader and the two known gabaritos"
```

---

## Task 2: Score an extraction instead of pass/failing it

**Files:**
- Create: `src/backend/assistant/eval/scoring.py`
- Test: `src/backend/assistant/tests/test_eval_scoring.py`

**Interfaces:**
- Consumes: `assistant.eval.dataset.ReceiptCase`, `assistant.agents.extraction.ReceiptExtraction`.
- Produces:
  - `ExtractionScore` (frozen dataclass): `case_id: str`, `money_ok: bool`, `item_recall: float`, `item_precision: float`, `amount_accuracy: float`, `category_accuracy: float`, `store_ok: bool`, `date_ok: bool`, `missed: tuple[str, ...]`, `spurious: tuple[str, ...]`, `overall: float` (property)
  - `AggregateScore` (frozen dataclass): `n: int`, `money_ok_rate: float`, `item_recall: float`, `item_precision: float`, `amount_accuracy: float`, `category_accuracy: float`, `store_accuracy: float`, `date_accuracy: float`, `overall: float`
  - `score_extraction(case: ReceiptCase, ext: ReceiptExtraction) -> ExtractionScore`
  - `aggregate_extraction(scores: Sequence[ExtractionScore]) -> AggregateScore`
  - `normalize_description(text: str) -> str`
  - `MATCH_THRESHOLD: float`, `MONEY_TOLERANCE: Decimal`, `WEIGHTS: dict[str, float]`

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_scoring.py`:

```python
"""Extraction scoring — deterministic, no model, no database.

Binary assertions cannot compare two models that are both imperfect, which is
why this exists. The one non-graduated dimension is the money invariant: a read
whose items do not reconcile with the amount paid scores ZERO overall no matter
how good the rest looks.
"""

from decimal import Decimal

from assistant.agents.extraction import ReceiptExtraction, ReceiptItem
from assistant.eval.dataset import ReceiptCase
from assistant.eval.scoring import (
    aggregate_extraction,
    normalize_description,
    score_extraction,
)


def make_case(**overrides) -> ReceiptCase:
    data = {
        "id": "t",
        "image": "x.jpg",
        "image_source": "tracked",
        "media_type": "image/jpeg",
        "provenance": "synthetic",
        "categories": ["Lanche", "Roupa"],
        "payment_methods": [{"name": "Pix", "type": "pix"}],
        "store": "americanas sa - 1063",
        "store_key": "americanas",
        "date": "2026-06-12",
        "discount": "0",
        "amount_paid": "20.00",
        "items": [
            {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "10.00",
             "category": "Lanche"},
            {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "10.00",
             "category": "Roupa"},
        ],
    }
    data.update(overrides)
    return ReceiptCase(**data)


def make_extraction(items, **overrides) -> ReceiptExtraction:
    data = {
        "store": "Lojas Americanas",
        "date": "2026-06-12",
        "items": [ReceiptItem(**i) for i in items],
        "discount": Decimal("0"),
        "amount_paid": Decimal("20.00"),
        "confidence": 0.9,
    }
    data.update(overrides)
    return ReceiptExtraction(**data)


PERFECT_ITEMS = [
    {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "10.00", "category": "Lanche"},
    {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "10.00", "category": "Roupa"},
]


def test_a_perfect_read_scores_one():
    score = score_extraction(make_case(), make_extraction(PERFECT_ITEMS))
    assert score.money_ok is True
    assert score.item_recall == 1.0
    assert score.item_precision == 1.0
    assert score.amount_accuracy == 1.0
    assert score.category_accuracy == 1.0
    assert score.store_ok is True
    assert score.date_ok is True
    assert score.overall == 1.0


def test_money_invariant_failure_zeroes_the_whole_score():
    """The Mercado Livre bug: a multi-unit line counted twice."""
    doubled = [
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "20.00",
         "category": "Lanche"},
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "10.00",
         "category": "Roupa"},
    ]
    score = score_extraction(make_case(), make_extraction(doubled))
    assert score.money_ok is False
    assert score.overall == 0.0
    # ...even though every other dimension is near-perfect:
    assert score.item_recall == 1.0
    assert score.category_accuracy == 1.0


def test_a_missing_amount_paid_fails_the_money_invariant():
    score = score_extraction(
        make_case(), make_extraction(PERFECT_ITEMS, amount_paid=None)
    )
    assert score.money_ok is False
    assert score.overall == 0.0


def test_discount_is_subtracted_before_reconciling():
    case = make_case(amount_paid="18.00", discount="2.00")
    ext = make_extraction(PERFECT_ITEMS, discount=Decimal("2.00"),
                          amount_paid=Decimal("18.00"))
    assert score_extraction(case, ext).money_ok is True


def test_a_missed_item_lowers_recall_and_is_named():
    partial = [PERFECT_ITEMS[0], {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
                                  "line_total": "10.00", "category": "Roupa"}]
    del partial[1]
    score = score_extraction(
        make_case(), make_extraction(partial, amount_paid=Decimal("20.00"))
    )
    assert score.item_recall == 0.5
    assert score.item_precision == 1.0
    assert "SOUTIEN TOP B+ TAF21 BRANCO GG" in score.missed


def test_a_hallucinated_item_lowers_precision_and_is_named():
    extra = PERFECT_ITEMS + [
        {"description": "PRODUTO QUE NAO EXISTE", "line_total": "0.00", "category": "Lanche"}
    ]
    score = score_extraction(make_case(), make_extraction(extra))
    assert score.item_recall == 1.0
    assert round(score.item_precision, 4) == round(2 / 3, 4)
    assert "PRODUTO QUE NAO EXISTE" in score.spurious


def test_a_wrong_category_is_scored_separately_from_recall():
    miscategorised = [
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "10.00",
         "category": "Roupa"},
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "10.00",
         "category": "Roupa"},
    ]
    score = score_extraction(make_case(), make_extraction(miscategorised))
    assert score.item_recall == 1.0
    assert score.category_accuracy == 0.5
    assert 0.0 < score.overall < 1.0


def test_a_null_category_counts_as_wrong():
    nulled = [
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "10.00", "category": None},
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "10.00",
         "category": "Roupa"},
    ]
    assert score_extraction(make_case(), make_extraction(nulled)).category_accuracy == 0.5


def test_store_is_matched_by_key_not_by_equality():
    assert score_extraction(make_case(), make_extraction(PERFECT_ITEMS)).store_ok is True
    wrong = make_extraction(PERFECT_ITEMS, store="Supermercado Pague Menos")
    assert score_extraction(make_case(), wrong).store_ok is False


def test_a_wrong_date_is_scored_but_not_fatal():
    ext = make_extraction(PERFECT_ITEMS, date="2026-06-13")
    score = score_extraction(make_case(), ext)
    assert score.date_ok is False
    assert score.overall > 0.9


def test_scoring_is_deterministic_for_the_same_input():
    case, ext = make_case(), make_extraction(PERFECT_ITEMS)
    assert score_extraction(case, ext) == score_extraction(case, ext)


def test_normalize_description_is_case_and_punctuation_insensitive():
    assert normalize_description("LAYS  CLASSICA, B&G") == normalize_description(
        "lays classica b g"
    )


def test_aggregate_averages_each_dimension_and_counts_money_failures():
    good = score_extraction(make_case(), make_extraction(PERFECT_ITEMS))
    bad = score_extraction(
        make_case(), make_extraction(PERFECT_ITEMS, amount_paid=None)
    )
    agg = aggregate_extraction([good, bad])
    assert agg.n == 2
    assert agg.money_ok_rate == 0.5
    assert agg.item_recall == 1.0
    assert agg.overall == 0.5


def test_aggregate_of_nothing_is_zero_not_a_crash():
    agg = aggregate_extraction([])
    assert agg.n == 0 and agg.overall == 0.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_scoring.py -q
```

Expected: `ModuleNotFoundError: No module named 'assistant.eval.scoring'`.

- [ ] **Step 3: Implement the scorer**

Create `src/backend/assistant/eval/scoring.py`:

```python
"""Score one extraction against its ground truth. Pure, deterministic, offline.

Two models that are both imperfect cannot be compared with assertions, so every
dimension here is a ratio — except the money invariant, which is a gate. A read
whose items do not reconcile with the amount paid produces a wrong ledger entry
in production; scoring it 0.8 because the descriptions were nice would make the
harness recommend exactly the failure this product cannot afford.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
import re

from assistant.agents.extraction import ReceiptExtraction
from assistant.eval.dataset import ReceiptCase

# Below this similarity two descriptions are different products, not a sloppy
# read of the same one. Tuned against the real fixtures: "BACONZITOS B&G ELMA
# CHIPS M" vs "Baconzitos ELMA CHIPS" scores ~0.8; two different snacks ~0.4.
MATCH_THRESHOLD = 0.6

# Same tolerance the production consistency check uses, for the same reason:
# a five-cent gap is a rounding artefact on a thermal print, not a miscount.
MONEY_TOLERANCE = Decimal("0.05")

# Sums to 1.0. Recall dominates because a missed item is a missed expense; store
# and date are cheap to fix by hand and weighted accordingly.
WEIGHTS = {
    "item_recall": 0.35,
    "amount_accuracy": 0.25,
    "item_precision": 0.15,
    "category_accuracy": 0.15,
    "store": 0.05,
    "date": 0.05,
}

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_description(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_description(a), normalize_description(b)).ratio()


@dataclass(frozen=True)
class ExtractionScore:
    """One case, one model, every dimension the epic asked for."""

    case_id: str
    money_ok: bool
    item_recall: float
    item_precision: float
    amount_accuracy: float
    category_accuracy: float
    store_ok: bool
    date_ok: bool
    missed: tuple[str, ...]
    spurious: tuple[str, ...]

    @property
    def overall(self) -> float:
        """Weighted score, or 0.0 when the money invariant failed."""
        if not self.money_ok:
            return 0.0
        return round(
            WEIGHTS["item_recall"] * self.item_recall
            + WEIGHTS["amount_accuracy"] * self.amount_accuracy
            + WEIGHTS["item_precision"] * self.item_precision
            + WEIGHTS["category_accuracy"] * self.category_accuracy
            + WEIGHTS["store"] * (1.0 if self.store_ok else 0.0)
            + WEIGHTS["date"] * (1.0 if self.date_ok else 0.0),
            6,
        )


def _match_items(case: ReceiptCase, ext: ReceiptExtraction) -> dict[int, int]:
    """Greedy truth-index -> extracted-index map. Deterministic by construction.

    Truth items are visited in file order and each takes its best unclaimed
    candidate; ties break to the lowest extracted index. No global optimum is
    attempted — a receipt has tens of lines, not thousands, and a reproducible
    answer matters more here than an optimal one.
    """
    taken: set[int] = set()
    matched: dict[int, int] = {}
    for t_idx, truth in enumerate(case.items):
        best_idx, best_score = None, MATCH_THRESHOLD
        for e_idx, got in enumerate(ext.items):
            if e_idx in taken:
                continue
            score = _similarity(truth.description, got.description)
            if score > best_score:
                best_idx, best_score = e_idx, score
        if best_idx is not None:
            taken.add(best_idx)
            matched[t_idx] = best_idx
    return matched


def _money_ok(case: ReceiptCase, ext: ReceiptExtraction) -> bool:
    """Do the model's own numbers reconcile with what was actually paid?

    Requires BOTH: it reported the right amount paid, and its line totals minus
    its discount land on that amount. Either half alone lets a real bug through
    — the Americanas split reported the right total and produced R$0.00 on one
    category; the Mercado Livre read produced lines that summed to R$66.48 more
    than the order.
    """
    if ext.amount_paid is None:
        return False
    if abs(ext.amount_paid - case.amount_paid) > MONEY_TOLERANCE:
        return False
    lines = sum((i.line_total for i in ext.items), Decimal("0"))
    net = lines - (ext.discount or Decimal("0"))
    return abs(net - case.amount_paid) <= MONEY_TOLERANCE


def score_extraction(case: ReceiptCase, ext: ReceiptExtraction) -> ExtractionScore:
    """Every dimension of one read, against one gabarito."""
    matched = _match_items(case, ext)
    n_truth = len(case.items)
    n_got = len(ext.items)

    amount_hits = 0
    category_hits = 0
    for t_idx, e_idx in matched.items():
        truth, got = case.items[t_idx], ext.items[e_idx]
        if truth.line_total == got.line_total:
            amount_hits += 1
        if (got.category or "").strip().lower() == truth.category.strip().lower():
            category_hits += 1

    claimed = set(matched.values())
    return ExtractionScore(
        case_id=case.id,
        money_ok=_money_ok(case, ext),
        item_recall=(len(matched) / n_truth) if n_truth else 1.0,
        item_precision=(len(matched) / n_got) if n_got else (1.0 if not n_truth else 0.0),
        amount_accuracy=(amount_hits / n_truth) if n_truth else 1.0,
        category_accuracy=(category_hits / n_truth) if n_truth else 1.0,
        store_ok=case.store_key.lower() in normalize_description(ext.store or ""),
        date_ok=ext.date == case.date,
        missed=tuple(
            case.items[i].description for i in range(n_truth) if i not in matched
        ),
        spurious=tuple(
            ext.items[i].description for i in range(n_got) if i not in claimed
        ),
    )


@dataclass(frozen=True)
class AggregateScore:
    """A model's performance across the dataset."""

    n: int
    money_ok_rate: float
    item_recall: float
    item_precision: float
    amount_accuracy: float
    category_accuracy: float
    store_accuracy: float
    date_accuracy: float
    overall: float


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def aggregate_extraction(scores: Sequence[ExtractionScore]) -> AggregateScore:
    """Mean of each dimension. ``overall`` is the mean of the per-case overalls,
    so a single money failure costs a full case rather than being diluted."""
    return AggregateScore(
        n=len(scores),
        money_ok_rate=_mean([1.0 if s.money_ok else 0.0 for s in scores]),
        item_recall=_mean([s.item_recall for s in scores]),
        item_precision=_mean([s.item_precision for s in scores]),
        amount_accuracy=_mean([s.amount_accuracy for s in scores]),
        category_accuracy=_mean([s.category_accuracy for s in scores]),
        store_accuracy=_mean([1.0 if s.store_ok else 0.0 for s in scores]),
        date_accuracy=_mean([1.0 if s.date_ok else 0.0 for s in scores]),
        overall=_mean([s.overall for s in scores]),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_scoring.py -q
uv run ruff check src/backend/assistant/ && uv run ruff format src/backend/assistant/eval/
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/eval/scoring.py src/backend/assistant/tests/test_eval_scoring.py
git commit -m "feat(eval): score an extraction per dimension, with the money invariant as a gate"
```

---

## Task 3: Cost and latency accounting for a harness run

**Files:**
- Create: `src/backend/assistant/eval/costing.py`
- Test: `src/backend/assistant/tests/test_eval_costing.py`

**Interfaces:**
- Consumes: `assistant.pricing.cost_usd_for`.
- Produces:
  - `CallCost` (frozen dataclass): `model: str`, `input_tokens: int`, `output_tokens: int`, `latency_ms: int`, `cost_usd: Decimal | None`
  - `CostTotals` (frozen dataclass): `calls: int`, `input_tokens: int`, `output_tokens: int`, `cost_usd: Decimal`, `unpriced_calls: int`, `latency_ms_total: int`, `avg_latency_ms: int` (property)
  - `cost_of(model: str, usage, latency_ms: int) -> CallCost`
  - `total(costs: Iterable[CallCost]) -> CostTotals`

> **This is a synchronous, database-touching module.** `cost_usd_for` reads `ModelPrice`. Never call it from inside the async runners — see the Orientation note about `SynchronousOnlyOperation`. The runners return raw usage; the command converts.

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_costing.py`:

```python
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


def usage(inp, out):
    return SimpleNamespace(input_tokens=inp, output_tokens=out)


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
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_costing.py -q
```

Expected: `ModuleNotFoundError: No module named 'assistant.eval.costing'`.

- [ ] **Step 3: Implement**

Create `src/backend/assistant/eval/costing.py`:

```python
"""What a harness run cost, in tokens, dollars and milliseconds.

Reuses `assistant.pricing.cost_usd_for` rather than re-deriving prices: the
comparison table and the operator's production cost report must agree, and two
implementations of the same arithmetic eventually will not.

Deliberately NOT written to `UsageRecord`. A harness run has no household, and a
cost row nobody can be charged for pollutes the ledger the pricing decisions are
made from.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from assistant.pricing import cost_usd_for


@dataclass(frozen=True)
class CallCost:
    """One provider call inside the harness."""

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal | None


def cost_of(model: str, usage, latency_ms: int) -> CallCost:
    """Price one call. ``usage=None`` means the call failed before reporting any.

    Synchronous and hits the database (``ModelPrice``). Call it from the command,
    never from inside an async runner.
    """
    inp = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
    out = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
    cost = cost_usd_for(model, usage) if usage is not None else None
    return CallCost(
        model=model,
        input_tokens=inp,
        output_tokens=out,
        latency_ms=latency_ms,
        cost_usd=cost,
    )


@dataclass(frozen=True)
class CostTotals:
    """What a whole suite cost on one model."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced_calls: int
    latency_ms_total: int

    @property
    def avg_latency_ms(self) -> int:
        return int(self.latency_ms_total / self.calls) if self.calls else 0


def total(costs: Iterable[CallCost]) -> CostTotals:
    """Sum the priced calls; count the unpriced ones apart."""
    costs = list(costs)
    priced = [c.cost_usd for c in costs if c.cost_usd is not None]
    return CostTotals(
        calls=len(costs),
        input_tokens=sum(c.input_tokens for c in costs),
        output_tokens=sum(c.output_tokens for c in costs),
        cost_usd=sum(priced, Decimal("0")),
        unpriced_calls=sum(1 for c in costs if c.cost_usd is None),
        latency_ms_total=sum(c.latency_ms for c in costs),
    )
```

- [ ] **Step 4: Run to verify it passes, then commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_costing.py -q
git add src/backend/assistant/eval/costing.py src/backend/assistant/tests/test_eval_costing.py
git commit -m "feat(eval): token, cost and latency accounting for a harness run"
```

Expected: 5 passed.

---

## Task 4: Behavioural cases and the ledger scorer

The judgment half of the epic. Extraction is a vision problem; category resolution and billing-month reasoning are judgment problems, and judgment is what degrades when you downgrade a model.

**Files:**
- Create: `src/backend/assistant/eval/behaviour.py`
- Test: `src/backend/assistant/tests/test_eval_behaviour.py`

**Interfaces:**
- Consumes: `assistant.eval.dataset.PaymentMethodSpec`, `assistant.agents.extraction.ReceiptExtraction`, `assistant.agents.extraction.extraction_to_prompt`, `assistant.agents.tools.build_duplicate_receipt_directive`, `assistant.agents.tools.find_registered_duplicate`.
- Produces:
  - `ExpectedEntry` (frozen dataclass): `category: str`, `amount: Decimal | None = None`, `billing_month: date | None = None`, `payment_method: str | None = None`, `description_contains: str | None = None`
  - `World` (frozen dataclass): `categories: tuple[str, ...]`, `payment_methods: tuple[PaymentMethodSpec, ...]`, `receipt_payload: dict | None = None`, `registered_receipt: dict | None = None`, `existing_entries: tuple[dict, ...] = ()`
  - `BehaviourCase` (frozen dataclass): `id: str`, `why: str`, `world: World`, `opening: Literal["text","receipt","duplicate"]`, `turns: tuple[str, ...]`, `expected_entries: tuple[ExpectedEntry, ...] = ()`, `expected_total: Decimal | None = None`, `expect_no_new_entries: bool = False`, `today: date`
  - `BEHAVIOUR_CASES: tuple[BehaviourCase, ...]` (7 cases)
  - `LedgerRow` (frozen dataclass): `category: str`, `amount: Decimal`, `billing_month: date`, `payment_method: str`, `description: str`
  - `BehaviourScore` (frozen dataclass): `case_id: str`, `matched: int`, `expected: int`, `extra: int`, `total_ok: bool`, `errors: tuple[str, ...]`, `passed: bool` (property), `score: float` (property)
  - `score_ledger(case: BehaviourCase, rows: Sequence[LedgerRow]) -> BehaviourScore`
  - `load_behaviour_cases(ids: list[str] | None = None) -> list[BehaviourCase]`

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_behaviour.py`:

```python
"""Behavioural cases assert the LEDGER, never the prose.

The model's wording will vary between runs and between models; the entry it
creates must not. Every expectation in `BEHAVIOUR_CASES` is a row, an amount, a
billing month or the absence of a row.
"""

from datetime import date
from decimal import Decimal

from assistant.eval.behaviour import (
    BEHAVIOUR_CASES,
    BehaviourCase,
    ExpectedEntry,
    LedgerRow,
    World,
    load_behaviour_cases,
    score_ledger,
)


def row(category, amount, *, billing_month=date(2026, 7, 1), payment_method="Credito C6",
        description="Loja - coisas"):
    return LedgerRow(
        category=category,
        amount=Decimal(amount),
        billing_month=billing_month,
        payment_method=payment_method,
        description=description,
    )


def case(**overrides) -> BehaviourCase:
    data = {
        "id": "t",
        "why": "synthetic",
        "world": World(categories=("Roupa", "Lanche"), payment_methods=()),
        "opening": "text",
        "turns": ("oi",),
        "expected_entries": (
            ExpectedEntry(category="Roupa", amount=Decimal("9.13")),
            ExpectedEntry(category="Lanche", amount=Decimal("33.03")),
        ),
        "expected_total": Decimal("42.16"),
        "today": date(2026, 6, 20),
    }
    data.update(overrides)
    return BehaviourCase(**data)


def test_the_expected_ledger_passes():
    score = score_ledger(case(), [row("Roupa", "9.13"), row("Lanche", "33.03")])
    assert score.passed is True
    assert score.matched == 2 and score.extra == 0 and score.total_ok is True
    assert score.errors == ()


def test_row_order_does_not_matter():
    assert score_ledger(case(), [row("Lanche", "33.03"), row("Roupa", "9.13")]).passed


def test_the_americanas_failure_is_caught():
    """Roupa 42,16 / Lanche 0,00 — the real transcript in iteraction.txt."""
    score = score_ledger(case(), [row("Roupa", "42.16"), row("Lanche", "0.00")])
    assert score.passed is False
    assert score.matched == 0
    assert any("Roupa" in e for e in score.errors)


def test_a_missing_entry_fails():
    score = score_ledger(case(), [row("Roupa", "9.13")])
    assert score.passed is False
    assert score.matched == 1 and score.total_ok is False


def test_an_extra_entry_fails_even_when_every_expectation_matched():
    score = score_ledger(
        case(), [row("Roupa", "9.13"), row("Lanche", "33.03"), row("Roupa", "5.00")]
    )
    assert score.passed is False
    assert score.extra == 1


def test_amount_none_means_any_positive_amount():
    c = case(
        expected_entries=(
            ExpectedEntry(category="Roupa"),
            ExpectedEntry(category="Lanche"),
        )
    )
    assert score_ledger(c, [row("Roupa", "9.13"), row("Lanche", "33.03")]).passed
    assert not score_ledger(c, [row("Roupa", "42.16"), row("Lanche", "0.00")]).passed


def test_billing_month_is_asserted_when_declared():
    c = case(
        expected_entries=(
            ExpectedEntry(category="Roupa", amount=Decimal("9.13"),
                          billing_month=date(2026, 8, 1)),
        ),
        expected_total=Decimal("9.13"),
    )
    ok = score_ledger(c, [row("Roupa", "9.13", billing_month=date(2026, 8, 1))])
    bad = score_ledger(c, [row("Roupa", "9.13", billing_month=date(2026, 7, 1))])
    assert ok.passed and not bad.passed
    assert any("billing_month" in e for e in bad.errors)


def test_payment_method_and_description_are_asserted_when_declared():
    c = case(
        expected_entries=(
            ExpectedEntry(category="Roupa", amount=Decimal("9.13"),
                          payment_method="Pix", description_contains="Americanas"),
        ),
        expected_total=Decimal("9.13"),
    )
    bad = score_ledger(c, [row("Roupa", "9.13", payment_method="Credito C6")])
    assert not bad.passed and any("payment_method" in e for e in bad.errors)


def test_expect_no_new_entries_passes_only_on_an_untouched_ledger():
    c = case(expected_entries=(), expected_total=None, expect_no_new_entries=True)
    assert score_ledger(c, []).passed is True
    assert score_ledger(c, [row("Roupa", "9.13")]).passed is False


def test_the_suite_has_at_least_six_cases_and_unique_ids():
    assert len(BEHAVIOUR_CASES) >= 6
    assert len({c.id for c in BEHAVIOUR_CASES}) == len(BEHAVIOUR_CASES)


def test_every_case_asserts_something_about_the_ledger():
    for c in BEHAVIOUR_CASES:
        assert c.expected_entries or c.expect_no_new_entries, c.id


def test_every_case_pins_its_own_clock():
    """No time-bomb cases: billing-month judgment depends on today's date."""
    for c in BEHAVIOUR_CASES:
        assert isinstance(c.today, date), c.id


def test_every_case_declares_the_categories_and_methods_its_answer_needs():
    for c in BEHAVIOUR_CASES:
        names = {p.name for p in c.world.payment_methods}
        for exp in c.expected_entries:
            assert exp.category in c.world.categories, (c.id, exp.category)
            if exp.payment_method:
                assert exp.payment_method in names, (c.id, exp.payment_method)


def test_the_iteraction_failure_is_one_of_the_cases():
    assert any("americanas" in c.id for c in BEHAVIOUR_CASES)


def test_load_behaviour_cases_filters_by_id():
    (one,) = load_behaviour_cases([BEHAVIOUR_CASES[0].id])
    assert one is BEHAVIOUR_CASES[0]
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_behaviour.py -q
```

Expected: `ModuleNotFoundError: No module named 'assistant.eval.behaviour'`.

- [ ] **Step 3: Implement the types and the scorer**

Create `src/backend/assistant/eval/behaviour.py` with this header and scoring half (the case list follows in Step 4):

```python
"""Behavioural cases: the judgments a cheaper model will get wrong first.

Extraction is a vision problem. Resolving a category from a loose phrase,
picking the payment method, computing a credit card's billing month, splitting a
receipt on request and refusing to double-register — those are judgment, and
judgment is what degrades when you downgrade.

Every case asserts the RESULTING LEDGER, never the wording of the reply. There
is deliberately no LLM-as-judge (epic open question 4): a judge model adds cost,
variance, and a second thing to trust.

Plan decision D-B: each case declares its own categories and payment methods and
the harness seeds exactly those. No MemoryRule is ever seeded — a score that
moves when the operator's personal rules change is not a baseline.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from assistant.eval.dataset import PaymentMethodSpec


@dataclass(frozen=True)
class ExpectedEntry:
    """One ledger row a correct run must produce.

    ``amount=None`` means "any amount strictly greater than zero" — used where
    the exact figure comes from discount proration and pinning it would test
    `_prorate_discount`'s rounding rather than the model's judgment.
    """

    category: str
    amount: Decimal | None = None
    billing_month: date | None = None
    payment_method: str | None = None
    description_contains: str | None = None


@dataclass(frozen=True)
class World:
    """What exists before the turn runs."""

    categories: tuple[str, ...]
    payment_methods: tuple[PaymentMethodSpec, ...]
    # Payload for a PENDING ReceiptDraft, shaped exactly like
    # `ReceiptExtraction.model_dump(mode="json")` — the same thing the view writes.
    receipt_payload: dict | None = None
    # Payload for an already-REGISTERED draft, for the duplicate case.
    registered_receipt: dict | None = None
    # Entries that already exist: dicts with date/amount/description/category/
    # payment_method keys.
    existing_entries: tuple[dict, ...] = ()


@dataclass(frozen=True)
class BehaviourCase:
    """One scored conversation.

    ``opening`` decides how the FIRST prompt is built, mirroring production:
    - "text"      → `turns[0]` verbatim, as a user typing.
    - "receipt"   → `extraction_to_prompt(...)`, what the view sends after a photo.
    - "duplicate" → `build_duplicate_receipt_directive(...)`, the re-sent-photo path.
    """

    id: str
    why: str
    world: World
    opening: Literal["text", "receipt", "duplicate"]
    turns: tuple[str, ...]
    today: date
    expected_entries: tuple[ExpectedEntry, ...] = ()
    expected_total: Decimal | None = None
    expect_no_new_entries: bool = False


@dataclass(frozen=True)
class LedgerRow:
    """An `Entry` flattened to the fields a case can assert."""

    category: str
    amount: Decimal
    billing_month: date
    payment_method: str
    description: str


@dataclass(frozen=True)
class BehaviourScore:
    case_id: str
    matched: int
    expected: int
    extra: int
    total_ok: bool
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def score(self) -> float:
        """1.0 or 0.0. A ledger is right or it is wrong; there is no partial
        credit for creating half of someone's expenses."""
        return 1.0 if self.passed else 0.0


def _matches(exp: ExpectedEntry, row: LedgerRow) -> str | None:
    """``None`` when the row satisfies the expectation, else why it does not."""
    if row.category.strip().lower() != exp.category.strip().lower():
        return f"category {row.category!r} != {exp.category!r}"
    if exp.amount is None:
        if row.amount <= 0:
            return f"{exp.category}: expected a positive amount, got {row.amount}"
    elif row.amount != exp.amount:
        return f"{exp.category}: expected {exp.amount}, got {row.amount}"
    if exp.billing_month and row.billing_month != exp.billing_month:
        return (
            f"{exp.category}: billing_month {row.billing_month} != {exp.billing_month}"
        )
    if exp.payment_method and row.payment_method.strip().lower() != (
        exp.payment_method.strip().lower()
    ):
        return f"{exp.category}: payment_method {row.payment_method!r} != {exp.payment_method!r}"
    if exp.description_contains and exp.description_contains.lower() not in (
        row.description.lower()
    ):
        return f"{exp.category}: description {row.description!r} lacks {exp.description_contains!r}"
    return None


def score_ledger(case: BehaviourCase, rows: Sequence[LedgerRow]) -> BehaviourScore:
    """Compare the rows the run created against what the case expects."""
    errors: list[str] = []

    if case.expect_no_new_entries:
        if rows:
            errors.append(
                f"expected NO new entries, got {len(rows)}: "
                + ", ".join(f"{r.category} {r.amount}" for r in rows)
            )
        return BehaviourScore(
            case_id=case.id,
            matched=0,
            expected=0,
            extra=len(rows),
            total_ok=not rows,
            errors=tuple(errors),
        )

    unclaimed = list(range(len(rows)))
    matched = 0
    for exp in case.expected_entries:
        hit = None
        misses: list[str] = []
        for idx in unclaimed:
            problem = _matches(exp, rows[idx])
            if problem is None:
                hit = idx
                break
            misses.append(problem)
        if hit is None:
            errors.append(
                f"no row satisfied {exp.category}"
                + (f" ({'; '.join(misses)})" if misses else " (no rows left)")
            )
        else:
            unclaimed.remove(hit)
            matched += 1

    if unclaimed:
        errors.append(
            "unexpected extra rows: "
            + ", ".join(f"{rows[i].category} {rows[i].amount}" for i in unclaimed)
        )

    total = sum((r.amount for r in rows), Decimal("0"))
    total_ok = case.expected_total is None or total == case.expected_total
    if not total_ok:
        errors.append(f"ledger total {total} != expected {case.expected_total}")

    return BehaviourScore(
        case_id=case.id,
        matched=matched,
        expected=len(case.expected_entries),
        extra=len(unclaimed),
        total_ok=total_ok,
        errors=tuple(errors),
    )


def load_behaviour_cases(ids: list[str] | None = None) -> list[BehaviourCase]:
    """All cases, or the ids asked for."""
    by_id = {c.id: c for c in BEHAVIOUR_CASES}
    if ids is None:
        return list(BEHAVIOUR_CASES)
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"unknown behaviour case id(s): {', '.join(missing)}")
    return [by_id[i] for i in ids]
```

> **Note:** `from dataclasses import field` is not used by this module — drop it from the import line. `ruff check` will flag it.

- [ ] **Step 4: Write the seven behavioural cases**

Append to `src/backend/assistant/eval/behaviour.py`:

```python
# ── The cases ───────────────────────────────────────────────────────────────
#
# Fixed catalogue shared by most cases (plan decision D-B). Closing day 25 makes
# the billing-month cases unambiguous in both directions.

CREDITO = PaymentMethodSpec(name="Credito C6", type="credit_card", closing_day=25)
PIX = PaymentMethodSpec(name="Pix", type="pix")
DINHEIRO = PaymentMethodSpec(name="Dinheiro", type="cash")
CATALOGUE = (CREDITO, PIX, DINHEIRO)

AMERICANAS_PAYLOAD = {
    "store": "americanas sa - 1063",
    "date": "2026-06-12",
    "discount": "3.99",
    "amount_paid": "42.16",
    "payment_hint": "CREDITO",
    "receipt_type": "fiscal_cupom",
    "confidence": 0.9,
    "items": [
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "9.99"},
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99"},
        {"description": "LAYS CLASSICA B&G ELMA CHIPS M", "line_total": "9.99"},
        {"description": "WAFER MAIS AMENDOIM 102G HERSHEYS", "line_total": "6.19"},
        {"description": "BATATA PRINGLES CREME E CEBOLA 109G", "line_total": "9.99"},
    ],
}

HIPERMACIONAL_PAYLOAD = {
    "store": "HIPERMACIONAL LTDA",
    "date": "2026-06-15",
    "discount": "0",
    "amount_paid": "376.70",
    "payment_hint": "CREDITO",
    "receipt_type": "fiscal_cupom",
    "confidence": 0.9,
    "items": [
        {"description": d, "line_total": v}
        for d, v in [
            ("MASSA RAINHA PASTEL 1kg", "9.95"),
            ("LINGUICA CHURRASCO 500G BACON", "18.95"),
            ("LINGUICA CHURRASCO 500G BIQUINHO", "18.95"),
            ("QUEIJO ISIS COAL Z LAC kg", "32.73"),
            ("FILE PEITO REGINA 1kg", "24.75"),
            ("FILEZINHO REGINA MILANESA 700G", "23.75"),
            ("BATATA EASYCHEF PRE FRITA 2kg", "24.85"),
            ("QUEIJO ITAMBE ZERO LAC 150G", "24.90"),
            ("LEITE UHT PIRACANJU 1L", "10.99"),
            ("IOG BETANIA YO BEM 170G PAPAIA", "8.30"),
            ("IOG BETANIA YO BEM 170G MORANGO", "8.30"),
            ("ALHO kg", "2.62"),
            ("CEBOLA AMARELA kg", "3.32"),
            ("EMP LEMON PEPPER kg", "4.55"),
            ("EMP PAPRIC DEFUMADA kg", "2.58"),
            ("EMP GERGELIM MIX kg", "4.62"),
            ("PIMENTAO kg", "1.18"),
            ("CR LEITE PIRACANJU ZERO LACT 200G", "12.50"),
            ("OVOS CAIP TIJUCA 10UN", "9.95"),
            ("BATAT PALH ELMA CHIPS 190G", "22.99"),
            ("BISC TODDY WAFER 94G CHOC", "3.15"),
            ("ENERG EXTR POWER 473ML MANGO", "14.50"),
            ("RACAO CHAMP ADULTO 85G FRANGO", "9.45"),
            ("RACAO CHAMP ADULTO 85G CARNE", "9.45"),
            ("TOALHA PAPEL C 2 SCALA", "5.49"),
            ("AMAC DOWNY 1L BRISA", "29.99"),
            ("DESOD MONANGE AERO 150ML", "9.95"),
            ("ESPUMA GILLETTE 155ML", "23.99"),
        ]
    ],
}

BEHAVIOUR_CASES: tuple[BehaviourCase, ...] = (
    BehaviourCase(
        id="americanas-split-on-request",
        why=(
            "The transcript in docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/"
            "iteraction.txt: asked to split, the agent registered Roupa R$42,16 and "
            "Lanche R$0,00. The split is the whole point of per-item extraction."
        ),
        world=World(
            categories=("Roupa", "Lanche", "Alimentacao"),
            payment_methods=CATALOGUE,
            receipt_payload=AMERICANAS_PAYLOAD,
        ),
        opening="receipt",
        turns=(
            "Nao, separe as categorias. O soutien e Roupa; os salgadinhos, "
            "bolacha e batata sao Lanche. A loja e Lojas Americanas e paguei "
            "no Credito C6.",
            "Confirma, pode registrar.",
        ),
        today=date(2026, 6, 20),
        # 9.13 / 33.03: the discount is re-derived as sum(lines) - amount_paid
        # = 3.99 and prorated with the residue absorbed by the largest category.
        expected_entries=(
            ExpectedEntry(
                category="Roupa",
                amount=Decimal("9.13"),
                payment_method="Credito C6",
                description_contains="Americanas",
            ),
            ExpectedEntry(
                category="Lanche",
                amount=Decimal("33.03"),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("42.16"),
    ),
    BehaviourCase(
        id="hipermacional-six-categories-no-double-count",
        why=(
            "The real bug: Pets was counted twice (on its own line AND inside "
            "Alimentacao) and Lanche was merged away, turning R$376,70 into "
            "R$395,60. Six categories is where a weaker model starts merging."
        ),
        world=World(
            categories=(
                "Alimentacao", "Lanche", "Pets", "Casa", "Limpeza", "Perfumaria",
            ),
            payment_methods=CATALOGUE,
            receipt_payload=HIPERMACIONAL_PAYLOAD,
        ),
        opening="receipt",
        turns=("Paguei no Credito C6. Confirma, pode registrar.",),
        today=date(2026, 6, 20),
        expected_entries=(
            ExpectedEntry(category="Alimentacao", amount=Decimal("273.88")),
            ExpectedEntry(category="Lanche", amount=Decimal("14.50")),
            ExpectedEntry(category="Pets", amount=Decimal("18.90")),
            ExpectedEntry(category="Casa", amount=Decimal("5.49")),
            ExpectedEntry(category="Limpeza", amount=Decimal("29.99")),
            ExpectedEntry(category="Perfumaria", amount=Decimal("33.94")),
        ),
        expected_total=Decimal("376.70"),
    ),
    BehaviourCase(
        id="billing-month-after-closing-day",
        why=(
            "A credit purchase AFTER the closing day lands two months out, not "
            "one. Getting this wrong puts the expense on the wrong invoice and "
            "silently breaks every monthly total the dashboard shows."
        ),
        world=World(categories=("Alimentacao", "Lanche"), payment_methods=CATALOGUE),
        opening="text",
        turns=("Gastei 120 reais no supermercado hoje, no Credito C6.",),
        # Closing day 25; purchase on the 26th closes in July and is paid in August.
        today=date(2026, 6, 26),
        expected_entries=(
            ExpectedEntry(
                category="Alimentacao",
                amount=Decimal("120.00"),
                billing_month=date(2026, 8, 1),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("120.00"),
    ),
    BehaviourCase(
        id="billing-month-before-closing-day",
        why=(
            "The other side of the same rule: on/before the closing day the "
            "expense is paid the following month. A model that applies one rule "
            "everywhere passes exactly one of these two cases."
        ),
        world=World(categories=("Alimentacao", "Lanche"), payment_methods=CATALOGUE),
        opening="text",
        turns=("Gastei 80 reais no supermercado hoje, no Credito C6.",),
        today=date(2026, 6, 12),
        expected_entries=(
            ExpectedEntry(
                category="Alimentacao",
                amount=Decimal("80.00"),
                billing_month=date(2026, 7, 1),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("80.00"),
    ),
    BehaviourCase(
        id="category-and-method-from-a-loose-phrase",
        why=(
            "Nothing in the sentence names a category or a payment method "
            "verbatim. Resolving 'racao do cachorro' to Pets and 'pix' to the "
            "registered Pix method is the judgment that degrades first."
        ),
        world=World(
            categories=("Alimentacao", "Pets", "Casa"), payment_methods=CATALOGUE
        ),
        opening="text",
        turns=("Comprei racao pro cachorro por 45 reais no pix hoje.",),
        today=date(2026, 6, 12),
        expected_entries=(
            ExpectedEntry(
                category="Pets",
                amount=Decimal("45.00"),
                billing_month=date(2026, 6, 1),
                payment_method="Pix",
            ),
        ),
        expected_total=Decimal("45.00"),
    ),
    BehaviourCase(
        id="refuses-to-double-register-a-known-receipt",
        why=(
            "The PAGUE MENOS incident: a photo re-sent to fix the date opened a "
            "second commit flow and the following 'sim' registered the receipt "
            "twice. The ledger must not grow."
        ),
        world=World(
            categories=("Alimentacao", "Lanche"),
            payment_methods=CATALOGUE,
            registered_receipt=HIPERMACIONAL_PAYLOAD,
            existing_entries=(
                {
                    "date": "2026-06-15",
                    "amount": "376.70",
                    "description": "HIPERMACIONAL LTDA - mercearia",
                    "category": "Alimentacao",
                    "payment_method": "Credito C6",
                },
            ),
        ),
        opening="duplicate",
        turns=("Sim.", "Isso mesmo, pode confirmar."),
        today=date(2026, 6, 16),
        expect_no_new_entries=True,
    ),
    BehaviourCase(
        id="refuses-to-invent-an-unreadable-amount",
        why=(
            "When amount_paid is not legible the agent must ASK, never guess. A "
            "guessed total is a wrong expense that looks completely normal in "
            "the ledger and is never noticed."
        ),
        world=World(
            categories=("Alimentacao", "Lanche"),
            payment_methods=CATALOGUE,
            receipt_payload={
                "store": "MERCADINHO SAO JOSE",
                "date": "2026-06-18",
                "discount": None,
                "amount_paid": None,
                "payment_hint": None,
                "receipt_type": "fiscal_cupom",
                "confidence": 0.35,
                "items": [
                    {"description": "ARROZ 5KG", "line_total": "24.90"},
                    {"description": "FEIJAO 1KG", "line_total": "8.50"},
                ],
            },
        ),
        opening="receipt",
        turns=("Nao consigo ler o total, esta borrado.",),
        today=date(2026, 6, 20),
        expect_no_new_entries=True,
    ),
)
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_behaviour.py -q
uv run ruff check src/backend/assistant/eval/ && uv run ruff format src/backend/assistant/eval/
```

Expected: 15 passed. Delete the unused `field` import if ruff flags it.

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/eval/behaviour.py src/backend/assistant/tests/test_eval_behaviour.py
git commit -m "feat(eval): seven behavioural cases, scored on the resulting ledger"
```

---

## Task 5: The extraction runner, and the one seam it needs in production code

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py` (extract `build_extraction_prompt`, lines ~189-203)
- Create: `src/backend/assistant/eval/extraction_runner.py`
- Test: `src/backend/assistant/tests/test_eval_runners.py`

**Interfaces:**
- Consumes: `assistant.eval.dataset.ReceiptCase`, `assistant.agents.extraction.extraction_agent`.
- Produces:
  - `build_extraction_prompt(images: list[tuple[bytes, str]], categories: list[str] | None = None, payment_methods: list[str] | None = None) -> list` — in `extraction.py`
  - `RawRun` (frozen dataclass): `case_id: str`, `extraction: ReceiptExtraction | None`, `usage: object | None`, `latency_ms: int`, `error: str`
  - `async run_extraction_case(case: ReceiptCase, model) -> RawRun`
  - `async run_extraction_suite(cases: Sequence[ReceiptCase], model) -> list[RawRun]`

> **Constraint 12 applies here.** The refactor moves prompt-assembly into a function. Not one character of `EXTRACTION_INSTRUCTION` or the two appended blocks may change. If a diff of the resulting prompt string is non-empty, the refactor is wrong.

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_runners.py`:

```python
"""The runners, driven by TestModel — no provider, no money, no network."""

from decimal import Decimal

import pytest
from pydantic_ai.models.test import TestModel

from assistant.eval.dataset import load_receipt_cases
from assistant.eval.extraction_runner import run_extraction_case, run_extraction_suite

GOOD_READ = {
    "store": "Lojas Americanas",
    "date": "2026-06-12",
    "discount": "3.99",
    "amount_paid": "42.16",
    "confidence": 0.9,
    "items": [
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "9.99",
         "category": "Roupa"},
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99",
         "category": "Lanche"},
        {"description": "LAYS CLASSICA B&G ELMA CHIPS M", "line_total": "9.99",
         "category": "Lanche"},
        {"description": "WAFER MAIS AMENDOIM 102G HERSHEYS", "line_total": "6.19",
         "category": "Lanche"},
        {"description": "BATATA PRINGLES CREME E CEBOLA 109G", "line_total": "9.99",
         "category": "Lanche"},
    ],
}


def test_the_prompt_builder_produces_the_same_instruction_extract_receipt_uses():
    from assistant.agents.extraction import EXTRACTION_INSTRUCTION, build_extraction_prompt

    prompt = build_extraction_prompt([(b"x", "image/jpeg")])
    assert prompt[0] == EXTRACTION_INSTRUCTION
    assert len(prompt) == 2  # instruction + one BinaryContent


def test_the_prompt_builder_appends_categories_and_methods_verbatim():
    from assistant.agents.extraction import build_extraction_prompt

    prompt = build_extraction_prompt(
        [(b"x", "image/jpeg")], categories=["Roupa", "Lanche"], payment_methods=["Pix"]
    )
    assert "Roupa, Lanche" in prompt[0]
    assert "Pix" in prompt[0]


@pytest.mark.anyio
async def test_run_extraction_case_returns_output_usage_and_latency():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = await run_extraction_case(case, TestModel(custom_output_args=GOOD_READ))
    assert run.case_id == case.id
    assert run.error == ""
    assert run.extraction.amount_paid == Decimal("42.16")
    assert run.usage.input_tokens > 0
    assert run.latency_ms >= 0


@pytest.mark.anyio
async def test_a_failing_model_is_recorded_not_raised():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])

    class Boom(TestModel):
        async def request(self, *args, **kwargs):
            raise RuntimeError("provider exploded")

    run = await run_extraction_case(case, Boom())
    assert run.extraction is None
    assert "provider exploded" in run.error
    assert run.usage is None


@pytest.mark.anyio
async def test_run_extraction_suite_runs_every_case_in_order():
    cases = load_receipt_cases(["americanas-2026-06-12", "hipermacional-2026-06-15"])
    runs = await run_extraction_suite(cases, TestModel(custom_output_args=GOOD_READ))
    assert [r.case_id for r in runs] == [c.id for c in cases]
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_runners.py -q
```

Expected: `ImportError: cannot import name 'build_extraction_prompt'`.

- [ ] **Step 3: Extract the prompt builder (pure refactor)**

In `src/backend/assistant/agents/extraction.py`, insert this function immediately above `async def extract_receipt`:

```python
def build_extraction_prompt(
    images: list[tuple[bytes, str]],
    categories: list[str] | None = None,
    payment_methods: list[str] | None = None,
) -> list:
    """Assemble the vision prompt: instruction text plus every image.

    Split out of ``extract_receipt`` so the E08 harness can run the SAME prompt
    against a different model and read ``result.usage()`` back, which
    ``extract_receipt`` discards. Pure — no I/O, no metering, no settings read.
    """
    instruction = EXTRACTION_INSTRUCTION
    if categories:
        instruction += (
            "\nCategorias do usuário (atribua a categoria de CADA item escolhendo "
            "EXATAMENTE uma desta lista; se nenhuma servir, deixe category=null): "
            + ", ".join(categories)
            + "."
        )
    if payment_methods:
        instruction += (
            "\nFormas de pagamento cadastradas (proponha em payment_hint a que casa, "
            "ou deixe como aparece no recibo): " + ", ".join(payment_methods) + "."
        )
    return [instruction] + [BinaryContent(data=data, media_type=mt) for data, mt in images]
```

Then replace the body of `extract_receipt` between the docstring and `resolved = ...` (currently lines ~189-203) with a single call:

```python
    prompt = build_extraction_prompt(images, categories, payment_methods)
```

- [ ] **Step 4: Prove the refactor changed nothing**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_prompts.py \
    src/backend/assistant/tests/test_extraction.py \
    src/backend/assistant/tests/test_prompts.py -q
git diff src/backend/assistant/agents/extraction.py
```

Expected: all pass, and the diff shows only the function being moved — no changed prompt text.

- [ ] **Step 5: Write the runner**

Create `src/backend/assistant/eval/extraction_runner.py`:

```python
"""Run one model over the receipt dataset. Async, and free of the database.

Deliberately calls ``extraction_agent.run`` rather than ``extract_receipt``:
the harness needs ``result.usage()``, which ``extract_receipt`` drops, and it
must NOT meter into ``UsageRecord`` — a harness run has no household to bill.
The prompt is byte-identical to production's, via ``build_extraction_prompt``.

No database access here: pricing happens in the synchronous layer above. See the
plan's Orientation note on `sync_to_async` and connections.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass

from assistant.agents.extraction import ReceiptExtraction, build_extraction_prompt, extraction_agent
from assistant.eval.dataset import ReceiptCase


@dataclass(frozen=True)
class RawRun:
    """One model call: what came back, what it consumed, how long it took."""

    case_id: str
    extraction: ReceiptExtraction | None
    usage: object | None
    latency_ms: int
    error: str


async def run_extraction_case(case: ReceiptCase, model) -> RawRun:
    """Read one receipt with ``model``. Records failures, never raises them —
    a provider that refuses one image must not abort a 10-case comparison."""
    data, media_type = case.read_image()
    prompt = build_extraction_prompt(
        [(data, media_type)],
        categories=list(case.categories),
        payment_methods=[p.name for p in case.payment_methods],
    )
    started = time.perf_counter()
    try:
        result = await extraction_agent.run(prompt, model=model)
    except Exception as exc:  # noqa: BLE001 - a failed read is data, not a crash
        return RawRun(
            case_id=case.id,
            extraction=None,
            usage=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
    return RawRun(
        case_id=case.id,
        extraction=result.output,
        usage=result.usage(),
        latency_ms=int((time.perf_counter() - started) * 1000),
        error="",
    )


async def run_extraction_suite(cases: Sequence[ReceiptCase], model) -> list[RawRun]:
    """Every case, in order. Sequential on purpose: parallel calls make the
    latency column meaningless and provoke provider rate limits mid-run."""
    return [await run_extraction_case(case, model) for case in cases]
```

- [ ] **Step 6: Run the tests and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_runners.py -q
uv run ruff check src/backend/assistant/ && uv run ruff format --check src/backend/assistant/
git add src/backend/assistant/agents/extraction.py \
        src/backend/assistant/eval/extraction_runner.py \
        src/backend/assistant/tests/test_eval_runners.py
git commit -m "feat(eval): extraction runner, on the exact production prompt"
```

Expected: 5 passed.

---

## Task 6: The behavioural runner

**Files:**
- Create: `src/backend/assistant/eval/behaviour_runner.py`
- Modify: `src/backend/assistant/tests/test_eval_runners.py` (append)

**Interfaces:**
- Consumes: `assistant.eval.behaviour` (all types), `assistant.agents.assistant.assistant_agent`, `assistant.agents.scope.AgentScope`.
- Produces:
  - `build_world(case: BehaviourCase, household, user) -> None` (sync, ORM)
  - `build_opening_prompt(case: BehaviourCase, scope) -> str` (sync, ORM)
  - `snapshot_ledger(household, since_ids: set) -> list[LedgerRow]` (sync, ORM)
  - `BehaviourRun` (frozen dataclass): `case_id: str`, `rows: list[LedgerRow]`, `usages: list[object]`, `latency_ms: int`, `error: str`
  - `async run_behaviour_case(case: BehaviourCase, model, household, user) -> BehaviourRun`

---

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_eval_runners.py`:

```python
# ── Behavioural runner ──────────────────────────────────────────────────────

from datetime import date  # noqa: E402

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from assistant.eval.behaviour import (  # noqa: E402
    BehaviourCase,
    ExpectedEntry,
    World,
    load_behaviour_cases,
    score_ledger,
)
from assistant.eval.behaviour_runner import (  # noqa: E402
    build_opening_prompt,
    build_world,
    run_behaviour_case,
)
from assistant.eval.dataset import PaymentMethodSpec  # noqa: E402


def scripted(*responses):
    """A FunctionModel that returns the given responses in order, then stops."""
    calls = {"n": 0}

    def fn(messages, info):
        i = calls["n"]
        calls["n"] += 1
        return responses[i] if i < len(responses) else ModelResponse(parts=[TextPart("ok")])

    return FunctionModel(fn)


SIMPLE_CASE = BehaviourCase(
    id="simple",
    why="runner smoke test",
    world=World(
        categories=("Alimentacao",),
        payment_methods=(PaymentMethodSpec(name="Pix", type="pix"),),
    ),
    opening="text",
    turns=("Gastei 10 reais no mercado hoje, no pix.",),
    today=date(2026, 6, 12),
    expected_entries=(
        ExpectedEntry(category="Alimentacao", amount=Decimal("10.00")),
    ),
    expected_total=Decimal("10.00"),
)


@pytest.mark.django_db
def test_build_world_seeds_exactly_the_declared_catalogue(household, user):
    from finances.models import Category, PaymentMethod

    build_world(SIMPLE_CASE, household, user)
    assert list(Category.objects.for_household(household).values_list("name", flat=True)) == [
        "Alimentacao"
    ]
    assert list(
        PaymentMethod.objects.for_household(household).values_list("name", flat=True)
    ) == ["Pix"]


@pytest.mark.django_db
def test_build_world_seeds_no_memory_rules(household, user):
    """Plan decision D-B — a personalised score is not a baseline."""
    from assistant.models import MemoryRule

    for case in load_behaviour_cases():
        build_world(case, household, user)
    assert MemoryRule.objects.for_household(household).count() == 0


@pytest.mark.django_db
def test_a_receipt_opening_uses_the_production_prompt(household, user):
    from assistant.agents.scope import AgentScope

    (case,) = load_behaviour_cases(["americanas-split-on-request"])
    build_world(case, household, user)
    prompt = build_opening_prompt(case, AgentScope(household=household, user=user))
    assert "propose_receipt" in prompt
    assert "SOUTIEN TOP B+ TAF21 BRANCO GG" in prompt


@pytest.mark.django_db
def test_a_duplicate_opening_uses_the_production_directive(household, user):
    from assistant.agents.scope import AgentScope

    (case,) = load_behaviour_cases(["refuses-to-double-register-a-known-receipt"])
    build_world(case, household, user)
    prompt = build_opening_prompt(case, AgentScope(household=household, user=user))
    assert "JÁ REGISTRADO" in prompt


@pytest.mark.django_db(transaction=True)
def test_run_behaviour_case_returns_only_the_rows_the_run_created(household, user):
    from asgiref.sync import async_to_sync

    build_world(SIMPLE_CASE, household, user)
    model = scripted(
        ModelResponse(
            parts=[
                ToolCallPart(
                    "register_entry",
                    {
                        "date": "2026-06-12",
                        "amount": "10.00",
                        "description": "Mercado",
                        "category_name": "Alimentacao",
                        "payment_method_name": "Pix",
                    },
                )
            ]
        ),
        ModelResponse(parts=[TextPart("Registrei.")]),
    )
    run = async_to_sync(run_behaviour_case)(SIMPLE_CASE, model, household, user)
    assert run.error == ""
    assert len(run.rows) == 1
    assert run.rows[0].amount == Decimal("10.00")
    assert run.rows[0].category == "Alimentacao"
    assert score_ledger(SIMPLE_CASE, run.rows).passed is True


@pytest.mark.django_db(transaction=True)
def test_pre_existing_entries_are_excluded_from_the_snapshot(household, user):
    """The duplicate case seeds an entry BEFORE the turn; scoring it as
    'created by this run' would make the refusal case impossible to pass."""
    from asgiref.sync import async_to_sync

    (case,) = load_behaviour_cases(["refuses-to-double-register-a-known-receipt"])
    build_world(case, household, user)
    run = async_to_sync(run_behaviour_case)(
        case, scripted(ModelResponse(parts=[TextPart("Ja registrado.")])), household, user
    )
    assert run.rows == []
    assert score_ledger(case, run.rows).passed is True
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_runners.py -q
```

Expected: `ModuleNotFoundError: No module named 'assistant.eval.behaviour_runner'`.

- [ ] **Step 3: Implement**

Create `src/backend/assistant/eval/behaviour_runner.py`:

```python
"""Drive the real assistant agent through a behavioural case and read the ledger.

The agent under test is `assistant.agents.assistant.assistant_agent` itself,
with its real tools and real prompt — anything less would test a copy of the
product rather than the product.

The clock is pinned per case (`case.today`) because billing-month judgment is
the point of half of them, and `build_date_instructions` injects the real date
into every run. ``time_machine`` is a dev dependency, imported lazily so that
importing this module never drags it into a production import graph.
"""

import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time

from asgiref.sync import sync_to_async
from django.utils import timezone

from assistant.agents.assistant import assistant_agent
from assistant.agents.scope import AgentScope
from assistant.eval.behaviour import BehaviourCase, LedgerRow


def build_world(case: BehaviourCase, household, user) -> None:
    """Create exactly what the case declares. Idempotent per household."""
    from assistant.models import ReceiptDraft, ReceiptDraftStatus
    from finances.models import Category, Entry, PaymentMethod

    categories: dict[str, Category] = {}
    for name in case.world.categories:
        categories[name], _ = Category.objects.get_or_create(
            household=household, name=name, defaults={"created_by": user}
        )
    methods: dict[str, PaymentMethod] = {}
    for spec in case.world.payment_methods:
        methods[spec.name], _ = PaymentMethod.objects.get_or_create(
            household=household,
            name=spec.name,
            defaults={
                "created_by": user,
                "type": spec.type,
                "closing_day": spec.closing_day,
            },
        )

    for raw in case.world.existing_entries:
        Entry.objects.create(
            household=household,
            created_by=user,
            date=date.fromisoformat(raw["date"]),
            amount=raw["amount"],
            description=raw["description"],
            category=categories[raw["category"]],
            payment_method=methods[raw["payment_method"]],
        )

    if case.world.registered_receipt is not None:
        ReceiptDraft.objects.create(
            household=household,
            created_by=user,
            payload=case.world.registered_receipt,
            status=ReceiptDraftStatus.REGISTERED,
        )
    if case.world.receipt_payload is not None:
        ReceiptDraft.objects.create(
            household=household,
            created_by=user,
            payload=case.world.receipt_payload,
            status=ReceiptDraftStatus.PENDING,
        )


def build_opening_prompt(case: BehaviourCase, scope) -> str:
    """The first prompt, built the way production builds it for that entry point."""
    from assistant.agents.extraction import (
        ReceiptExtraction,
        extraction_to_prompt,
        receipt_needs_review,
    )
    from assistant.agents.tools import (
        build_duplicate_receipt_directive,
        find_registered_duplicate,
    )
    from django.conf import settings

    if case.opening == "text":
        return case.turns[0]

    if case.opening == "receipt":
        ext = ReceiptExtraction(**case.world.receipt_payload)
        needs_review = receipt_needs_review(ext, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
        return extraction_to_prompt(ext, "", needs_review=needs_review)

    payload = case.world.registered_receipt
    dup = find_registered_duplicate(scope, payload)
    if dup is None:
        raise RuntimeError(
            f"{case.id}: the duplicate opening needs a REGISTERED draft that "
            "find_registered_duplicate can match — check World.registered_receipt "
            "and World.existing_entries."
        )
    return build_duplicate_receipt_directive(scope, payload, dup)


def _entry_ids(household) -> set:
    from finances.models import Entry

    return set(Entry.objects.for_household(household).values_list("id", flat=True))


def snapshot_ledger(household, before: set) -> list[LedgerRow]:
    """Rows that did not exist before the run, oldest first."""
    from finances.models import Entry

    qs = (
        Entry.objects.for_household(household)
        .exclude(id__in=before)
        .select_related("category", "payment_method")
        .order_by("created_at")
    )
    return [
        LedgerRow(
            category=e.category.name,
            amount=e.amount,
            billing_month=e.billing_month,
            payment_method=e.payment_method.name,
            description=e.description,
        )
        for e in qs
    ]


@dataclass(frozen=True)
class BehaviourRun:
    case_id: str
    rows: list[LedgerRow]
    usages: list[object]
    latency_ms: int
    error: str


async def run_behaviour_case(case: BehaviourCase, model, household, user) -> BehaviourRun:
    """Run every turn of one case and return the rows it created.

    Turns after the first are only sent while the agent is still answering; a
    run that errors stops there rather than replaying a broken conversation.
    """
    import time_machine  # dev dependency; see the module docstring

    scope = AgentScope(household=household, user=user)
    before = await sync_to_async(_entry_ids)(household)
    opening = await sync_to_async(build_opening_prompt)(case, scope)
    prompts = [opening, *(case.turns if case.opening != "text" else case.turns[1:])]

    usages: list[object] = []
    history = None
    error = ""
    started = time.perf_counter()
    destination = timezone.make_aware(datetime.combine(case.today, clock_time(12, 0)))
    with time_machine.travel(destination, tick=True):
        for prompt in prompts:
            try:
                result = await assistant_agent.run(
                    prompt, deps=scope, message_history=history, model=model
                )
            except Exception as exc:  # noqa: BLE001 - a failed turn is data
                error = f"{type(exc).__name__}: {exc}"
                break
            usages.append(result.usage())
            history = result.all_messages()

    rows = await sync_to_async(snapshot_ledger)(household, before)
    return BehaviourRun(
        case_id=case.id,
        rows=rows,
        usages=usages,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_runners.py -q
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/backend/assistant/ && uv run ruff format src/backend/assistant/eval/
git add src/backend/assistant/eval/behaviour_runner.py \
        src/backend/assistant/tests/test_eval_runners.py
git commit -m "feat(eval): behavioural runner driving the real agent, scored on the ledger"
```

---

## Task 7: The report — a diffable comparison table

**Files:**
- Create: `src/backend/assistant/eval/report.py`
- Test: `src/backend/assistant/tests/test_eval_report.py`

**Interfaces:**
- Consumes: `assistant.eval.scoring`, `assistant.eval.costing`, `assistant.eval.behaviour`, `assistant.eval.extraction_runner.RawRun`, `assistant.eval.behaviour_runner.BehaviourRun`.
- Produces:
  - `ModelReport` (frozen dataclass): `model: str`, `suite: str`, `n: int`, `overall: float`, `dimensions: dict[str, float]`, `totals: CostTotals`, `failures: tuple[str, ...]`
  - `build_extraction_report(model: str, cases, runs) -> ModelReport`
  - `build_behaviour_report(model: str, cases, runs) -> ModelReport`
  - `render_markdown(reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()) -> str`
  - `render_json(reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()) -> str`

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_report.py`:

```python
"""The comparison table: one row per model, diffable over time."""

import json
from decimal import Decimal

import pytest
from pydantic_ai.models.test import TestModel

from assistant.eval.costing import CallCost
from assistant.eval.dataset import load_receipt_cases
from assistant.eval.extraction_runner import RawRun
from assistant.eval.report import (
    ModelReport,
    build_extraction_report,
    render_json,
    render_markdown,
)

GOOD_READ = {
    "store": "Lojas Americanas",
    "date": "2026-06-12",
    "discount": "3.99",
    "amount_paid": "42.16",
    "confidence": 0.9,
    "items": [
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "9.99",
         "category": "Roupa"},
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99",
         "category": "Lanche"},
        {"description": "LAYS CLASSICA B&G ELMA CHIPS M", "line_total": "9.99",
         "category": "Lanche"},
        {"description": "WAFER MAIS AMENDOIM 102G HERSHEYS", "line_total": "6.19",
         "category": "Lanche"},
        {"description": "BATATA PRINGLES CREME E CEBOLA 109G", "line_total": "9.99",
         "category": "Lanche"},
    ],
}


@pytest.mark.anyio
async def test_build_extraction_report_scores_and_prices_every_run():
    from assistant.eval.extraction_runner import run_extraction_case

    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = await run_extraction_case(case, TestModel(custom_output_args=GOOD_READ))
    report = build_extraction_report("fake:model", [case], [run])
    assert report.model == "fake:model"
    assert report.suite == "extraction"
    assert report.n == 1
    assert report.overall == 1.0
    assert report.dimensions["money_ok_rate"] == 1.0
    assert report.totals.calls == 1


def test_a_run_that_errored_is_reported_as_a_failure_not_dropped():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    run = RawRun(case.id, None, None, 120, "RuntimeError: provider exploded")
    report = build_extraction_report("fake:model", [case], [run])
    assert report.n == 1
    assert report.overall == 0.0
    assert any("provider exploded" in f for f in report.failures)
    assert report.totals.unpriced_calls == 1


def sample_report(model="a", overall=0.9):
    from assistant.eval.costing import total

    return ModelReport(
        model=model,
        suite="extraction",
        n=2,
        overall=overall,
        dimensions={"money_ok_rate": 1.0, "item_recall": 0.95},
        totals=total([CallCost(model, 1000, 200, 4000, Decimal("0.010000"))]),
        failures=(),
    )


def test_markdown_has_one_row_per_model_with_cost_and_latency():
    md = render_markdown(
        [sample_report("openai:gpt-5.4", 0.97), sample_report("openrouter:cheap", 0.61)],
        generated_at="2026-08-14T10:00:00-03:00",
    )
    assert "openai:gpt-5.4" in md and "openrouter:cheap" in md
    assert "0.97" in md and "0.61" in md
    assert "USD" in md
    assert "2026-08-14T10:00:00-03:00" in md


def test_markdown_names_skipped_cases_rather_than_hiding_them():
    md = render_markdown(
        [sample_report()], generated_at="t", skipped=["notas-2026-06-22"]
    )
    assert "notas-2026-06-22" in md
    assert "skipped" in md.lower()


def test_json_round_trips_and_is_stable_key_order():
    payload = render_json([sample_report()], generated_at="t")
    data = json.loads(payload)
    assert data["generated_at"] == "t"
    assert data["reports"][0]["model"] == "a"
    assert data["reports"][0]["totals"]["cost_usd"] == "0.010000"
    assert render_json([sample_report()], generated_at="t") == payload
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_report.py -q
```

Expected: `ModuleNotFoundError: No module named 'assistant.eval.report'`.

- [ ] **Step 3: Implement**

Create `src/backend/assistant/eval/report.py`:

```python
"""Turn raw runs into the comparison table the model decision is made from.

Written to a file as well as stdout so runs are diffable over time: the point of
a baseline is that next quarter's number can be subtracted from this one.

A case that errored is reported as a scored failure, never dropped. A dropped
failure makes a broken model look like a small dataset.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from assistant.eval.behaviour import BehaviourCase, score_ledger
from assistant.eval.costing import CostTotals, cost_of, total
from assistant.eval.dataset import ReceiptCase
from assistant.eval.scoring import aggregate_extraction, score_extraction


@dataclass(frozen=True)
class ModelReport:
    """One model, one suite, everything the comparison table shows."""

    model: str
    suite: str
    n: int
    overall: float
    dimensions: dict[str, float]
    totals: CostTotals
    failures: tuple[str, ...]


def build_extraction_report(model: str, cases: Sequence[ReceiptCase], runs) -> ModelReport:
    """Score every extraction run and price every call."""
    by_id = {c.id: c for c in cases}
    scores, costs, failures = [], [], []
    for run in runs:
        costs.append(cost_of(model, run.usage, run.latency_ms))
        if run.error or run.extraction is None:
            failures.append(f"{run.case_id}: {run.error or 'no output'}")
            continue
        score = score_extraction(by_id[run.case_id], run.extraction)
        scores.append(score)
        if score.overall < 1.0:
            detail = []
            if not score.money_ok:
                detail.append("money invariant FAILED")
            if score.missed:
                detail.append(f"missed {len(score.missed)}")
            if score.spurious:
                detail.append(f"spurious {len(score.spurious)}")
            failures.append(f"{run.case_id}: {', '.join(detail) or 'partial'}")

    agg = aggregate_extraction(scores)
    n = len(runs)
    # Errored runs score zero and still count, so the denominator is every case
    # attempted rather than only the ones that came back.
    overall = round(agg.overall * len(scores) / n, 6) if n else 0.0
    return ModelReport(
        model=model,
        suite="extraction",
        n=n,
        overall=overall,
        dimensions={
            "money_ok_rate": agg.money_ok_rate,
            "item_recall": agg.item_recall,
            "item_precision": agg.item_precision,
            "amount_accuracy": agg.amount_accuracy,
            "category_accuracy": agg.category_accuracy,
            "store_accuracy": agg.store_accuracy,
            "date_accuracy": agg.date_accuracy,
        },
        totals=total(costs),
        failures=tuple(failures),
    )


def build_behaviour_report(model: str, cases: Sequence[BehaviourCase], runs) -> ModelReport:
    """Score every behavioural run against its expected ledger."""
    by_id = {c.id: c for c in cases}
    scores, costs, failures = [], [], []
    for run in runs:
        for usage in run.usages or [None]:
            costs.append(cost_of(model, usage, 0))
        costs.append(cost_of(model, None, run.latency_ms))
        if run.error:
            failures.append(f"{run.case_id}: {run.error}")
            scores.append(0.0)
            continue
        score = score_ledger(by_id[run.case_id], run.rows)
        scores.append(score.score)
        if not score.passed:
            failures.append(f"{run.case_id}: {'; '.join(score.errors)}")

    n = len(runs)
    return ModelReport(
        model=model,
        suite="behaviour",
        n=n,
        overall=round(sum(scores) / n, 6) if n else 0.0,
        dimensions={"cases_passed": float(sum(1 for s in scores if s == 1.0))},
        totals=total(costs),
        failures=tuple(failures),
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def render_markdown(
    reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()
) -> str:
    """The human-readable comparison. One table per suite."""
    lines = [
        "# Model evaluation (E08)",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    if skipped:
        lines += [
            f"> **{len(skipped)} case(s) skipped** — image not found. Set "
            "`EVAL_FIXTURES_DIR` (see `docs/eval-dataset.md`): "
            + ", ".join(skipped),
            "",
        ]
    for suite in ("extraction", "behaviour"):
        rows = [r for r in reports if r.suite == suite]
        if not rows:
            continue
        keys = sorted({k for r in rows for k in r.dimensions})
        header = ["Model", "n", "Score", *keys, "In tok", "Out tok", "USD", "Avg ms"]
        lines += [
            f"## {suite.capitalize()}",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "---|" * len(header),
        ]
        for r in sorted(rows, key=lambda r: -r.overall):
            cells = [
                f"`{r.model}`",
                str(r.n),
                _fmt(r.overall),
                *[_fmt(r.dimensions.get(k, 0.0)) for k in keys],
                str(r.totals.input_tokens),
                str(r.totals.output_tokens),
                f"{r.totals.cost_usd}",
                str(r.totals.avg_latency_ms),
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        unpriced = sum(r.totals.unpriced_calls for r in rows)
        if unpriced:
            lines += [
                f"> {unpriced} call(s) had no `ModelPrice` row and are **not** "
                "included in the USD column. Seed a price before comparing on cost.",
                "",
            ]
        for r in rows:
            if r.failures:
                lines += [f"### `{r.model}` — what it got wrong", ""]
                lines += [f"- {f}" for f in r.failures]
                lines.append("")
    return "\n".join(lines)


def render_json(
    reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()
) -> str:
    """The machine-readable twin, for diffing runs across months."""

    def encode(value):
        return str(value) if isinstance(value, Decimal) else value

    payload = {
        "generated_at": generated_at,
        "skipped": list(skipped),
        "reports": [
            {
                "model": r.model,
                "suite": r.suite,
                "n": r.n,
                "overall": r.overall,
                "dimensions": r.dimensions,
                "totals": {
                    "calls": r.totals.calls,
                    "input_tokens": r.totals.input_tokens,
                    "output_tokens": r.totals.output_tokens,
                    "cost_usd": encode(r.totals.cost_usd),
                    "unpriced_calls": r.totals.unpriced_calls,
                    "avg_latency_ms": r.totals.avg_latency_ms,
                },
                "failures": list(r.failures),
            }
            for r in reports
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
```

- [ ] **Step 4: Run and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_report.py -q
uv run ruff check src/backend/assistant/eval/ && uv run ruff format src/backend/assistant/eval/
git add src/backend/assistant/eval/report.py src/backend/assistant/tests/test_eval_report.py
git commit -m "feat(eval): diffable markdown + JSON comparison report"
```

Expected: 6 passed. Remove the unused `score_extraction` import if ruff flags it.

---

## Task 8: The `eval_models` command

One documented command, gated, and safe to point at any database.

**Files:**
- Create: `src/backend/assistant/management/commands/eval_models.py`
- Test: `src/backend/assistant/tests/test_eval_command.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: everything above.
- Produces: `python manage.py eval_models --models <csv> [--suite extraction|behaviour|both] [--cases <csv>] [--out <path>]`

**Safety contract, all three of which the tests assert:**
1. Refuses to run without `RUN_LLM_TESTS=1`.
2. Every database write happens inside `transaction.atomic()` and is **always rolled back** — the throwaway household never survives the command, on any database.
3. The event loop is started with `asgiref.sync.async_to_sync`, never `asyncio.run` (Orientation note 6).

---

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_eval_command.py`:

```python
"""The one documented command. Gated, and safe against any database."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command


@pytest.fixture
def llm_enabled(monkeypatch):
    monkeypatch.setenv("RUN_LLM_TESTS", "1")


@pytest.mark.django_db
def test_refuses_to_run_without_the_env_flag(monkeypatch):
    monkeypatch.delenv("RUN_LLM_TESTS", raising=False)
    with pytest.raises(CommandError, match="RUN_LLM_TESTS"):
        call_command("eval_models", "--models", "fake:model")


@pytest.mark.django_db
def test_requires_at_least_one_model(llm_enabled):
    with pytest.raises(CommandError, match="--models"):
        call_command("eval_models", "--models", "")


@pytest.mark.django_db
def test_an_unknown_case_id_fails_loudly(llm_enabled):
    with pytest.raises(CommandError, match="unknown case"):
        call_command("eval_models", "--models", "fake:m", "--cases", "nope")


@pytest.mark.django_db(transaction=True)
def test_a_dry_run_scores_the_stub_model_and_writes_the_report(llm_enabled, tmp_path):
    out = tmp_path / "report.md"
    buf = StringIO()
    call_command(
        "eval_models",
        "--models", "fake:model",
        "--suite", "both",
        "--stub",
        "--out", str(out),
        stdout=buf,
    )
    assert out.exists()
    text = out.read_text()
    assert "fake:model" in text and "Extraction" in text
    assert out.with_suffix(".json").exists()
    data = json.loads(out.with_suffix(".json").read_text())
    assert {r["suite"] for r in data["reports"]} == {"extraction", "behaviour"}


@pytest.mark.django_db(transaction=True)
def test_the_run_leaves_no_rows_behind(llm_enabled, tmp_path):
    """The throwaway household is rolled back on ANY database, always."""
    from accounts.models import Household
    from finances.models import Entry

    before_h, before_e = Household.objects.count(), Entry.objects.count()
    call_command(
        "eval_models", "--models", "fake:model", "--suite", "both", "--stub",
        "--out", str(tmp_path / "r.md"), stdout=StringIO(),
    )
    assert Household.objects.count() == before_h
    assert Entry.objects.count() == before_e


@pytest.mark.django_db(transaction=True)
def test_missing_images_are_reported_as_skipped_not_as_failures(
    llm_enabled, tmp_path, settings
):
    settings.EVAL_FIXTURES_DIR = str(tmp_path / "absent")
    buf = StringIO()
    call_command(
        "eval_models", "--models", "fake:model", "--suite", "extraction", "--stub",
        "--out", str(tmp_path / "r.md"), stdout=buf,
    )
    assert "skip" in buf.getvalue().lower()
```

- [ ] **Step 2: Run to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_command.py -q
```

Expected: `CommandError: Unknown command: 'eval_models'`.

- [ ] **Step 3: Implement**

Create `src/backend/assistant/management/commands/eval_models.py`:

```python
"""Score one or more models against the golden dataset. E08 S08-4.

    RUN_LLM_TESTS=1 uv run python src/backend/manage.py eval_models \\
        --models "openai:gpt-5.4" --suite both --out docs/superpowers/evidence/eval/baseline.md

This command SPENDS MONEY. It is gated on `RUN_LLM_TESTS=1` for the same reason
the real-LLM tests are, and it never runs in normal CI.

Everything it writes to the database is rolled back. The behavioural suite needs
a household with a real catalogue, and a harness that leaves debris in whatever
database it was pointed at is a harness nobody dares run twice.
"""

import os
from datetime import UTC, datetime

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from assistant.eval.behaviour import load_behaviour_cases
from assistant.eval.behaviour_runner import build_world, run_behaviour_case
from assistant.eval.dataset import DatasetError, available_receipt_cases
from assistant.eval.extraction_runner import run_extraction_suite
from assistant.eval.report import (
    build_behaviour_report,
    build_extraction_report,
    render_json,
    render_markdown,
)

STUB_READ = {
    "store": "Loja Stub",
    "date": "2026-06-12",
    "discount": "0",
    "amount_paid": "1.00",
    "confidence": 0.5,
    "items": [{"description": "item", "line_total": "1.00", "category": None}],
}


class _Rollback(Exception):
    """Raised to unwind the atomic block. Never propagates out of `handle`."""


class Command(BaseCommand):
    help = "Score models against the E08 golden dataset. Costs money; needs RUN_LLM_TESTS=1."

    def add_arguments(self, parser):
        parser.add_argument("--models", required=True, help="Comma-separated model strings.")
        parser.add_argument(
            "--suite", choices=["extraction", "behaviour", "both"], default="both"
        )
        parser.add_argument("--cases", default="", help="Comma-separated case ids.")
        parser.add_argument("--out", default="", help="Markdown path; JSON gets the same stem.")
        parser.add_argument(
            "--stub",
            action="store_true",
            help="Use TestModel instead of a provider. For testing the harness itself.",
        )

    def handle(self, *args, **opts):
        if os.environ.get("RUN_LLM_TESTS") != "1":
            raise CommandError(
                "This command calls real models and costs money. "
                "Re-run with RUN_LLM_TESTS=1 once you mean it."
            )
        models = [m.strip() for m in opts["models"].split(",") if m.strip()]
        if not models:
            raise CommandError("--models needs at least one model string.")

        ids = [c.strip() for c in opts["cases"].split(",") if c.strip()] or None
        suite = opts["suite"]
        reports, skipped = [], []

        try:
            with transaction.atomic():
                reports, skipped = self._run(models, suite, ids, stub=opts["stub"])
                raise _Rollback
        except _Rollback:
            pass
        except DatasetError as exc:
            raise CommandError(str(exc)) from exc
        except ValueError as exc:  # unknown behaviour case id
            raise CommandError(f"unknown case: {exc}") from exc

        generated_at = timezone.localtime(datetime.now(UTC)).isoformat(timespec="seconds")
        markdown = render_markdown(reports, generated_at=generated_at, skipped=skipped)
        self.stdout.write(markdown)

        out = (opts["out"] or "").strip()
        if out:
            from pathlib import Path

            md_path = Path(out)
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(markdown, encoding="utf-8")
            json_path = md_path.with_suffix(".json")
            json_path.write_text(
                render_json(reports, generated_at=generated_at, skipped=skipped),
                encoding="utf-8",
            )
            self.stdout.write(f"\nWrote {md_path} and {json_path}")

    # ── internals ───────────────────────────────────────────────────────────

    def _model_for(self, name, stub):
        if not stub:
            return name
        from pydantic_ai.models.test import TestModel

        return TestModel(custom_output_args=STUB_READ, call_tools=[])

    def _run(self, models, suite, ids, *, stub):
        reports, skipped = [], []
        if suite in ("extraction", "both"):
            cases, skipped = available_receipt_cases(ids)
            if skipped:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {len(skipped)} case(s) with no image on disk: "
                        + ", ".join(skipped)
                        + "\nSet EVAL_FIXTURES_DIR — see docs/eval-dataset.md."
                    )
                )
            for name in models:
                self.stdout.write(f"extraction · {name} · {len(cases)} case(s)…")
                runs = async_to_sync(run_extraction_suite)(
                    cases, self._model_for(name, stub)
                )
                reports.append(build_extraction_report(name, cases, runs))

        if suite in ("behaviour", "both"):
            cases = load_behaviour_cases(ids)
            for name in models:
                self.stdout.write(f"behaviour · {name} · {len(cases)} case(s)…")
                runs = []
                for case in cases:
                    household, user = self._throwaway(case.id, name)
                    build_world(case, household, user)
                    runs.append(
                        async_to_sync(run_behaviour_case)(
                            case, self._model_for(name, stub), household, user
                        )
                    )
                reports.append(build_behaviour_report(name, cases, runs))

        return reports, skipped

    def _throwaway(self, case_id, model_name):
        """A fresh household per case, so one case cannot see another's rows.

        Rolled back with everything else. The suffix keeps the unique email
        constraint happy when the same case runs against several models.
        """
        from accounts.models import Household, Membership, Role
        from core.models import CustomUser

        slug = f"{case_id}-{abs(hash(model_name)) % 10**6}"
        household = Household.objects.create(name=f"eval-{slug}")
        user = CustomUser.objects.create(
            username=f"eval-{slug}", email=f"eval-{slug}@example.invalid"
        )
        Membership.objects.create(user=user, household=household, role=Role.OWNER)
        return household, user
```

Add to `.gitignore`:

```
# E08 scratch eval runs. The committed baseline lives at
# docs/superpowers/evidence/eval/baseline-*.{md,json} and is added explicitly.
docs/superpowers/evidence/eval/scratch-*
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_command.py -q
```

Expected: 6 passed. If `test_the_run_leaves_no_rows_behind` fails, the atomic block is not wrapping `_run` — fix that before moving on; it is the one guarantee that makes this command safe to point at a real database.

- [ ] **Step 5: Full suite and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80

git add src/backend/assistant/management/commands/eval_models.py \
        src/backend/assistant/tests/test_eval_command.py .gitignore
git commit -m "feat(eval): eval_models command — gated, rolled back, writes a diffable report"
```

---

## Task 9: Curate the remaining eight receipt cases

The expensive part, and the part that must be right. This is data entry with a machine-checked gate, not code.

**Files:**
- Create: `src/backend/assistant/eval/cases/*.json` (8 new files)
- Create: `docs/eval-dataset.md`
- Test: covered by `test_eval_dataset.py` (arithmetic gate already written in Task 1)

**Source images** (all currently untracked, none gitignored — do **not** `git add` any of them):

| Source | File |
|---|---|
| `assistant/tests/fixtures/` (already tracked) | `receipt_mercadolivre_desconto.png` |
| `docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/` | `IMG_20260612_174310143_HDR.jpg`, `IMG_20260615_072007792_HDR.jpg`, `IMG_20260619_083106209.jpg`, `IMG_20260619_204123336.jpg`, `IMG_20260708_180705067_HDR.jpg` |
| `docs/notas/` | `IMG_20260622_191443851_HDR.jpg`, `IMG_20260622_191450110_HDR.jpg` |

That is 1 tracked + 7 private = 8 new cases, bringing the dataset to **10**, which is the DoD floor.

---

- [ ] **Step 1: Create the private fixtures directory and copy the seven photos**

```bash
mkdir -p ~/ledger-eval-fixtures
cp docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/*.jpg ~/ledger-eval-fixtures/
cp docs/notas/*.jpg ~/ledger-eval-fixtures/
ls -1 ~/ledger-eval-fixtures/
```

Add to your local `.env` (which is gitignored):

```
EVAL_FIXTURES_DIR=/home/bessa/ledger-eval-fixtures
```

- [ ] **Step 2: Confirm none of the photos is about to be committed**

```bash
git status --porcelain docs/notas docs/.ai | head
```

Expected: they appear as `??` (untracked) and must stay that way. If any shows as staged, unstage it — plan decision D-A.

- [ ] **Step 3: Transcribe each receipt into a case file**

For **each** of the 8 images, in turn:

1. Open the image with the Read tool and read it end to end.
2. Copy `src/backend/assistant/eval/cases/americanas-2026-06-12.json` to a new file named `<store-slug>-<YYYY-MM-DD>.json` and set `id` to the same slug.
3. Fill in every field:
   - `image_source`: `"tracked"` only for `receipt_mercadolivre_desconto.png`; `"private"` for the seven copied photos, with `image` set to the bare filename.
   - `media_type`: `"image/png"` for the Mercado Livre screenshot, `"image/jpeg"` for the photos.
   - `provenance`: one sentence — where the receipt came from and why it is in the set. For private images add: *"Not committed: real household receipt, public repository (plan decision D-A)."*
   - `hard_cases`: pick from `thermal-print`, `rotated`, `low-contrast`, `multi-category`, `discount`, `multi-unit-line`, `marketplace-order`, `long-receipt`, `already-registered`.
   - `store` verbatim from the header; `store_key` a lowercase substring any correct read must contain.
   - `categories`: the taxonomy this case is scored against (decision D-B). Include every category its items need and one or two plausible distractors.
   - `payment_methods`: usually `Credito C6` (closing_day 25), `Pix`, `Dinheiro`.
   - `items`: **every line on the receipt**, description exactly as printed, `line_total` the final charged amount for that line — never a unit price times a quantity you computed.
   - `discount` and `amount_paid` exactly as printed.
4. Run the gate immediately:

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_eval_dataset.py::test_every_committed_case_is_arithmetically_consistent -q
```

A failure here means the transcription is wrong, not that the tolerance is too tight. Re-read the image.

**Deliberate coverage.** Across the ten cases the set must span, and `hard_cases` must record, at minimum: a thermal print, a rotated or low-contrast photo, a multi-category receipt, a discounted multi-unit line (`receipt_mercadolivre_desconto.png` — the marketplace quantity bug), and one receipt that is also used as the already-registered case. If a hard case has no photo, say so in `docs/eval-dataset.md` rather than inventing one.

- [ ] **Step 4: Write the provenance document**

Create `docs/eval-dataset.md`:

```markdown
# The E08 golden dataset

Ground truth for every scored receipt lives in `src/backend/assistant/eval/cases/*.json`
and **is committed**. The receipt **photos are not**.

## Why the images are not in the repository

`bessavagner/expense_tracker_v2` is a public repository, and these are real
household receipts: they carry a CNPJ, a card's last four digits, dates, and a
list of what someone bought. Three fixtures under
`src/backend/assistant/tests/fixtures/` predate this decision and stay where they
are — deleting them would not un-publish them. Nothing new joins them.

## Running the harness with the images

    mkdir -p ~/ledger-eval-fixtures
    # copy the photos named by `image` in the case files into it
    echo 'EVAL_FIXTURES_DIR=/home/bessa/ledger-eval-fixtures' >> .env

Without it, cases marked `"image_source": "private"` are **skipped with a
warning**. A fresh clone and CI stay green; the comparison table names every
case it skipped so a partial run is never mistaken for a full one.

## Adding a case

1. Put the photo in `$EVAL_FIXTURES_DIR`.
2. Copy an existing case file and fill in every field. Transcribe **every** line;
   `line_total` is the amount actually charged for that line, never a unit price
   you multiplied yourself.
3. Run the gate:

       POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q

   `test_every_committed_case_is_arithmetically_consistent` requires
   `sum(line_total) - discount == amount_paid` exactly. It is the only automatic
   defence against a typo, and a wrong gabarito silently teaches the harness to
   prefer a worse model.
4. Never `git add` the photo.

## What the set deliberately covers

| Hard case | Why it is in the set |
|---|---|
| `thermal-print` | Faded thermal paper is the common real input. |
| `rotated` / `low-contrast` | Phone photos are not scans. |
| `multi-category` | Where a weaker model merges categories and loses money. |
| `discount` | The discount is re-derived and prorated, not read. |
| `multi-unit-line` | The Mercado Livre bug: a 2-unit line priced as a total. |
| `already-registered` | The PAGUE MENOS duplicate incident. |

## Categories and memory

Each case declares its own `categories` and `payment_methods`, and the harness
seeds exactly those. It never seeds a `MemoryRule`. A score that moves when the
operator's personal rules change is not a baseline; memory-driven resolution
stays covered by `test_category_memory.py` and `test_memory_tools.py`.
```

- [ ] **Step 5: Verify the dataset is complete and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q
uv run python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import sys; sys.path.insert(0,'src/backend'); django.setup()
from assistant.eval.dataset import load_receipt_cases
cases = load_receipt_cases()
print(len(cases), 'cases')
print(sorted({h for c in cases for h in c.hard_cases}))
"
git status --porcelain | grep -E '\.(jpg|png)$' || echo "no images staged — correct"
git add src/backend/assistant/eval/cases/ docs/eval-dataset.md
git commit -m "feat(eval): curate the golden dataset to ten cases, with provenance"
```

Expected: `10 cases`, and the hard-case list covers thermal print, rotation/contrast, multi-category, discount, multi-unit line and already-registered.

---

## Task 10: The manually-triggered CI workflow

**Files:**
- Create: `.github/workflows/eval.yml`

**Interfaces:**
- Consumes: the `eval_models` command.
- Produces: a `workflow_dispatch` job that uploads the report as an artifact. Never runs on push, pull request, or schedule.

---

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/eval.yml`:

```yaml
# E08 S08-5. Manual only — this job calls real models and spends real money.
# There is deliberately no `push`, `pull_request` or `schedule` trigger: the
# epic's "Out of scope" says automated per-PR evaluation is cost-prohibitive.
#
# Only the tracked fixtures are reachable here. The private photos are not in
# the repository (docs/eval-dataset.md), so this run reports the rest as skipped
# and its numbers are a SUBSET of a local run. The baseline in
# docs/superpowers/evidence/eval/ is produced locally, on the full dataset.
name: Model evaluation

on:
  workflow_dispatch:
    inputs:
      models:
        description: "Comma-separated model strings, e.g. openai:gpt-5.4,openrouter:qwen/qwen3.7-flash"
        required: true
      suite:
        description: "Which suite to run"
        required: true
        default: both
        type: choice
        options: [extraction, behaviour, both]

jobs:
  evaluate:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: expense_tracker_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      POSTGRES_DB: expense_tracker_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      SECRET_KEY: test-secret-key
      DEBUG: "true"
      RUN_LLM_TESTS: "1"
      LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.12
      - run: uv sync

      # `migrate`, not the test runner: the command needs a real database with
      # the seeded ModelPrice rows, or every cost cell comes back unpriced.
      - name: Prepare the database
        run: uv run python src/backend/manage.py migrate

      - name: Evaluate
        run: |
          uv run python src/backend/manage.py eval_models \
            --models "${{ inputs.models }}" \
            --suite "${{ inputs.suite }}" \
            --out eval-report.md

      - uses: actions/upload-artifact@v4
        with:
          name: eval-report
          path: |
            eval-report.md
            eval-report.json
```

- [ ] **Step 2: Verify it does not affect normal CI**

```bash
uv run python -c "
import yaml, pathlib
wf = yaml.safe_load(pathlib.Path('.github/workflows/eval.yml').read_text())
triggers = wf[True] if True in wf else wf['on']
assert set(triggers) == {'workflow_dispatch'}, triggers
print('manual only — ok')
"
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

Expected: `manual only — ok`, and the suite still passes with unchanged runtime.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/eval.yml
git commit -m "ci(eval): manually-triggered model evaluation workflow"
```

---

## Task 11: Establish the baseline and document it

The deliverable of the whole epic: a number for the **current production models**, which every future model is judged against.

**Files:**
- Create: `docs/superpowers/evidence/eval/baseline-2026-08-14.md` and `.json`
- Modify: `docs/runbook.md` (new section before `### Known gap: transcription cost is null`)
- Modify: `README.md` and `AGENTS.md` (one-line pointer each, if `AGENTS.md` exists)

---

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

Any `None` means that model's calls will land in the "unpriced" count and its USD cell will be wrong. Seed a `ModelPrice` row first — from the provider's **live** pricing page, with `source_url` and `checked_on` filled in (Global Constraint 15).

- [ ] **Step 2: Run the extraction baseline**

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 uv run python src/backend/manage.py eval_models \
  --models "openai:gpt-5.4" \
  --suite extraction \
  --out docs/superpowers/evidence/eval/baseline-2026-08-14.md
```

Read the output before continuing. If `money_ok_rate` is below 1.0 on a case whose gabarito you hand-checked, **the gabarito is the first suspect** — a scored failure on a receipt the product reads correctly today means the ground truth is wrong. Fix it and re-run.

- [ ] **Step 3: Run the behavioural baseline and merge it into the same report**

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 uv run python src/backend/manage.py eval_models \
  --models "openai:gpt-5.4" \
  --suite both \
  --out docs/superpowers/evidence/eval/baseline-2026-08-14.md
```

- [ ] **Step 4: Sanity-check the run against the safety contract**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from accounts.models import Household
print('eval households left behind:', Household.objects.filter(name__startswith='eval-').count())
"
```

Expected: `0`. Anything else means the rollback did not hold — stop and fix Task 8 before trusting any number in the report.

- [ ] **Step 5: Write the runbook section**

Insert into `docs/runbook.md`, immediately before `### Known gap: transcription cost is null`:

````markdown
## Evaluating a model (E08)

The question this answers is "can we ship on a cheaper model?", with a number
instead of an opinion. It does **not** change which model production uses —
that is E09.

### Run it

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 uv run python src/backend/manage.py eval_models \
  --models "openai:gpt-5.4,openrouter:qwen/qwen3.7-flash" \
  --suite both \
  --out docs/superpowers/evidence/eval/2026-08-14.md
```

- `--suite extraction` reads receipt photos and scores the read.
- `--suite behaviour` drives the real assistant through seven conversations and
  scores the **ledger rows** it produced.
- `--cases a,b` narrows to specific case ids while iterating.
- Without `RUN_LLM_TESTS=1` the command refuses. That is deliberate: it spends
  money.

### What it costs

One full `--suite both` run is 10 vision calls plus roughly 12 chat turns per
model. On `openai:gpt-5.4` that came to the figure in the `USD` column of
`docs/superpowers/evidence/eval/baseline-2026-08-14.md` — read it there rather
than from this sentence, which will rot. Multiply by the number of models in
`--models`. A cell showing `0` with a non-zero `unpriced` note means the model
has no `ModelPrice` row, not that it was free.

### Reading the output

| Column | What it means |
|---|---|
| `Score` | 0–1. Extraction: weighted across the dimensions. Behaviour: fraction of cases whose ledger was exactly right. |
| `money_ok_rate` | Fraction of receipts whose items reconciled with the amount paid. **A model below 1.0 here is disqualified regardless of the rest** — a case that fails it scores 0 overall. |
| `item_recall` | Lines the model found, over lines that exist. A miss is a missing expense. |
| `item_precision` | Lines the model found that are real. Low means invention. |
| `amount_accuracy` | Matched lines whose value was exactly right. |
| `category_accuracy` | Matched lines filed under the right category. |
| `cases_passed` | Behaviour only. Out of `n`. |
| `USD` | Priced calls only. Unpriced calls are counted in a note, never as zero. |

Under each table is a **"what it got wrong"** list naming every case that failed
and why. Read it — an aggregate of 0.85 built from one catastrophic case and
nine perfect ones is a different model from one that is uniformly mediocre.

If the report says cases were **skipped**, the private photos are missing. See
`docs/eval-dataset.md` and set `EVAL_FIXTURES_DIR`. A skipped case is never a
failure, but a run with skips is not comparable to one without.

### Safety

Everything the behavioural suite writes — households, users, categories,
entries, receipt drafts — happens inside a transaction that is **always** rolled
back, so the command is safe to point at any database. `test_eval_command.py`
asserts that; if you change the command, keep that test.

### Adding a case

`docs/eval-dataset.md`. Ground truth is committed, receipt photos are not.
````

- [ ] **Step 6: Add the pointers**

In `README.md`, in the quickstart, after the existing runbook pointer, add:

```markdown
- Comparing models before a swap: `docs/runbook.md` → *Evaluating a model (E08)*.
```

If `AGENTS.md` exists, add the same one-liner to its documentation index.

- [ ] **Step 7: Full verification and commit**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run

git add docs/superpowers/evidence/eval/baseline-2026-08-14.md \
        docs/superpowers/evidence/eval/baseline-2026-08-14.json \
        docs/runbook.md README.md
git commit -m "docs(eval): baseline comparison for the production models, plus the runbook"
```

- [ ] **Step 8: Close the epic**

Tick the Definition of Done boxes in `docs/backlog/E08-ai-evaluation-harness.md` and update its `status` to `done` in the frontmatter and in `docs/backlog/INDEX.md`. Paste the baseline table into the commit body as evidence.

```bash
git add docs/backlog/E08-ai-evaluation-harness.md docs/backlog/INDEX.md
git commit -m "docs(backlog): close E08 — evaluation harness with a scored baseline"
```

---

## Definition of Done — mapped to tasks

| DoD assertion | Task |
|---|---|
| Golden dataset ≥ 10 receipt cases with complete ground truth | 1, 9 |
| ≥ 6 behavioural cases, each asserting resulting ledger state | 4 (seven cases) |
| Comparison table for the **current production models** | 11 |
| Money invariant scored and weighted decisively | 2 |
| Scoring logic unit-tested deterministically without a model | 2, 3, 4, 7 |
| The `iteraction.txt` Americanas failure is a scored case | 4 (`americanas-split-on-request`) |
| Normal CI runtime unchanged | 8 (step 5), 10 (step 2) |
| `docs/runbook.md` documents the command, its cost, how to read it | 11 |
| Stays behind `RUN_LLM_TESTS=1`, never in normal CI | 8, 10 |
| Optional manually-triggered CI workflow | 10 |

## Open questions, resolved

| Epic question | Resolution |
|---|---|
| 1 — privacy of the untracked photos | **Decision D-A.** Private directory via `EVAL_FIXTURES_DIR`; ground truth committed, images never. The repository is public. |
| 2 — "good enough to ship" threshold | Deliberately not set. Establish the baseline (Task 11); E09 sets the threshold against it. |
| 3 — does category accuracy depend on the user's categories | **Decision D-B.** Fixed per-case taxonomy, no `MemoryRule`. A personalised score is not a baseline. |
| 4 — LLM-as-judge for behavioural cases | No. `score_ledger` asserts rows deterministically (Task 4). |
