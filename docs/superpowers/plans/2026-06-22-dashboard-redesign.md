# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-weight the dashboard into a bento layout with three elevation tiers and star cards (hero Saldo, accent Economia, full-width signature Tendência, highlighted Projeção), backed by additive API fields for delta chips, sparklines, and a donut.

**Architecture:** Three additive DRF API changes (previous-month deltas, per-month returns, donut "Outros" slice) feed restructured React island cards. A new `HeroSummaryCard` + reusable `KpiTile` replace the flat `SummaryCard`; `TopCategoriesCard` becomes a donut; the dashboard template moves from a uniform 2-col grid to an explicit 12-col bento grid with a CSS entrance animation.

**Tech Stack:** Django + DRF, pytest (backend), React 18 + Recharts 2 + TypeScript + Vite, Tailwind/daisyUI ("ledger" theme: Fraunces / Hanken Grotesk / IBM Plex Mono).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-22-dashboard-redesign-design.md` — implement exactly.
- **TDD + worktree:** work in an isolated worktree; backend changes are TDD (failing test → fail → impl → pass → commit). Frontend cards have no JS unit runner — the gate is `cd src/backend/frontend && npx tsc --noEmit` (zero errors) plus the mandatory visual verification (Task 10).
- **Keep the "ledger" identity** — no new fonts or palette. Use existing daisyUI semantic classes, `CHART_COLORS`/`SERIES` from `theme.ts`, `formatBRL`/`formatBRLCompact` from `format.ts`, `useApiData`.
- **API changes are additive** — never remove/rename existing response fields; only add.
- **Money** is `Decimal` server-side, serialized as `"%.2f"` strings; parsed once at the FE boundary.
- **Test DB:** pgvector container on **port 5433**. Run backend tests from repo root: `POSTGRES_PORT=5433 uv run pytest <paths> -v`. Backend test fixtures: `logged_client`, `user`, `other_user`, `model_bakery.baker` (see `finances/tests/test_api_dashboard.py`).
- **Build artifacts are git-tracked** (Task 9): `cd src/backend/frontend && npm run build` → `static/frontend/mount.js`; `cd src/backend && uv run python manage.py tailwind build --force` → `static/css/tailwind.css`. Commit both.
- **`prefers-reduced-motion: reduce`** must disable the entrance animation.
- **Visual verification (Task 10) is mandatory** at lg / md / mobile before completion.

## File Structure

**Backend**
- Modify `src/backend/finances/api/views.py` — `SummaryView` (prev + deltas), `EvolutionView` (returns), `TopCategoriesView` ("Outros").
- Modify `src/backend/finances/tests/test_api_dashboard.py` — tests for the three additions.

**Frontend** (`src/backend/frontend/src/`)
- Modify `types.ts` — extend `SummaryData`, `EvolutionPoint`, `CategoryData`; add `SparkPoint`.
- Create `cards/KpiTile.tsx` — reusable KPI tile (label, value, delta chip, optional sparkline).
- Create `cards/HeroSummaryCard.tsx` — hero Saldo + mini renda/gastos + budget bar + KPI strip.
- Modify `cards/EconomiaCard.tsx` — accent treatment.
- Modify `cards/DailyTrendCard.tsx` — signature size (taller chart).
- Modify `cards/ProjectionCard.tsx`, `cards/EvolutionCard.tsx` — title scale; Evolution stays medium.
- Modify `cards/TopCategoriesCard.tsx` — donut.
- Modify `cards/AlertsCard.tsx`, `cards/RecentEntriesCard.tsx`, `cards/InstallmentsCard.tsx` — quiet tier.
- Modify `mount.tsx` — register `HeroSummaryCard` (and drop `SummaryCard` registration if replaced).
- Modify `src/backend/static/css/input.css` — entrance animation keyframes + reduced-motion guard.
- Modify `src/backend/templates/dashboard/dashboard_page.html` — 12-col bento grid + per-tile spans + animation classes.

**Build artifacts** — `static/frontend/mount.js`, `static/css/tailwind.css`.

---

## Task 1: Backend — `SummaryView` previous-month values + deltas

**Files:**
- Modify: `src/backend/finances/api/views.py` (`SummaryView`)
- Test: `src/backend/finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: existing `_get_month_params`, `Income`, `Entry`, `Category`; `add_months` from `finances.services.whatif`.
- Produces: `SummaryView` GET response gains two keys (existing keys unchanged):
  - `"prev"`: `{"income","expenses","returns","balance"}` — `"%.2f"` strings (previous billing month).
  - `"delta_pct"`: `{"income","expenses","returns","balance"}` — float rounded to 1 decimal, or `null` when the previous value is 0.

- [ ] **Step 1: Write the failing test**

Append to `finances/tests/test_api_dashboard.py` inside `TestSummaryEndpoint` (match existing fixture style):

