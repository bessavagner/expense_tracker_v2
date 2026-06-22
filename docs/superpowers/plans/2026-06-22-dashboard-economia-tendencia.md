# Dashboard: Economia do mês + Tendência de gasto diário — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two dashboard indicators — a "Economia do mês" KPI card (how much less was spent on diversas vs the robust historical baseline) and a "Tendência de gasto diário" chart (daily spend smoothed by a rolling median + IQR band, with a 7/15/30/90-day period selector).

**Architecture:** Two new backend service functions feed two new DRF APIViews, each registered under `/api/dashboard/`. Two new React island cards (Recharts) consume them and are mounted into the existing dashboard grid via `data-react-component`. The robust baseline reuses the existing `monthly_diverse_total_median`.

**Tech Stack:** Django + DRF (backend), pytest (tests), React 18 + Recharts 2 + TypeScript + Vite (frontend island), Tailwind/daisyUI (styling).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-22-dashboard-economia-tendencia-design.md` — implement exactly.
- **TDD + worktree:** Work in an isolated git worktree (project rule). Write the failing test first, watch it fail, implement minimal, watch it pass, commit. Small frequent commits.
- **"Diversas" = `Entry.entry_type == EntryType.REGULAR`**, `amount__gt=0`, **excluding** the adjustment category — `.exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)` (constant lives in `finances/services/category_stats.py`, value `"ajuste"`).
- **Economia uses `billing_month`** (consistent with `SummaryView`). **Daily trend uses `date`** (real transaction date) and ignores the month selector.
- **Band = IQR (p25–p75)**, percentiles by linear interpolation. Money is `Decimal`, quantized to cents (`Decimal("0.01")`, `ROUND_HALF_UP`).
- **Rolling-window map (period → rolling):** `{7: 3, 15: 5, 30: 7, 90: 15}`. Invalid period → clamp to 30.
- **Test DB:** pgvector container on port 5433 must be up (project rule). Run tests with `uv run pytest` from repo root (`testpaths = src/backend`, `DJANGO_SETTINGS_MODULE=config.settings`).
- **Frontend build artifacts are git-tracked.** After any FE change rebuild and commit BOTH:
  - JS: `cd src/backend/frontend && npm run build` → `src/backend/static/frontend/mount.js`
  - CSS: `cd src/backend && uv run python manage.py tailwind build --force` → `src/backend/static/css/tailwind.css`
- **Visual verification is mandatory** (spec §"Verificação visual"): screenshots of both cards, multiple periods, desktop + mobile, before declaring done.

---

## File Structure

**Backend**
- Modify `src/backend/finances/services/category_stats.py` — add `diverse_savings_for_month`; add `_percentile` helper (or reuse for both modules).
- Create `src/backend/finances/services/daily_trend.py` — `daily_spend_trend` + period→rolling map.
- Modify `src/backend/finances/api/views.py` — add `DiverseSavingsView`, `DailyTrendView`.
- Modify `src/backend/finances/api/urls.py` — register both routes.
- Create `src/backend/finances/tests/test_diverse_savings.py`
- Create `src/backend/finances/tests/test_daily_trend.py`
- Modify `src/backend/finances/tests/test_api_dashboard.py` — API contract tests for both endpoints.

**Frontend** (`src/backend/frontend/src/`)
- Modify `types.ts` — `DiverseSavingsData`, `DailyTrendPoint`, `DailyTrendData`.
- Create `cards/EconomiaCard.tsx`
- Create `cards/DailyTrendCard.tsx`
- Modify `mount.tsx` — register both components.
- Modify `src/backend/templates/dashboard/dashboard_page.html` — add two grid cells.

---

## Task 1: Backend — `diverse_savings_for_month` service

**Files:**
- Modify: `src/backend/finances/services/category_stats.py`
- Test: `src/backend/finances/tests/test_diverse_savings.py`

**Interfaces:**
- Consumes: `monthly_diverse_total_median(user, window, as_of)` (existing), `ADJUSTMENT_CATEGORY_PATTERN` (existing), `Entry`, `EntryType`.
- Produces: `diverse_savings_for_month(user, billing_month: date, window: int = 6) -> dict` returning keys `baseline: Decimal`, `actual: Decimal`, `economia: Decimal`, `has_baseline: bool`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_diverse_savings.py`. Use the existing test fixtures/patterns from `test_category_stats.py` for creating users/categories/entries (read it first to match helper style: user, `Category`, `PaymentMethod`, `Entry` creation). Then:

