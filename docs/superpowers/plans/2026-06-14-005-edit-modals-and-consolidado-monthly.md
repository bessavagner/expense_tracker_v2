# 005 — Edit Modals + Monthly Consolidado — Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Universal edit-in-modal for all per-month entries, global bottom spacing fix, and a monthly card-dashboard Consolidado.

**Architecture:** Django + HTMX + Alpine + DaisyUI. A single parameterized modal partial (`partials/_modal_edit_form.html`) is reused; each section's modal-edit view re-renders its own section (outerHTML) and fires `entry-saved` to close the shared `#entry-modal`. Consolidado becomes month-scoped (month/year selectors) with category cards.

**Tech Stack:** pytest, Django 6, HTMX 2, Alpine 3, DaisyUI 5 / Tailwind 4 (prebuilt `static/css/tailwind.css`).

**Worktree:** `.claude/worktrees/005-edit-modals-consolidado` (branch `005-edit-modals-consolidado`). Run tests from `src/backend` via `uv run pytest`. `.env` (POSTGRES_PORT=5433 pgvector) must be present at worktree root.

---

## Task 1: Global bottom spacing (FAB/chat no longer cover last row)

**Files:**
- Modify: `src/backend/templates/base.html` (the `<main>` element, ~line 43)
- Test: `src/backend/core/tests/test_base_layout.py` (create)

