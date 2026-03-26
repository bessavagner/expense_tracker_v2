# Sub-Project 2: HTMX Views — Design Spec

## Overview

Server-rendered pages for all data management screens of the expense tracker. Uses HTMX for dynamic interactions (tab switching, inline editing, modal forms, expandable rows) without full page reloads. DaisyUI provides the component library. Alpine.js handles minor client-side state.

**Builds on:** Sub-Project 1 (Foundation) — all models, services, and admin are in place.

**Does NOT include:** Dashboard (Sub-Project 4, React islands), AI Chat (Sub-Project 5, React island), CSV Import (Sub-Project 3).

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Navigation | Top navbar | Only 4 nav items, maximizes content area, chat widget claims right side |
| Entry creation | Modal (any page) + inline row (entries page) | Modal for quick entry from anywhere, inline for rapid-fire on entries page |
| Settings organization | Single page with tabs | Keeps related config together, HTMX tab switching is instant |
| Consolidated detail | Expandable rows | Drill-down without navigation, lazy-loaded via HTMX |
| View pattern | Django CBVs with HTMX mixin | Full page on direct nav, fragment on HTMX request |
| Form saves | Immediate per-field (settings) / per-row (entries) | No "Save All" button, each change persists immediately |

## Pages

### 1. Base Layout (`base.html`)

All pages extend this template. Contains:
- **Top navbar:** logo ("Expense Tracker"), 4 nav links (Dashboard, Entradas, Consolidado, Configuracoes), "Nova Entrada" button (opens modal), username
- **Content area:** fills remaining space, page-specific content
- **Chat placeholder:** collapsed sidebar on the right (60px wide, icon + label). Expands to full chat widget in Sub-Project 5. All content areas account for this via CSS grid/flexbox.
- **Toast container:** Alpine.js component for transient notifications (success, error)
- **Scripts:** HTMX, Alpine.js, DaisyUI/Tailwind CSS

### 2. Entries Page

**URLs:** `/entries/` (current month), `/entries/<year>/<month>/`

**Components:**
- **Month tabs:** 12 month buttons + year dropdown. Active month highlighted. HTMX: `hx-get="/entries/2026/3/"` swaps table, no full reload.
- **Inline entry form:** always-visible green row at top of table. Fields: date, amount, description, category (select), payment method (select). Submit via `hx-post="/entries/create/"` → adds row, clears form, updates summary.
- **Entries table:** columns: Data, Valor, Descricao, Categoria, Forma, Fatura (billing month).
  - Regular entries: normal display
  - Installment entries: description shows "(2/10)" suffix, non-editable individually
  - Systemic entries: distinct background, linked to SystemicExpense
  - Refunds: green text (negative amounts)
  - Row click → `hx-get="/entries/<id>/edit/"` replaces row with editable inline form
  - Delete: trash icon on hover, `hx-delete` with confirmation
- **Summary bar:** total expenses, total returns, net amount, entry count

### 3. Modal Entry Form

Triggered by "Nova Entrada" button in navbar. Available from any page.

**Fields:** date, amount, description, category, payment method, entry type toggle (Regular / Parcelamento).

**Installment mode:** when "Parcelamento" selected, shows additional fields: num_installments, installment_amount. Creates InstallmentPlan + generates child entries.

**Submit:** `hx-post="/entries/create/"` → closes modal, shows toast. If user is on the entries page for the relevant billing month, the new entry appears in the table.

### 4. Consolidated Views

**URL:** `/consolidated/` (diverse expenses), `/consolidated/systemics/`

**Sub-tabs:** "Gastos Diversos" and "Gastos Sistematicos". HTMX tab switching.

**Table:** category rows, 12 month columns. Values are aggregated totals per category per billing month.

**Color coding:**
- Values exceeding budget ceiling: red
- Values at 90-100% of ceiling: yellow/warning
- Within budget: normal

**Expandable rows:** click category row → `hx-get="/consolidated/detail/<category_id>/<year>/<month>/"` loads individual entries as a detail panel below the row. Click again to collapse.

**Summary row:** column totals per month at the bottom.

**Period selector:** year dropdown, shows 12 months at a time.

### 5. Settings Page

**URL:** `/settings/`

**Three tabs:** Renda | Formas de Pagamento | Categorias. HTMX tab switching.

**Renda tab:**
- Table: name, amount, month, recurring flag, recurrence_start, recurrence_end
- Inline add/edit rows (HTMX pattern)
- No delete — clear amount for future months