```python
from datetime import date
from decimal import Decimal

import pytest

from finances.models import Category, Entry, PaymentMethod
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.category_stats import diverse_savings_for_month

pytestmark = pytest.mark.django_db


def _mk(user, *, billing_month, amount, category, pm, entry_type=EntryType.REGULAR):
    return Entry.objects.create(
        user=user,
        date=billing_month,
        amount=Decimal(amount),
        description="x",
        category=category,
        payment_method=pm,
        entry_type=entry_type,
        billing_month=billing_month,
        billing_month_override=True,
    )


@pytest.fixture
def setup(django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    cat = Category.objects.create(user=user, name="Mercado")
    adj = Category.objects.create(user=user, name="Ajuste de saldo")
    pm = PaymentMethod.objects.create(
        user=user, name="Pix", type=PaymentType.PIX
    )
    return user, cat, adj, pm


def test_economia_positive_when_below_robust_baseline(setup):
    user, cat, adj, pm = setup
    # Prior 6 months: 1000 each -> median baseline 1000.
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pm)
    # Current month (julho): spent only 600.
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pm)

    out = diverse_savings_for_month(user, date(2025, 7, 1))

    assert out["baseline"] == Decimal("1000")
    assert out["actual"] == Decimal("600")
    assert out["economia"] == Decimal("400")
    assert out["has_baseline"] is True


def test_economia_negative_when_above_baseline(setup):
    user, cat, adj, pm = setup
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pm)
    _mk(user, billing_month=date(2025, 7, 1), amount="1500", category=cat, pm=pm)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["economia"] == Decimal("-500")


def test_outlier_month_does_not_break_baseline(setup):
    user, cat, adj, pm = setup
    # Five months at 1000, one wild outlier at 9000 -> median still 1000.
    for m in range(1, 6):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pm)
    _mk(user, billing_month=date(2025, 6, 1), amount="9000", category=cat, pm=pm)
    _mk(user, billing_month=date(2025, 7, 1), amount="1000", category=cat, pm=pm)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["baseline"] == Decimal("1000")


def test_adjustment_entries_excluded_from_actual(setup):
    user, cat, adj, pm = setup
    for m in range(1, 7):
        _mk(user, billing_month=date(2025, m, 1), amount="1000", category=cat, pm=pm)
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pm)
    # #AJUSTE-SALDO entry must NOT inflate actual.
    _mk(user, billing_month=date(2025, 7, 1), amount="5000", category=adj, pm=pm)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["actual"] == Decimal("600")


def test_no_history_has_baseline_false(setup):
    user, cat, adj, pm = setup
    _mk(user, billing_month=date(2025, 7, 1), amount="600", category=cat, pm=pm)

    out = diverse_savings_for_month(user, date(2025, 7, 1))
    assert out["baseline"] == Decimal("0")
    assert out["has_baseline"] is False
    assert out["economia"] == Decimal("-600")
```