- [ ] **Step 1: Write failing test**
```python
# src/backend/core/tests/test_base_layout.py
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

@pytest.mark.django_db
def test_main_has_bottom_padding_for_floating_controls(client):
    User = get_user_model()
    User.objects.create_user(username="u1", password="pw")
    client.login(username="u1", password="pw")
    resp = client.get(reverse("finances:settings"))
    html = resp.content.decode()
    assert "pb-28" in html  # main clears the fixed FAB + chat button
```
- [ ] **Step 2: Run → FAIL** (`uv run pytest core/tests/test_base_layout.py -q`)
- [ ] **Step 3: Implement** — change `<main class="flex-1 p-4 w-full max-w-7xl mx-auto">` to `<main class="flex-1 p-4 pb-28 w-full max-w-7xl mx-auto">`
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(005): global bottom padding so FAB/chat clear last row`

---

## Task 2: Shared modal partial + Lançamento row-click edit

Refactor the existing regular-entry modal to the shared partial and make the whole entries-table row open the edit modal (replacing the tiny ✏️). Keep `test_entry_edit_modal.py` green.

**Files:**
- Create: `src/backend/templates/partials/_modal_edit_form.html`
- Modify: `src/backend/finances/views/entries.py` (`EntryEditModalView.get`/`.post` render the shared partial with context `post_url`, `swap_target`, `swap_mode`, `title`)
- Modify: `src/backend/templates/entries/_entry_row.html` (row clickable; delete button stopPropagation; drop ✏️)
- Test: existing `src/backend/finances/tests/test_entry_edit_modal.py` (must stay green); add row-click assertion in `test_views_entries.py` or a new test.

- [ ] **Step 1:** Create shared partial:
```html
{# partials/_modal_edit_form.html #}
<h3 class="font-bold text-lg mb-4">{{ title|default:"Editar" }}</h3>
<form hx-post="{{ post_url }}"
      hx-target="{{ swap_target }}"
      hx-swap="{{ swap_mode|default:'outerHTML' }}"
      class="space-y-3">
    {% csrf_token %}
    {% for field in form %}
    <div class="form-control">
        <label class="label"><span class="label-text">{{ field.label }}</span></label>
        {{ field }}
        {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn btn-accent w-full">Salvar</button>
</form>
```
- [ ] **Step 2:** Point `EntryEditModalView` GET/POST at the shared partial. In both, build context:
```python
context = {
    "form": form,
    "title": "Editar Entrada",
    "post_url": reverse("finances:entry_edit_modal", args=[entry.id]),
    "swap_target": f"#entry-{entry.id}",
    "swap_mode": "outerHTML",
}
html = render_to_string("partials/_modal_edit_form.html", context, request=request)
```
(POST-success path unchanged: returns `entries/_entry_row.html` + HX-Trigger showToast + entry-saved. Keep `_patch_form_querysets`.) Add `from django.urls import reverse`. The old `partials/_modal_entry_edit_form.html` may be deleted.
- [ ] **Step 3:** Update `_entry_row.html` — make the `<tr>` open the modal, remove ✏️, keep 🗑️ with stopPropagation:
```html
{% load finance_filters %}
{% url 'finances:entry_delete' entry.id as delete_url %}
<tr id="entry-{{ entry.id }}"
    x-show="q === '' || $el.dataset.search.includes(q.toLowerCase())"
    data-search="{{ entry.description|lower }} {{ entry.category.name|lower }} {{ entry.amount }}"
    class="cursor-pointer hover:bg-base-200 {% if entry.amount < 0 %}text-success{% endif %} {% if entry.entry_type == 'systemic' %}bg-base-200{% endif %}"
    {% if entry.entry_type == 'regular' %}
    hx-get="{% url 'finances:entry_edit_modal' entry.id %}"
    hx-target="#entry-modal-content" hx-swap="innerHTML"
    onclick="document.getElementById('entry-modal').showModal()"
    {% endif %}>
    <td>{{ entry.date|date:"d/m" }}</td>
    <td class="whitespace-nowrap">{{ entry.amount|money }}</td>
    <td>{{ entry.description }}</td>
    <td><span class="badge badge-sm">{{ entry.category.name }}</span></td>
    <td>{{ entry.payment_method.name }}</td>
    <td>{{ entry.billing_month|date:"M" }}</td>
    <td>
        {% if entry.entry_type == 'regular' and delete_url %}
        <button class="btn btn-ghost btn-xs text-error"
                hx-delete="{{ delete_url }}"
                hx-target="#entry-{{ entry.id }}"
                hx-swap="outerHTML swap:1s"
                hx-confirm="Excluir esta entrada?"
                onclick="event.stopPropagation()">🗑️</button>
        {% endif %}
    </td>
</tr>
```
- [ ] **Step 4:** Run `uv run pytest finances/tests/test_entry_edit_modal.py finances/tests/test_views_entries.py -q` → PASS. Add a test asserting the row carries `hx-get` to the edit-modal url.
- [ ] **Step 5:** Commit `feat(005): shared modal partial + clickable lançamento row edit`

---

## Task 3: Renda edit-in-modal (cockpit income)

**Files:**
- Modify: `src/backend/finances/views/cockpit.py` (add `CockpitIncomeEditModalView`)
- Modify: `src/backend/finances/urls.py` (route `cockpit_income_edit_modal`)
- Modify: `src/backend/templates/cockpit/_income_section.html` (clickable row → modal; delete stopPropagation)
- Test: `src/backend/finances/tests/test_cockpit_income_edit_modal.py` (create)

- [ ] **Step 1: Failing tests** — GET returns form prefilled with the income; POST valid updates the Income and returns `#cockpit-income` section with HX-Trigger containing `entry-saved`; POST renders updated amount; cross-user 404.
```python
# essentials
import pytest
from datetime import date
from django.contrib.auth import get_user_model
from django.urls import reverse
from finances.models import Income

@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="u", password="pw")

@pytest.fixture
def income(user):
    return Income.objects.create(user=user, name="Salário", amount=5000, month=date(2026,6,1))

def test_get_returns_form(client, user, income):
    client.force_login(user)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026,6,income.id])
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Salário" in resp.content.decode()

def test_post_updates_and_rerenders_section(client, user, income):
    client.force_login(user)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026,6,income.id])
    resp = client.post(url, {"name":"Salário","amount":"5500","month":"2026-06-01","is_recurring":""})
    assert resp.status_code == 200
    income.refresh_from_db()
    assert income.amount == 5500
    assert "entry-saved" in resp.headers.get("HX-Trigger","")
    assert "cockpit-income" in resp.content.decode()

def test_cross_user_404(client, income):
    other = get_user_model().objects.create_user(username="o", password="pw")
    client.force_login(other)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026,6,income.id])
    assert client.get(url).status_code == 404
```
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement view:**
```python
from django.urls import reverse
from finances.forms import IncomeForm

class CockpitIncomeEditModalView(HtmxLoginRequiredMixin, View):
    def _income(self, request, pk):
        inc = Income.objects.filter(user=request.user, pk=pk).first()
        if not inc:
            raise Http404
        return inc

    def get(self, request, year, month, pk):
        inc = self._income(request, pk)
        form = IncomeForm(instance=inc)
        context = {
            "form": form, "title": "Editar Renda",
            "post_url": reverse("finances:cockpit_income_edit_modal", args=[year, month, inc.id]),
            "swap_target": "#cockpit-income", "swap_mode": "outerHTML",
        }
        return HttpResponse(render_to_string("partials/_modal_edit_form.html", context, request=request))

    def post(self, request, year, month, pk):
        inc = self._income(request, pk)
        form = IncomeForm(request.POST, instance=inc)
        if form.is_valid():
            form.save()
            html = render_to_string(
                "cockpit/_income_section.html", _income_context(request, int(year), int(month)), request=request)
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Renda atualizada!", "type": "success"}, "entry-saved": true}')
            return response
        context = {
            "form": form, "title": "Editar Renda",
            "post_url": reverse("finances:cockpit_income_edit_modal", args=[year, month, inc.id]),
            "swap_target": "#cockpit-income", "swap_mode": "outerHTML",
        }
        return HttpResponse(render_to_string("partials/_modal_edit_form.html", context, request=request))
```
Route: `path("cockpit/<int:year>/<int:month>/income/<uuid:pk>/edit-modal/", CockpitIncomeEditModalView.as_view(), name="cockpit_income_edit_modal")` and add to the import list.
- [ ] **Step 4:** Make income row clickable in `_income_section.html`:
```html
<tr class="cursor-pointer hover:bg-base-200"
    hx-get="{% url 'finances:cockpit_income_edit_modal' current_year current_month inc.pk %}"
    hx-target="#entry-modal-content" hx-swap="innerHTML"
    onclick="document.getElementById('entry-modal').showModal()">
  <td>{{ inc.name }}</td>
  <td class="text-right whitespace-nowrap">{{ inc.amount|money }}</td>
  <td class="text-right">
    <button class="btn btn-ghost btn-xs"
            hx-delete="{% url 'finances:cockpit_income_delete' current_year current_month inc.pk %}"
            hx-target="#cockpit-income" hx-swap="outerHTML"
            hx-confirm="Excluir esta renda?"
            onclick="event.stopPropagation()">Excluir</button>
  </td>
</tr>
```
- [ ] **Step 5:** Run → PASS. Commit `feat(005): edit renda in modal (cockpit income row)`

---

## Task 4: Sistemático edit-in-modal (this-month entry)

Replace the inline amount form: a lançado row shows amount as text and is clickable to edit its `Entry` via modal (full `EntryForm`); keep "não ocorreu". Non-lançado rows keep "lançar".

**Files:**
- Modify: `src/backend/finances/views/cockpit.py` (`CockpitSystemicEditModalView`; reuse `_patch_form_querysets` logic locally or import from entries)
- Modify: `src/backend/finances/urls.py` (`cockpit_systemic_edit_modal`)
- Modify: `src/backend/templates/cockpit/_systemic_section.html`
- Test: `src/backend/finances/tests/test_cockpit_systemic_edit_modal.py`

`pk` = SystemicExpense id; the view resolves this month's Entry (`systemic_expense=pk, billing_month=(y,m,1)`); 404 if none lançado.

- [ ] **Step 1: Failing tests** — GET returns prefilled `EntryForm` for the month entry; POST valid updates entry amount/desc and re-renders `#cockpit-systemic` + `entry-saved`; GET 404 when not lançado; cross-user 404.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement view:**
```python
from finances.forms import EntryForm
from finances.models import Category, PaymentMethod

class CockpitSystemicEditModalView(HtmxLoginRequiredMixin, View):
    def _entry(self, request, year, month, pk):
        billing_month = date(int(year), int(month), 1)
        entry = Entry.objects.filter(
            user=request.user, systemic_expense_id=pk, billing_month=billing_month).first()
        if not entry:
            raise Http404
        return entry

    def _patch(self, form, entry):
        form.fields["category"].queryset = (
            form.fields["category"].queryset | Category.objects.filter(pk=entry.category_id))
        form.fields["payment_method"].queryset = (
            form.fields["payment_method"].queryset | PaymentMethod.objects.filter(pk=entry.payment_method_id))

    def _ctx(self, request, year, month, pk, form):
        return {"form": form, "title": "Editar Sistemático",
                "post_url": reverse("finances:cockpit_systemic_edit_modal", args=[year, month, pk]),
                "swap_target": "#cockpit-systemic", "swap_mode": "outerHTML"}

    def get(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = EntryForm(instance=entry, user=request.user); self._patch(form, entry)
        return HttpResponse(render_to_string("partials/_modal_edit_form.html",
                            self._ctx(request, year, month, pk, form), request=request))

    def post(self, request, year, month, pk):
        entry = self._entry(request, year, month, pk)
        form = EntryForm(request.POST, instance=entry, user=request.user); self._patch(form, entry)
        if form.is_valid():
            form.save()
            html = render_to_string("cockpit/_systemic_section.html",
                    _systemic_context(request, int(year), int(month)), request=request)
            response = HttpResponse(html)
            response["HX-Trigger"] = ('{"showToast": {"message": "Sistemático atualizado!", "type": "success"}, "entry-saved": true}')
            return response
        return HttpResponse(render_to_string("partials/_modal_edit_form.html",
                            self._ctx(request, year, month, pk, form), request=request))
```
Route: `cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/edit-modal/`.
- [ ] **Step 4:** Template — for `row.entry` rows make `<tr>` clickable to the modal, amount shown as text, "não ocorreu" button with stopPropagation; for non-lançado keep the "lançar" button row (not clickable). Remove the inline amount `<form>`/input.
- [ ] **Step 5:** Run → PASS. Commit `feat(005): edit sistemático month-entry in modal`

---

## Task 5: Parcelamento edit-in-modal (this-month entry)

**Files:**
- Modify: `src/backend/finances/services/installment_month.py` (add `"entry": this_entry` to each row dict)
- Modify: `src/backend/finances/views/cockpit.py` (`CockpitParcelamentoEditModalView`, `entry_pk` = Entry id)
- Modify: `src/backend/finances/urls.py` (`cockpit_parcelamento_edit_modal`)
- Modify: `src/backend/templates/cockpit/_parcelamentos_section.html` (clickable row)
- Test: `src/backend/finances/tests/test_cockpit_parcelamento_edit_modal.py`; update `test_cockpit_parcelamentos_views.py` if it asserts row keys.

- [ ] **Step 1:** Add `"entry": this_entry` to the row dict in `installment_rows_for_month`.
- [ ] **Step 2: Failing tests** — GET returns prefilled EntryForm for an installment entry; POST valid updates and re-renders `#cockpit-parcelamentos` + `entry-saved`; cross-user 404. (Use `InstallmentPlan.generate_entries()` to create entries; pick one for the month.)
- [ ] **Step 3: Implement view** (same shape as Task 4 but resolves Entry by `entry_pk` filtered `entry_type=installment, user`; re-renders parcelamentos section). Re-render uses:
```python
ctx = {"current_year": y, "current_month": m,
       "parcelamento_rows": installment_rows_for_month(request.user, y, m)}
html = render_to_string("cockpit/_parcelamentos_section.html", ctx, request=request)
```
Route: `cockpit/<int:year>/<int:month>/parcelamento/<uuid:entry_pk>/edit-modal/`.
- [ ] **Step 4:** Template — make the `<tr>` clickable (`hx-get` to the modal url with `row.entry.id`, target `#entry-modal-content`, open dialog), keeping the existing Alpine `x-show` search.
- [ ] **Step 5:** Run → PASS. Commit `feat(005): edit parcelamento month-entry in modal`

---

## Task 6: Consolidado backend — monthly context

**Files:**
- Modify: `src/backend/finances/views/consolidated.py` (`ConsolidatedView.get_context_data` → month-scoped; `CategoryDetailView` template → new partial)
- Test: `src/backend/finances/tests/test_views_consolidated.py` (update to month context), `test_consolidated_dropdown.py` (month+year selectors)

- [ ] **Step 1: Update/Write failing tests** — context has `current_month`, `months == list(range(1,13))`, `category_cards` (each: `id`, `name`, `total`, `budget_ceiling`, `pct`, `status`, `has_ceiling`), `month_total`, `income_total`, `saldo`; diverse excludes systemic, systemics tab includes only systemic; cards sorted by `total` desc; only the selected month is aggregated.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `get_context_data`:
```python
year = int(self.request.GET.get("year", date.today().year))
month = int(self.request.GET.get("month", date.today().month))
billing_month = date(year, month, 1)
context["current_year"] = year
context["current_month"] = month
context["months"] = list(range(1, 13))
context["year_range"] = range(2024, date.today().year + 2)
context["tab"] = "systemics" if self.entry_type_filter == EntryType.SYSTEMIC else "diverse"

qs = Entry.objects.filter(user=self.request.user, billing_month=billing_month)
qs = (qs.filter(entry_type=EntryType.SYSTEMIC) if self.entry_type_filter == EntryType.SYSTEMIC
      else qs.exclude(entry_type=EntryType.SYSTEMIC))
agg = (qs.values("category__id", "category__name", "category__budget_ceiling")
         .annotate(total=Sum("amount")).order_by("-total"))
cards = []
for r in agg:
    total = r["total"] or Decimal("0")
    ceiling = r["category__budget_ceiling"]
    has_ceiling = bool(ceiling and ceiling > 0)
    pct = int((total / ceiling * 100).quantize(Decimal("1"))) if has_ceiling else 0
    status = "success"
    if has_ceiling:
        if pct >= 100: status = "error"
        elif pct >= 90: status = "warning"
    cards.append({"id": r["category__id"], "name": r["category__name"], "total": total,
                  "budget_ceiling": ceiling, "pct": pct, "status": status, "has_ceiling": has_ceiling})
context["category_cards"] = cards
context["month_total"] = sum((c["total"] for c in cards), Decimal("0"))
context["income_total"] = sum(
    (i.amount for i in Income.objects.filter(user=self.request.user, month=billing_month)), Decimal("0"))
context["saldo"] = context["income_total"] - context["month_total"]
```
Add imports `from finances.models import Income`. Switch `CategoryDetailView.template_name`/`htmx_template_name` to `consolidated/_category_entries.html`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(005): month-scoped consolidado context + summary`

---

## Task 7: Consolidado templates — selectors, summary, cards, detail

**Files:**
- Rewrite: `src/backend/templates/consolidated/consolidated_page.html` (month+year selectors; keep sub-tabs carrying month)
- Rewrite: `src/backend/templates/consolidated/_consolidated_table.html` → card dashboard (rename content, keep filename used by the view's `htmx_template_name`/include)
- Create: `src/backend/templates/consolidated/_category_entries.html`
- Delete: `src/backend/templates/consolidated/_category_detail.html`

- [ ] **Step 1:** `consolidated_page.html`: header with month `<select>` (`{{ m|month_abbr }}`) + year `<select>`, both calling `htmx.ajax('GET', '/consolidated/{systemics/}?year=&month=', {target:'#consolidated-container', swap:'innerHTML'})`; sub-tab links carry `?year={{current_year}}&month={{current_month}}`; `{% load finance_filters %}`.
- [ ] **Step 2:** `_consolidated_table.html` becomes the card dashboard:
```html
{% load finance_filters %}
<div class="grid grid-cols-3 gap-2 mb-4">
  <div class="stat bg-base-100 rounded-box p-3"><div class="stat-title text-xs">Total gasto</div><div class="stat-value text-lg">{{ month_total|money }}</div></div>
  <div class="stat bg-base-100 rounded-box p-3"><div class="stat-title text-xs">Renda</div><div class="stat-value text-lg">{{ income_total|money }}</div></div>
  <div class="stat bg-base-100 rounded-box p-3"><div class="stat-title text-xs">Saldo</div><div class="stat-value text-lg {% if saldo < 0 %}text-error{% else %}text-success{% endif %}">{{ saldo|money }}</div></div>
</div>
<div class="space-y-3">
  {% for card in category_cards %}
  <div class="card bg-base-100 border border-base-200 shadow-sm" x-data="{open:false}">
    <div class="card-body p-4">
      <div class="flex items-center justify-between">
        <h3 class="font-semibold">{{ card.name }}</h3>
        <span class="font-bold whitespace-nowrap">{{ card.total|money }}</span>
      </div>
      {% if card.has_ceiling %}
      <progress class="progress progress-{{ card.status }} w-full" value="{% if card.pct > 100 %}100{% else %}{{ card.pct }}{% endif %}" max="100"></progress>
      <span class="text-xs opacity-70">{{ card.pct }}% de {{ card.budget_ceiling|money }}</span>
      {% else %}
      <span class="text-xs opacity-50">sem teto</span>
      {% endif %}
      <button class="btn btn-ghost btn-xs justify-start mt-1 w-fit"
              hx-get="{% url 'finances:category_detail' card.id current_year current_month %}{% if tab == 'systemics' %}?type=systemic{% endif %}"
              hx-target="#detail-{{ card.id }}" hx-swap="innerHTML" hx-trigger="click once"
              @click="open=!open"><span x-text="open ? '▾' : '▸'"></span> ver lançamentos</button>
      <div id="detail-{{ card.id }}" x-show="open" class="mt-2"></div>
    </div>
  </div>
  {% empty %}
  <div class="text-center py-8 text-base-content/60"><span class="text-3xl">📊</span><p class="font-semibold mt-2">Nenhum gasto neste mês</p></div>
  {% endfor %}
</div>
```
- [ ] **Step 3:** `_category_entries.html`:
```html
{% load finance_filters %}
<table class="table table-xs">
  <tbody>
  {% for entry in entries %}
    <tr><td>{{ entry.date|date:"d/m" }}</td><td>{{ entry.description }}</td>
        <td class="text-right whitespace-nowrap">{{ entry.amount|money }}</td>
        <td>{{ entry.payment_method.name }}</td></tr>
  {% empty %}
    <tr><td colspan="4" class="text-center opacity-60">Sem entradas.</td></tr>
  {% endfor %}
  </tbody>
</table>
```
- [ ] **Step 4:** Delete `_category_detail.html`. Run `uv run pytest finances/tests/test_views_consolidated.py finances/tests/test_consolidated_dropdown.py finances/tests/test_consolidated_detail_filter.py -q` → PASS (update assertions as needed).
- [ ] **Step 5: Commit** `feat(005): consolidado monthly card dashboard`

---

## Task 8: CSS rebuild, full suite, visual verification, final review

- [ ] **Step 1:** `cd src/backend && uv run python manage.py tailwind build --force` (ensures `progress-*`, `pb-28`, `stat`, `cursor-pointer`, etc. are in `static/css/tailwind.css`); commit the rebuilt CSS.
- [ ] **Step 2:** Full suite: `uv run pytest -q` → all green. Fix any regressions.
- [ ] **Step 3:** `ruff check src/backend` → clean (fix line length / imports).
- [ ] **Step 4:** Visual verification via Playwright (login `bessavagner` / `vBessa30%`), desktop 1280×800 + mobile 390×844:
  - Entradas: click a lançamento row → modal opens prefilled; save updates row. Click renda row → modal; save. Click a lançado sistemático row → modal; save. Click a parcelamento row → modal; save.
  - Configurações: scroll to last row → not covered by FAB/chat.
  - Consolidado: month/year selectors switch month; cards show budget bars + Total/Renda/Saldo; "ver lançamentos" expands. Mobile layout clean (no horizontal overflow).
- [ ] **Step 5:** Final independent code review pass; then `superpowers:finishing-a-development-branch`.

---

## Notes / invariants
- All new views are `HtmxLoginRequiredMixin` + user-scoped; cross-user access → 404.
- Every modal POST success returns the re-rendered section/row **and** an `HX-Trigger` JSON containing `entry-saved` (closes `#entry-modal` via the `base.html` listener) plus a `showToast`.
- Delete/secondary buttons inside clickable rows use `onclick="event.stopPropagation()"` so they don't trigger the row's edit modal.
- Don't commit `.env`. Rebuild `tailwind.css` whenever new utility classes are introduced.
