# Projection What-If, Category Averages, Dashboard & Agent Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a session-based what-if projection simulator, per-category 3-month moving averages, an estimated saldo/acumulado track, a dashboard projection card, and a planner-agent tool — all sharing the existing projection engine.

**Architecture:** All financial math lives in deterministic services (`finances/services/`); the LLM only composes args and narrates. `build_projection` gains an optional `overlay` (hypothetical per-month deltas) and an estimated track. A new `whatif.py` defines the hypothetical primitives shared by the UI (session) and the agent tool.

**Tech Stack:** Django 5, HTMX + daisyUI/Tailwind templates, React islands (dashboard, untouched here), PydanticAI agents, pytest + model_bakery, pgvector container on :5433 for tests.

## Global Constraints

- **TDD, worktree, strict quality gates** — non-negotiable project rule. Every task is test-first.
- **Math in code, never in the LLM** — agents only narrate deterministic service output (`assistant/agents/analytics.py`).
- **Projection origin** = `DEFAULT_PROJECTION_ORIGIN = date(2025, 11, 1)`; `acumulado` anchors there.
- **Decimal everywhere**, quantize money to cents (`Decimal("0.01")`, `ROUND_HALF_UP`).
- **Refunds excluded** from spend stats via `amount > 0`.
- **Tests run** with `cd src/backend && uv run pytest <path> -v` (needs pgvector container on :5433).
- **Lint:** `cd src/backend && uv run ruff check <files>` must pass before each commit.
- **No new JS build dependency** for the dashboard card (server-rendered SVG).
- **Estimated track** uses **regular-only** category averages (avoid double-counting systemic/installments). Current incomplete month uses `max(actual_regular_this_month, average)` per category (Opção B).

---

## File structure

- `finances/services/whatif.py` (new) — `HypoType`, `HypotheticalItem`, `expand_hypotheticals`, `simulate_projection_summary`.
- `finances/services/category_stats.py` (new) — `category_moving_averages`, `category_moving_averages_named`.
- `finances/services/projection.py` (modify) — `overlay` param + estimated track fields.
- `finances/management/commands/recompute_category_averages.py` (new).
- `assistant/agents/analytics.py` (modify) — `detect_anomalies` wiring + `category_averages` wrapper.
- `assistant/agents/analyst.py` (modify) — `category_averages` tool.
- `assistant/agents/planner.py` (modify) — `simulate_projection` tool.
- `assistant/agents/orchestrator.py` (modify) — delegation hint.
- `finances/views/projection.py` (modify) — read session overlay; add/remove/clear views.
- `finances/views/dashboard.py` (modify) — projection card context.
- `finances/views/settings.py` (modify) — DRY categories context + averages.
- `finances/urls.py` (modify) — what-if routes.
- Templates: `projection/_whatif_panel.html` (new), `projection/projection_page.html` + `_projection_table.html` (modify), `dashboard/dashboard_page.html` (modify), `settings/_categories_tab.html` (modify).
- Tests: `finances/tests/test_whatif.py`, `test_category_stats.py`, `test_recompute_category_averages.py`, `test_projection_estimated.py`, additions to `test_projection_service.py`, `test_views_projection.py`, `test_views_settings.py`, dashboard view test; `assistant/tests/test_simulate_projection.py`, `test_category_averages_tool.py`.

---

## Task 1: whatif primitives — `HypotheticalItem` + `expand_hypotheticals`

**Files:**
- Create: `finances/services/whatif.py`
- Test: `finances/tests/test_whatif.py`

**Interfaces:**
- Produces:
  - `class HypoType(str, Enum)` with `EXPENSE_ONEOFF, EXPENSE_RECURRING, INCOME, INSTALLMENT, LOAN`.
  - `class HypotheticalItem(BaseModel)` fields: `id: str`, `type: HypoType`, `label: str = ""`, `amount: Decimal`, `month: date`, `end_month: date | None = None`, `n_installments: int | None = None`, `installment_amount: Decimal | None = None`.
  - `expand_hypotheticals(items: list[HypotheticalItem], span_months: list[date]) -> tuple[dict[tuple[date, str], Decimal], int]` — returns `(overlay, ignored_count)`. Keys: `(billing_month, kind)`, `kind ∈ {"income","regular","installment"}`.
  - `add_months(d: date, n: int) -> date` (public helper).

- [ ] **Step 1: Write the failing tests**

```python
# finances/tests/test_whatif.py
from datetime import date
from decimal import Decimal

from finances.services.whatif import (
    HypotheticalItem,
    HypoType,
    add_months,
    expand_hypotheticals,
)

SPAN = [date(2026, m, 1) for m in range(1, 13)]  # all of 2026


def _item(**kw):
    base = dict(id="x", type=HypoType.EXPENSE_ONEOFF, label="t", amount=Decimal("0"),
                month=date(2026, 3, 1))
    base.update(kw)
    return HypotheticalItem(**base)


def test_add_months_wraps_year():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)


def test_expense_oneoff():
    overlay, ignored = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("300"), month=date(2026, 3, 1))],
        SPAN,
    )
    assert overlay == {(date(2026, 3, 1), "regular"): Decimal("300.00")}
    assert ignored == 0


def test_expense_recurring_inclusive_range():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_RECURRING, amount=Decimal("100"),
               month=date(2026, 3, 1), end_month=date(2026, 5, 1))],
        SPAN,
    )
    assert overlay == {
        (date(2026, 3, 1), "regular"): Decimal("100.00"),
        (date(2026, 4, 1), "regular"): Decimal("100.00"),
        (date(2026, 5, 1), "regular"): Decimal("100.00"),
    }


def test_income_oneoff():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.INCOME, amount=Decimal("2000"), month=date(2026, 6, 1))], SPAN
    )
    assert overlay == {(date(2026, 6, 1), "income"): Decimal("2000.00")}


def test_installment_spreads_n_months():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.INSTALLMENT, amount=Decimal("400"),
               month=date(2026, 1, 1), n_installments=3)],
        SPAN,
    )
    assert overlay == {
        (date(2026, 1, 1), "installment"): Decimal("400.00"),
        (date(2026, 2, 1), "installment"): Decimal("400.00"),
        (date(2026, 3, 1), "installment"): Decimal("400.00"),
    }


def test_loan_income_now_parcelas_from_next_month():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.LOAN, amount=Decimal("20000"), month=date(2026, 6, 1),
               n_installments=2, installment_amount=Decimal("1900"))],
        SPAN,
    )
    assert overlay == {
        (date(2026, 6, 1), "income"): Decimal("20000.00"),
        (date(2026, 7, 1), "installment"): Decimal("1900.00"),
        (date(2026, 8, 1), "installment"): Decimal("1900.00"),
    }


def test_deltas_outside_span_are_ignored_and_counted():
    overlay, ignored = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("50"), month=date(2030, 1, 1))],
        SPAN,
    )
    assert overlay == {}
    assert ignored == 1


def test_same_month_kind_amounts_accumulate():
    overlay, _ = expand_hypotheticals(
        [
            _item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("100"), month=date(2026, 3, 1)),
            _item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("25"), month=date(2026, 3, 1)),
        ],
        SPAN,
    )
    assert overlay == {(date(2026, 3, 1), "regular"): Decimal("125.00")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && uv run pytest finances/tests/test_whatif.py -v`
