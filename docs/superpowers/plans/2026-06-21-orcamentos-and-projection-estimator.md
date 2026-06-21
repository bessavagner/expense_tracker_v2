# Orçamentos + Estimador mediana/teto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group categories into editable "orçamentos" with per-budget dashboard alerts, and let the projection screen estimate future "diversas" by either the historical median (current) or the planned ceiling.

**Architecture:** Phase 1 adds a `Budget` model + nullable FK `Category.budget`, a deterministic `budget_stats.py` service, a refactored `AlertsView` (per-budget alerts + individual alerts for orphan categories), and Settings UI (HTMX) for budget CRUD and category assignment. Phase 2 adds `monthly_diverse_total_ceiling` (built on Phase 1's consolidated ceiling), a `diverse_estimator` switch in `build_projection`, and a session-persisted toggle on the projection screen.

**Tech Stack:** Django + DRF (alerts API), HTMX + daisyUI/Tailwind templates, pytest + model_bakery, PostgreSQL (pgvector container on :5433 for tests/dev).

## Global Constraints

- **TDD + worktree + quality gates** per phase (project rule, non-negotiable).
- Tests: `pytest` run from `src/backend`. DB needs the pgvector container on **:5433** (not system Postgres).
- Money is `Decimal`; reconciliation entries (`#AJUSTE-SALDO`, category name contains "ajuste") are excluded from spend — reuse `finances.services.category_stats.ADJUSTMENT_CATEGORY_PATTERN`.
- One category belongs to at most one budget (FK `Category.budget`, `null=True`, `on_delete=SET_NULL`).
- Projection toggle default = **median**; lives in GET param **and** session (survives what-if POSTs). Never persisted on a model.
- Teto consolidado = `Σ Budget.amount` + `Σ budget_ceiling` of categories with `budget IS NULL`.
- If any template adds new Tailwind classes, rebuild + commit `mount.js` + `tailwind.css` (Tailwind needs `--force`).
- All paths below are relative to `src/backend/` unless noted.

---

# Phase 1 — Orçamentos

## File Structure (Phase 1)

- Create `finances/models/budget.py` — `Budget` model.
- Modify `finances/models/__init__.py` — export `Budget`.
- Modify `finances/models/category.py` — add `budget` FK.
- Create migration `finances/migrations/00NN_budget.py` (generated).
- Modify `finances/admin.py` — register `Budget`.
- Create `finances/services/budget_stats.py` — spend/ceiling math.
- Modify `finances/api/views.py` — `AlertsView` per-budget alerts.
- Modify `finances/forms.py` — `BudgetForm`, `CategoryAssignBudgetForm`.
- Modify `finances/views/settings.py` — budgets tab + assignment views.
- Modify `finances/urls.py` — budget routes.
- Create `templates/settings/_budgets_tab.html`.
- Modify `templates/settings/settings_page.html` — "Orçamentos" tab.
- Modify `templates/settings/_categories_tab.html` — budget `<select>` per row.
- Tests: `finances/tests/test_budget_model.py`, `test_budget_stats.py`, extend `test_api_dashboard.py`, `test_views_settings.py`.

---

### Task 1: Budget model + Category FK + migration

**Files:**
- Create: `finances/models/budget.py`
- Modify: `finances/models/__init__.py`
- Modify: `finances/models/category.py:14` (add field after `name`/`budget_ceiling`)
- Modify: `finances/admin.py`
- Test: `finances/tests/test_budget_model.py`

**Interfaces:**
- Produces: `Budget(id: UUID, user: FK, name: str, amount: Decimal, created_at, updated_at)` with `related_name="budgets"`; `Category.budget` FK with `related_name="categories"`.

- [ ] **Step 1: Write the failing test**

```python
# finances/tests/test_budget_model.py
from decimal import Decimal

import pytest
from django.db import IntegrityError
from model_bakery import baker


@pytest.mark.django_db
class TestBudgetModel:
    def test_create_budget_defaults_amount_zero(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        assert b.amount == Decimal("0")
        assert str(b.id)  # uuid pk

    def test_name_unique_per_user(self, user):
        baker.make("finances.Budget", user=user, name="Casa")
        with pytest.raises(IntegrityError):
            baker.make("finances.Budget", user=user, name="Casa")

    def test_deleting_budget_nulls_category_fk(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        cat = baker.make("finances.Category", user=user, name="Luz", budget=b)
        b.delete()
        cat.refresh_from_db()
        assert cat.budget is None

    def test_category_budget_related_name(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        baker.make("finances.Category", user=user, name="Luz", budget=b)
        assert b.categories.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_budget_model.py -v`
Expected: FAIL — `Budget` model / `Category.budget` field do not exist.

- [ ] **Step 3: Create the model**

```python
# finances/models/budget.py
import uuid

from django.conf import settings
from django.db import models


class Budget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="budgets",
    )
    name = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Teto do orçamento (editável)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name
```

- [ ] **Step 4: Add FK on Category**

In `finances/models/category.py`, after the `name` field (line ~14), add:

```python
    budget = models.ForeignKey(
        "finances.Budget",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
    )
```

- [ ] **Step 5: Export + register**

In `finances/models/__init__.py` add `from finances.models.budget import Budget`, add `"Budget"` to `__all__`.

In `finances/admin.py` add `Budget` to the import and register:

```python
@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "user")
    list_filter = ("user",)
    search_fields = ("name",)
    ordering = ("name",)
```

- [ ] **Step 6: Make migration**

Run: `python manage.py makemigrations finances`
Expected: a new migration creating `Budget` and adding `Category.budget`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest finances/tests/test_budget_model.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add finances/models/budget.py finances/models/__init__.py finances/models/category.py finances/admin.py finances/migrations/ finances/tests/test_budget_model.py
git commit -m "feat(budget): Budget model + Category.budget FK"
```

---

### Task 2: budget_stats service

**Files:**
- Create: `finances/services/budget_stats.py`
- Test: `finances/tests/test_budget_stats.py`

**Interfaces:**
- Consumes: `Budget`, `Category`, `Entry` models; `ADJUSTMENT_CATEGORY_PATTERN` from `category_stats`.
- Produces:
  - `budget_spend_for_month(user, billing_month) -> list[dict]` — keys: `budget` (Budget), `name`, `amount` (Decimal), `spent` (Decimal), `pct` (int), `status` ("error"|"warning"|"success").
  - `orphan_category_spend_for_month(user, billing_month) -> list[dict]` — keys: `name`, `ceiling` (Decimal), `spent`, `pct`, `status`.
  - `total_diverse_ceiling(user) -> Decimal`.
  - `seed_amount_from_ceilings(budget) -> Decimal`.

- [ ] **Step 1: Write the failing test**

```python
# finances/tests/test_budget_stats.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services import budget_stats


def _entry(user, cat, amount, billing_month):
    return baker.make(
        "finances.Entry", user=user, date=billing_month, amount=Decimal(amount),
        category=cat, entry_type=EntryType.REGULAR, billing_month=billing_month,
        billing_month_override=True,
    )


@pytest.mark.django_db
class TestBudgetStats:
    def test_spend_and_status(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        agua = baker.make("finances.Category", user=user, name="Água", budget=b)
        _entry(user, luz, "600", date(2026, 6, 1))
        _entry(user, agua, "550", date(2026, 6, 1))  # total 1150 -> over
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["spent"] == Decimal("1150")
        assert row["pct"] == 115
        assert row["status"] == "error"

    def test_warning_band(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        _entry(user, luz, "950", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["status"] == "warning"

    def test_excludes_adjustment_entries(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        ajuste = baker.make("finances.Category", user=user, name="Ajuste de saldo", budget=b)
        _entry(user, ajuste, "5000", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["spent"] == Decimal("0")

    def test_orphan_categories(self, user):
        orphan = baker.make(
            "finances.Category", user=user, name="Lazer",
            budget=None, budget_ceiling=Decimal("200"),
        )
        _entry(user, orphan, "250", date(2026, 6, 1))
        [row] = budget_stats.orphan_category_spend_for_month(user, date(2026, 6, 1))
        assert row["name"] == "Lazer"
        assert row["status"] == "error"

    def test_orphan_ignores_zero_ceiling(self, user):
        orphan = baker.make(
            "finances.Category", user=user, name="SemTeto",
            budget=None, budget_ceiling=Decimal("0"),
        )
        _entry(user, orphan, "100", date(2026, 6, 1))
        assert budget_stats.orphan_category_spend_for_month(user, date(2026, 6, 1)) == []

    def test_total_diverse_ceiling(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))  # ceiling ignored; budget.amount used
        baker.make("finances.Category", user=user, name="Lazer", budget=None,
                   budget_ceiling=Decimal("200"))
        assert budget_stats.total_diverse_ceiling(user) == Decimal("1200")

    def test_seed_amount_from_ceilings(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("0"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))
        baker.make("finances.Category", user=user, name="Água", budget=b,
                   budget_ceiling=Decimal("150"))
        assert budget_stats.seed_amount_from_ceilings(b) == Decimal("550")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_budget_stats.py -v`
Expected: FAIL — module `budget_stats` not found.

- [ ] **Step 3: Implement the service**

```python
# finances/services/budget_stats.py
"""Deterministic per-budget spend + planned-ceiling math."""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from finances.models import Budget, Category, Entry
from finances.services.category_stats import ADJUSTMENT_CATEGORY_PATTERN

ZERO = Decimal("0")


def _status(spent: Decimal, cap: Decimal) -> tuple[int, str]:
    if cap <= 0:
        return 0, "success"
    pct = int((spent / cap * 100).to_integral_value())
    if pct >= 100:
        return pct, "error"
    if pct >= 90:
        return pct, "warning"
    return pct, "success"


def _spend_by_category(user, billing_month: date) -> dict:
    rows = (
        Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
        .exclude(category__name__icontains=ADJUSTMENT_CATEGORY_PATTERN)
        .values("category_id")
        .annotate(total=Sum("amount"))
    )
    return {r["category_id"]: r["total"] or ZERO for r in rows}


def budget_spend_for_month(user, billing_month: date) -> list[dict]:
    spend = _spend_by_category(user, billing_month)
    out = []
    for b in Budget.objects.filter(user=user).prefetch_related("categories"):
        spent = sum((spend.get(c.id, ZERO) for c in b.categories.all()), ZERO)
        pct, status = _status(spent, b.amount)
        out.append(
            {"budget": b, "name": b.name, "amount": b.amount,
             "spent": spent, "pct": pct, "status": status}
        )
    return out


def orphan_category_spend_for_month(user, billing_month: date) -> list[dict]:
    spend = _spend_by_category(user, billing_month)
    out = []
    for c in Category.objects.filter(user=user, budget__isnull=True):
        if not c.budget_ceiling or c.budget_ceiling <= 0:
            continue
        spent = spend.get(c.id, ZERO)
        pct, status = _status(spent, c.budget_ceiling)
        out.append(
            {"name": c.name, "ceiling": c.budget_ceiling,
             "spent": spent, "pct": pct, "status": status}
        )
    return out


def total_diverse_ceiling(user) -> Decimal:
    budgets = Budget.objects.filter(user=user).aggregate(t=Sum("amount"))["t"] or ZERO
    orphans = (
        Category.objects.filter(user=user, budget__isnull=True)
        .aggregate(t=Sum("budget_ceiling"))["t"]
        or ZERO
    )
    return budgets + orphans


def seed_amount_from_ceilings(budget) -> Decimal:
    return budget.categories.aggregate(t=Sum("budget_ceiling"))["t"] or ZERO
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest finances/tests/test_budget_stats.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add finances/services/budget_stats.py finances/tests/test_budget_stats.py
git commit -m "feat(budget): budget_stats service (spend, ceiling, seed)"
```

---

### Task 3: AlertsView — per-budget alerts

**Files:**
- Modify: `finances/api/views.py:148-183` (replace the per-category budget loop)
- Test: `finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: `budget_spend_for_month`, `orphan_category_spend_for_month` from Task 2.
- Produces: same `AlertsView` JSON contract (list of `{severity, message}`), now budget-driven.

- [ ] **Step 1: Write the failing test**

```python
# add to finances/tests/test_api_dashboard.py
from datetime import date
from decimal import Decimal

from model_bakery import baker


@pytest.mark.django_db
class TestAlertsByBudget:
    def _entry(self, user, cat, amount, bm):
        from finances.models.entry import EntryType
        return baker.make(
            "finances.Entry", user=user, date=bm, amount=Decimal(amount),
            category=cat, entry_type=EntryType.REGULAR, billing_month=bm,
            billing_month_override=True,
        )

    def test_budget_overflow_alert(self, logged_client, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        self._entry(user, luz, "1200", date(2026, 6, 1))
        resp = logged_client.get("/api/dashboard/alerts/?year=2026&month=6")
        msgs = [a["message"] for a in resp.json()]
        assert any("Casa ultrapassou teto" in m for m in msgs)

    def test_orphan_category_still_alerts(self, logged_client, user):
        orphan = baker.make("finances.Category", user=user, name="Lazer",
                            budget=None, budget_ceiling=Decimal("100"))
        self._entry(user, orphan, "150", date(2026, 6, 1))
        resp = logged_client.get("/api/dashboard/alerts/?year=2026&month=6")
        msgs = [a["message"] for a in resp.json()]
        assert any("Lazer ultrapassou teto" in m for m in msgs)
```

(`logged_client`/`user` fixtures live in `finances/tests/conftest.py`. Alerts URL is `/api/dashboard/alerts/`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_api_dashboard.py -k Budget -v`
Expected: FAIL — current alerts are per-category by name, not "Casa".

- [ ] **Step 3: Replace the budget-alert loop**

In `finances/api/views.py`, replace the block from `# Budget alerts` through the `else: ok_count += 1` (the `category_totals` loop, lines ~150-183) with:

```python
        # Budget alerts (per-budget, plus individual alerts for orphan categories)
        from finances.services.budget_stats import (
            budget_spend_for_month,
            orphan_category_spend_for_month,
        )

        ok_count = 0

        def _emit(label, spent, cap, pct, status):
            nonlocal ok_count
            if status == "error":
                over = spent - cap
                alerts.append({
                    "severity": "danger",
                    "message": f"{label} ultrapassou teto em R$ {over:.2f}",
                })
            elif status == "warning":
                alerts.append({
                    "severity": "warning",
                    "message": f"{label} em {pct}% do teto (R$ {spent:.0f} / R$ {cap:.0f})",
                })
            else:
                ok_count += 1

        for row in budget_spend_for_month(user, billing_month):
            _emit(row["name"], row["spent"], row["amount"], row["pct"], row["status"])
        for row in orphan_category_spend_for_month(user, billing_month):
            _emit(row["name"], row["spent"], row["ceiling"], row["pct"], row["status"])
```

Then update the success message text (line ~204-208) to:

```python
                    "message": f"{ok_count} orçamentos dentro do teto",
```

Leave the installment-info block and the severity sort untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest finances/tests/test_api_dashboard.py -v`
Expected: PASS (new + existing alert tests). Fix any existing alert test that asserted the old per-category wording.

- [ ] **Step 5: Commit**

```bash
git add finances/api/views.py finances/tests/test_api_dashboard.py
git commit -m "feat(budget): dashboard alerts per orçamento + orphan categories"
```

---

### Task 4: Settings — Orçamentos tab (CRUD + recalc)

**Files:**
- Modify: `finances/forms.py` (add `BudgetForm`)
- Modify: `finances/views/settings.py` (budget tab + CRUD + recalc views)
- Modify: `finances/urls.py` (budget routes)
- Create: `templates/settings/_budgets_tab.html`
- Modify: `templates/settings/settings_page.html` (add "Orçamentos" tab link)
- Test: `finances/tests/test_views_settings.py`

**Interfaces:**
- Consumes: `Budget`, `seed_amount_from_ceilings`.
- Produces: named URLs `settings_budgets`, `settings_budget_create`, `settings_budget_edit`, `settings_budget_delete`, `settings_budget_recalc`; partial `settings/_budgets_tab.html`.

- [ ] **Step 1: Write the failing test**

```python
# add to finances/tests/test_views_settings.py
from decimal import Decimal

from django.urls import reverse
from model_bakery import baker


@pytest.mark.django_db
class TestBudgetSettings:
    def test_create_budget(self, logged_client, user):
        url = reverse("finances:settings_budget_create")
        resp = logged_client.post(url, {"name": "Casa", "amount": "1000"})
        assert resp.status_code == 200
        assert user.budgets.filter(name="Casa", amount=Decimal("1000")).exists()

    def test_recalc_sets_amount_to_ceiling_sum(self, logged_client, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("0"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))
        url = reverse("finances:settings_budget_recalc", args=[b.id])
        resp = logged_client.post(url)
        assert resp.status_code == 200
        b.refresh_from_db()
        assert b.amount == Decimal("400")

    def test_delete_budget(self, logged_client, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        url = reverse("finances:settings_budget_delete", args=[b.id])
        resp = logged_client.delete(url)
        assert resp.status_code == 200
        assert not user.budgets.filter(id=b.id).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_views_settings.py -k Budget -v`
Expected: FAIL — URLs/views don't exist (`NoReverseMatch`).

- [ ] **Step 3: Add the form**

In `finances/forms.py` (after `CategoryCreateForm`):

```python
class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["name", "amount"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
        }
```

Add `Budget` to the `from finances.models import ...` line at the top of `forms.py`.

- [ ] **Step 4: Add views**

In `finances/views/settings.py`, import `Budget`, `BudgetForm`, and `seed_amount_from_ceilings`, then add (after the Categories section):

```python
# --- Budgets ---

def _budgets_tab_context(user):
    from finances.services.budget_stats import seed_amount_from_ceilings
    budgets = []
    for b in Budget.objects.filter(user=user).prefetch_related("categories"):
        budgets.append({"obj": b, "ceiling_sum": seed_amount_from_ceilings(b),
                        "n_categories": b.categories.count()})
    return {"budgets": budgets, "form": BudgetForm()}


def _render_budgets_tab(request, message=None):
    html = render_to_string(
        "settings/_budgets_tab.html", _budgets_tab_context(request.user), request=request
    )
    response = HttpResponse(html)
    if message:
        response["HX-Trigger"] = (
            '{"showToast": {"message": "%s", "type": "success"}}' % message
        )
    return response


class BudgetsTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_budgets_tab.html"
    htmx_template_name = "settings/_budgets_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_budgets_tab_context(self.request.user))
        return context


class BudgetCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = BudgetForm(request.POST)
        if form.is_valid():
            b = form.save(commit=False)
            b.user = request.user
            b.save()
        return _render_budgets_tab(request, "Orçamento criado!")


class BudgetEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        b = Budget.objects.filter(user=request.user, pk=pk).first()
        if not b:
            raise Http404
        form = BudgetForm(request.POST, instance=b)
        if form.is_valid():
            form.save()
        return _render_budgets_tab(request, "Orçamento atualizado!")


class BudgetRecalcView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        from finances.services.budget_stats import seed_amount_from_ceilings
        b = Budget.objects.filter(user=request.user, pk=pk).first()
        if not b:
            raise Http404
        b.amount = seed_amount_from_ceilings(b)
        b.save(update_fields=["amount", "updated_at"])
        return _render_budgets_tab(request, "Teto recalculado!")


class BudgetDeleteView(HtmxLoginRequiredMixin, View):
    def delete(self, request, pk):
        b = Budget.objects.filter(user=request.user, pk=pk).first()
        if not b:
            raise Http404
        b.delete()
        return _render_budgets_tab(request)
```

- [ ] **Step 5: Add routes**

In `finances/urls.py`, import the new views and add (next to the categories routes):

```python
    path("settings/budgets/", BudgetsTabView.as_view(), name="settings_budgets"),
    path("settings/budgets/create/", BudgetCreateView.as_view(), name="settings_budget_create"),
    path("settings/budgets/<uuid:pk>/edit/", BudgetEditView.as_view(), name="settings_budget_edit"),
    path("settings/budgets/<uuid:pk>/recalc/", BudgetRecalcView.as_view(), name="settings_budget_recalc"),
    path("settings/budgets/<uuid:pk>/delete/", BudgetDeleteView.as_view(), name="settings_budget_delete"),
```

- [ ] **Step 6: Create the tab template**

```html
<!-- templates/settings/_budgets_tab.html -->
<form hx-post="{% url 'finances:settings_budget_create' %}"
      hx-target="#settings-content" hx-swap="innerHTML"
      class="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4 items-end">
    {% csrf_token %}
    {{ form.name }}
    {{ form.amount }}
    <button type="submit" class="btn btn-sm btn-accent col-span-2 md:col-span-1">Adicionar</button>
</form>

<div class="overflow-x-auto min-w-0">
<table class="table table-sm">
    <thead>
        <tr><th>Orçamento</th><th>Teto</th><th>Σ tetos categorias</th><th>Categorias</th><th></th></tr>
    </thead>
    <tbody>
        {% for b in budgets %}
        <tr>
            <td>{{ b.obj.name }}</td>
            <td>
                <input type="number" name="amount" value="{{ b.obj.amount }}" step="0.01"
                       class="input input-bordered input-xs w-24"
                       hx-post="{% url 'finances:settings_budget_edit' b.obj.id %}"
                       hx-trigger="change" hx-include="this"
                       hx-vals='{"name": "{{ b.obj.name|escapejs }}"}'
                       hx-target="#settings-content" hx-swap="innerHTML">
            </td>
            <td class="text-xs text-base-content/70">R$ {{ b.ceiling_sum|floatformat:2 }}</td>
            <td class="text-xs">{{ b.n_categories }}</td>
            <td class="flex gap-1">
                <button class="btn btn-ghost btn-xs"
                        hx-post="{% url 'finances:settings_budget_recalc' b.obj.id %}"
                        hx-target="#settings-content" hx-swap="innerHTML"
                        title="Recalcular pela soma dos tetos">🔄</button>
                <button class="btn btn-ghost btn-xs text-error"
                        hx-delete="{% url 'finances:settings_budget_delete' b.obj.id %}"
                        hx-target="#settings-content" hx-swap="innerHTML"
                        hx-confirm="Excluir orçamento {{ b.obj.name }}? As categorias ficam sem orçamento.">🗑️</button>
            </td>
        </tr>
        {% empty %}
        <tr><td colspan="5" class="text-center py-6">
            <span class="text-2xl">📊</span>
            <p class="text-xs text-base-content/60 mt-1">Nenhum orçamento. Crie um e agrupe categorias na aba Categorias.</p>
        </td></tr>
        {% endfor %}
    </tbody>
</table>
</div>
```

Note: `hx-vals` re-sends `name` because `BudgetForm` requires it on the inline amount edit.

- [ ] **Step 7: Add the tab to settings_page.html**

In `templates/settings/settings_page.html`, after the Categorias tab `<a>` (line ~24-28), add an analogous tab:

```html
    <a class="tab" id="tab-budgets"
       hx-get="{% url 'finances:settings_budgets' %}"
       hx-target="#settings-content" hx-swap="innerHTML"
       @click="document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('tab-active')); $el.classList.add('tab-active')">Orçamentos</a>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest finances/tests/test_views_settings.py -k Budget -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Rebuild frontend assets (new Tailwind classes)**

Run the project's frontend build (Tailwind `--force`) and stage `mount.js` + `tailwind.css` if changed.

- [ ] **Step 10: Commit**

```bash
git add finances/forms.py finances/views/settings.py finances/urls.py templates/settings/_budgets_tab.html templates/settings/settings_page.html finances/tests/test_views_settings.py
git add src/backend/frontend/  # if assets rebuilt
git commit -m "feat(budget): Settings orçamentos tab (CRUD + recalc)"
```

---

### Task 5: Assign category to budget (Categories tab)

**Files:**
- Modify: `finances/views/settings.py` (`categories_tab_context` + assign view)
- Modify: `finances/urls.py` (assign route)
- Modify: `templates/settings/_categories_tab.html` (budget `<select>` column)
- Test: `finances/tests/test_views_settings.py`

**Interfaces:**
- Consumes: `Budget`, `Category`.
- Produces: named URL `settings_cat_assign`; categories context gains `budgets` (queryset).

- [ ] **Step 1: Write the failing test**

```python
# add to finances/tests/test_views_settings.py (TestBudgetSettings class)
    def test_assign_category_to_budget(self, logged_client, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        cat = baker.make("finances.Category", user=user, name="Luz", budget=None)
        url = reverse("finances:settings_cat_assign", args=[cat.id])
        resp = logged_client.post(url, {"budget": str(b.id)})
        assert resp.status_code == 200
        cat.refresh_from_db()
        assert cat.budget_id == b.id

    def test_unassign_category(self, logged_client, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        cat = baker.make("finances.Category", user=user, name="Luz", budget=b)
        url = reverse("finances:settings_cat_assign", args=[cat.id])
        resp = logged_client.post(url, {"budget": ""})
        assert resp.status_code == 200
        cat.refresh_from_db()
        assert cat.budget_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_views_settings.py -k assign -v`
Expected: FAIL — `settings_cat_assign` does not exist.

- [ ] **Step 3: Extend categories context + add assign view**

In `finances/views/settings.py`, add `budgets` to `categories_tab_context`:

```python
def categories_tab_context(user):
    averages = category_moving_averages(user, window=3)
    total_ceiling = Category.objects.filter(user=user).aggregate(t=Sum("budget_ceiling"))["t"]
    total_avg = sum(averages.values(), Decimal("0"))
    return {
        "categories": Category.objects.filter(user=user).select_related("budget"),
        "form": CategoryCreateForm(),
        "category_averages": averages,
        "total_ceiling": total_ceiling,
        "total_avg_3m": total_avg or None,
        "budgets": Budget.objects.filter(user=user),
    }
```

Add the assign view:

```python
class CategoryAssignBudgetView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        cat = Category.objects.filter(user=request.user, pk=pk).first()
        if not cat:
            raise Http404
        raw = request.POST.get("budget") or None
        cat.budget = (
            Budget.objects.filter(user=request.user, pk=raw).first() if raw else None
        )
        cat.save(update_fields=["budget", "updated_at"])
        context = categories_tab_context(request.user)
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Orçamento da categoria atualizado!", "type": "success"}}'
        return response
```

- [ ] **Step 4: Add route**

In `finances/urls.py`, add:

```python
    path("settings/categories/<uuid:pk>/assign/", CategoryAssignBudgetView.as_view(), name="settings_cat_assign"),
```

- [ ] **Step 5: Add the budget column to the categories table**

In `templates/settings/_categories_tab.html`, add a header `<th>Orçamento</th>` and, in each row (after the Teto cell), a select:

```html
            <td>
                <select name="budget" class="select select-bordered select-xs w-32"
                        hx-post="{% url 'finances:settings_cat_assign' cat.id %}"
                        hx-trigger="change" hx-include="this"
                        hx-target="#settings-content" hx-swap="innerHTML">
                    <option value="">— sem orçamento —</option>
                    {% for b in budgets %}
                    <option value="{{ b.id }}" {% if cat.budget_id == b.id %}selected{% endif %}>{{ b.name }}</option>
                    {% endfor %}
                </select>
            </td>
```

Update the empty-state and `tfoot` `colspan` from 5 to 6.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest finances/tests/test_views_settings.py -k "assign or unassign" -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Rebuild frontend assets if Tailwind classes changed; commit**

```bash
git add finances/views/settings.py finances/urls.py templates/settings/_categories_tab.html finances/tests/test_views_settings.py
git commit -m "feat(budget): assign category to orçamento in Settings"
```

---

# Phase 2 — Toggle mediana/teto na projeção

## File Structure (Phase 2)

- Modify `finances/services/category_stats.py` — `monthly_diverse_total_ceiling`.
- Modify `finances/services/projection.py` — `diverse_estimator` param.
- Modify `finances/views/projection.py` — read/persist `estimate`, pass through.
- Modify `templates/projection/projection_page.html` — toggle control.
- Tests: extend `test_category_stats`, `test_projection_service` / `test_projection_estimated`, `test_views_projection`.

---

### Task 6: monthly_diverse_total_ceiling

**Files:**
- Modify: `finances/services/category_stats.py`
- Test: `finances/tests/test_category_stats.py` (create if absent)

**Interfaces:**
- Consumes: `total_diverse_ceiling` (Task 2).
- Produces: `monthly_diverse_total_ceiling(user) -> Decimal`.

- [ ] **Step 1: Write the failing test**

```python
# finances/tests/test_category_stats.py
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.category_stats import monthly_diverse_total_ceiling


@pytest.mark.django_db
def test_monthly_diverse_total_ceiling(user):
    b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
    baker.make("finances.Category", user=user, name="Luz", budget=b,
               budget_ceiling=Decimal("400"))
    baker.make("finances.Category", user=user, name="Lazer", budget=None,
               budget_ceiling=Decimal("250"))
    assert monthly_diverse_total_ceiling(user) == Decimal("1250")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_category_stats.py::test_monthly_diverse_total_ceiling -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement (append to category_stats.py)**

```python
def monthly_diverse_total_ceiling(user) -> Decimal:
    """Planned diversas ceiling: Σ budgets + ceilings of un-budgeted categories.

    The "teto" alternative to ``monthly_diverse_total_median`` for the projection.
    Imported lazily to keep this module free of a budget_stats import cycle.
    """
    from finances.services.budget_stats import total_diverse_ceiling
    return total_diverse_ceiling(user)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest finances/tests/test_category_stats.py::test_monthly_diverse_total_ceiling -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add finances/services/category_stats.py finances/tests/test_category_stats.py
git commit -m "feat(projection): monthly_diverse_total_ceiling estimator"
```

---

### Task 7: build_projection diverse_estimator switch

**Files:**
- Modify: `finances/services/projection.py:54-133` (signature + estimator selection)
- Test: `finances/tests/test_projection_service.py`

**Interfaces:**
- Consumes: `monthly_diverse_total_median`, `monthly_diverse_total_ceiling`.
- Produces: `build_projection(user, start_month, num_months, today=None, overlay=None, diverse_estimator="median")`.

- [ ] **Step 1: Write the failing test**

```python
# add to finances/tests/test_projection_service.py
@pytest.mark.django_db
class TestDiverseEstimator:
    def test_ceiling_estimator_uses_total_ceiling(self, user, cat, pix):
        from decimal import Decimal
        from model_bakery import baker
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("3000"))
        baker.make("finances.Category", user=user, name="Lazer", budget=None,
                   budget_ceiling=Decimal("500"))
        # future month, no posted diversas -> estimate drives diverse_estimated
        rows = build_projection(
            user, date(2026, 7, 1), 1, today=date(2026, 6, 15),
            diverse_estimator="ceiling",
        )
        assert rows[0]["diverse_estimated"] == Decimal("3500")

    def test_median_is_default(self, user, cat, pix):
        rows_default = build_projection(user, date(2026, 7, 1), 1, today=date(2026, 6, 15))
        rows_median = build_projection(user, date(2026, 7, 1), 1, today=date(2026, 6, 15),
                                       diverse_estimator="median")
        assert rows_default[0]["diverse_estimated"] == rows_median[0]["diverse_estimated"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_projection_service.py -k Estimator -v`
Expected: FAIL — `build_projection() got an unexpected keyword argument 'diverse_estimator'`.

- [ ] **Step 3: Add the parameter + selection**

In `finances/services/projection.py`:

1. Update the import line (~16) to also import the ceiling estimator:

```python
from finances.services.category_stats import (
    monthly_diverse_total_ceiling,
    monthly_diverse_total_median,
)
```

2. Update the signature (~54):

```python
def build_projection(user, start_month: date, num_months: int, today: date | None = None,
                     overlay: dict | None = None, diverse_estimator: str = "median"):
```

3. Replace the `est_typical_diverse = ...` line (~133) with:

```python
    if diverse_estimator == "ceiling":
        est_typical_diverse = monthly_diverse_total_ceiling(user)
    else:
        est_typical_diverse = monthly_diverse_total_median(user, window=6, as_of=today)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest finances/tests/test_projection_service.py finances/tests/test_projection_estimated.py -v`
Expected: PASS (new + existing projection tests still green).

- [ ] **Step 5: Commit**

```bash
git add finances/services/projection.py finances/tests/test_projection_service.py
git commit -m "feat(projection): diverse_estimator switch (median|ceiling)"
```

---

### Task 8: Projection view + toggle UI

**Files:**
- Modify: `finances/views/projection.py` (read/persist `estimate`, pass through)
- Modify: `templates/projection/projection_page.html` (toggle control)
- Test: `finances/tests/test_views_projection.py`

**Interfaces:**
- Consumes: `build_projection(..., diverse_estimator=)`.
- Produces: context key `estimate` ("median"|"teto"); session key `projection_estimate`.

- [ ] **Step 1: Write the failing test**

```python
# add to finances/tests/test_views_projection.py
@pytest.mark.django_db
class TestEstimateToggle:
    def test_teto_param_uses_ceiling(self, logged_client, user):
        from decimal import Decimal
        from model_bakery import baker
        baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("9999"))
        resp = logged_client.get("/projection/?estimate=teto&start=2026-07&months=1")
        assert resp.status_code == 200
        assert resp.context["estimate"] == "teto"
        assert resp.context["rows"][0]["diverse_estimated"] == Decimal("9999")

    def test_default_is_median(self, logged_client, user):
        resp = logged_client.get("/projection/?start=2026-07&months=1")
        assert resp.context["estimate"] == "median"

    def test_estimate_persists_in_session(self, logged_client, user):
        logged_client.get("/projection/?estimate=teto&start=2026-07&months=1")
        # subsequent request without the param keeps the choice
        resp = logged_client.get("/projection/?start=2026-07&months=1")
        assert resp.context["estimate"] == "teto"
```

(Confirm the projection URL path from `finances/urls.py` — it is `/projection/`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest finances/tests/test_views_projection.py -k Estimate -v`
Expected: FAIL — no `estimate` in context.

- [ ] **Step 3: Read + persist the estimate in the view**

In `finances/views/projection.py`, add a session key constant near `SESSION_KEY`:

```python
ESTIMATE_SESSION_KEY = "projection_estimate"
```

Add a helper and wire it into `build_projection_context`:

```python
def _parse_estimate(request) -> str:
    """'teto' or 'median'. GET wins; otherwise last session choice; default median."""
    raw = request.GET.get("estimate")
    if raw in ("teto", "median"):
        request.session[ESTIMATE_SESSION_KEY] = raw
        return raw
    return request.session.get(ESTIMATE_SESSION_KEY, "median")
```

In `build_projection_context`, after computing `months`:

```python
    estimate = _parse_estimate(request)
    estimator = "ceiling" if estimate == "teto" else "median"
    rows = build_projection(request.user, start, months, today=today, diverse_estimator=estimator)
```

(Replace the existing `rows = build_projection(...)` call.) Add `"estimate": estimate,` to the returned context dict.

- [ ] **Step 4: Add the toggle to the template**

In `templates/projection/projection_page.html`, inside the controls `<form>` (after the "Meses" label, ~line 39), add:

```html
    <label class="form-control">
        <span class="label-text text-xs mb-1">Diversas (futuro)</span>
        <select name="estimate" class="select select-bordered select-sm w-32">
            <option value="median" {% if estimate == "median" %}selected{% endif %}>Mediana</option>
            <option value="teto" {% if estimate == "teto" %}selected{% endif %}>Teto</option>
        </select>
    </label>
```

The form already has `hx-get` → `#projection-container` on `change`, so the toggle re-renders the table automatically.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest finances/tests/test_views_projection.py -v`
Expected: PASS (new + existing).

- [ ] **Step 6: Rebuild frontend assets if Tailwind classes changed.**

- [ ] **Step 7: Full suite + lint**

Run: `pytest -q && ruff check finances`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add finances/views/projection.py templates/projection/projection_page.html finances/tests/test_views_projection.py
git add src/backend/frontend/  # if assets rebuilt
git commit -m "feat(projection): mediana/teto toggle on projection screen"
```

---

## Self-Review

**Spec coverage:**
- Budget model + FK → Task 1. ✓
- budget_stats (spend, ceiling, seed) → Task 2. ✓
- Alerts per budget + orphan individual + success copy → Task 3. ✓
- Settings budget CRUD + recalc → Task 4. ✓
- Category→budget assignment (`<select>` in categories tab) → Task 5. ✓
- `monthly_diverse_total_ceiling` → Task 6. ✓
- `build_projection` estimator switch → Task 7. ✓
- View `?estimate=` + session persistence + toggle UI → Task 8. ✓
- Teto consolidado = Σ budgets + orphan ceilings → Tasks 2 & 6. ✓
- Default median; "não projetar abaixo do já lançado" preserved (unchanged code path) → Task 7. ✓
- Consolidado view unchanged (out of scope) → no task, by design. ✓

**Placeholder scan:** No TBD/TODO; all code blocks concrete.

**Type consistency:** `budget_spend_for_month`/`orphan_category_spend_for_month` dict keys (`name`, `spent`, `amount`/`ceiling`, `pct`, `status`) consistent between Task 2 (producer) and Task 3 (consumer). `diverse_estimator` ("median"|"ceiling") consistent Tasks 7–8; UI value ("median"|"teto") mapped to estimator in Task 8. `seed_amount_from_ceilings` used in Tasks 2/4/6 with same signature.

**Verification notes for the implementer:**
- Confirm the alerts API path in `finances/api/urls.py` before asserting it in Task 3/8 tests.
- Confirm `logged_client`/`user` fixtures exist in `conftest.py` (used across the suite).
- Run migrations against the :5433 container before the suite.