**Formas de Pagamento tab:**
- Table: name, type (badge), closing day, active toggle
- Toggle is_active via `hx-patch`
- Inline add, inline edit for closing day
- Cannot delete if entries reference it (PROTECT FK) → toast error

**Categorias tab:**
- Table: name, budget ceiling, is_system badge
- Inline edit budget_ceiling (click to edit, save on blur/enter)
- Add new category via inline row
- System categories: lock icon, no delete/rename
- Cannot delete if entries reference it → toast error

**All tabs:** changes save immediately via HTMX (per-field, no page-level save button).

## Template Structure

```
templates/
├── base.html                    # Navbar, chat placeholder, scripts, DaisyUI theme
├── partials/
│   ├── _navbar.html             # Top navigation bar
│   ├── _modal_entry_form.html   # Modal form for new entry
│   ├── _toast.html              # Toast notification component
│   └── _year_selector.html      # Year dropdown (reusable)
├── entries/
│   ├── entries_page.html        # Full page (extends base)
│   ├── _entries_table.html      # Table fragment (swapped on tab change)
│   ├── _entry_row.html          # Single row
│   ├── _entry_edit_row.html     # Editable row (inline edit)
│   └── _inline_entry_form.html  # Green top row for quick entry
├── consolidated/
│   ├── consolidated_page.html   # Full page (extends base)
│   ├── _consolidated_table.html # Table fragment
│   └── _category_detail.html    # Expandable detail rows
└── settings/
    ├── settings_page.html       # Full page with tabs
    ├── _income_tab.html         # Income tab content
    ├── _payment_methods_tab.html
    └── _categories_tab.html
```

## URL Structure

```
/entries/                            → entries page (current month)
/entries/<year>/<month>/             → entries for specific month (HTMX fragment or full page)
/entries/create/                     → create entry (POST, returns fragment or closes modal)
/entries/<id>/edit/                  → edit entry row (GET: edit form, POST: save)
/entries/<id>/delete/                → delete entry (DELETE)

/consolidated/                       → consolidated diverse expenses
/consolidated/systemics/             → consolidated systemic expenses
/consolidated/detail/<cat_id>/<year>/<month>/ → category detail expansion (HTMX fragment)

/settings/                           → settings page (default: income tab)
/settings/income/                    → income tab content (HTMX fragment)
/settings/payment-methods/           → payment methods tab content (HTMX fragment)
/settings/categories/                → categories tab content (HTMX fragment)
/settings/income/create/             → create income (POST)
/settings/income/<id>/edit/          → edit income (GET/POST)
/settings/payment-methods/<id>/toggle/ → toggle active status (PATCH)
/settings/payment-methods/create/    → create payment method (POST)
/settings/categories/create/         → create category (POST)
/settings/categories/<id>/edit/      → edit category budget (POST)
```

## Django Views Pattern

### HTMX Mixin

```python
class HtmxMixin:
    """Return fragment template for HTMX requests, full page otherwise."""
    template_name = ""       # Full page template
    htmx_template_name = ""  # Fragment template

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return [self.htmx_template_name]
        return [self.template_name]
```

### View Structure

All views:
- Inherit from Django CBVs (ListView, CreateView, UpdateView, DeleteView) + HtmxMixin
- Filter querysets by `request.user` (multi-tenancy ready)
- Return appropriate template based on HTMX detection
- Use `HX-Trigger` response header for toast notifications

### Form Handling

- Django ModelForms for validation
- Validation errors returned as re-rendered form fragment with inline error messages
- Success: return updated fragment + `HX-Trigger: showToast` header

## Dependencies to Add

```
django-htmx>=1.21       # HTMX middleware and helpers
```

Alpine.js and HTMX loaded via CDN in `base.html` (no build step).

## Testing Strategy

### BDD Specs (pytest-bdd)

Feature files for key behaviors:
- Viewing entries for a specific month shows correct entries
- Inline entry creation adds row to table
- Modal entry creation with installment generates plan + entries
- Editing entry recalculates billing month
- Consolidated view shows correct category aggregations
- Consolidated expandable rows show individual entries
- Settings: budget ceiling change persists immediately
- Settings: cannot delete system category or referenced payment method

### Unit Tests

- Each view: correct template, correct context, correct queryset filtering
- HTMX detection: full page vs. fragment response
- Form validation: required fields, decimal parsing, date format
- Permission: views filter by user, can't access other user's data
- Consolidated aggregation: correct sums per category per month

### Test Approach

- Django test client with `HTTP_HX_REQUEST=true` header to simulate HTMX
- `model_bakery` for test data
- pytest-bdd for behavior specs
- No browser/Selenium tests — HTMX is server-side testable via HTTP