Expected: FAIL — `ModuleNotFoundError: finances.services.whatif`.

- [ ] **Step 3: Implement `whatif.py`**

```python
# finances/services/whatif.py
"""What-if projection primitives.

Pure, deterministic. Shared by the projection screen (session) and the planner
agent tool. NO import of pydantic_ai here — only pydantic — so finances stays
decoupled from the agent framework.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel

_CENTS = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


class HypoType(str, Enum):
    EXPENSE_ONEOFF = "expense_oneoff"
    EXPENSE_RECURRING = "expense_recurring"
    INCOME = "income"
    INSTALLMENT = "installment"
    LOAN = "loan"


class HypotheticalItem(BaseModel):
    id: str
    type: HypoType
    label: str = ""
    amount: Decimal
    month: date
    end_month: date | None = None
    n_installments: int | None = None
    installment_amount: Decimal | None = None


def _item_deltas(item: HypotheticalItem):
    """Yield (billing_month, kind, amount) tuples for one hypothetical."""
    m = item.month.replace(day=1)
    if item.type == HypoType.EXPENSE_ONEOFF:
        yield (m, "regular", item.amount)
    elif item.type == HypoType.EXPENSE_RECURRING:
        end = (item.end_month or item.month).replace(day=1)
        cur = m
        while cur <= end:
            yield (cur, "regular", item.amount)
            cur = add_months(cur, 1)
    elif item.type == HypoType.INCOME:
        if item.end_month:
            end = item.end_month.replace(day=1)
            cur = m
            while cur <= end:
                yield (cur, "income", item.amount)
                cur = add_months(cur, 1)
        else:
            yield (m, "income", item.amount)
    elif item.type == HypoType.INSTALLMENT:
        for i in range(item.n_installments or 0):
            yield (add_months(m, i), "installment", item.amount)
    elif item.type == HypoType.LOAN:
        yield (m, "income", item.amount)
        parcela = item.installment_amount or Decimal("0")
        for i in range(item.n_installments or 0):
            yield (add_months(m, i + 1), "installment", parcela)


def expand_hypotheticals(
    items: list[HypotheticalItem], span_months: list[date]
) -> tuple[dict[tuple[date, str], Decimal], int]:
    span = set(span_months)
    deltas: dict[tuple[date, str], Decimal] = defaultdict(lambda: Decimal("0"))
    ignored = 0
    for item in items:
        for m, kind, amount in _item_deltas(item):
            if m in span:
                deltas[(m, kind)] += Decimal(amount)
            else:
                ignored += 1
    return {k: _q(v) for k, v in deltas.items()}, ignored
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/backend && uv run pytest finances/tests/test_whatif.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd src/backend && uv run ruff check finances/services/whatif.py finances/tests/test_whatif.py
git add src/backend/finances/services/whatif.py src/backend/finances/tests/test_whatif.py
git commit -m "feat(whatif): hypothetical primitives + expand_hypotheticals"
```

---

## Task 2: `build_projection` overlay parameter

**Files:**
- Modify: `finances/services/projection.py`
- Test: append to `finances/tests/test_projection_service.py`

**Interfaces:**
- Consumes: `expand_hypotheticals` output shape `{(date, kind): Decimal}` (Task 1).
- Produces: `build_projection(user, start_month, num_months, today=None, overlay=None)` — `overlay` default `None` (no change); when given, its deltas add into per-month income/entry buckets. `kind ∈ {"income","regular","installment","systemic"}`.

- [ ] **Step 1: Write the failing tests**

```python
# append to finances/tests/test_projection_service.py
class TestProjectionOverlay:
    def test_overlay_none_matches_baseline(self, user, cat, pix):
        m = date(2026, 5, 1)
        _entry(user, cat, pix, "150", m, EntryType.REGULAR)
        baker.make("finances.Income", user=user, amount=Decimal("2000"), month=m)
        base = build_projection(user, m, 2, today=date(2026, 6, 15))
        same = build_projection(user, m, 2, today=date(2026, 6, 15), overlay=None)
        assert [r["acumulado"] for r in base] == [r["acumulado"] for r in same]

    def test_overlay_expense_lowers_saldo_and_acumulado(self, user):
        m = date(2026, 6, 1)
        baker.make("finances.Income", user=user, amount=Decimal("2000"), month=m)
        overlay = {(m, "regular"): Decimal("500")}
        row = build_projection(user, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["diverse"] == Decimal("500")
        assert row["saldo_projetado"] == Decimal("1500")  # 2000 - 500
        assert row["acumulado"] == Decimal("1500")

    def test_overlay_income_raises_saldo(self, user):
        m = date(2026, 6, 1)
        overlay = {(m, "income"): Decimal("1000")}
        row = build_projection(user, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["income"] == Decimal("1000")
        assert row["saldo_projetado"] == Decimal("1000")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_projection_service.py::TestProjectionOverlay -v`
Expected: FAIL — `build_projection() got an unexpected keyword argument 'overlay'`.

- [ ] **Step 3: Implement the overlay merge**

In `finances/services/projection.py`, change the signature and add the merge right after the `income_totals` loop (before `active_systemic_total`):