> NOTE: First open `src/backend/finances/tests/test_category_stats.py` and `tests/conftest.py`. If they expose a ready user/category/payment_method fixture, use it instead of the inline fixture above to match house style. Confirm the `PaymentType` enum member name (`PIX`) — adjust if the project uses a different member.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_diverse_savings.py -v`
Expected: FAIL — `ImportError: cannot import name 'diverse_savings_for_month'`.

- [ ] **Step 3: Write minimal implementation**

In `src/backend/finances/services/category_stats.py`, add (after `monthly_diverse_total_median`):

```python
def diverse_savings_for_month(user, billing_month, window=6) -> dict:
    """Economia em diversas vs o padrão histórico robusto.

    baseline = mediana das diversas dos ``window`` meses anteriores (robusta a
    outliers); actual = total de diversas (REGULAR, >0, exclui #AJUSTE) no
    ``billing_month``. economia = baseline - actual (>0 => gastou menos que o
    habitual).
    """
    baseline = monthly_diverse_total_median(user, window=window, as_of=billing_month)
    actual = (
        Entry.objects.filter(
            user=user,
            amount__gt=0,
            entry_type=EntryType.REGULAR,
            billing_month=billing_month,
        )
        .exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    return {
        "baseline": baseline,
        "actual": actual,
        "economia": baseline - actual,
        "has_baseline": baseline > 0,
    }
```

`Sum` is already imported at the top of the file; `Decimal`, `Entry`, `EntryType`, `ADJUSTMENT_CATEGORY_PATTERN` are already in scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_diverse_savings.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/services/category_stats.py src/backend/finances/tests/test_diverse_savings.py
git commit -m "feat(dashboard): diverse_savings_for_month service (robust baseline)"
```

---

## Task 2: Backend — `daily_spend_trend` service

**Files:**
- Create: `src/backend/finances/services/daily_trend.py`
- Test: `src/backend/finances/tests/test_daily_trend.py`

**Interfaces:**
- Consumes: `Entry`, `ADJUSTMENT_CATEGORY_PATTERN` (import from `category_stats`).
- Produces:
  - `ROLLING_BY_PERIOD: dict[int, int]` = `{7: 3, 15: 5, 30: 7, 90: 15}`
  - `daily_spend_trend(user, period: int = 30, as_of: date | None = None) -> list[dict]`, each dict `{"date": date, "median": Decimal, "p25": Decimal, "p75": Decimal}`, oldest first, length == `period`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_daily_trend.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest

from finances.models import Category, Entry, PaymentMethod
from finances.models.entry import EntryType
from finances.models.payment_method import PaymentType
from finances.services.daily_trend import ROLLING_BY_PERIOD, daily_spend_trend

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    cat = Category.objects.create(user=user, name="Mercado")
    adj = Category.objects.create(user=user, name="Ajuste de saldo")
    pm = PaymentMethod.objects.create(user=user, name="Pix", type=PaymentType.PIX)
    return user, cat, adj, pm


def _mk(user, *, d, amount, category, pm):
    return Entry.objects.create(
        user=user,
        date=d,
        amount=Decimal(amount),
        description="x",
        category=category,
        payment_method=pm,
        entry_type=EntryType.REGULAR,
        billing_month=d.replace(day=1),
        billing_month_override=True,
    )


def test_series_length_and_order(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    series = daily_spend_trend(user, period=30, as_of=as_of)
    assert len(series) == 30
    assert series[0]["date"] == date(2025, 7, 1)
    assert series[-1]["date"] == as_of


def test_days_without_spend_count_as_zero(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    # No entries at all -> every rolling stat is 0.
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert all(p["median"] == Decimal("0") for p in series)
    assert all(p["p75"] == Decimal("0") for p in series)


def test_groups_by_real_date(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    # 100 on each of the last 3 days -> rolling(7d period -> window 3) median 100 at as_of.
    for k in range(3):
        _mk(user, d=as_of - timedelta(days=k), amount="100", category=cat, pm=pm)
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert series[-1]["median"] == Decimal("100")


def test_robust_to_single_outlier(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 30)
    # period 30 -> rolling 7. Put 50 on each of last 7 days, one of them 5000.
    for k in range(7):
        amount = "5000" if k == 3 else "50"
        _mk(user, d=as_of - timedelta(days=k), amount=amount, category=cat, pm=pm)
    series = daily_spend_trend(user, period=30, as_of=as_of)
    # Median of [50,50,50,5000,50,50,50] is 50 — outlier does not move the line.
    assert series[-1]["median"] == Decimal("50")
    # But the band's upper edge (p75) is still 50 here (only one high value);
    # the point is the central line stays robust.


def test_iqr_band(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    # window of 3 (period 7): values 10, 20, 30 over last 3 days.
    _mk(user, d=as_of, amount="30", category=cat, pm=pm)
    _mk(user, d=as_of - timedelta(days=1), amount="20", category=cat, pm=pm)
    _mk(user, d=as_of - timedelta(days=2), amount="10", category=cat, pm=pm)
    series = daily_spend_trend(user, period=7, as_of=as_of)
    last = series[-1]
    # sorted [10,20,30]: median=20, p25=15, p75=25 (linear interpolation).
    assert last["median"] == Decimal("20")
    assert last["p25"] == Decimal("15.00")
    assert last["p75"] == Decimal("25.00")


def test_adjustment_excluded(setup):
    user, cat, adj, pm = setup
    as_of = date(2025, 7, 7)
    _mk(user, d=as_of, amount="5000", category=adj, pm=pm)  # #AJUSTE
    series = daily_spend_trend(user, period=7, as_of=as_of)
    assert series[-1]["median"] == Decimal("0")


def test_invalid_period_clamps_to_30(setup):
    user, cat, adj, pm = setup
    series = daily_spend_trend(user, period=999, as_of=date(2025, 7, 30))
    assert len(series) == 30


def test_rolling_map():
    assert ROLLING_BY_PERIOD == {7: 3, 15: 5, 30: 7, 90: 15}
```

> NOTE: Confirm `PaymentType.PIX` member name against `finances/models/payment_method.py`; adjust if different.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_daily_trend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finances.services.daily_trend'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/backend/finances/services/daily_trend.py`:

```python
"""Daily spend trend, smoothed by a rolling median + IQR band (robust to outliers)."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from finances.models import Entry
from finances.services.category_stats import ADJUSTMENT_CATEGORY_PATTERN

_CENTS = Decimal("0.01")

# Period (x-axis span, days) -> rolling window (days) for the median/IQR.
# The window stays well under the period so the smoothed series has real points.
ROLLING_BY_PERIOD = {7: 3, 15: 5, 30: 7, 90: 15}
_DEFAULT_PERIOD = 30


def _percentile(values: list[Decimal], q: Decimal) -> Decimal:
    """Linear-interpolation percentile. ``q`` in [0, 1]."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return Decimal("0")
    if n == 1:
        return xs[0]
    pos = q * (n - 1)
    lo = int(pos)
    if lo + 1 >= n:
        return xs[lo]
    frac = pos - lo
    return (xs[lo] + (xs[lo + 1] - xs[lo]) * frac).quantize(_CENTS, rounding=ROUND_HALF_UP)


def daily_spend_trend(user, period=30, as_of=None) -> list[dict]:
    """Rolling median + IQR (p25/p75) of daily spend over the last ``period`` days.

    Daily spend = Σ ``Entry.amount`` (>0, excluding #AJUSTE) grouped by the real
    ``date``; missing days count as 0. Each output point applies the rolling
    window (see ``ROLLING_BY_PERIOD``) ending on that day. Oldest first.
    """
    if period not in ROLLING_BY_PERIOD:
        period = _DEFAULT_PERIOD
    as_of = as_of or date.today()
    rolling = ROLLING_BY_PERIOD[period]

    start_display = as_of - timedelta(days=period - 1)
    start_fetch = start_display - timedelta(days=rolling - 1)

    rows = (
        Entry.objects.filter(
            user=user, amount__gt=0, date__gte=start_fetch, date__lte=as_of
        )
        .exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)
        .values("date")
        .annotate(total=Sum("amount"))
    )
    by_day = {r["date"]: r["total"] for r in rows}

    out = []
    for i in range(period):
        day = start_display + timedelta(days=i)
        window = [
            by_day.get(day - timedelta(days=k), Decimal("0")) for k in range(rolling)
        ]
        out.append(
            {
                "date": day,
                "median": _percentile(window, Decimal("0.5")),
                "p25": _percentile(window, Decimal("0.25")),
                "p75": _percentile(window, Decimal("0.75")),
            }
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_daily_trend.py -v`
Expected: PASS (8 passed).

> If `test_iqr_band` fails on exact cents, inspect the printed values and align the assertion with the linear-interpolation result actually produced — do not weaken the rounding, fix the expected literal.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/services/daily_trend.py src/backend/finances/tests/test_daily_trend.py
git commit -m "feat(dashboard): daily_spend_trend service (rolling median + IQR)"
```

---

## Task 3: Backend — API endpoints + routes

**Files:**
- Modify: `src/backend/finances/api/views.py`
- Modify: `src/backend/finances/api/urls.py`
- Test: `src/backend/finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: `diverse_savings_for_month`, `daily_spend_trend`, existing `_get_month_params`.
- Produces routes:
  - `GET /api/dashboard/diverse-savings/?year=&month=` → `{baseline, actual, economia, has_baseline}` (money as `"%.2f"` strings).
  - `GET /api/dashboard/daily-trend/?period=7|15|30|90` → `{period: int, series: [{date: "YYYY-MM-DD", median, p25, p75}]}`.

- [ ] **Step 1: Write the failing test**

First read `src/backend/finances/tests/test_api_dashboard.py` to match its client/login fixture style (how it authenticates and what URL base it uses). Then append tests modeled on the existing ones, e.g.:

```python
def test_diverse_savings_endpoint(auth_client, ...):  # match existing fixture names
    resp = auth_client.get("/api/dashboard/diverse-savings/?year=2025&month=7")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"baseline", "actual", "economia", "has_baseline"}
    assert isinstance(body["has_baseline"], bool)


def test_diverse_savings_requires_auth(client):
    resp = client.get("/api/dashboard/diverse-savings/?year=2025&month=7")
    assert resp.status_code in (401, 403)


def test_daily_trend_endpoint(auth_client, ...):
    resp = auth_client.get("/api/dashboard/daily-trend/?period=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period"] == 7
    assert len(body["series"]) == 7
    point = body["series"][0]
    assert set(point) == {"date", "median", "p25", "p75"}


def test_daily_trend_invalid_period_clamps(auth_client, ...):
    resp = auth_client.get("/api/dashboard/daily-trend/?period=999")
    assert resp.json()["period"] == 30


def test_daily_trend_requires_auth(client):
    resp = client.get("/api/dashboard/daily-trend/?period=7")
    assert resp.status_code in (401, 403)
```

> Replace `auth_client, ...` with the actual authenticated-client fixture used by the existing tests in that file. Match the existing tests' auth-failure status code expectation (use whatever the file already asserts for unauthenticated requests).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_api_dashboard.py -v -k "diverse_savings or daily_trend"`
Expected: FAIL — 404 (routes not registered yet).

- [ ] **Step 3: Write minimal implementation**

In `src/backend/finances/api/views.py`, update the import and add two views:

```python
from finances.services.category_stats import (
    category_moving_averages,
    diverse_savings_for_month,
)
from finances.services.daily_trend import daily_spend_trend
```

```python
class DiverseSavingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        data = diverse_savings_for_month(request.user, billing_month)
        return Response(
            {
                "baseline": f"{data['baseline']:.2f}",
                "actual": f"{data['actual']:.2f}",
                "economia": f"{data['economia']:.2f}",
                "has_baseline": data["has_baseline"],
            }
        )


class DailyTrendView(APIView):
    permission_classes = [IsAuthenticated]
    ALLOWED = (7, 15, 30, 90)

    def get(self, request):
        try:
            period = int(request.query_params.get("period", 30))
        except (TypeError, ValueError):
            period = 30
        if period not in self.ALLOWED:
            period = 30
        series = daily_spend_trend(request.user, period=period)
        return Response(
            {
                "period": period,
                "series": [
                    {
                        "date": f"{p['date']:%Y-%m-%d}",
                        "median": f"{p['median']:.2f}",
                        "p25": f"{p['p25']:.2f}",
                        "p75": f"{p['p75']:.2f}",
                    }
                    for p in series
                ],
            }
        )
```

In `src/backend/finances/api/urls.py`, add the imports and routes:

```python
from finances.api.views import (
    AlertsView,
    DailyTrendView,
    DiverseSavingsView,
    EvolutionView,
    InstallmentsView,
    ProjectionCardView,
    RecentEntriesView,
    SummaryView,
    TopCategoriesView,
)
```
```python
    path("diverse-savings/", DiverseSavingsView.as_view(), name="api_diverse_savings"),
    path("daily-trend/", DailyTrendView.as_view(), name="api_daily_trend"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_api_dashboard.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/api/views.py src/backend/finances/api/urls.py src/backend/finances/tests/test_api_dashboard.py
git commit -m "feat(dashboard): diverse-savings + daily-trend API endpoints"
```

---

## Task 4: Frontend — types + EconomiaCard

**Files:**
- Modify: `src/backend/frontend/src/types.ts`
- Create: `src/backend/frontend/src/cards/EconomiaCard.tsx`

**Interfaces:**
- Consumes: `useApiData`, `formatBRL`.
- Produces: `EconomiaCard` default export, props `{ apiUrl: string }`; type `DiverseSavingsData`.

- [ ] **Step 1: Add the type**

In `src/backend/frontend/src/types.ts` add:

```typescript
export interface DiverseSavingsData {
  baseline: string;
  actual: string;
  economia: string;
  has_baseline: boolean;
}
```

- [ ] **Step 2: Create the card**

Create `src/backend/frontend/src/cards/EconomiaCard.tsx`:

```tsx
import { formatBRL } from "../format";
import type { DiverseSavingsData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

export default function EconomiaCard({ apiUrl }: Props) {
  const data = useApiData<DiverseSavingsData>(apiUrl);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  const economia = parseFloat(data.economia);
  const saved = economia >= 0;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Economia do mês</h3>

        {!data.has_baseline ? (
          <div className="text-xs opacity-60 mt-2">
            Sem base histórica ainda — registre mais meses de diversas.
          </div>
        ) : (
          <>
            <div className="text-[11px] uppercase tracking-wide opacity-60 mt-1">
              {saved ? "Economizou em diversas" : "Acima do habitual"}
            </div>
            <div
              className={`amount text-2xl font-bold ${saved ? "text-success" : "text-warning"}`}
            >
              {formatBRL(Math.abs(economia))}
            </div>
            <div className="text-[11px] opacity-60">
              habitual {formatBRL(data.baseline)} · gasto {formatBRL(data.actual)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Register in mount.tsx**

In `src/backend/frontend/src/mount.tsx` add the import and the COMPONENTS entry:

```tsx
import EconomiaCard from "./cards/EconomiaCard";
```
```tsx
  EconomiaCard,
```

- [ ] **Step 4: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/backend/frontend/src/types.ts src/backend/frontend/src/cards/EconomiaCard.tsx src/backend/frontend/src/mount.tsx
git commit -m "feat(dashboard): EconomiaCard React island"
```

---

## Task 5: Frontend — DailyTrendCard (chart + period selector)

**Files:**
- Modify: `src/backend/frontend/src/types.ts`
- Create: `src/backend/frontend/src/cards/DailyTrendCard.tsx`
- Modify: `src/backend/frontend/src/mount.tsx`

**Interfaces:**
- Consumes: `useApiData`, `formatBRL`, `formatBRLCompact`, `CHART_COLORS`, Recharts `ComposedChart/Area/Line`.
- Produces: `DailyTrendCard` default export, props `{ apiUrl: string }`; types `DailyTrendPoint`, `DailyTrendData`.
- The card owns the period in React state and fetches `${apiUrl}?period=${period}`. The template gives `apiUrl` WITHOUT query params for this card (the endpoint ignores year/month).

- [ ] **Step 1: Add the types**

In `src/backend/frontend/src/types.ts` add:

```typescript
export interface DailyTrendPoint {
  date: string;
  median: string;
  p25: string;
  p75: string;
}

export interface DailyTrendData {
  period: number;
  series: DailyTrendPoint[];
}
```

- [ ] **Step 2: Create the card**

Create `src/backend/frontend/src/cards/DailyTrendCard.tsx`. The IQR band is drawn as two stacked areas: a transparent base up to `p25`, then a filled band of height `p75 − p25`. The median is a line on top.

```tsx
import { useState } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import EmptyState from "../components/EmptyState";
import { formatBRL, formatBRLCompact } from "../format";
import { CHART_COLORS } from "../theme";
import type { DailyTrendData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

const MEDIAN = CHART_COLORS[0]; // teal — central line
const BAND = CHART_COLORS[1]; // slate blue — variability band
const PERIODS = [7, 15, 30, 90];

export default function DailyTrendCard({ apiUrl }: Props) {
  const [period, setPeriod] = useState(30);
  const data = useApiData<DailyTrendData>(`${apiUrl}?period=${period}`);

  const chartData =
    data?.series.map((p) => {
      const lo = parseFloat(p.p25);
      const hi = parseFloat(p.p75);
      return {
        date: p.date.slice(5), // "2025-07-03" → "07-03"
        median: parseFloat(p.median),
        base: lo, // transparent spacer
        band: hi - lo, // stacked filled band (p25..p75)
      };
    }) ?? [];

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="card-title text-sm">Tendência de gasto diário</h3>
          <select
            className="select select-bordered select-xs"
            value={period}
            onChange={(e) => setPeriod(Number(e.target.value))}
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {p} dias
              </option>
            ))}
          </select>
        </div>

        {!data ? (
          <div className="h-48 animate-pulse" />
        ) : chartData.length === 0 ? (
          <EmptyState
            emoji="📈"
            title="Sem dados"
            description="Registre gastos para ver a tendência diária"
          />
        ) : (
          <>
            <div className="text-[11px] opacity-60 mt-1">
              mediana móvel (robusta a picos) · faixa = variação típica (p25–p75)
            </div>
            <ResponsiveContainer width="100%" height={160} className="mt-1">
              <ComposedChart
                data={chartData}
                margin={{ top: 6, right: 4, bottom: 0, left: 0 }}
              >
                <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={20} />
                <YAxis
                  tick={{ fontSize: 10 }}
                  width={52}
                  tickFormatter={(v: number) => formatBRLCompact(v)}
                />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    formatBRL(value),
                    name === "median" ? "Mediana" : name,
                  ]}
                  labelFormatter={(l: string) => `Dia ${l}`}
                />
                {/* transparent spacer up to p25 */}
                <Area
                  type="monotone"
                  dataKey="base"
                  stackId="band"
                  stroke="none"
                  fill="none"
                  isAnimationActive={false}
                  legendType="none"
                  tooltipType="none"
                />
                {/* filled IQR band: p25..p75 */}
                <Area
                  type="monotone"
                  dataKey="band"
                  stackId="band"
                  stroke="none"
                  fill={BAND}
                  fillOpacity={0.18}
                  isAnimationActive={false}
                  legendType="none"
                  tooltipType="none"
                />
                <Line
                  type="monotone"
                  dataKey="median"
                  name="median"
                  stroke={MEDIAN}
                  strokeWidth={2}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </>
        )}
      </div>
    </div>
  );
}
```

> NOTE: `tooltipType="none"` may not exist on the installed Recharts type defs. If `npx tsc --noEmit` complains, remove those props (the spacer/band tooltip entries are cosmetic) or filter them in the `Tooltip formatter`.

- [ ] **Step 3: Register in mount.tsx**

```tsx
import DailyTrendCard from "./cards/DailyTrendCard";
```
```tsx
  DailyTrendCard,
```

- [ ] **Step 4: Type-check**

Run: `cd src/backend/frontend && npx tsc --noEmit`
Expected: no errors (resolve any Recharts prop-type issues per the note).

- [ ] **Step 5: Commit**

```bash
git add src/backend/frontend/src/types.ts src/backend/frontend/src/cards/DailyTrendCard.tsx src/backend/frontend/src/mount.tsx
git commit -m "feat(dashboard): DailyTrendCard React island (median + IQR band)"
```

---

## Task 6: Wire cards into the dashboard template

**Files:**
- Modify: `src/backend/templates/dashboard/dashboard_page.html`

**Interfaces:**
- Consumes: `data-react-component` mount mechanism, `{{ api_params }}` (year/month).
- EconomiaCard gets `?{{ api_params }}` (respects month). DailyTrendCard gets the bare endpoint (no params — it owns the period and ignores month).

- [ ] **Step 1: Add the two grid cells**

In `src/backend/templates/dashboard/dashboard_page.html`, inside `#dashboard-cards`, add (place EconomiaCard right after SummaryCard, and DailyTrendCard after EvolutionCard or at the end):

```html
    <div data-react-component="EconomiaCard" data-api-url="/api/dashboard/diverse-savings/?{{ api_params }}"></div>
    <div data-react-component="DailyTrendCard" data-api-url="/api/dashboard/daily-trend/"></div>
```

- [ ] **Step 2: Commit**

```bash
git add src/backend/templates/dashboard/dashboard_page.html
git commit -m "feat(dashboard): mount Economia + Tendência cards in grid"
```

---

## Task 7: Build & commit frontend artifacts

**Files:**
- Modify (generated): `src/backend/static/frontend/mount.js`, `src/backend/static/css/tailwind.css`

- [ ] **Step 1: Build JS**

Run: `cd src/backend/frontend && npm run build`
Expected: builds with no TS errors; `../static/frontend/mount.js` updated.

- [ ] **Step 2: Build Tailwind (with --force)**

Run: `cd src/backend && uv run python manage.py tailwind build --force`
Expected: `static/css/tailwind.css` regenerated (new classes used: `select-xs`, `text-warning`, etc. must be present).

- [ ] **Step 3: Verify new classes landed**

Run: `grep -c "select-xs" src/backend/static/css/tailwind.css`
Expected: ≥ 1 (if 0, the `--force` rebuild did not pick up the class — re-run Step 2).

- [ ] **Step 4: Commit**

```bash
git add src/backend/static/frontend/mount.js src/backend/static/css/tailwind.css
git commit -m "build(dashboard): rebuild mount.js + tailwind.css for new cards"
```

---

## Task 8: Visual verification (MANDATORY)

Per spec §"Verificação visual" — not optional. Requires a running app, logged in, with real data.

**Files:** none (produces screenshot evidence).

- [ ] **Step 1: Run the app & log in**

Use the project's run path (per memory: dev runs on `friday` at `192.168.1.7:8700`, or local `:8700`). Use the `/run` skill or the `playwright` MCP. Navigate to the dashboard logged in as a user with history.

- [ ] **Step 2: Screenshot EconomiaCard**

Capture the dashboard showing "Economia do mês". Confirm visually:
- value, color (green = economia / amber = acima do habitual), and the "habitual … · gasto …" caption render correctly;
- the "Sem base histórica ainda" state renders for a user/month without history (use a fresh month if needed).

- [ ] **Step 3: Screenshot DailyTrendCard at two periods**

Capture "Tendência de gasto diário". Confirm:
- the `ComposedChart` draws the median line and the shaded IQR band;
- the `<select>` exists and **changing 7 ↔ 90 dias re-renders the chart** — capture both 7-day and 90-day screenshots to compare.

- [ ] **Step 4: Mobile width**

Resize to mobile (e.g. 390×844) and screenshot both cards; confirm the grid is not broken.

- [ ] **Step 5: Record evidence & finalize**

Save the screenshots (e.g. under `.temp/` or attach to the PR) as verification evidence. If anything diverges from expected, iterate (fix → rebuild → re-capture) before declaring done.

- [ ] **Step 6: Full test + lint gate**

Run: `uv run pytest src/backend/finances/tests/test_diverse_savings.py src/backend/finances/tests/test_daily_trend.py src/backend/finances/tests/test_api_dashboard.py -v`
Run: `uv run ruff check src/backend/finances`
Expected: all green.

---

## Self-Review (completed by plan author)

- **Spec coverage:** Indicator 1 → Tasks 1, 3, 4, 6. Indicator 2 → Tasks 2, 3, 5, 6. Build artifacts → Task 7. Mandatory visual verification → Task 8. Tests → Tasks 1–3 (+8 gate). All spec sections mapped.
- **Type consistency:** `diverse_savings_for_month` keys (`baseline/actual/economia/has_baseline`) match the API serialization and `DiverseSavingsData`. `daily_spend_trend` point keys (`date/median/p25/p75`) match `DailyTrendPoint` and the API. `ROLLING_BY_PERIOD` used identically in service + test. `ALLOWED` periods in the API match the FE `PERIODS` and the rolling map keys.
- **Placeholders:** none — all code provided. Three NOTE callouts flag house-style fixture names, `PaymentType` member, and a Recharts prop-type fallback to confirm at implementation time (not deferred work).
```
