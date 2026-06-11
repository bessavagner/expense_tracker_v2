# Monthly Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Entradas (entries) month page into a "monthly cockpit" where income, systemic expenses, and credit-card closing days are viewed/edited per month (including past months), and fix the Consolidado dropdown toggle.

**Architecture:** Server-rendered Django + HTMX partials (existing pattern: a view renders a partial template, returns it on POST, uses `HX-Trigger` for toasts). The Entradas page (`EntryListView` → `entries/entries_page.html`) gains four month-scoped sections, each backed by a small view + partial under `finances/`. No new models — `Income.month`, `Entry(entry_type=SYSTEMIC, systemic_expense=…)`, and `PaymentMethodClosingDay` already exist.

**Tech Stack:** Django 6, HTMX, Alpine.js, DaisyUI/Tailwind, pytest + pytest-django, model-bakery. Tests need the local pgvector container on port 5433 (`docker compose up -d db`). Run tests with `uv run pytest`.

**Conventions to follow:**
- Test classes must start with `Test` (pytest config `python_classes = ["Test*"]`); `TestCase` subclasses are also collected.
- Views use `HtmxLoginRequiredMixin` (in `finances/views/mixins.py`).
- Money displayed via `{% load finance_filters %}` + `|brl`.
- Each deliverable is independently shippable; commit after each task. Work in a git worktree.

---

## Deliverable 1 — Fix Consolidado dropdown toggle

**Root cause:** In `templates/consolidated/_consolidated_table.html`, each amount cell has `hx-get` (loads detail, then `hx-on::after-request` forces the detail row `display='table-row'`) AND an Alpine `@click` toggle. On the 2nd click Alpine sets `display='none'` but htmx still fires the GET and `after-request` re-shows it → never closes. Alpine's `$event.preventDefault()` does not cancel htmx's own request.

**Fix:** add the `once` modifier so htmx loads the detail only on the first click; subsequent clicks are handled purely by the Alpine toggle.

### Task 1.1: Make the dropdown toggle closed on re-click

**Files:**
- Modify: `src/backend/templates/consolidated/_consolidated_table.html:16-24`
- Test: `src/backend/finances/tests/test_consolidated_dropdown.py` (create)

- [ ] **Step 1: Write the failing test** (template assertion — fast, no browser)

```python
# src/backend/finances/tests/test_consolidated_dropdown.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry


class TestConsolidatedDropdownToggle(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        cat = baker.make(Category, user=self.user, name="Alimentação")
        baker.make(
            Entry, user=self.user, category=cat, amount="10.00",
            date=date(2026, 1, 5), billing_month=date(2026, 1, 1),
        )

    def test_detail_cell_loads_only_once(self):
        """htmx must load the detail once; Alpine handles open/close afterwards."""
        resp = self.client.get("/consolidated/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # The amount cell must use the `once` modifier so re-clicks don't re-fire htmx.
        self.assertIn('hx-trigger="click once"', html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_consolidated_dropdown.py -v`
Expected: FAIL — `hx-trigger="click once"` not found.

- [ ] **Step 3: Add the `hx-trigger` to the amount cell**

In `_consolidated_table.html`, on the `<td …>` that has `hx-get="{% url 'finances:category_detail' … %}"`, add the attribute `hx-trigger="click once"`. Keep the existing `@click` Alpine toggle and `hx-on::after-request` as-is. Resulting cell opening tag:

```html
<td class="text-right whitespace-nowrap cursor-pointer hover:bg-base-200 {% if row.budget_status|get_item:m == 'danger' %}text-error font-bold{% elif row.budget_status|get_item:m == 'warning' %}text-warning font-bold{% endif %}"
    hx-get="{% url 'finances:category_detail' row.category__id current_year m %}"
    hx-target="#detail-{{ row.category__id }}-{{ m }}"
    hx-swap="innerHTML"
    hx-trigger="click once"
    hx-on::after-request="document.getElementById('detail-{{ row.category__id }}-{{ m }}').style.display = 'table-row'"
    @click="const r = document.getElementById('detail-{{ row.category__id }}-{{ m }}'); if (r && r.innerHTML.trim()) { r.style.display = r.style.display === 'table-row' ? 'none' : 'table-row'; }">
```