```python
def build_projection(user, start_month: date, num_months: int, today: date | None = None,
                     overlay: dict | None = None):
```

After the `income_totals` population block, insert:

```python
    # --- what-if overlay: hypothetical per-month deltas (Decimal) ---
    if overlay:
        for (m, kind), amount in overlay.items():
            if kind == "income":
                income_totals[m] = income_totals.get(m, ZERO) + amount
            else:
                key = (m, kind)
                entry_totals[key] = entry_totals.get(key, ZERO) + amount
```

(`kind` strings already equal `EntryType.REGULAR/INSTALLMENT/SYSTEMIC` values, so `(m, kind)` matches existing keys.)

- [ ] **Step 4: Run to verify pass (incl. full projection regression)**

Run: `cd src/backend && uv run pytest finances/tests/test_projection_service.py -v`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Lint + commit**

```bash
cd src/backend && uv run ruff check finances/services/projection.py
git add src/backend/finances/services/projection.py src/backend/finances/tests/test_projection_service.py
git commit -m "feat(projection): optional what-if overlay parameter"
```

---

## Task 3: category moving averages service

**Files:**
- Create: `finances/services/category_stats.py`
- Test: `finances/tests/test_category_stats.py`

**Interfaces:**
- Produces:
  - `category_moving_averages(user, window=3, as_of=None, entry_type=None) -> dict[UUID, Decimal]` — average monthly spend per category over the `window` complete billing months **before** `as_of`'s month; `amount > 0` only; `entry_type` filters (`None` = all types, `"regular"` = diversas only); denominator = number of those window-months in which the category had spend; categories with no spend in the window are absent.
  - `category_moving_averages_named(user, window=3, as_of=None, entry_type=None) -> list[dict]` — `[{"id", "name", "avg", "months_used"}]` sorted by `-avg`.

- [ ] **Step 1: Write the failing tests**

```python
# finances/tests/test_category_stats.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.category_stats import (
    category_moving_averages,
    category_moving_averages_named,
)


def _e(user, cat, pm, amount, bm, et=EntryType.REGULAR):
    return baker.make("finances.Entry", user=user, date=bm, amount=Decimal(amount),
                      category=cat, payment_method=pm, entry_type=et,
                      billing_month=bm, billing_month_override=True)


@pytest.fixture
def cat(user):
    return baker.make("finances.Category", user=user, name="Alimentação")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestCategoryMovingAverages:
    AS_OF = date(2026, 6, 20)  # window = mar, abr, mai

    def test_three_full_months_average(self, user, cat, pix):
        _e(user, cat, pix, "900", date(2026, 3, 1))
        _e(user, cat, pix, "1000", date(2026, 4, 1))
        _e(user, cat, pix, "1100", date(2026, 5, 1))
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("1000.00")

    def test_excludes_current_incomplete_month(self, user, cat, pix):
        _e(user, cat, pix, "900", date(2026, 3, 1))
        _e(user, cat, pix, "5000", date(2026, 6, 1))  # current month — ignored
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("900.00")  # only mar had data; /1

    def test_excludes_refunds(self, user, cat, pix):
        _e(user, cat, pix, "1000", date(2026, 3, 1))
        _e(user, cat, pix, "-200", date(2026, 3, 1))  # refund, excluded
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("1000.00")

    def test_partial_history_divides_by_months_with_data(self, user, cat, pix):
        _e(user, cat, pix, "600", date(2026, 4, 1))
        _e(user, cat, pix, "800", date(2026, 5, 1))  # 2 of 3 months
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("700.00")  # 1400 / 2

    def test_category_without_spend_absent(self, user, cat, pix):
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert cat.id not in avg

    def test_entry_type_filter_regular_only(self, user, cat, pix):
        _e(user, cat, pix, "300", date(2026, 4, 1), EntryType.REGULAR)
        _e(user, cat, pix, "900", date(2026, 4, 1), EntryType.SYSTEMIC)
        reg = category_moving_averages(user, as_of=self.AS_OF, entry_type="regular")
        allt = category_moving_averages(user, as_of=self.AS_OF)
        assert reg[cat.id] == Decimal("300.00")
        assert allt[cat.id] == Decimal("1200.00")

    def test_named_sorted_desc(self, user, cat, pix):
        other = baker.make("finances.Category", user=user, name="Lanche")
        _e(user, cat, pix, "1000", date(2026, 4, 1))
        _e(user, other, pix, "200", date(2026, 4, 1))
        named = category_moving_averages_named(user, as_of=self.AS_OF)
        assert [n["name"] for n in named] == ["Alimentação", "Lanche"]
        assert named[0]["avg"] == Decimal("1000.00")
        assert named[0]["months_used"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_category_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: finances.services.category_stats`.

- [ ] **Step 3: Implement `category_stats.py`**

```python
# finances/services/category_stats.py
"""Per-category moving-average spend. Deterministic, computed live."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from finances.models import Category, Entry
from finances.services.whatif import add_months

_CENTS = Decimal("0.01")


def _window_months(as_of: date, window: int) -> list[date]:
    current = as_of.replace(day=1)
    return [add_months(current, -i) for i in range(1, window + 1)]


def category_moving_averages(user, window=3, as_of=None, entry_type=None) -> dict:
    as_of = as_of or date.today()
    months = _window_months(as_of, window)
    qs = Entry.objects.filter(
        user=user, amount__gt=0, billing_month__in=months
    )
    if entry_type is not None:
        qs = qs.filter(entry_type=entry_type)
    rows = qs.values("category_id", "billing_month").annotate(total=Sum("amount"))

    totals: dict = {}
    counts: dict = {}
    for r in rows:
        cid = r["category_id"]
        totals[cid] = totals.get(cid, Decimal("0")) + (r["total"] or Decimal("0"))
        counts[cid] = counts.get(cid, 0) + 1

    return {
        cid: (totals[cid] / counts[cid]).quantize(_CENTS, rounding=ROUND_HALF_UP)
        for cid in totals
    }


def category_moving_averages_named(user, window=3, as_of=None, entry_type=None) -> list:
    as_of = as_of or date.today()
    months = _window_months(as_of, window)
    avgs = category_moving_averages(user, window, as_of, entry_type)
    qs = Entry.objects.filter(user=user, amount__gt=0, billing_month__in=months)
    if entry_type is not None:
        qs = qs.filter(entry_type=entry_type)
    names = dict(Category.objects.filter(user=user).values_list("id", "name"))
    out = [
        {
            "id": cid,
            "name": names.get(cid, "?"),
            "avg": avg,
            "months_used": qs.filter(category_id=cid).values("billing_month").distinct().count(),
        }
        for cid, avg in avgs.items()
    ]
    out.sort(key=lambda x: x["avg"], reverse=True)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `cd src/backend && uv run pytest finances/tests/test_category_stats.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd src/backend && uv run ruff check finances/services/category_stats.py finances/tests/test_category_stats.py