```python
    def test_includes_prev_and_delta(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        # Previous month (2026-02): expenses 200
        baker.make(
            "finances.Entry", user=user, date=date(2026, 2, 5), amount=Decimal("200"),
            category=cat, payment_method=pm, billing_month=date(2026, 2, 1),
        )
        # Current month (2026-03): expenses 300
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("300"),
            category=cat, payment_method=pm, billing_month=date(2026, 3, 1),
        )
        data = logged_client.get("/api/dashboard/summary/?year=2026&month=3").json()
        assert data["prev"]["expenses"] == "200.00"
        # (300 - 200) / 200 * 100 = 50.0
        assert data["delta_pct"]["expenses"] == 50.0

    def test_delta_null_when_prev_zero(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("300"),
            category=cat, payment_method=pm, billing_month=date(2026, 3, 1),
        )
        data = logged_client.get("/api/dashboard/summary/?year=2026&month=3").json()
        assert data["prev"]["expenses"] == "0.00"
        assert data["delta_pct"]["expenses"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py::TestSummaryEndpoint::test_includes_prev_and_delta" -v`
Expected: FAIL — `KeyError: 'prev'`.

- [ ] **Step 3: Write minimal implementation**

In `src/backend/finances/api/views.py`, add the import (top, with other service imports):

```python
from finances.services.whatif import add_months
```

Refactor `SummaryView.get` to compute per-month totals via a helper and produce prev + deltas. Replace the body of `SummaryView` with:

```python
class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _month_totals(user, billing_month):
        _decimal = DecimalField()
        income = Income.objects.filter(user=user, month=billing_month).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")
        totals = Entry.objects.filter(user=user, billing_month=billing_month).aggregate(
            expenses=Sum(
                Case(When(amount__gt=0, then="amount"), default=Value(0), output_field=_decimal)
            ),
            returns=Sum(
                Case(When(amount__lt=0, then="amount"), default=Value(0), output_field=_decimal)
            ),
        )
        expenses = totals["expenses"] or Decimal("0")
        returns = abs(totals["returns"] or Decimal("0"))
        balance = income - expenses + returns
        return {
            "income": income,
            "expenses": expenses,
            "returns": returns,
            "balance": balance,
        }

    @staticmethod
    def _delta_pct(cur, prev):
        if prev == 0:
            return None
        return round(float(cur - prev) / float(prev) * 100, 1)

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        cur = self._month_totals(user, billing_month)
        prev = self._month_totals(user, add_months(billing_month, -1))

        total_ceiling = Category.objects.filter(user=user).aggregate(total=Sum("budget_ceiling"))[
            "total"
        ] or Decimal("0")
        budget_pct = (
            round(float(cur["expenses"]) / float(total_ceiling) * 100, 1)
            if total_ceiling > 0
            else None
        )

        return Response(
            {
                "income": f"{cur['income']:.2f}",
                "expenses": f"{cur['expenses']:.2f}",
                "returns": f"{cur['returns']:.2f}",
                "balance": f"{cur['balance']:.2f}",
                "budget_pct": budget_pct,
                "prev": {k: f"{v:.2f}" for k, v in prev.items()},
                "delta_pct": {
                    k: self._delta_pct(cur[k], prev[k]) for k in cur
                },
            }
        )
```

`Case`, `When`, `Value`, `DecimalField`, `Sum` are already imported at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py::TestSummaryEndpoint" -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/api/views.py src/backend/finances/tests/test_api_dashboard.py
git commit -m "feat(dashboard): SummaryView prev-month values + delta_pct"
```

---

## Task 2: Backend — `EvolutionView` per-month returns

**Files:**
- Modify: `src/backend/finances/api/views.py` (`EvolutionView`)
- Test: `src/backend/finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: existing `_get_month_params`, `Entry`, `Income`.
- Produces: each `EvolutionView` series point gains `"returns"` (`"%.2f"` string, abs of negative entries that month). Existing `month/expenses/income` unchanged.

- [ ] **Step 1: Write the failing test**

Append to `finances/tests/test_api_dashboard.py` inside the evolution test class (find the existing `class TestEvolutionEndpoint` and match its style):

```python
    def test_includes_returns_per_month(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("-150"),
            category=cat, payment_method=pm, billing_month=date(2026, 3, 1),
        )
        series = logged_client.get("/api/dashboard/evolution/?year=2026&month=3").json()
        march = next(p for p in series if p["month"] == "2026-03")
        assert march["returns"] == "150.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py" -v -k returns_per_month`
Expected: FAIL — `KeyError: 'returns'`.

- [ ] **Step 3: Write minimal implementation**

In `EvolutionView.get`, add a returns aggregate alongside the existing expense aggregate and include it in each point. Replace the `entry_totals` block and the `result` comprehension with:

