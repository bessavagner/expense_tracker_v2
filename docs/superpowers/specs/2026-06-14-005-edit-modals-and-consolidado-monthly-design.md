# 005 — Edit Modals + Monthly Consolidado — Design

**Date:** 2026-06-14
**Status:** Approved direction (pending spec review)

## Goal

Three frontend/UX improvements to the personal-finance app:

1. **Universal edit-in-modal:** clicking any per-month entry row (Lançamento, Renda, Sistemático, Parcelamento) opens a modal to edit it.
2. **Settings bottom spacing:** the floating "+" FAB and chat button no longer cover the last table row on any page.
3. **Consolidado redesign:** replace the cluttered annual 12-month × categories grid with a focused **monthly** view — month/year selectors (like Dashboard/Entradas) plus a card dashboard (budget bars + Total/Renda/Saldo header + expandable lançamentos).

## Tech context

Django 6 + HTMX + Alpine.js + DaisyUI v5 / Tailwind v4 (prebuilt `static/css/tailwind.css` via `manage.py tailwind build`). Templates under `src/backend/templates/`. Tests: pytest. Shared modal lives in `base.html` (`<dialog id="entry-modal">` + `#entry-modal-content`); a `entry-saved` HX-Trigger closes it (existing `document.body` listener).

---

## Feature 1 — Universal edit-in-modal

### Current state
- **Lançamentos (regular `Entry`)** already edit via the shared modal: a small ✏️ button does `hx-get` → `entry_edit_modal` into `#entry-modal-content`, opens the dialog; POST saves and swaps the row (`#entry-{id}`) + fires `entry-saved`. (`EntryEditModalView`, `partials/_modal_entry_edit_form.html`.)
- **Renda (`Income`)** has **no** edit on the month cockpit (`_income_section.html` shows only "Excluir"). `Income` is a separate model (name, amount, month, recurrence).
- **Sistemáticos** edit only the amount via an inline number field; the underlying object is a per-month `Entry` (type `systemic`).
- **Parcelamentos** rows are read-only; each row maps to that month's installment `Entry` (type `installment`).

### Design

Introduce **one parameterized modal-form partial** and reuse it across all four section types. Each section's edit view renders the modal form (GET) and, on POST success, **re-renders its own section** (matching the existing cockpit convention of `outerHTML`-swapping the whole section) and fires `entry-saved` to close the modal.

**Shared partial** `partials/_modal_edit_form.html` (context: `form`, `post_url`, `swap_target`, `swap_mode` default `outerHTML`, `title`):
```html
<h3 class="font-bold text-lg mb-4">{{ title|default:"Editar" }}</h3>
<form hx-post="{{ post_url }}" hx-target="{{ swap_target }}" hx-swap="{{ swap_mode|default:'outerHTML' }}" class="space-y-3">
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

**Per type:**

| Type | Object edited | Form | New route (name) | POST success → swap target | Re-render |
|------|---------------|------|------------------|----------------------------|-----------|
| Lançamento | `Entry` (regular) | `EntryForm` | *existing* `entry_edit_modal` | `#entry-{id}` outerHTML | `entries/_entry_row.html` |
| Renda | `Income` | `IncomeForm` | `cockpit_income_edit_modal` (`<y>/<m>/income/<pk>/edit-modal/`) | `#cockpit-income` outerHTML | `cockpit/_income_section.html` |
| Sistemático | this-month `Entry` (systemic) | `EntryForm` | `cockpit_systemic_edit_modal` (`<y>/<m>/systemic/<pk>/edit-modal/`, `pk`=SystemicExpense) | `#cockpit-systemic` outerHTML | `cockpit/_systemic_section.html` |
| Parcelamento | this-month `Entry` (installment) | `EntryForm` | `cockpit_parcelamento_edit_modal` (`<y>/<m>/parcelamento/<uuid:entry_pk>/edit-modal/`) | `#cockpit-parcelamentos` outerHTML | `cockpit/_parcelamentos_section.html` |

Notes:
- **Scope of editing per-month entry (systemic/installment):** the modal edits the **month's `Entry`** (date, amount, description, category, payment_method) — *not* the parent definition/plan. Editing a whole installment plan's total/number-of-parcels (which would regenerate entries) stays out of scope; users still delete+recreate for that. This keeps all four flows consistent and safe.
- **Systemático** row is clickable to edit **only when lançado** (an Entry exists this month). When not lançado, the existing "lançar" button is the action.
- **Parcelamento** route takes the `Entry` pk directly (the row already resolves `this_entry`); expose `row.entry` in `installment_rows_for_month` so the template has the pk.
- **Lançamento** is refactored to use the shared partial too (behavior preserved; existing `test_entry_edit_modal.py` must stay green).
- `EntryForm` querysets are user-scoped; reuse the existing `_patch_form_querysets` helper so the entry's current category/PM remain valid choices.
- **Row click UX:** the whole row becomes the click target (cursor-pointer + `hx-get` on `<tr>`), replacing the tiny ✏️ button as the primary affordance. Delete stays a distinct button; clicks on the delete button must not also trigger the row edit (use `hx-trigger="click"` on row and let the button's own handlers fire; place delete button with `@click.stop` / `onclick="event.stopPropagation()"` so it doesn't bubble to the row).