git add src/backend/finances/services/category_stats.py src/backend/finances/tests/test_category_stats.py
git commit -m "feat(category-stats): per-category moving average service"
```

---

## Task 4: wire `detect_anomalies` + `recompute_category_averages` command

**Files:**
- Modify: `assistant/agents/analytics.py:145-169` (`detect_anomalies`)
- Create: `finances/management/commands/recompute_category_averages.py`
- Test: `finances/tests/test_recompute_category_averages.py`; update `assistant/tests/test_analytics.py`

**Interfaces:**
- Consumes: `category_moving_averages` (Task 3).
- Produces: command `recompute_category_averages [--apply]` populating `Category.quarterly_avg` (window 3) and `Category.historical_avg` (full history).

- [ ] **Step 1: Write the failing test for the command**

```python
# finances/tests/test_recompute_category_averages.py
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from finances.models import Category
from finances.models.entry import EntryType


def _e(user, cat, pm, amount, bm):
    return baker.make("finances.Entry", user=user, date=bm, amount=Decimal(amount),
                      category=cat, payment_method=pm, entry_type=EntryType.REGULAR,
                      billing_month=bm, billing_month_override=True)


@pytest.mark.django_db
def test_dry_run_does_not_write(user):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    _e(user, cat, pix, "900", date(2026, 3, 1))
    call_command("recompute_category_averages", stdout=StringIO())
    cat.refresh_from_db()
    assert cat.quarterly_avg is None


@pytest.mark.django_db
def test_apply_populates_quarterly_avg(user, settings):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        _e(user, cat, pix, "1000", bm)
    call_command("recompute_category_averages", "--apply", "--as-of=2026-06-20",
                 stdout=StringIO())
    cat.refresh_from_db()
    assert cat.quarterly_avg == Decimal("1000.00")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_recompute_category_averages.py -v`
Expected: FAIL — `Unknown command: 'recompute_category_averages'`.

- [ ] **Step 3: Implement the command**

```python
# finances/management/commands/recompute_category_averages.py
from datetime import date, datetime

from django.core.management.base import BaseCommand

from finances.models import Category
from finances.services.category_stats import category_moving_averages


class Command(BaseCommand):
    help = "Popula Category.quarterly_avg (3m) e historical_avg (todo histórico)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="grava (senão dry-run)")
        parser.add_argument("--as-of", default=None, help="YYYY-MM-DD (default hoje)")

    def handle(self, *args, **opts):
        as_of = (
            datetime.strptime(opts["as_of"], "%Y-%m-%d").date()
            if opts["as_of"] else date.today()
        )
        changed = 0
        for cat in Category.objects.all():
            q = category_moving_averages(cat.user, window=3, as_of=as_of).get(cat.id)
            h = category_moving_averages(cat.user, window=1200, as_of=as_of).get(cat.id)
            if opts["apply"]:
                cat.quarterly_avg = q
                cat.historical_avg = h
                cat.save(update_fields=["quarterly_avg", "historical_avg", "updated_at"])
            changed += 1
            self.stdout.write(f"{cat.user_id} {cat.name}: 3m={q} hist={h}")
        verb = "gravado" if opts["apply"] else "DRY-RUN"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {changed} categoria(s)."))
```

- [ ] **Step 4: Wire `detect_anomalies` to the live average**

In `assistant/agents/analytics.py`, replace the field read with the live service:

```python
# top of file
from finances.services.category_stats import category_moving_averages
```

In `detect_anomalies`, replace `avg = cat.quarterly_avg or cat.historical_avg` with:

```python
    averages = category_moving_averages(user, window=3, as_of=bm)
    ...
    for cat in Category.objects.filter(user=user, id__in=totals.keys()):
        avg = averages.get(cat.id)
        if not avg or avg <= 0:
            continue
```

(`as_of=bm` so the window is the 3 months before the analysed month.)

- [ ] **Step 5: Run command + analytics tests**

Run: `cd src/backend && uv run pytest finances/tests/test_recompute_category_averages.py assistant/tests/test_analytics.py -v`
Expected: PASS. If `test_analytics.py` set `quarterly_avg` directly, update those tests to instead create entries in the 3 prior months so the live average drives `detect_anomalies`.

- [ ] **Step 6: Lint + commit**

```bash
cd src/backend && uv run ruff check finances/management/commands/recompute_category_averages.py assistant/agents/analytics.py
git add src/backend/finances/management/commands/recompute_category_averages.py \
        src/backend/assistant/agents/analytics.py \
        src/backend/finances/tests/test_recompute_category_averages.py \
        src/backend/assistant/tests/test_analytics.py
git commit -m "feat(category-stats): live averages in detect_anomalies + recompute command"
```

---

## Task 5: estimated track in `build_projection`

**Files:**
- Modify: `finances/services/projection.py`
- Test: `finances/tests/test_projection_estimated.py`

**Interfaces:**
- Consumes: `category_moving_averages(user, entry_type="regular", as_of=...)` (Task 3).
- Produces: each `build_projection` row gains `diverse_estimated`, `total_estimated`, `saldo_projetado_estimado`, `acumulado_estimado` (all `Decimal`).

**Estimate rule per month `m` (current_month = today.replace(day=1)):**
- `m < current_month`: `diverse_estimated = diverse` (real).
- `m > current_month`: `diverse_estimated = sum(regular averages)`.
- `m == current_month`: per category `max(actual_regular_this_month[cat], avg_regular[cat])`, summed across the union of both keysets.

- [ ] **Step 1: Write the failing tests**

```python
# finances/tests/test_projection_estimated.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.projection import build_projection