```python
        _decimal = DecimalField()
        entry_rows = (
            Entry.objects.filter(user=user, billing_month__in=months)
            .values("billing_month")
            .annotate(
                expenses=Sum(
                    Case(When(amount__gt=0, then="amount"), default=Value(0), output_field=_decimal)
                ),
                returns=Sum(
                    Case(When(amount__lt=0, then="amount"), default=Value(0), output_field=_decimal)
                ),
            )
        )
        entry_totals = {r["billing_month"]: r for r in entry_rows}
        income_totals = {
            row["month"]: row["total"]
            for row in Income.objects.filter(user=user, month__in=months)
            .values("month")
            .annotate(total=Sum("amount"))
        }

        result = [
            {
                "month": f"{m:%Y-%m}",
                "expenses": f"{(entry_totals.get(m, {}).get('expenses') or Decimal('0')):.2f}",
                "income": f"{income_totals.get(m, Decimal('0')):.2f}",
                "returns": f"{abs(entry_totals.get(m, {}).get('returns') or Decimal('0')):.2f}",
            }
            for m in reversed(months)  # oldest first
        ]
        return Response(result)
```

`Case`, `When`, `Value`, `DecimalField`, `Sum`, `Decimal`, `date` are already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py" -v -k Evolution`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/api/views.py src/backend/finances/tests/test_api_dashboard.py
git commit -m "feat(dashboard): EvolutionView per-month returns"
```

---

## Task 3: Backend — `TopCategoriesView` "Outros" slice

**Files:**
- Modify: `src/backend/finances/api/views.py` (`TopCategoriesView`)
- Test: `src/backend/finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: existing `_get_month_params`, `Entry`, `category_moving_averages`.
- Produces: when total month expenses exceed the sum of the top 5, `TopCategoriesView` appends a final item `{"name": "Outros", "amount": "%.2f", "pct": float, "avg_3m": null}` (remainder ≥ 0). Existing items unchanged.

- [ ] **Step 1: Write the failing test**

Append to the top-categories test class in `finances/tests/test_api_dashboard.py` (match `class TestTopCategoriesEndpoint` style):

```python
    def test_appends_outros_remainder(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        # 6 categories of 100 each -> top 5 shown, 1 spills into "Outros".
        for i in range(6):
            c = baker.make("finances.Category", user=user, name=f"C{i}")
            baker.make(
                "finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("100"),
                category=c, payment_method=pm, billing_month=date(2026, 3, 1),
            )
        data = logged_client.get("/api/dashboard/top-categories/?year=2026&month=3").json()
        outros = [d for d in data if d["name"] == "Outros"]
        assert len(outros) == 1
        assert outros[0]["amount"] == "100.00"
        assert outros[0]["avg_3m"] is None

    def test_no_outros_when_five_or_fewer(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        for i in range(3):
            c = baker.make("finances.Category", user=user, name=f"C{i}")
            baker.make(
                "finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("100"),
                category=c, payment_method=pm, billing_month=date(2026, 3, 1),
            )
        data = logged_client.get("/api/dashboard/top-categories/?year=2026&month=3").json()
        assert all(d["name"] != "Outros" for d in data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py" -v -k outros`
Expected: FAIL — no "Outros" item.

- [ ] **Step 3: Write minimal implementation**

In `TopCategoriesView.get`, after building `result` from the top-5 `category_totals`, compute the remainder against ALL expenses for the month and append "Outros". Add before `return Response(result)`:

```python
        grand_total = (
            Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )
        shown_total = sum((ct["total"] for ct in category_totals), Decimal("0"))
        remainder = grand_total - shown_total
        if remainder > 0:
            result.append(
                {
                    "name": "Outros",
                    "amount": f"{remainder:.2f}",
                    "pct": round(float(remainder) / float(grand_total) * 100, 1),
                    "avg_3m": None,
                }
            )
```