### Settings → Renda tab
Out of scope for row-edit (the tab shows **grouped** income sources, not individual `Income` rows; per-month editing happens in the cockpit). The tab keeps its current group-delete. (Existing `IncomeUpdateView`/`settings_income_edit` route remains available but unchanged.)

---

## Feature 2 — Settings (and global) bottom spacing

### Problem
The fixed FAB (`#fab-new-entry`, `bottom-6`, ~3.5–4rem tall) and chat button (`bottom-6`) overlay the last row of long tables — visible in Configurações. Affects every page.

### Design
Add bottom padding to the shared `<main>` in `base.html` so all page content scrolls clear of the floating controls:
```html
<main class="flex-1 p-4 pb-28 w-full max-w-7xl mx-auto">
```
`pb-28` (7rem) clears both the FAB and chat bubble with margin. Single global change; no per-tab edits.

---

## Feature 3 — Consolidado: monthly card dashboard

### Current state
`ConsolidatedView` builds a year-at-a-glance: categories as rows, 12 months as columns; cells expand to entries (`CategoryDetailView` → `_category_detail.html`, a `<td colspan=13>`). Year selector + Diversos/Sistemáticos sub-tabs. Complaint: too cluttered.

### Design — replace with a single-month dashboard

**Selectors + header** (mirrors Dashboard/Entradas with `month_abbr`):
- Month `<select>` (1–12, shows `{{ m|month_abbr }}`) and Year `<select>` (`year_range`), each triggering an HTMX reload of `#consolidated-container` to `?year=Y&month=M` on the active sub-tab.
- Keep **Diversos / Sistemáticos** sub-tabs (same filter semantics: diverse excludes systemic; systemics tab includes only systemic).
- **Summary header**: three figures — **Total gasto** (sum of the month's filtered entries), **Renda** (sum of `Income` for the month), **Saldo** = Renda − Total gasto (green if ≥ 0, red if < 0). On the Sistemáticos tab, Renda/Saldo may still show (renda is global to the month) — show all three on both tabs for consistency.

**Category cards** (one per category with spend in the month):
- Header: category name + month total (`money`).
- If the category has a `budget_ceiling > 0`: a DaisyUI `progress` bar with width = `min(100, total/ceiling*100)%`, colored by status — `progress-success` (<90%), `progress-warning` (≥90% & <100%), `progress-error` (≥100%); caption `"{pct}% de {ceiling|money}"`.
- If no ceiling: no bar, caption "sem teto".
- A **"▸ ver lançamentos"** toggle: `hx-get` → `category_detail` (existing route) into a hidden `<div id="detail-{cat}-{month}">`, Alpine toggles visibility (same lazy `click once` + toggle pattern as today, adapted from table-row to div).
- Cards sorted by month total descending (most significant first); empty state when no spend.

**Backend (`ConsolidatedView`)**:
- Read `month` from GET (default `date.today().month`) in addition to `year`.
- Aggregate the selected `billing_month=(year,month,1)` filtered entries by category → `total`, `budget_ceiling`, `pct`, `status`.
- Compute `month_total` (sum), `income_total` (sum of `Income` for that month), `saldo`.
- Context adds: `current_month`, `months`, `month_abbr`-ready, `category_cards` (sorted desc by total), `month_total`, `income_total`, `saldo`. Keep `tab`, `current_year`, `year_range`.
- `ConsolidatedSystemicsView` unchanged subclass (filter only).

**Detail partial**: replace the table-row `_category_detail.html` with a card-friendly `consolidated/_category_entries.html` (a compact list/`table table-xs` of date · description · amount · payment method). `CategoryDetailView` switches to this template (its queryset/filtering is unchanged, so `test_consolidated_detail_filter.py` stays green — assertions are on returned entries).

**Removed:** the wide 12-month grid markup in `_consolidated_table.html` (rewritten to the card dashboard) and `_category_detail.html` (replaced). `test_views_consolidated.py` / `test_consolidated_dropdown.py` will be updated to the new month-based context (selectors present, cards present, summary present).

### Routes
- `consolidated/` and `consolidated/systemics/` unchanged paths; both now accept `?year=&month=`.
- `category_detail` route unchanged.

---

## Testing strategy
- **TDD** for every backend view/route (pytest, user-scoped, HTMX).
- Feature 1: GET returns modal form for each type; POST with valid data saves and returns the re-rendered section + `entry-saved` HX-Trigger; POST invalid re-renders the modal form with errors; cross-user 404s.
- Feature 2: rendered `base.html`/settings page `<main>` contains `pb-28` (regression guard).
- Feature 3: view context has month selector range, `category_cards` with totals/status, summary (`month_total`, `income_total`, `saldo`); systemic vs diverse filtering; detail route returns month entries.
- **Visual verification** via Playwright (desktop 1280×800 + mobile 390×844), logged in, after a `manage.py tailwind build --force` (new utility classes like `progress-*`, `pb-28` must be in the prebuilt CSS).

## Out of scope
- Editing installment-plan structure (total/num parcels) with entry regeneration.
- Per-row edit in the grouped Settings → Renda tab.
- Vencimentos editing (already an inline closing-day field; not an "entry").