(Also drop the now-unnecessary `$event.preventDefault();` — it was only there to fight htmx.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_consolidated_dropdown.py -v`
Expected: PASS.

- [ ] **Step 5: Manually verify in the browser (local server already running on :8000)**

Navigate to `/consolidated/`, click a non-empty amount → detail opens; click again → detail closes; click again → opens. (Same for `/consolidated/systemics/`.)

- [ ] **Step 6: Commit**

```bash
git add src/backend/templates/consolidated/_consolidated_table.html src/backend/finances/tests/test_consolidated_dropdown.py
git commit -m "fix(consolidated): close detail dropdown on re-click (hx-trigger click once)"
```

---

## Deliverable 2 — Renda do mês (income section in the cockpit)

The Entradas page shows the income rows whose `month` equals the selected month, with add/edit/delete. "Add" supports **repeat until December** of the same year (creates one `Income` row per month). Each row stays independently editable (also for past months).

### Task 2.1: Cockpit income form with "repeat until December"

**Files:**
- Modify: `src/backend/finances/forms.py` (add `CockpitIncomeForm` after `IncomeForm`, ~line 125)
- Test: `src/backend/finances/tests/test_cockpit_income.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_cockpit_income.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Income


class TestCockpitIncomeForm(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)

    def test_repeat_until_december_creates_one_row_per_month(self):
        from finances.forms import CockpitIncomeForm

        form = CockpitIncomeForm(
            data={"name": "Salário", "amount": "5000.00", "month": "2026-10-01",
                  "repeat_until_december": True}
        )
        self.assertTrue(form.is_valid(), form.errors)
        created = form.save_for_user(self.user)
        # Oct, Nov, Dec => 3 rows
        self.assertEqual(len(created), 3)
        months = sorted(i.month for i in created)
        self.assertEqual(months, [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)])
        self.assertTrue(all(i.amount.quantize(__import__("decimal").Decimal("0.01"))
                            == __import__("decimal").Decimal("5000.00") for i in created))
        self.assertTrue(all(i.user_id == self.user.id for i in created))

    def test_without_repeat_creates_single_row(self):
        from finances.forms import CockpitIncomeForm

        form = CockpitIncomeForm(
            data={"name": "Freela", "amount": "800.00", "month": "2026-10-01",
                  "repeat_until_december": False}
        )
        self.assertTrue(form.is_valid(), form.errors)
        created = form.save_for_user(self.user)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].month, date(2026, 10, 1))
        self.assertEqual(Income.objects.filter(user=self.user).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_income.py -v`
Expected: FAIL — `CockpitIncomeForm` does not exist.

- [ ] **Step 3: Implement `CockpitIncomeForm`**

```python
# src/backend/finances/forms.py  (add after IncomeForm)
from datetime import date as _date


class CockpitIncomeForm(forms.ModelForm):
    repeat_until_december = forms.BooleanField(required=False)

    class Meta:
        model = Income
        fields = ["name", "amount", "month"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(attrs={"class": "input input-bordered input-sm w-full", "step": "0.01"}),
            "month": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
        }

    def save_for_user(self, user):
        """Create one Income per target month; returns the created list."""
        base = self.cleaned_data
        start = base["month"].replace(day=1)
        if self.cleaned_data.get("repeat_until_december"):
            months = [_date(start.year, m, 1) for m in range(start.month, 13)]
        else:
            months = [start]
        created = []
        recurring = len(months) > 1
        for m in months:
            created.append(
                Income.objects.create(
                    user=user, name=base["name"], amount=base["amount"], month=m,
                    is_recurring=recurring,
                    recurrence_start=months[0] if recurring else None,
                    recurrence_end=months[-1] if recurring else None,
                )
            )
        return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_income.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/forms.py src/backend/finances/tests/test_cockpit_income.py
git commit -m "feat(finances): CockpitIncomeForm with repeat-until-December"
```

### Task 2.2: Month-scoped income views (list partial / create / delete)

**Files:**
- Create: `src/backend/finances/views/cockpit.py`
- Modify: `src/backend/finances/urls.py` (add imports + routes)
- Create: `src/backend/templates/cockpit/_income_section.html`
- Test: `src/backend/finances/tests/test_cockpit_income_views.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_cockpit_income_views.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Income


class TestCockpitIncomeViews(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_create_income_for_month_renders_section(self):
        resp = self.client.post(
            "/cockpit/2026/10/income/create/",
            {"name": "Salário", "amount": "5000.00", "month": "2026-10-01"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Salário", resp.content.decode())
        self.assertEqual(Income.objects.filter(user=self.user, month=date(2026, 10, 1)).count(), 1)

    def test_section_lists_only_selected_month(self):
        baker.make(Income, user=self.user, name="Out", amount="100", month=date(2026, 10, 1))
        baker.make(Income, user=self.user, name="Nov", amount="200", month=date(2026, 11, 1))
        resp = self.client.get("/cockpit/2026/10/income/")
        body = resp.content.decode()
        self.assertIn("Out", body)
        self.assertNotIn("Nov", body)

    def test_delete_income_removes_row(self):
        inc = baker.make(Income, user=self.user, name="X", amount="100", month=date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Income.objects.filter(pk=inc.pk).exists())

    def test_user_cannot_touch_another_users_income(self):
        other = baker.make(CustomUser)
        inc = baker.make(Income, user=other, name="X", amount="100", month=date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Income.objects.filter(pk=inc.pk).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_income_views.py -v`
Expected: FAIL — 404 (routes don't exist).

- [ ] **Step 3: Implement the views**

```python
# src/backend/finances/views/cockpit.py
from datetime import date

from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views import View

from finances.forms import CockpitIncomeForm
from finances.models import Income
from finances.views.mixins import HtmxLoginRequiredMixin


def _income_context(request, year, month):
    return {
        "current_year": year,
        "current_month": month,
        "incomes": Income.objects.filter(
            user=request.user, month=date(year, month, 1)
        ).order_by("name"),
        "income_form": CockpitIncomeForm(initial={"month": date(year, month, 1)}),
    }


def _render_income_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_income_section.html", _income_context(request, year, month), request=request
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


class CockpitIncomeSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_income_section(request, int(year), int(month))


class CockpitIncomeCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request, year, month):
        form = CockpitIncomeForm(request.POST)
        if form.is_valid():
            form.save_for_user(request.user)
            return _render_income_section(request, int(year), int(month), toast="Renda salva!")
        ctx = _income_context(request, int(year), int(month))
        ctx["income_form"] = form
        return HttpResponse(render_to_string("cockpit/_income_section.html", ctx, request=request))


class CockpitIncomeDeleteView(HtmxLoginRequiredMixin, View):
    def delete(self, request, year, month, pk):
        inc = Income.objects.filter(user=request.user, pk=pk).first()
        if not inc:
            raise Http404
        inc.delete()
        return _render_income_section(request, int(year), int(month), toast="Renda excluída!")
```

- [ ] **Step 4: Add routes** in `src/backend/finances/urls.py`

Add to the imports block:
```python
from finances.views.cockpit import (
    CockpitIncomeCreateView,
    CockpitIncomeDeleteView,
    CockpitIncomeSectionView,
)
```
Add to `urlpatterns` (after the Entries block):
```python
    # Cockpit — income
    path("cockpit/<int:year>/<int:month>/income/", CockpitIncomeSectionView.as_view(), name="cockpit_income"),
    path("cockpit/<int:year>/<int:month>/income/create/", CockpitIncomeCreateView.as_view(), name="cockpit_income_create"),
    path("cockpit/<int:year>/<int:month>/income/<uuid:pk>/delete/", CockpitIncomeDeleteView.as_view(), name="cockpit_income_delete"),
```

- [ ] **Step 5: Create the section partial**

```html
{# src/backend/templates/cockpit/_income_section.html #}
{% load finance_filters %}
<div id="cockpit-income" class="card bg-base-100 shadow-sm mb-4">
  <div class="card-body p-4">
    <h3 class="font-semibold flex items-center gap-2">💰 Renda do mês</h3>
    <table class="table table-sm">
      <tbody>
        {% for inc in incomes %}
        <tr>
          <td>{{ inc.name }}</td>
          <td class="text-right whitespace-nowrap">{{ inc.amount|brl }}</td>
          <td class="text-right">
            <button class="btn btn-ghost btn-xs"
                    hx-delete="{% url 'finances:cockpit_income_delete' current_year current_month inc.pk %}"
                    hx-target="#cockpit-income" hx-swap="outerHTML"
                    hx-confirm="Excluir esta renda?">🗑</button>
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="3" class="text-center opacity-60">Nenhuma renda neste mês.</td></tr>
        {% endfor %}
      </tbody>
      <tfoot>
        <tr class="font-bold"><td>Total</td>
          <td class="text-right whitespace-nowrap">{% income_total incomes %}</td><td></td></tr>
      </tfoot>
    </table>
    <form hx-post="{% url 'finances:cockpit_income_create' current_year current_month %}"
          hx-target="#cockpit-income" hx-swap="outerHTML"
          class="flex flex-wrap items-end gap-2 mt-2">
      {{ income_form.name }}{{ income_form.amount }}{{ income_form.month }}
      <label class="label cursor-pointer gap-1 text-xs">
        {{ income_form.repeat_until_december }} repetir até dez
      </label>
      <button class="btn btn-primary btn-sm" type="submit">+ adicionar</button>
    </form>
  </div>
</div>
```

Note: the `{% income_total %}` tag and a maskable edit flow are added next; for now, replace the tfoot total line with a Python-computed value to avoid a missing tag. Simplest: compute in `_income_context` and render `{{ income_month_total|brl }}`. Update `_income_context` to add:
```python
    total = sum((i.amount for i in incomes_qs), Decimal("0"))
```
(See Step 3 — refactor `incomes` to a list and add `"income_month_total": total`.) Then tfoot:
```html
<td class="text-right whitespace-nowrap">{{ income_month_total|brl }}</td>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_income_views.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances/views/cockpit.py src/backend/finances/urls.py src/backend/templates/cockpit/_income_section.html src/backend/finances/tests/test_cockpit_income_views.py
git commit -m "feat(cockpit): month-scoped income section (list/create/delete)"
```

### Task 2.3: Mount the income section on the Entradas page

**Files:**
- Modify: `src/backend/templates/entries/entries_page.html` (include the section, loaded via htmx for the current month)
- Modify: `src/backend/finances/views/entries.py:43-67` (pass `current_year`/`current_month` already present — add nothing if present)
- Test: `src/backend/finances/tests/test_entries_page_sections.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_entries_page_sections.py
from datetime import date
from django.test import TestCase
from model_bakery import baker
from core.models import CustomUser


class TestEntriesPageSections(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_entries_page_includes_income_section_loader(self):
        resp = self.client.get("/entries/2026/10/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The page should lazy-load the income section for this month via htmx.
        self.assertIn("/cockpit/2026/10/income/", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_entries_page_sections.py -v`
Expected: FAIL — the URL is not in the page.

- [ ] **Step 3: Include the section loader in `entries_page.html`**

After the `<div id="entries-container">…</div>` block, add a container that lazy-loads the income section for the current month:

```html
<div hx-get="{% url 'finances:cockpit_income' current_year current_month %}"
     hx-trigger="load" hx-swap="outerHTML"></div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_entries_page_sections.py -v`
Expected: PASS.

- [ ] **Step 5: Manual check + Commit**

Browse `/entries/2026/10/`: the "Renda do mês" card renders, add/delete works, "repetir até dez" creates Nov+Dec too (check by switching month tabs).

```bash
git add src/backend/templates/entries/entries_page.html src/backend/finances/tests/test_entries_page_sections.py
git commit -m "feat(cockpit): mount income section on Entradas page"
```

---

## Deliverable 3 — Gastos sistemáticos do mês

List every **active** `SystemicExpense` template for the selected month. For each, find the SYSTEMIC `Entry` whose `billing_month` is that month (and `systemic_expense` matches). If present → show amount (editable) + "não ocorreu" (delete). If absent → "não lançado" + "lançar R$<default>" (create via `create_monthly_entry`).

### Task 3.1: Service to pair active systemics with the month's entry

**Files:**
- Create: `src/backend/finances/services/systemic_month.py`
- Test: `src/backend/finances/tests/test_systemic_month.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_systemic_month.py
from datetime import date
from django.test import TestCase
from model_bakery import baker
from core.models import CustomUser
from finances.models import Category, Entry, SystemicExpense
from finances.models.entry import EntryType


class TestSystemicMonth(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.cat = baker.make(Category, user=self.user)

    def test_pairs_active_templates_with_month_entry(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(SystemicExpense, user=self.user, name="Aluguel",
                        category=self.cat, default_amount="1500", is_active=True)
        s2 = baker.make(SystemicExpense, user=self.user, name="Academia",
                        category=self.cat, default_amount="80", is_active=True)
        baker.make(SystemicExpense, user=self.user, name="Antigo",
                   category=self.cat, default_amount="10", is_active=False)
        entry = s1.create_monthly_entry(date(2026, 10, 1))

        rows = systemic_rows_for_month(self.user, 2026, 10)
        by_name = {r["systemic"].name: r for r in rows}
        self.assertEqual(set(by_name), {"Aluguel", "Academia"})  # inactive excluded
        self.assertEqual(by_name["Aluguel"]["entry"], entry)
        self.assertIsNone(by_name["Academia"]["entry"])

    def test_entry_from_other_month_not_paired(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(SystemicExpense, user=self.user, name="Aluguel",
                        category=self.cat, default_amount="1500", is_active=True)
        s1.create_monthly_entry(date(2026, 9, 1))
        rows = systemic_rows_for_month(self.user, 2026, 10)
        self.assertIsNone(rows[0]["entry"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_systemic_month.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the service**

```python
# src/backend/finances/services/systemic_month.py
from datetime import date

from finances.models import Entry, SystemicExpense
from finances.models.entry import EntryType


def systemic_rows_for_month(user, year, month):
    """Return [{"systemic": <template>, "entry": <Entry or None>}] for active templates."""
    billing_month = date(year, month, 1)
    templates = (
        SystemicExpense.objects.filter(user=user, is_active=True)
        .select_related("category", "payment_method")
        .order_by("name")
    )
    entries = {
        e.systemic_expense_id: e
        for e in Entry.objects.filter(
            user=user, entry_type=EntryType.SYSTEMIC, billing_month=billing_month,
            systemic_expense__isnull=False,
        )
    }
    return [{"systemic": t, "entry": entries.get(t.id)} for t in templates]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/backend/finances/tests/test_systemic_month.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/services/systemic_month.py src/backend/finances/tests/test_systemic_month.py
git commit -m "feat(finances): systemic_rows_for_month service"
```

### Task 3.2: Systemic section views (list / lançar / edit amount / não ocorreu)

**Files:**
- Modify: `src/backend/finances/views/cockpit.py` (add systemic views)
- Modify: `src/backend/finances/urls.py` (routes)
- Create: `src/backend/templates/cockpit/_systemic_section.html`
- Test: `src/backend/finances/tests/test_cockpit_systemic_views.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_cockpit_systemic_views.py
from datetime import date
from decimal import Decimal
from django.test import TestCase
from model_bakery import baker
from core.models import CustomUser
from finances.models import Category, Entry, SystemicExpense
from finances.models.entry import EntryType


class TestCockpitSystemicViews(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user)
        self.s = baker.make(SystemicExpense, user=self.user, name="Aluguel",
                            category=self.cat, default_amount="1500", is_active=True)

    def test_lancar_creates_entry_with_default(self):
        resp = self.client.post(f"/cockpit/2026/10/systemic/{self.s.pk}/post/")
        self.assertEqual(resp.status_code, 200)
        e = Entry.objects.get(user=self.user, systemic_expense=self.s, billing_month=date(2026, 10, 1))
        self.assertEqual(e.amount, Decimal("1500.00"))
        self.assertEqual(e.entry_type, EntryType.SYSTEMIC)

    def test_edit_amount_updates_entry(self):
        e = self.s.create_monthly_entry(date(2026, 10, 1))
        resp = self.client.post(f"/cockpit/2026/10/systemic/{self.s.pk}/post/", {"amount": "1600.50"})
        self.assertEqual(resp.status_code, 200)
        e.refresh_from_db()
        self.assertEqual(e.amount, Decimal("1600.50"))

    def test_nao_ocorreu_deletes_entry(self):
        e = self.s.create_monthly_entry(date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/systemic/{self.s.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Entry.objects.filter(pk=e.pk).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_systemic_views.py -v`
Expected: FAIL — routes don't exist.

- [ ] **Step 3: Implement the systemic views** (append to `cockpit.py`)

```python
# src/backend/finances/views/cockpit.py  (additions)
from decimal import Decimal, InvalidOperation

from finances.models import Entry, SystemicExpense
from finances.models.entry import EntryType
from finances.services.systemic_month import systemic_rows_for_month


def _systemic_context(request, year, month):
    return {
        "current_year": year,
        "current_month": month,
        "systemic_rows": systemic_rows_for_month(request.user, year, month),
    }


def _render_systemic_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_systemic_section.html", _systemic_context(request, year, month), request=request
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


class CockpitSystemicSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_systemic_section(request, int(year), int(month))


class CockpitSystemicPostView(HtmxLoginRequiredMixin, View):
    """Create the month entry (lançar) or update its amount."""

    def post(self, request, year, month, pk):
        y, m = int(year), int(month)
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        billing_month = date(y, m, 1)
        entry = Entry.objects.filter(
            user=request.user, systemic_expense=systemic, billing_month=billing_month
        ).first()
        amount = request.POST.get("amount")
        if entry is None:
            value = _parse_amount(amount, systemic.default_amount)
            systemic.create_monthly_entry(billing_month, amount=value)
        elif amount is not None:
            entry.amount = _parse_amount(amount, entry.amount)
            entry.save(update_fields=["amount", "updated_at"])
        return _render_systemic_section(request, y, m, toast=f"{systemic.name} lançado!")


class CockpitSystemicDeleteView(HtmxLoginRequiredMixin, View):
    """'Não ocorreu' — remove the month entry."""

    def delete(self, request, year, month, pk):
        y, m = int(year), int(month)
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            raise Http404
        Entry.objects.filter(
            user=request.user, systemic_expense=systemic, billing_month=date(y, m, 1)
        ).delete()
        return _render_systemic_section(request, y, m, toast=f"{systemic.name}: não ocorreu")


def _parse_amount(raw, fallback):
    try:
        return Decimal(str(raw)) if raw not in (None, "") else fallback
    except (InvalidOperation, TypeError):
        return fallback
```

Note `Entry.save(update_fields=[..., "updated_at"])` — confirm `Entry` has `updated_at` (auto_now); if not, drop it from `update_fields`. Check `finances/models/entry.py` first.

- [ ] **Step 4: Routes** in `finances/urls.py`

Imports:
```python
from finances.views.cockpit import (
    CockpitSystemicDeleteView,
    CockpitSystemicPostView,
    CockpitSystemicSectionView,
)
```
Routes:
```python
    path("cockpit/<int:year>/<int:month>/systemic/", CockpitSystemicSectionView.as_view(), name="cockpit_systemic"),
    path("cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/post/", CockpitSystemicPostView.as_view(), name="cockpit_systemic_post"),
    path("cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/delete/", CockpitSystemicDeleteView.as_view(), name="cockpit_systemic_delete"),
```

- [ ] **Step 5: Section partial**

```html
{# src/backend/templates/cockpit/_systemic_section.html #}
{% load finance_filters %}
<div id="cockpit-systemic" class="card bg-base-100 shadow-sm mb-4">
  <div class="card-body p-4">
    <h3 class="font-semibold flex items-center gap-2">🔁 Gastos sistemáticos do mês</h3>
    <table class="table table-sm">
      <tbody>
        {% for row in systemic_rows %}
        <tr>
          <td>{{ row.systemic.name }}</td>
          <td class="text-right whitespace-nowrap">
            {% if row.entry %}{{ row.entry.amount|brl }}{% else %}<span class="opacity-50">não lançado</span>{% endif %}
          </td>
          <td class="text-right">
            {% if row.entry %}
              <form class="inline-flex gap-1" hx-post="{% url 'finances:cockpit_systemic_post' current_year current_month row.systemic.pk %}"
                    hx-target="#cockpit-systemic" hx-swap="outerHTML">
                <input name="amount" type="number" step="0.01" value="{{ row.entry.amount }}" class="input input-bordered input-xs w-24">
                <button class="btn btn-ghost btn-xs" type="submit">✎</button>
              </form>
              <button class="btn btn-ghost btn-xs"
                      hx-delete="{% url 'finances:cockpit_systemic_delete' current_year current_month row.systemic.pk %}"
                      hx-target="#cockpit-systemic" hx-swap="outerHTML"
                      hx-confirm="Marcar como não ocorrido neste mês?">não ocorreu</button>
            {% else %}
              <button class="btn btn-outline btn-xs"
                      hx-post="{% url 'finances:cockpit_systemic_post' current_year current_month row.systemic.pk %}"
                      hx-target="#cockpit-systemic" hx-swap="outerHTML">lançar {{ row.systemic.default_amount|brl }}</button>
            {% endif %}
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="3" class="text-center opacity-60">Nenhum gasto sistemático ativo.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_systemic_views.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Mount on Entradas page + commit**

In `entries_page.html`, add another lazy-loader after the income one:
```html
<div hx-get="{% url 'finances:cockpit_systemic' current_year current_month %}"
     hx-trigger="load" hx-swap="outerHTML"></div>
```

```bash
git add src/backend/finances/views/cockpit.py src/backend/finances/urls.py src/backend/templates/cockpit/_systemic_section.html src/backend/templates/entries/entries_page.html src/backend/finances/tests/test_cockpit_systemic_views.py
git commit -m "feat(cockpit): month systemic section (lançar/editar/não-ocorreu)"
```

---

## Deliverable 4 — Vencimentos do mês (credit-card closing day)

For active `credit_card` payment methods, show the effective closing day for the month via `resolve_closing_day(month)`, editable. Saving writes/updates `PaymentMethodClosingDay`; clearing reverts to default (deletes the override).

### Task 4.1: Confirm/locate `resolve_closing_day`

**Files:**
- Read: `src/backend/finances/models/payment_method.py` and grep for `resolve_closing_day`
- Test: covered in Task 4.2

- [ ] **Step 1: Locate the helper**

Run: `grep -rn "def resolve_closing_day" src/backend/finances/`
Expected: a function/method that returns the override for a month if present, else `PaymentMethod.closing_day`. Note its call signature (likely `pm.resolve_closing_day(month)` or `resolve_closing_day(pm, month)`); use that exact signature in Task 4.2. If it does NOT exist, implement it on `PaymentMethod`:

```python
# src/backend/finances/models/payment_method.py  (method on PaymentMethod)
def resolve_closing_day(self, month):
    from finances.models.payment_method_closing_day import PaymentMethodClosingDay
    override = PaymentMethodClosingDay.objects.filter(
        payment_method=self, month=month.replace(day=1)
    ).first()
    return override.closing_day if override else self.closing_day
```

### Task 4.2: Vencimentos section views + override write/clear

**Files:**
- Modify: `src/backend/finances/views/cockpit.py`
- Modify: `src/backend/finances/urls.py`
- Create: `src/backend/templates/cockpit/_vencimentos_section.html`
- Test: `src/backend/finances/tests/test_cockpit_vencimentos.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_cockpit_vencimentos.py
from datetime import date
from django.test import TestCase
from model_bakery import baker
from core.models import CustomUser
from finances.models import PaymentMethod
from finances.models.payment_method import PaymentType
from finances.models.payment_method_closing_day import PaymentMethodClosingDay


class TestCockpitVencimentos(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.pm = baker.make(PaymentMethod, user=self.user, name="Nubank",
                             type=PaymentType.CREDIT_CARD, closing_day=10, is_active=True)

    def test_section_lists_only_active_credit_cards(self):
        baker.make(PaymentMethod, user=self.user, name="Pix", type=PaymentType.PIX, is_active=True)
        resp = self.client.get("/cockpit/2026/10/vencimentos/")
        body = resp.content.decode()
        self.assertIn("Nubank", body)
        self.assertNotIn("Pix", body)

    def test_set_override_creates_row(self):
        resp = self.client.post(f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": "12"})
        self.assertEqual(resp.status_code, 200)
        ov = PaymentMethodClosingDay.objects.get(payment_method=self.pm, month=date(2026, 10, 1))
        self.assertEqual(ov.closing_day, 12)

    def test_update_override(self):
        baker.make(PaymentMethodClosingDay, payment_method=self.pm, month=date(2026, 10, 1), closing_day=12)
        self.client.post(f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": "15"})
        ov = PaymentMethodClosingDay.objects.get(payment_method=self.pm, month=date(2026, 10, 1))
        self.assertEqual(ov.closing_day, 15)

    def test_clear_override_reverts_to_default(self):
        baker.make(PaymentMethodClosingDay, payment_method=self.pm, month=date(2026, 10, 1), closing_day=12)
        self.client.post(f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": ""})
        self.assertFalse(PaymentMethodClosingDay.objects.filter(
            payment_method=self.pm, month=date(2026, 10, 1)).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_vencimentos.py -v`
Expected: FAIL — routes don't exist.

- [ ] **Step 3: Implement views** (append to `cockpit.py`)

```python
# src/backend/finances/views/cockpit.py  (additions)
from finances.models import PaymentMethod
from finances.models.payment_method import PaymentType
from finances.models.payment_method_closing_day import PaymentMethodClosingDay


def _vencimentos_context(request, year, month):
    billing_month = date(year, month, 1)
    cards = PaymentMethod.objects.filter(
        user=request.user, type=PaymentType.CREDIT_CARD, is_active=True
    ).order_by("name")
    rows = []
    for pm in cards:
        override = PaymentMethodClosingDay.objects.filter(
            payment_method=pm, month=billing_month
        ).first()
        rows.append({
            "pm": pm,
            "effective_day": override.closing_day if override else pm.closing_day,
            "is_override": override is not None,
        })
    return {"current_year": year, "current_month": month, "venc_rows": rows}


def _render_vencimentos_section(request, year, month, toast=None):
    html = render_to_string(
        "cockpit/_vencimentos_section.html", _vencimentos_context(request, year, month), request=request
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{toast}", "type": "success"}}}}'
    return response


class CockpitVencimentosSectionView(HtmxLoginRequiredMixin, View):
    def get(self, request, year, month):
        return _render_vencimentos_section(request, int(year), int(month))


class CockpitVencimentoSetView(HtmxLoginRequiredMixin, View):
    def post(self, request, year, month, pk):
        y, m = int(year), int(month)
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            raise Http404
        billing_month = date(y, m, 1)
        raw = (request.POST.get("closing_day") or "").strip()
        if raw == "":
            PaymentMethodClosingDay.objects.filter(payment_method=pm, month=billing_month).delete()
            toast = f"{pm.name}: vencimento padrão"
        else:
            day = max(1, min(31, int(raw)))
            PaymentMethodClosingDay.objects.update_or_create(
                payment_method=pm, month=billing_month, defaults={"closing_day": day}
            )
            toast = f"{pm.name}: fecha dia {day}"
        return _render_vencimentos_section(request, y, m, toast=toast)
```

- [ ] **Step 4: Routes**

```python
from finances.views.cockpit import (
    CockpitVencimentosSectionView,
    CockpitVencimentoSetView,
)
```
```python
    path("cockpit/<int:year>/<int:month>/vencimentos/", CockpitVencimentosSectionView.as_view(), name="cockpit_vencimentos"),
    path("cockpit/<int:year>/<int:month>/vencimentos/<uuid:pk>/", CockpitVencimentoSetView.as_view(), name="cockpit_vencimento_set"),
```

- [ ] **Step 5: Section partial**

```html
{# src/backend/templates/cockpit/_vencimentos_section.html #}
<div id="cockpit-vencimentos" class="card bg-base-100 shadow-sm mb-4">
  <div class="card-body p-4">
    <h3 class="font-semibold flex items-center gap-2">📅 Vencimentos do mês (cartões)</h3>
    <table class="table table-sm">
      <tbody>
        {% for row in venc_rows %}
        <tr>
          <td>{{ row.pm.name }}</td>
          <td>
            <form class="inline-flex items-center gap-1"
                  hx-post="{% url 'finances:cockpit_vencimento_set' current_year current_month row.pm.pk %}"
                  hx-target="#cockpit-vencimentos" hx-swap="outerHTML">
              fecha dia <input name="closing_day" type="number" min="1" max="31"
                     value="{{ row.effective_day|default_if_none:'' }}" class="input input-bordered input-xs w-16">
              <button class="btn btn-ghost btn-xs" type="submit">✎</button>
              {% if row.is_override %}<span class="badge badge-xs badge-warning">override</span>
              {% else %}<span class="opacity-50 text-xs">padrão</span>{% endif %}
            </form>
          </td>
        </tr>
        {% empty %}
        <tr><td colspan="2" class="text-center opacity-60">Nenhum cartão de crédito ativo.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest src/backend/finances/tests/test_cockpit_vencimentos.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Mount on Entradas page + commit**

Add lazy-loader to `entries_page.html`:
```html
<div hx-get="{% url 'finances:cockpit_vencimentos' current_year current_month %}"
     hx-trigger="load" hx-swap="outerHTML"></div>
```

```bash
git add src/backend/finances/views/cockpit.py src/backend/finances/urls.py src/backend/templates/cockpit/_vencimentos_section.html src/backend/templates/entries/entries_page.html src/backend/finances/tests/test_cockpit_vencimentos.py
git commit -m "feat(cockpit): month vencimentos section (per-month closing day override)"
```

---

## Final integration & polish

### Task 5.1: Full suite + lint + visual pass

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest src/backend -q`
Expected: all pass (existing 309 + new cockpit tests).

- [ ] **Step 2: Lint**

Run: `uv run ruff check src/backend`
Expected: All checks passed.

- [ ] **Step 3: Visual pass with frontend-design skill**

Use the `frontend-design` skill to refine the four section cards (spacing, mobile layout, consistent DaisyUI components, the inline edit affordances). Verify on the local server (`http://127.0.0.1:8000/entries/2026/10/`, login `bessavagner`/`localdev123`) at mobile width. Reproduce: add recurring income, lançar/edit/“não ocorreu” a systemic, set/clear a closing-day override, and the Consolidado dropdown open/close.

- [ ] **Step 4: Commit any polish**

```bash
git add -A && git commit -m "style(cockpit): UI/UX polish across month sections"
```

### Task 5.2: Optional cleanup (only if requested)

- Remove the income editing UI from Settings (now redundant) — keep the model + Settings tab for templates only. Defer unless the user asks; the Settings income tab is harmless to leave.

---

## Self-review notes
- **Spec coverage:** item 1 (view income) → Deliverable 2 income section; item 2 (dropdown) → Deliverable 1; item 3 (per-month income/systemic/closing day incl. past) → Deliverables 2/3/4 (month is a URL param, no restriction on past months). ✓
- **Type/signature consistency:** view helpers `_income_context/_systemic_context/_vencimentos_context` and their `_render_*` pairs are named consistently; URL names match `entries_page.html` loaders. `create_monthly_entry(month, amount=…)` matches the model signature in `systemic_expense.py`.
- **Watch-outs flagged inline:** confirm `Entry.updated_at` before using it in `update_fields`; confirm/implement `resolve_closing_day` signature (Task 4.1); the income tfoot total is computed in Python (Task 2.2 Step 5 note), not a custom template tag.
</content>