`Sum`, `Decimal`, `Entry` are already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest "src/backend/finances/tests/test_api_dashboard.py" -v -k "TopCategories or outros"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/api/views.py src/backend/finances/tests/test_api_dashboard.py
git commit -m "feat(dashboard): TopCategoriesView Outros remainder slice"
```

---

## Task 4: Frontend — types + entrance-animation CSS foundation

**Files:**
- Modify: `src/backend/frontend/src/types.ts`
- Modify: `src/backend/static/css/input.css`

**Interfaces:**
- Produces (TS types consumed by later tasks):
  - `SummaryData` gains `prev: { income: string; expenses: string; returns: string; balance: string }` and `delta_pct: { income: number | null; expenses: number | null; returns: number | null; balance: number | null }`.
  - `EvolutionPoint` gains `returns: string`.
  - `CategoryData` unchanged in shape (the `"Outros"` item reuses it with `avg_3m: null`).
  - New `SparkPoint = { v: number }` for KPI sparklines.
- Produces (CSS): a `.bento-enter` class that fades+translates in, gated by `prefers-reduced-motion`; staggering is done with inline `animation-delay` in the template (Task 8).

- [ ] **Step 1: Extend types**

In `src/backend/frontend/src/types.ts`, update `SummaryData` and `EvolutionPoint`, and add `SparkPoint`:

```typescript
export interface SummaryData {
  income: string;
  expenses: string;
  returns: string;
  balance: string;
  budget_pct: number | null;
  prev: { income: string; expenses: string; returns: string; balance: string };
  delta_pct: {
    income: number | null;
    expenses: number | null;
    returns: number | null;
    balance: number | null;
  };
}
```

```typescript
export interface EvolutionPoint {
  month: string;
  expenses: string;
  income: string;
  returns: string;
}
```

Add at the end of the file:

```typescript
export interface SparkPoint {
  v: number;
}
```

- [ ] **Step 2: Add the entrance-animation CSS**

In `src/backend/static/css/input.css`, append at the end of the file:

```css
/* ---- Dashboard bento entrance: one orchestrated reveal on load ---- */
@layer utilities {
  @keyframes bento-rise {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .bento-enter {
    opacity: 0;
    animation: bento-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }
  /* Quiet hover lift for medium tiles only (applied via .tile-hover). */
  .tile-hover {
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .tile-hover:hover {
    transform: translateY(-1px);
  }
  @media (prefers-reduced-motion: reduce) {
    .bento-enter { opacity: 1; animation: none; }
    .tile-hover { transition: none; }
    .tile-hover:hover { transform: none; }
  }
}
```

- [ ] **Step 3: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: errors ONLY in cards that read the old shapes (those are fixed in later tasks). If the only errors are "Property 'returns' is missing" / "Property 'prev' is missing" in `SummaryCard.tsx`/`EvolutionCard.tsx` consumers, that's expected at this stage. If `SummaryCard.tsx` still exists and errors, leave it — Task 5 removes it. To keep this task green, also do Step 4.

- [ ] **Step 4: Keep the build green by relaxing nothing — verify only types file compiles**

Run: `cd src/backend/frontend && npx tsc --noEmit 2>&1 | grep -v "SummaryCard.tsx" | grep -v "EvolutionCard.tsx" || true`
Expected: no NEW errors beyond the two consumer files updated in Tasks 5/6. (Document any other error in the report instead of suppressing it.)

- [ ] **Step 5: Commit**

```bash
git add src/backend/frontend/src/types.ts src/backend/static/css/input.css
git commit -m "feat(dashboard): types for deltas/returns + bento entrance CSS"
```

---

## Task 5: Frontend — `KpiTile` + `HeroSummaryCard`

**Files:**
- Create: `src/backend/frontend/src/cards/KpiTile.tsx`
- Create: `src/backend/frontend/src/cards/HeroSummaryCard.tsx`
- Modify: `src/backend/frontend/src/cards/SummaryCard.tsx` (delete) and `mount.tsx`

**Interfaces:**
- Consumes: `SummaryData` (Task 4), `EvolutionPoint` (Task 4, for sparkline series), `useApiData`, `formatBRL`, `CHART_COLORS`/`SERIES`, Recharts `Sparkline` via `LineChart`.
- Produces: `HeroSummaryCard` default export, props `{ apiUrl: string }`. It fetches the summary endpoint for the hero/KPIs; it optionally fetches the evolution endpoint (passed as a second data-attr `data-spark-url`) for sparklines. `KpiTile` named/default export, props `{ label: string; value: string; deltaPct: number | null; spark?: number[]; invertDelta?: boolean }`.

> Note: deltas — for **Gastos**, an increase is "bad". Pass `invertDelta` so the chip colors red on increase. For Renda/Saldo, increase is green.

- [ ] **Step 1: Create `KpiTile`**

Create `src/backend/frontend/src/cards/KpiTile.tsx`:

```tsx
import { Line, LineChart, ResponsiveContainer } from "recharts";
import type { SparkPoint } from "../types";
import { CHART_COLORS } from "../theme";

interface Props {
  label: string;
  value: string; // already formatted (e.g. "R$ 1.234,56" or "198%")
  deltaPct: number | null;
  spark?: number[];
  invertDelta?: boolean;
}

export default function KpiTile({ label, value, deltaPct, spark, invertDelta }: Props) {
  const up = (deltaPct ?? 0) >= 0;
  // "good" = green. For inverted metrics (Gastos), up is bad.
  const good = invertDelta ? !up : up;
  const sparkData: SparkPoint[] = (spark ?? []).map((v) => ({ v }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm tile-hover">
      <div className="card-body p-3 gap-1">
        <div className="text-[11px] uppercase tracking-wide opacity-60">{label}</div>
        <div className="amount text-2xl font-bold leading-none whitespace-nowrap">{value}</div>
        <div className="flex items-center justify-between gap-2">
          {deltaPct === null ? (
            <span className="text-[11px] opacity-50">—</span>
          ) : (
            <span className={`text-[11px] font-semibold ${good ? "text-success" : "text-error"}`}>
              {up ? "▲" : "▼"} {Math.abs(deltaPct)}%
            </span>
          )}
          {sparkData.length > 1 && (
            <div className="h-6 w-16">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparkData}>
                  <Line
                    type="monotone"
                    dataKey="v"
                    stroke={CHART_COLORS[0]}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `HeroSummaryCard`**

Create `src/backend/frontend/src/cards/HeroSummaryCard.tsx`. The hero shows Saldo big; the KPI strip renders four `KpiTile`s. Sparklines for Renda/Gastos come from the evolution endpoint (`data-spark-url`); Retornos/Orçamento% have no reliable series → no sparkline (per spec).

```tsx
import { formatBRL } from "../format";
import type { EvolutionPoint, SummaryData } from "../types";
import { useApiData } from "../useApiData";
import KpiTile from "./KpiTile";

interface Props {
  apiUrl: string;
  sparkUrl?: string;
}

export default function HeroSummaryCard({ apiUrl, sparkUrl }: Props) {
  const data = useApiData<SummaryData>(apiUrl);
  const evo = useApiData<EvolutionPoint[]>(sparkUrl ?? "");

  if (!data)
    return <div className="card bg-base-100 border border-base-300 shadow-md animate-pulse h-48" />;

  const balance = parseFloat(data.balance);
  const bDelta = data.delta_pct.balance;
  const up = (bDelta ?? 0) >= 0;

  const incomeSpark = evo?.map((p) => parseFloat(p.income)) ?? [];
  const expenseSpark = evo?.map((p) => parseFloat(p.expenses)) ?? [];

  return (
    <div className="card bg-gradient-to-br from-primary/10 to-base-100 border border-base-300 shadow-md">
      <div className="card-body p-5 gap-3">
        <div className="text-[11px] uppercase tracking-wide opacity-60">Saldo do mês</div>
        <div className="flex items-baseline gap-3 flex-wrap">
          <span
            className={`amount font-display text-4xl md:text-5xl font-bold leading-none ${
              balance >= 0 ? "text-base-content" : "text-error"
            }`}
          >
            {formatBRL(data.balance)}
          </span>
          {bDelta !== null && (
            <span className={`text-sm font-semibold ${up ? "text-success" : "text-error"}`}>
              {up ? "▲" : "▼"} {Math.abs(bDelta)}%
            </span>
          )}
        </div>

        <div className="flex gap-6 text-sm">
          <span className="opacity-70">
            Renda <span className="amount font-bold text-success">{formatBRL(data.income)}</span>
          </span>
          <span className="opacity-70">
            Gastos <span className="amount font-bold text-error">{formatBRL(data.expenses)}</span>
          </span>
        </div>

        {data.budget_pct !== null && (
          <div>
            <div className="text-[11px] opacity-60 mb-1">Orçamento utilizado: {data.budget_pct}%</div>
            <progress
              className={`progress w-full ${
                data.budget_pct > 100
                  ? "progress-error"
                  : data.budget_pct > 90
                    ? "progress-warning"
                    : "progress-accent"
              }`}
              value={Math.min(data.budget_pct, 100)}
              max="100"
            />
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
          <KpiTile label="Renda" value={formatBRL(data.income)} deltaPct={data.delta_pct.income} spark={incomeSpark} />
          <KpiTile label="Gastos" value={formatBRL(data.expenses)} deltaPct={data.delta_pct.expenses} spark={expenseSpark} invertDelta />
          <KpiTile label="Retornos" value={formatBRL(data.returns)} deltaPct={data.delta_pct.returns} />
          <KpiTile
            label="Orçamento"
            value={data.budget_pct === null ? "—" : `${data.budget_pct}%`}
            deltaPct={null}
          />
        </div>
      </div>
    </div>
  );
}
```

> `useApiData("")` must no-op on empty URL. Verify `useApiData.ts` handles an empty string (it fetches in an effect keyed on `apiUrl`). If it would fetch `""`, guard it: in `HeroSummaryCard`, only render sparklines when `evo` is present, which already happens. If `npx tsc`/runtime shows a fetch to `""`, add an early `if (!apiUrl) return null;` guard inside `useApiData`'s effect (document this change in the report).

- [ ] **Step 3: Replace `SummaryCard` registration**

Delete `src/backend/frontend/src/cards/SummaryCard.tsx`. In `mount.tsx`, remove the `SummaryCard` import and COMPONENTS entry, and add:

```tsx
import HeroSummaryCard from "./cards/HeroSummaryCard";
```
```tsx
  HeroSummaryCard,
```

- [ ] **Step 4: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: zero errors (resolve any Recharts prop typing per the note in the prior feature; if `useApiData("")` typing complains, pass `sparkUrl ?? undefined` and guard).

- [ ] **Step 5: Commit**

```bash
git add src/backend/frontend/src/cards/KpiTile.tsx src/backend/frontend/src/cards/HeroSummaryCard.tsx src/backend/frontend/src/mount.tsx
git rm src/backend/frontend/src/cards/SummaryCard.tsx
git commit -m "feat(dashboard): HeroSummaryCard + KpiTile (hero Saldo, KPI strip, sparklines)"
```

---

## Task 6: Frontend — accent/signature/scale restyle (Economia, DailyTrend, Projection, Evolution)

**Files:**
- Modify: `src/backend/frontend/src/cards/EconomiaCard.tsx`
- Modify: `src/backend/frontend/src/cards/DailyTrendCard.tsx`
- Modify: `src/backend/frontend/src/cards/ProjectionCard.tsx`
- Modify: `src/backend/frontend/src/cards/EvolutionCard.tsx`

**Interfaces:** presentational only; no data-shape changes. Acceptance is `npx tsc --noEmit` + visual verification (Task 10).

- [ ] **Step 1: EconomiaCard accent**

In `EconomiaCard.tsx`, change the outer card wrapper (the non-loading branch) to an accent treatment and enlarge the value. Replace the outer `div` className `card bg-base-100 border border-base-300 shadow-sm` with:

```tsx
    <div className="card bg-gradient-to-br from-secondary/15 to-base-100 border border-base-300 shadow-md">
```

And bump the value size: change the economia value line `text-2xl` → `text-3xl`. (Keep the existing green/amber `text-success`/`text-warning` logic and the `has_baseline` states unchanged.)

- [ ] **Step 2: DailyTrendCard signature size**

In `DailyTrendCard.tsx`, increase the chart height for the signature role: change the `ResponsiveContainer` `height={160}` to `height={240}`. (Layout width comes from the template span in Task 8; no class change needed here.)

- [ ] **Step 3: ProjectionCard + EvolutionCard title scale**

In both `ProjectionCard.tsx` and `EvolutionCard.tsx`, the card title currently uses `card-title text-sm`. Leave the headline numbers as-is but make the small section title consistent with the new scale: where the title is a plain `<h3 className="card-title text-sm">Evolução</h3>`, change to:

```tsx
        <h3 className="text-[11px] uppercase tracking-wide opacity-60">Evolução</h3>
```

Apply the same pattern to `ProjectionCard.tsx`'s `<h3 className="card-title text-sm">Projeção</h3>` → `<h3 className="text-[11px] uppercase tracking-wide opacity-60">Projeção</h3>`. Do NOT touch the chart logic.

- [ ] **Step 4: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add src/backend/frontend/src/cards/EconomiaCard.tsx src/backend/frontend/src/cards/DailyTrendCard.tsx src/backend/frontend/src/cards/ProjectionCard.tsx src/backend/frontend/src/cards/EvolutionCard.tsx
git commit -m "feat(dashboard): accent Economia, signature DailyTrend, title scale"
```

---

## Task 7: Frontend — `TopCategoriesCard` donut

**Files:**
- Modify: `src/backend/frontend/src/cards/TopCategoriesCard.tsx`

**Interfaces:** Consumes `CategoryData[]` (now possibly including an `"Outros"` item from Task 3), `CHART_COLORS`, `formatBRL`, Recharts `PieChart`.

- [ ] **Step 1: Rewrite as a donut**

Replace the body of `TopCategoriesCard.tsx` (keep the loading + empty states; swap the ranked-bars block for a donut + legend):

```tsx
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { formatBRL } from "../format";
import type { CategoryData } from "../types";
import EmptyState from "../components/EmptyState";
import { CHART_COLORS } from "../theme";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

export default function TopCategoriesCard({ apiUrl }: Props) {
  const data = useApiData<CategoryData[]>(apiUrl);

  if (!data)
    return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  if (data.length === 0) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="text-[11px] uppercase tracking-wide opacity-60">Top Categorias</h3>
          <EmptyState
            emoji="🏷️"
            title="Sem categorias"
            description="Categorize suas despesas para ver o ranking"
            actionHref="/settings/"
            actionLabel="Configurações"
          />
        </div>
      </div>
    );
  }

  const slices = data.map((c) => ({ name: c.name, value: parseFloat(c.amount), pct: c.pct }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm tile-hover">
      <div className="card-body p-4">
        <h3 className="text-[11px] uppercase tracking-wide opacity-60">Top Categorias</h3>
        <div className="flex items-center gap-3">
          <div className="w-32 h-32 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={40}
                  outerRadius={62}
                  paddingAngle={2}
                  isAnimationActive={false}
                >
                  {slices.map((s, i) => (
                    <Cell
                      key={s.name}
                      fill={
                        s.name === "Outros"
                          ? "var(--color-base-300, #ccc)"
                          : CHART_COLORS[i % CHART_COLORS.length]
                      }
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatBRL(v)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-1 text-xs">
            {slices.map((s, i) => (
              <li key={s.name} className="flex items-center gap-2">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                  style={{
                    backgroundColor:
                      s.name === "Outros" ? "#bbb" : CHART_COLORS[i % CHART_COLORS.length],
                  }}
                />
                <span className="opacity-70 truncate">{s.name}</span>
                <span className="ml-auto amount font-bold whitespace-nowrap">{formatBRL(s.value)}</span>
                <span className="opacity-50 w-10 text-right">{s.pct}%</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
```

> The "média 3m / acima / abaixo" annotation is dropped from this card in the donut form (it lived in the bars). The above/below signal already lives elsewhere; do not re-add it here. Note this consciously in the report (spec replaced bars with donut).

- [ ] **Step 2: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add src/backend/frontend/src/cards/TopCategoriesCard.tsx
git commit -m "feat(dashboard): TopCategories donut with Outros slice"
```

---

## Task 8: Frontend — quiet tier + bento template wiring

**Files:**
- Modify: `src/backend/frontend/src/cards/AlertsCard.tsx`, `cards/RecentEntriesCard.tsx`, `cards/InstallmentsCard.tsx`
- Modify: `src/backend/templates/dashboard/dashboard_page.html`

**Interfaces:** presentational + layout. Acceptance = `npx tsc --noEmit` + visual verification.

- [ ] **Step 1: Quiet tier on the three list cards**

In each of `AlertsCard.tsx`, `RecentEntriesCard.tsx`, `InstallmentsCard.tsx`, change the outer card wrapper from `card bg-base-100 border border-base-300 shadow-sm` to the quiet treatment:

```tsx
    <div className="card bg-base-200 border border-base-200">
```

Apply to ALL return branches in each file (loading skeleton can keep `bg-base-200`). Also update each card's `<h3 className="card-title text-sm">…</h3>` to `<h3 className="text-[11px] uppercase tracking-wide opacity-60">…</h3>`. Do not change list logic.

- [ ] **Step 2: Rewrite the dashboard grid as bento**

Replace the `#dashboard-cards` grid block in `src/backend/templates/dashboard/dashboard_page.html` with the 12-col bento. Each tile gets `bento-enter` and a staggered `animation-delay` inline style. `HeroSummaryCard` carries a `data-spark-url` for KPI sparklines.

```html
<!-- React island cards grid (bento) -->
<div class="grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-4 auto-rows-min" id="dashboard-cards">
    <div class="bento-enter md:col-span-4 lg:col-span-8" style="animation-delay:0ms"
         data-react-component="HeroSummaryCard"
         data-api-url="/api/dashboard/summary/?{{ api_params }}"
         data-spark-url="/api/dashboard/evolution/?{{ api_params }}"></div>
    <div class="bento-enter md:col-span-2 lg:col-span-4" style="animation-delay:60ms"
         data-react-component="EconomiaCard" data-api-url="/api/dashboard/diverse-savings/?{{ api_params }}"></div>

    <div class="bento-enter md:col-span-6 lg:col-span-12" style="animation-delay:120ms"
         data-react-component="DailyTrendCard" data-api-url="/api/dashboard/daily-trend/"></div>

    <div class="bento-enter md:col-span-3 lg:col-span-7" style="animation-delay:180ms"
         data-react-component="ProjectionCard" data-api-url="/api/dashboard/projection/?{{ api_params }}"></div>
    <div class="bento-enter md:col-span-3 lg:col-span-5" style="animation-delay:240ms"
         data-react-component="TopCategoriesCard" data-api-url="/api/dashboard/top-categories/?{{ api_params }}"></div>

    <div class="bento-enter md:col-span-3 lg:col-span-7" style="animation-delay:300ms"
         data-react-component="EvolutionCard" data-api-url="/api/dashboard/evolution/?{{ api_params }}"></div>
    <div class="bento-enter md:col-span-3 lg:col-span-5" style="animation-delay:360ms"
         data-react-component="AlertsCard" data-api-url="/api/dashboard/alerts/?{{ api_params }}"></div>

    <div class="bento-enter md:col-span-3 lg:col-span-6" style="animation-delay:420ms"
         data-react-component="RecentEntriesCard" data-api-url="/api/dashboard/recent-entries/?{{ api_params }}"></div>
    <div class="bento-enter md:col-span-3 lg:col-span-6" style="animation-delay:480ms"
         data-react-component="InstallmentsCard" data-api-url="/api/dashboard/installments/?{{ api_params }}"></div>
</div>
```

> `HeroSummaryCard` must read `data-spark-url`. The mount mechanism currently passes only `apiUrl` (see `mount.tsx`). Update `mount.tsx`'s mounting loop to also read `data-spark-url` and pass it as the `sparkUrl` prop. In `mount.tsx`, where it reads `const apiUrl = el.getAttribute("data-api-url") || "";`, add `const sparkUrl = el.getAttribute("data-spark-url") || undefined;` and render `<Component apiUrl={apiUrl} sparkUrl={sparkUrl} />`. The shared component type must allow the optional prop: change the `COMPONENTS` record type to `React.ComponentType<{ apiUrl: string; sparkUrl?: string }>`.

- [ ] **Step 3: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add src/backend/frontend/src/cards/AlertsCard.tsx src/backend/frontend/src/cards/RecentEntriesCard.tsx src/backend/frontend/src/cards/InstallmentsCard.tsx src/backend/frontend/src/mount.tsx src/backend/templates/dashboard/dashboard_page.html
git commit -m "feat(dashboard): quiet list tier + 12-col bento grid + stagger"
```

---

## Task 9: Build & commit frontend artifacts

**Files:** `src/backend/static/frontend/mount.js`, `src/backend/static/css/tailwind.css`

- [ ] **Step 1: Build JS** — `cd src/backend/frontend && npm run build` (zero TS errors).
- [ ] **Step 2: Build Tailwind** — `cd src/backend && uv run python manage.py tailwind build --force`.
- [ ] **Step 3: Verify new classes landed**

Run: `grep -c "col-span-8" src/backend/static/css/tailwind.css; grep -c "bento-enter" src/backend/static/css/tailwind.css; grep -c "from-primary" src/backend/static/css/tailwind.css`
Expected: each ≥ 1. (If any is 0, re-run Step 2 — `--force` must scan the new template/CSS classes.)

- [ ] **Step 4: Commit**

```bash
git add src/backend/static/frontend/mount.js src/backend/static/css/tailwind.css
git commit -m "build(dashboard): rebuild mount.js + tailwind.css for redesign"
```

---

## Task 10: Visual verification (MANDATORY)

Per spec §"Verificação visual". Requires the running app, logged in, with rich data (use the dev DB on :5433; user `bessavagner` has ~2000 entries; mint a session cookie as in the prior feature, or use `/run`).

**Files:** none (produces screenshot evidence under `docs/superpowers/evidence/2026-06-22-dashboard-redesign/`).

- [ ] **Step 1: Run the worktree server** on a free port against `POSTGRES_PORT=5433`, `DEBUG=True`; authenticate (session cookie for `bessavagner`).
- [ ] **Step 2: Desktop (lg, ~1280px)** — screenshot full page. Confirm: hero Saldo dominates (largest type); Economia is the colored accent; Tendência spans full width; lists (Alertas/Entradas/Parcelas) visibly recede (`bg-base-200`, no shadow); KPI strip shows delta chips + sparklines for Renda/Gastos.
- [ ] **Step 3: Donut** — screenshot Top Categorias; confirm the donut renders and the "Outros" slice/legend appears when there are >5 categories and totals reconcile.
- [ ] **Step 4: md breakpoint (~820px)** — resize; screenshot; confirm tiles reflow (KPIs 2×2, two-up rows) without breakage.
- [ ] **Step 5: Mobile (390×844)** — screenshot; confirm single column in priority order, nothing clipped.
- [ ] **Step 6: Motion** — confirm the entrance stagger plays on load; then emulate `prefers-reduced-motion: reduce` (Playwright `page.emulateMedia({ reducedMotion: 'reduce' })`) and reload; confirm tiles appear with no animation.
- [ ] **Step 7: Console** — confirm 0 console errors on load.
- [ ] **Step 8: Evidence + gate** — save screenshots under `docs/superpowers/evidence/2026-06-22-dashboard-redesign/`; then run:
  - `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_api_dashboard.py -v`
  - `uv run ruff check src/backend/finances`
  - `cd src/backend/frontend && npx tsc --noEmit`
  Expected: all green. Iterate (fix → rebuild → recapture) on any divergence before declaring done.

---

## Self-Review (completed by plan author)

- **Spec coverage:** bento layout → Task 8; 3 elevation tiers → Hero/Economia (T5/T6), medium (default), quiet (T8); typography scale → T5/T6/T8 titles + hero; star cards → Saldo hero (T5), Economia accent (T6), Tendência signature (T6 height + T8 span), Projeção highlight (T6/T8 span); KPI strip + delta chips + sparklines → T1+T5; donut + "Outros" → T3+T7; Evolution returns/sparkline data → T2; motion + reduced-motion → T4+T8; API additive changes → T1/T2/T3; build artifacts → T9; mandatory visual verification (3 breakpoints + states) → T10. All mapped.
- **Type consistency:** `SummaryData.prev`/`delta_pct` (T4) consumed in T5; `EvolutionPoint.returns` (T4) consumed by hero sparklines (T5); `CategoryData` "Outros" item (T3) consumed by donut (T7); `KpiTile` props match `HeroSummaryCard` usage; `mount.tsx` component type widened to `{apiUrl; sparkUrl?}` in T8 matches `HeroSummaryCard` props in T5.
- **Placeholders:** none — full code for backend + new components; restyles specified as exact class-string changes. Three NOTE callouts flag judgment points (empty `useApiData` guard, dropped média-3m annotation, mount `data-spark-url` wiring) to confirm at implementation, not deferred work.
- **Note on frontend "tests":** these cards are presentational; per Global Constraints the gate is `npx tsc --noEmit` + the mandatory Task 10 visual verification, not pytest. Backend tasks (T1–T3) carry real pytest TDD.
```