def _e(user, cat, pm, amount, bm, et=EntryType.REGULAR):
    return baker.make("finances.Entry", user=user, date=bm, amount=Decimal(amount),
                      category=cat, payment_method=pm, entry_type=et,
                      billing_month=bm, billing_month_override=True)


@pytest.fixture
def cat(user):
    return baker.make("finances.Category", user=user, name="Alimentação")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestEstimatedTrack:
    TODAY = date(2026, 6, 20)  # window mar/abr/mai

    def _seed_avg_1000(self, user, cat, pix):
        for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
            _e(user, cat, pix, "1000", bm)

    def test_future_month_uses_average(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        rows = build_projection(user, date(2026, 6, 1), 2, today=self.TODAY)
        july = next(r for r in rows if r["month"] == date(2026, 7, 1))
        assert july["diverse"] == Decimal("0")          # nothing posted
        assert july["diverse_estimated"] == Decimal("1000.00")

    def test_past_month_estimated_equals_real(self, user, cat, pix):
        m = date(2026, 5, 1)
        _e(user, cat, pix, "750", m)
        rows = build_projection(user, m, 1, today=self.TODAY)
        assert rows[0]["diverse"] == Decimal("750")
        assert rows[0]["diverse_estimated"] == Decimal("750")

    def test_current_month_max_actual_over_average(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        _e(user, cat, pix, "1400", date(2026, 6, 1))  # already over average
        rows = build_projection(user, date(2026, 6, 1), 1, today=self.TODAY)
        assert rows[0]["diverse_estimated"] == Decimal("1400.00")

    def test_current_month_average_when_under(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        _e(user, cat, pix, "200", date(2026, 6, 1))  # under average
        rows = build_projection(user, date(2026, 6, 1), 1, today=self.TODAY)
        assert rows[0]["diverse_estimated"] == Decimal("1000.00")

    def test_acumulado_estimado_accumulates(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        baker.make("finances.Income", user=user, amount=Decimal("3000"), month=date(2026, 7, 1))
        rows = build_projection(user, date(2026, 7, 1), 1, today=self.TODAY)
        r = rows[0]
        assert r["saldo_projetado_estimado"] == r["income"] - r["total_estimated"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_projection_estimated.py -v`
Expected: FAIL — `KeyError: 'diverse_estimated'`.

- [ ] **Step 3: Implement the estimated track**

In `finances/services/projection.py`, add the import and precompute the regular averages + current-month actuals before the row loop:

```python
from finances.services.category_stats import category_moving_averages
```

After `active_systemic_total` and before `rows = []`:

```python
    # --- estimated diversas (per-category regular moving average) ---
    reg_avg = category_moving_averages(user, window=3, as_of=today, entry_type="regular")
    est_future_diverse = sum(reg_avg.values(), ZERO)
    # current-month actual regular per category (for max(actual, avg))
    cur_actual = {
        r["category_id"]: (r["total"] or ZERO)
        for r in Entry.objects.filter(
            user=user, billing_month=current_month,
            entry_type=EntryType.REGULAR, amount__gt=0,
        ).values("category_id").annotate(total=Sum("amount"))
    }
    est_current_diverse = sum(
        (max(cur_actual.get(cid, ZERO), reg_avg.get(cid, ZERO))
         for cid in set(cur_actual) | set(reg_avg)),
        ZERO,
    )
```

Inside the `for m in all_months` loop, after `diverse = ...` and the existing `total`/`saldo` computations, add:

```python
        if m < current_month:
            diverse_estimated = diverse
        elif m == current_month:
            diverse_estimated = est_current_diverse
        else:
            diverse_estimated = est_future_diverse
        total_estimated = programmed + diverse_estimated
        saldo_projetado_estimado = income - total_estimated
        acumulado_estimado += saldo_projetado_estimado
```

Initialise `acumulado_estimado = ZERO` next to `acumulado = ZERO`. Add the four keys to the appended row dict:

```python
                "diverse_estimated": diverse_estimated,
                "total_estimated": total_estimated,
                "saldo_projetado_estimado": saldo_projetado_estimado,
                "acumulado_estimado": acumulado_estimado,
```

The pre-window `continue` (`if m < start_month`) must run **after** `acumulado_estimado` is updated (mirror the existing `acumulado` handling) so the estimated anchor matches the real one.

- [ ] **Step 4: Run estimated + regression**

Run: `cd src/backend && uv run pytest finances/tests/test_projection_estimated.py finances/tests/test_projection_service.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd src/backend && uv run ruff check finances/services/projection.py
git add src/backend/finances/services/projection.py src/backend/finances/tests/test_projection_estimated.py
git commit -m "feat(projection): estimated saldo/acumulado track from category averages"
```

---

## Task 6: Feature 1 surfaces — settings tab + analyst tool

**Files:**
- Modify: `finances/views/settings.py` (DRY categories context), `templates/settings/_categories_tab.html`
- Modify: `assistant/agents/analytics.py` (wrapper), `assistant/agents/analyst.py` (tool)
- Test: update `finances/tests/test_views_settings.py`; create `assistant/tests/test_category_averages_tool.py`

**Interfaces:**
- Consumes: `category_moving_averages_named` (Task 3).
- Produces: `category_averages(user, year=None, month=None) -> str` in `analytics.py`; settings context key `category_averages` (dict `id -> avg`).

- [ ] **Step 1: Write the failing view test**

```python
# finances/tests/test_views_settings.py — add
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker
from finances.models.entry import EntryType


@pytest.mark.django_db
def test_categories_tab_shows_moving_average(logged_client, user):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        baker.make("finances.Entry", user=user, date=bm, amount=Decimal("1000"),
                   category=cat, payment_method=pix, entry_type=EntryType.REGULAR,
                   billing_month=bm, billing_month_override=True)
    resp = logged_client.get("/settings/categories/")
    assert resp.status_code == 200
    assert b"dia" in resp.content.lower() or b"3m" in resp.content  # "média (3m)" header
```

(The averages depend on `date.today()`; if the suite runs outside the mar–mai window, freeze time with `freezegun`/`time_machine` if available, or assert only that the column header renders. Keep the assertion on the header text to stay date-robust.)

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_views_settings.py::test_categories_tab_shows_moving_average -v`
Expected: FAIL — header text absent.

- [ ] **Step 3: DRY the categories context + inject averages**

In `finances/views/settings.py`, add a module helper and use it in all four places (`CategoriesTabView.get_context_data`, `CategoryCreateView`, `CategoryEditView`, `CategoryDeleteView`):

```python
from finances.services.category_stats import category_moving_averages

def categories_tab_context(user):
    return {
        "categories": Category.objects.filter(user=user),
        "form": CategoryCreateForm(),
        "category_averages": category_moving_averages(user, window=3),
    }
```

Replace each inline `{"categories": ..., "form": ...}` dict with `categories_tab_context(request.user)` (and in `CategoriesTabView` use `context.update(categories_tab_context(self.request.user))`).

- [ ] **Step 4: Template column**

In `templates/settings/_categories_tab.html`, add a header cell and a body cell:

```html
<!-- thead row -->
<tr><th>Nome</th><th>Teto</th><th>Média (3m)</th><th>Sistema</th><th></th></tr>
```

```html
<!-- in the {% for cat %} row, after the Teto <td> -->
<td class="text-xs text-base-content/70">
    {% with avg=category_averages|dictkey:cat.id %}
        {% if avg %}R$ {{ avg|floatformat:2 }}{% else %}—{% endif %}
    {% endwith %}
</td>
```

Add a `dictkey` filter if none exists, in `finances/templatetags/finance_filters.py`:

```python
@register.filter
def dictkey(d, key):
    return d.get(key) if hasattr(d, "get") else None
```

(Update the empty-state `colspan="4"` to `colspan="5"`.)

- [ ] **Step 5: Analyst tool + wrapper**

In `assistant/agents/analytics.py`:

```python
from finances.services.category_stats import category_moving_averages_named

def category_averages(user, year: int | None = None, month: int | None = None) -> str:
    """Média móvel (3m) de gasto por categoria."""
    as_of = _billing_month(year, month) if (year and month) else None
    rows = category_moving_averages_named(user, window=3, as_of=as_of)
    if not rows:
        return "Sem histórico suficiente para médias por categoria."
    lines = ["Média de gasto por categoria (3 meses):"]
    lines += [f"- {r['name']}: R$ {r['avg']:.2f} ({r['months_used']}m)" for r in rows]
    return "\n".join(lines)
```

In `assistant/agents/analyst.py`, register the tool (mirror existing `@analyst_agent.tool` pattern):

```python
@analyst_agent.tool
async def get_category_averages(ctx: RunContext[User], year: int | None = None,
                                month: int | None = None) -> str:
    """Média móvel (3 meses) de gasto por categoria."""
    return await sync_to_async(analytics.category_averages)(ctx.deps, year, month)
```

- [ ] **Step 6: Agent tool test**

```python
# assistant/tests/test_category_averages_tool.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from assistant.agents import analytics
from finances.models.entry import EntryType


@pytest.mark.django_db
def test_category_averages_text(user):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        baker.make("finances.Entry", user=user, date=bm, amount=Decimal("1000"),
                   category=cat, payment_method=pix, entry_type=EntryType.REGULAR,
                   billing_month=bm, billing_month_override=True)
    out = analytics.category_averages(user, 2026, 6)
    assert "Alimentação" in out
    assert "1000.00" in out
```

- [ ] **Step 7: Run + lint + commit**

```bash
cd src/backend && uv run pytest finances/tests/test_views_settings.py assistant/tests/test_category_averages_tool.py -v
cd src/backend && uv run ruff check finances/views/settings.py assistant/agents/analytics.py assistant/agents/analyst.py finances/templatetags/finance_filters.py
git add -A && git commit -m "feat(category-stats): show 3m average in settings + analyst tool"
```

---

## Task 7: Feature 3 — what-if panel on the projection screen

**Files:**
- Modify: `finances/views/projection.py`, `finances/urls.py`, `templates/projection/projection_page.html`, `templates/projection/_projection_table.html`
- Create: `templates/projection/_whatif_panel.html`
- Test: `finances/tests/test_views_projection.py` (add)

**Interfaces:**
- Consumes: `HypotheticalItem`, `expand_hypotheticals` (Task 1); `build_projection(..., overlay=...)` (Task 2).
- Produces: session key `request.session["projection_whatif"]` (list of dicts); routes `projection_whatif_add/remove/clear`; context `whatif_items`, rows carry both base (`acumulado`) and simulated (`acumulado_sim`).

**Session-overlay approach:** `ProjectionView` builds the projection twice when there are hypotheticals — once without overlay (base) and once with — and zips the simulated `acumulado`/`saldo_projetado` onto each base row as `*_sim`. When the session is empty, only the base is computed.

- [ ] **Step 1: Write the failing view tests**

```python
# finances/tests/test_views_projection.py — add
import pytest


@pytest.mark.django_db
def test_whatif_add_then_table_shows_simulado(logged_client):
    r = logged_client.post("/projection/whatif/add/", {
        "type": "income", "label": "bônus", "amount": "5000", "month": "2026-08",
    })
    assert r.status_code == 200
    assert b"Simula" in r.content  # simulated row label rendered

@pytest.mark.django_db
def test_whatif_clear_empties_session(logged_client):
    logged_client.post("/projection/whatif/add/", {
        "type": "expense_oneoff", "label": "x", "amount": "100", "month": "2026-08"})
    logged_client.post("/projection/whatif/clear/")
    sess = logged_client.session
    assert sess.get("projection_whatif", []) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_views_projection.py -k whatif -v`
Expected: FAIL — 404 (routes absent).

- [ ] **Step 3: Form + session helpers + views**

Add to `finances/views/projection.py`:

```python
import uuid
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.http import HttpResponse
from finances.services.whatif import HypotheticalItem, HypoType, expand_hypotheticals

SESSION_KEY = "projection_whatif"

def _parse_month_field(raw):  # "YYYY-MM" -> date(first)
    y, m = (int(p) for p in raw.split("-")[:2])
    return date(y, m, 1)

def _session_items(request):
    return [HypotheticalItem(**d) for d in request.session.get(SESSION_KEY, [])]
```

`ProjectionView.get_context_data` — after computing `start`, `months`, build the span and overlay:

```python
        items = _session_items(self.request)
        rows = build_projection(self.request.user, start, months, today=today)
        if items:
            span = [r["month"] for r in rows]
            overlay, _ = expand_hypotheticals(items, span)
            sim = build_projection(self.request.user, start, months, today=today, overlay=overlay)
            sim_by_month = {r["month"]: r for r in sim}
            for r in rows:
                s = sim_by_month[r["month"]]
                r["acumulado_sim"] = s["acumulado"]
                r["saldo_projetado_sim"] = s["saldo_projetado"]
        context["rows"] = rows
        context["whatif_items"] = items
        context["has_whatif"] = bool(items)
```

Add the three views at module level:

```python
class ProjectionWhatifAddView(HtmxLoginRequiredMixin, TemplateView):
    htmx_template_name = "projection/_projection_table.html"

    def post(self, request):
        items = request.session.get(SESSION_KEY, [])
        item = HypotheticalItem(
            id=uuid.uuid4().hex[:8],
            type=HypoType(request.POST["type"]),
            label=request.POST.get("label", ""),
            amount=request.POST["amount"],
            month=_parse_month_field(request.POST["month"]),
            end_month=(_parse_month_field(request.POST["end_month"])
                       if request.POST.get("end_month") else None),
            n_installments=(int(request.POST["n_installments"])
                            if request.POST.get("n_installments") else None),
            installment_amount=(request.POST["installment_amount"]
                                if request.POST.get("installment_amount") else None),
        )
        items.append(item.model_dump(mode="json"))
        request.session[SESSION_KEY] = items
        return _render_projection(request)

class ProjectionWhatifRemoveView(HtmxLoginRequiredMixin, TemplateView):
    def post(self, request, item_id):
        items = [d for d in request.session.get(SESSION_KEY, []) if d["id"] != item_id]
        request.session[SESSION_KEY] = items
        return _render_projection(request)

class ProjectionWhatifClearView(HtmxLoginRequiredMixin, TemplateView):
    def post(self, request):
        request.session[SESSION_KEY] = []
        return _render_projection(request)
```

`_render_projection(request)` renders the same context as `ProjectionView` (extract the context build into a shared `build_projection_context(request)` function used by both the view and these helpers, to stay DRY). It returns `HttpResponse(render_to_string("projection/_projection_table.html", ctx, request=request))`.

- [ ] **Step 4: Routes**

In `finances/urls.py`, beside the `projection/` route:

```python
from finances.views.projection import (
    ProjectionView, ProjectionWhatifAddView,
    ProjectionWhatifRemoveView, ProjectionWhatifClearView,
)
...
    path("projection/whatif/add/", ProjectionWhatifAddView.as_view(), name="projection_whatif_add"),
    path("projection/whatif/<str:item_id>/remove/", ProjectionWhatifRemoveView.as_view(), name="projection_whatif_remove"),
    path("projection/whatif/clear/", ProjectionWhatifClearView.as_view(), name="projection_whatif_clear"),
```

- [ ] **Step 5: Panel + table templates**

Create `templates/projection/_whatif_panel.html`: a type `<select>` that toggles field groups (avulsa/recorrente/renda/parcelamento/empréstimo), an HTMX form `hx-post="{% url 'finances:projection_whatif_add' %}" hx-target="#projection-container"`, the active-items list (each with a remove button `hx-post=".../remove/"`), and a "Limpar" button. Use `select-bordered select-sm`/`input-bordered input-sm` to match existing style.

In `_projection_table.html`, add rows for **saldo projetado estimado** and **acumulado estimado** (always), and when `has_whatif`, an **acumulado simulado** row + per-month delta (`acumulado_sim - acumulado`) with the label text containing "Simula".

Include the panel in `projection_page.html` above `#projection-container`.

- [ ] **Step 6: Run + lint + commit**

```bash
cd src/backend && uv run pytest finances/tests/test_views_projection.py -v
cd src/backend && uv run ruff check finances/views/projection.py finances/urls.py
git add -A && git commit -m "feat(projection): session what-if simulator + estimated rows"
```

---

## Task 8: Feature 2 — dashboard projection card

**Files:**
- Modify: `finances/views/dashboard.py`, `templates/dashboard/dashboard_page.html`
- Test: `finances/tests/test_views_dashboard.py` (new)

**Interfaces:**
- Consumes: `build_projection` (estimated fields, Task 5), `category_moving_averages_named` (Task 3).
- Produces: context `projection_row`, `projection_trend` (list of `{month, acumulado, acumulado_estimado}`), `sparkline_points` (str for SVG `points`), `category_averages_named`.

- [ ] **Step 1: Write the failing test**

```python
# finances/tests/test_views_dashboard.py
import pytest


@pytest.mark.django_db
def test_dashboard_has_projection_card(logged_client):
    resp = logged_client.get("/")
    assert resp.status_code == 200
    assert b"Proje" in resp.content  # "Projeção do mês" card heading
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest finances/tests/test_views_dashboard.py -v`
Expected: FAIL — heading absent.

- [ ] **Step 3: View context**

In `finances/views/dashboard.py`, extend `get_context_data`:

```python
from finances.services.projection import build_projection
from finances.services.category_stats import category_moving_averages_named

        cur = today.replace(day=1)
        proj = build_projection(self.request.user, cur, 6, today=today)
        context["projection_row"] = proj[0] if proj else None
        trend = [{"month": r["month"], "acumulado": r["acumulado"],
                  "acumulado_estimado": r["acumulado_estimado"]} for r in proj]
        context["projection_trend"] = trend
        context["sparkline_points"] = _sparkline_points([t["acumulado_estimado"] for t in trend])
        context["category_averages_named"] = category_moving_averages_named(self.request.user)
```

Add a module helper:

```python
def _sparkline_points(values, width=120, height=28):
    if not values:
        return ""
    nums = [float(v) for v in values]
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    step = width / max(len(nums) - 1, 1)
    pts = [
        f"{i * step:.1f},{height - (v - lo) / span * height:.1f}"
        for i, v in enumerate(nums)
    ]
    return " ".join(pts)
```

- [ ] **Step 4: Template card**

In `dashboard/dashboard_page.html`, add a server-rendered card inside the `#dashboard-cards` grid (it coexists with the React islands):

```html
{% if projection_row %}
<div class="card bg-base-100 shadow-sm">
  <div class="card-body p-4">
    <h3 class="font-semibold text-sm mb-2">Projeção do mês</h3>
    <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
      <span>Total</span><span class="text-right">R$ {{ projection_row.total|floatformat:2 }}</span>
      <span>Renda</span><span class="text-right">R$ {{ projection_row.income|floatformat:2 }}</span>
      <span>Saldo projetado</span><span class="text-right">R$ {{ projection_row.saldo_projetado|floatformat:2 }}</span>
      <span>Saldo estimado</span><span class="text-right">R$ {{ projection_row.saldo_projetado_estimado|floatformat:2 }}</span>
      <span class="font-medium">Acumulado</span><span class="text-right font-medium">R$ {{ projection_row.acumulado|floatformat:2 }}</span>
      <span class="font-medium">Acumulado estimado</span><span class="text-right font-medium">R$ {{ projection_row.acumulado_estimado|floatformat:2 }}</span>
    </div>
    <svg viewBox="0 0 120 28" class="w-full h-8 mt-2 text-primary">
      <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="{{ sparkline_points }}"/>
    </svg>
  </div>
</div>
{% endif %}
```

Add a small "Médias por categoria (3m)" card listing `category_averages_named` (name + `R$ avg`).

- [ ] **Step 5: Run + lint + commit**

```bash
cd src/backend && uv run pytest finances/tests/test_views_dashboard.py -v
cd src/backend && uv run ruff check finances/views/dashboard.py
git add -A && git commit -m "feat(dashboard): month projection card + sparkline + category averages"
```

---

## Task 9: Feature 4 — planner agent what-if tool

**Files:**
- Modify: `finances/services/whatif.py` (add summary), `assistant/agents/planner.py`, `assistant/agents/orchestrator.py:73-84` (hint)
- Test: `assistant/tests/test_simulate_projection.py`

**Interfaces:**
- Consumes: `HypotheticalItem`, `expand_hypotheticals` (Task 1), `build_projection(overlay=...)` (Task 2).
- Produces: `simulate_projection_summary(user, items, start, months, today=None) -> str`; planner tool `simulate_projection`.

- [ ] **Step 1: Write the failing service test**

```python
# assistant/tests/test_simulate_projection.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.whatif import HypotheticalItem, HypoType, simulate_projection_summary


@pytest.mark.django_db
def test_summary_reports_delta(user):
    baker.make("finances.Income", user=user, amount=Decimal("3000"), month=date(2026, 7, 1))
    items = [HypotheticalItem(id="a", type=HypoType.INCOME, label="bônus",
                              amount=Decimal("1000"), month=date(2026, 7, 1))]
    out = simulate_projection_summary(user, items, start=date(2026, 7, 1), months=1,
                                      today=date(2026, 6, 20))
    assert "1000" in out
    assert "2026-07" in out or "07/2026" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src/backend && uv run pytest assistant/tests/test_simulate_projection.py -v`
Expected: FAIL — `ImportError: cannot import name 'simulate_projection_summary'`.

- [ ] **Step 3: Implement the summary**

Append to `finances/services/whatif.py`:

```python
def simulate_projection_summary(user, items, start, months, today=None):
    from finances.services.projection import build_projection  # avoid import cycle

    base = build_projection(user, start, months, today=today)
    span = [r["month"] for r in base]
    overlay, ignored = expand_hypotheticals(items, span)
    sim = build_projection(user, start, months, today=today, overlay=overlay)

    lines = ["Simulação de cenário (acumulado base → simulado):"]
    worst = None
    for b, s in zip(base, sim):
        delta = s["acumulado"] - b["acumulado"]
        ym = b["month"].strftime("%Y-%m")
        lines.append(
            f"- {ym}: R$ {b['acumulado']:.2f} → R$ {s['acumulado']:.2f} (Δ {delta:+.2f})"
        )
        if worst is None or s["acumulado"] < worst[1]:
            worst = (ym, s["acumulado"])
    if worst:
        lines.append(f"Menor acumulado simulado: R$ {worst[1]:.2f} em {worst[0]}.")
    if ignored:
        lines.append(f"({ignored} lançamento(s) fora do horizonte foram ignorados.)")
    return "\n".join(lines)
```

- [ ] **Step 4: Register the planner tool**

In `assistant/agents/planner.py`:

```python
from datetime import date
from finances.services.whatif import HypotheticalItem, simulate_projection_summary

@planner_agent.tool
async def simulate_projection(ctx: RunContext[User], items: list[HypotheticalItem],
                              start_year: int, start_month: int, months: int = 12) -> str:
    """Simula o efeito de lançamentos hipotéticos na projeção (what-if).

    items: lista de hipóteses (despesa avulsa/recorrente, renda, parcelamento,
    empréstimo). start_year/start_month: início do horizonte; months: nº de meses.
    """
    start = date(start_year, start_month, 1)
    return await sync_to_async(simulate_projection_summary)(ctx.deps, items, start, months)
```

In `assistant/agents/orchestrator.py`, extend the `delegate_planejamento` docstring to mention "simulação de cenários / what-if (empréstimo, nova renda, gasto recorrente)".

- [ ] **Step 5: Run + lint + commit**

```bash
cd src/backend && uv run pytest assistant/tests/test_simulate_projection.py -v
cd src/backend && uv run ruff check finances/services/whatif.py assistant/agents/planner.py assistant/agents/orchestrator.py
git add -A && git commit -m "feat(assistant): planner what-if projection tool"
```

---

## Final verification

- [ ] **Run the full finances + assistant suites**

Run: `cd src/backend && uv run pytest finances assistant -q`
Expected: all green (no regressions).

- [ ] **Lint the whole touched set**

Run: `cd src/backend && uv run ruff check finances assistant`

- [ ] **Manual smoke (friday/jarvis dev):** open `/projection/`, add a loan hypothesis, confirm base vs simulado rows; open `/` dashboard, confirm projection card + sparkline; open settings categories, confirm the 3m average column; ask the chat agent "e se eu pegar 20k em 12x de 1900 a partir de agosto?".

- [ ] **Frontend build:** none required — no `.tsx`/Tailwind-class additions beyond existing utilities. If any new Tailwind class was introduced in templates, rebuild + commit `tailwind.css` per project rule.
```
