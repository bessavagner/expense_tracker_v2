# Frontend Adjustments (Prompt 003) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the prompt-003 UI/UX and responsiveness adjustments across Dashboard, Entradas, Consolidado, Configurações, plus a shared global shell (hamburger nav, floating chat, floating "+" FAB).

**Architecture:** Server-rendered Django templates with HTMX + Alpine.js + DaisyUI/Tailwind v4. React stays only in the existing `ChatWidget` island, simplified to floating-only. One new backend view (`entry_edit_modal`) handles editing a lançamento in the shared `#entry-modal`. Everything else is template/CSS.

**Tech Stack:** Django 6, HTMX 2, Alpine.js 3, DaisyUI + TailwindCSS v4 (built via `vite build --watch` into `static/frontend/mount.js` for React; Tailwind CSS prebuilt to `static/css/tailwind.css`), React 18 (ChatWidget), pytest + pytest-django.

---

## Working environment

- **Worktree:** `/home/bessa/Documents/projetos/expense_tracker_v2-003` (branch `003-design-adjustments`).
- **Dedicated dev server for visual checks** (does not touch main/friday): from the worktree run a runserver on port **8701** and a one-off vite build. Set up once before Phase A:

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2-003
uv sync
( cd src/backend/frontend && pnpm install )
# DB: reuse the existing local pgvector container on :5433 (shared); .env is NOT in git — copy it:
cp /home/bessa/Documents/projetos/expense_tracker_v2/.env .
# build the React bundle once (rebuild after any ChatWidget change):
( cd src/backend/frontend && pnpm exec vite build )
# run the dev server for this worktree on 8701:
( cd src/backend && uv run python manage.py runserver 0.0.0.0:8701 )
```

- **Visual verification:** use Playwright MCP against `http://localhost:8701/` (login `bessavagner` / `vBessa30%`), checking both a desktop viewport (1280×800) and a mobile viewport (390×844). After each phase, screenshot the affected screen in both viewports.
- **Tailwind classes:** any NEW utility class string used in templates must already exist in the prebuilt `static/css/tailwind.css`. If a class is missing (blank styling in the browser), rebuild CSS: `cd src/backend && uv run python manage.py tailwind build`. Re-run after adding novel classes.
- **Commit** after each task with the message shown.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `templates/partials/_navbar.html` | Top nav | Single hamburger (all sizes), brand inside menu, drop "+ Nova Entrada" |
| `templates/base.html` | Page shell | Remove `<aside>`/chat-pin wrapper; single `<main>`; floating "+" FAB; modal-close listener |
| `frontend/src/cards/ChatWidget.tsx` | Chat island | Floating-only; 🤖 icon; larger button; remove pinned mode |
| `frontend/src/hooks/useChatPinned.ts` | Pin state | Deleted (no longer used) |
| `templates/dashboard/dashboard_page.html` | Dashboard | Bigger month/year selects |
| `templates/entries/entries_page.html` | Entradas page | Month/year selects; reorder sections |
| `templates/entries/_entries_table.html` | Lançamentos table | Summary on top; search box; mobile cards |
| `templates/entries/_inline_entry_form.html` | Add form | Responsive grid |
| `templates/entries/_entry_row.html` | Entry row | Edit button → modal |
| `templates/cockpit/_parcelamentos_section.html` | Parcelamentos | Search box; mobile cards |
| `templates/consolidated/consolidated_page.html` | Consolidado page | Narrow year select |
| `templates/consolidated/_consolidated_table.html` | Consolidado table | Sticky total row; scroll-to-month script |
| `templates/settings/_systemics_tab.html`, `_payment_methods_tab.html`, `_categories_tab.html` | Settings tabs | Responsive add-form grids |
| `templates/partials/_modal_entry_edit_form.html` | NEW edit modal body | Prefilled edit form |
| `finances/views/entries.py` | Entry views | NEW `EntryEditModalView` |
| `finances/urls.py` | Routes | NEW `entry_edit_modal` route |
| `finances/tests/test_entry_edit_modal.py` | NEW tests | TDD for the modal view |

---

## Phase A — Global shell

### Task A1: Navbar → single hamburger on all sizes, brand inside menu, no "+ Nova Entrada"

**Files:**
- Modify: `src/backend/templates/partials/_navbar.html` (full rewrite)

- [ ] **Step 1: Replace the file contents**

```html
<nav class="navbar bg-neutral text-neutral-content">
    <div class="flex flex-1 items-center gap-2">
        <!-- Hamburger menu (all viewports) -->
        <div class="dropdown">
            <div tabindex="0" role="button" class="btn btn-ghost" aria-label="Menu">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
            </div>
            <ul tabindex="0" class="menu menu-sm dropdown-content bg-neutral rounded-box z-10 mt-3 w-56 p-2 shadow">
                <li class="menu-title text-neutral-content/80">Expense Tracker</li>
                <li><a href="{% url 'finances:dashboard' %}" class="{% if request.resolver_match.url_name == 'dashboard' %}active{% endif %}">Dashboard</a></li>
                <li><a href="{% url 'finances:entries' %}" class="{% if request.resolver_match.url_name and 'entries' in request.resolver_match.url_name %}active{% endif %}">Entradas</a></li>
                <li><a href="{% url 'finances:consolidated' %}" class="{% if request.resolver_match.url_name and 'consolidated' in request.resolver_match.url_name %}active{% endif %}">Consolidado</a></li>
                <li><a href="{% url 'finances:settings' %}" class="{% if request.resolver_match.url_name and 'settings' in request.resolver_match.url_name %}active{% endif %}">Configurações</a></li>
                <li><a href="{% url 'finances:import_upload' %}" class="{% if request.resolver_match.url_name and 'import' in request.resolver_match.url_name %}active{% endif %}">Importar</a></li>
            </ul>
        </div>
    </div>
    <div class="flex-none items-center gap-1">
        <!-- Theme toggle (persisted in localStorage; defaults to OS preference) -->
        <button class="btn btn-ghost btn-sm btn-circle"
                title="Alternar tema" aria-label="Alternar tema (claro/escuro)"
                x-data="{ theme: document.documentElement.getAttribute('data-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'ledger-dark' : 'ledger') }"
                @click="theme = theme === 'ledger-dark' ? 'ledger' : 'ledger-dark'; document.documentElement.setAttribute('data-theme', theme); try { localStorage.setItem('theme', theme); } catch (e) {}">
            <span x-text="theme === 'ledger-dark' ? '☀️' : '🌙'">🌙</span>
        </button>
        <span class="text-sm opacity-70 truncate max-w-32 hidden sm:inline">{{ request.user.username }}</span>
        <form method="post" action="{% url 'logout' %}" class="inline">
            {% csrf_token %}
            <button type="submit" class="btn btn-ghost btn-sm" title="Sair">Sair</button>
        </form>
    </div>
</nav>
```

- [ ] **Step 2: Visual check** — load `http://localhost:8701/` desktop + mobile; confirm one hamburger, "Expense Tracker" as the menu header, links navigate, no "+ Nova Entrada" in the bar.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/partials/_navbar.html
git commit -m "feat(003): single hamburger nav with brand inside menu"
```

### Task A2: base.html — remove aside, single main, floating "+" FAB, modal-close listener

**Files:**
- Modify: `src/backend/templates/base.html:40-65`

- [ ] **Step 1:** Replace the `<div class="flex" ...> ... </div>` block (the chat-pin wrapper around `<main>` and `<aside>`, lines 40–55) with a single main column:

```html
    <main class="flex-1 p-4 w-full max-w-7xl mx-auto">
        {% block content %}{% endblock %}
    </main>

    <!-- Floating chat island (React) -->
    <div data-react-component="ChatWidget" data-api-url="/api/assistant/"></div>

    <!-- Floating "+" FAB: opens the shared entry modal; persists on every page -->
    <button id="fab-new-entry"
            class="fixed bottom-6 right-24 z-50 w-14 h-14 md:w-16 md:h-16 rounded-full bg-accent text-accent-content text-3xl shadow-lg hover:scale-110 transition-transform flex items-center justify-center"
            title="Nova entrada" aria-label="Nova entrada"
            hx-get="{% url 'finances:entry_modal' %}"
            hx-target="#entry-modal-content"
            hx-swap="innerHTML"
            onclick="document.getElementById('entry-modal').showModal()">+</button>
```

- [ ] **Step 2:** In the same file, just before the closing `</body>`, add a listener so any view can close the entry modal by emitting an `entry-saved` HX-Trigger event:

```html
    <script>
      document.body.addEventListener('entry-saved', function () {
        const m = document.getElementById('entry-modal');
        if (m) m.close();
      });
    </script>
```

- [ ] **Step 3: Visual check** — every page shows a floating "+" near the bottom-right; clicking it opens the entry modal. (Chat button verified in A3.)

- [ ] **Step 4: Commit**

```bash
git add src/backend/templates/base.html
git commit -m "feat(003): remove chat aside, single column, floating + FAB"
```

### Task A3: ChatWidget → floating-only, 🤖 icon, larger button

**Files:**
- Modify: `src/backend/frontend/src/cards/ChatWidget.tsx`
- Delete: `src/backend/frontend/src/hooks/useChatPinned.ts`

- [ ] **Step 1:** Remove the pinned feature. In `ChatWidget.tsx`:
  - Delete the import `import { useChatPinned } from "../hooks/useChatPinned";`.
  - Delete the line `const { isPinned, setIsPinned } = useChatPinned();`.
  - Delete the "Restore pinned state on mount" `useEffect` (the block dispatching `chat:pin`).
  - Delete `handleResizeStart`, `handlePin`, and the `resizeRef` ref.
  - In `handleClose`, drop the `if (isPinned) setIsPinned(false);` line (keep `setIsOpen(false); setIsMinimized(false);`).
  - In `chatHeader`, delete the pin button (`📌`) and the minimize button block that is gated on `isPinned`.
  - Delete the entire `// --- Pinned mode ---` `if (isPinned) { ... }` block.

- [ ] **Step 2:** Change the collapsed button (the `if (!isOpen)` return) to a larger robot button:

```tsx
  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 md:w-16 md:h-16 bg-neutral text-neutral-content rounded-full flex items-center justify-center text-2xl shadow-lg hover:scale-110 transition-transform cursor-pointer"
        title="Abrir assistente"
      >
        🤖
      </button>
    );
  }
```

- [ ] **Step 3:** Confirm the floating popup return (end of component) is the only open-state branch and stays:

```tsx
  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] h-[32rem] max-h-[calc(100vh-6rem)] flex flex-col bg-base-100 border border-base-300 rounded-lg shadow-xl">
      {chatHeader}
      {chatMessages}
      {quickReplies}
      {chatInput}
    </div>
  );
```

- [ ] **Step 4:** Delete the now-unused hook file:

```bash
git rm src/backend/frontend/src/hooks/useChatPinned.ts
```

- [ ] **Step 5: Rebuild the bundle and verify it compiles**

Run: `cd src/backend/frontend && pnpm exec vite build`
Expected: build succeeds, no TypeScript errors, `../static/frontend/mount.js` regenerated.

- [ ] **Step 6: Visual check** — collapsed chat shows a large 🤖 at bottom-right; the "+" FAB sits to its left; opening chat shows the floating popup (opaque), no pin/sidebar.

- [ ] **Step 7: Commit**

```bash
git add src/backend/frontend/src/cards/ChatWidget.tsx
git commit -m "feat(003): chat floating-only with robot icon, drop pinned mode"
```

---

## Phase B — Dashboard

### Task B1: Enlarge month/year selects

**Files:**
- Modify: `src/backend/templates/dashboard/dashboard_page.html:10-23`

- [ ] **Step 1:** Change both `<select class="select select-sm select-bordered" ...>` to a larger, wider control. Month select:

```html
        <select class="select select-bordered min-w-[8rem]"
                onchange="window.location.href='/?year={{ current_year }}&month=' + this.value">
```

Year select:

```html
        <select class="select select-bordered min-w-[6rem]"
                onchange="window.location.href='/?year=' + this.value + '&month={{ current_month }}'">
```

- [ ] **Step 2: Visual check** — dashboard selects are clearly wider/taller and legible on desktop.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/dashboard/dashboard_page.html
git commit -m "feat(003): enlarge dashboard month/year selects"
```

---

## Phase C — Entradas

### Task C1: Month/year selects (replace month tabs)

**Files:**
- Modify: `src/backend/templates/entries/entries_page.html:10-24`

- [ ] **Step 1:** Replace the month-tabs block (`<div class="tabs tabs-bordered mb-4"> ... </div>`) with two selects mirroring the dashboard, navigating to `entries_month`:

```html
<div class="flex gap-2 items-center mb-4">
    <select class="select select-bordered min-w-[8rem]"
            onchange="window.location = '/entries/{{ current_year }}/' + this.value + '/'">
        {% for m in months %}
        <option value="{{ m }}" {% if m == current_month %}selected{% endif %}>{{ m|stringformat:"02d" }}/{{ current_year }}</option>
        {% endfor %}
    </select>
    <select class="select select-bordered min-w-[6rem]"
            onchange="window.location = '/entries/' + this.value + '/{{ current_month }}/'">
        {% for y in year_range %}
        <option value="{{ y }}" {% if y == current_year %}selected{% endif %}>{{ y }}</option>
        {% endfor %}
    </select>
</div>
```

- [ ] **Step 2: Visual check** — Entradas month/year look identical to Dashboard; changing either navigates correctly.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/entries/entries_page.html
git commit -m "feat(003): entries month/year selects matching dashboard"
```

### Task C2: Reorder Entradas sections (form + summary on top; lançamentos/parcelamentos next; renda/vencimentos last)

**Files:**
- Modify: `src/backend/templates/entries/entries_page.html` (block content body, after the selects)

- [ ] **Step 1:** Replace the content from after the selects to the end of `{% block content %}` with this order:

```html
<!-- Lançamentos (inline form lives at the top of this partial) -->
<h3 class="text-lg font-semibold mb-2">🧾 Lançamentos</h3>
<div id="entries-container">
    {% include "entries/_entries_table.html" %}
</div>

<!-- Parcelamentos -->
<div hx-get="{% url 'finances:cockpit_parcelamentos' current_year current_month %}"
     hx-trigger="load" hx-swap="outerHTML"></div>

<!-- Sistemáticos -->
<div hx-get="{% url 'finances:cockpit_systemic' current_year current_month %}"
     hx-trigger="load" hx-swap="outerHTML"></div>

<!-- Renda + Vencimentos (final) -->
<div class="grid gap-4 md:grid-cols-2 items-start">
    <div hx-get="{% url 'finances:cockpit_income' current_year current_month %}"
         hx-trigger="load" hx-swap="outerHTML"></div>
    <div hx-get="{% url 'finances:cockpit_vencimentos' current_year current_month %}"
         hx-trigger="load" hx-swap="outerHTML"></div>
</div>
```

- [ ] **Step 2:** In `src/backend/templates/entries/_entries_table.html`, move the Summary block to the TOP (above the inline form). Cut the `<!-- Summary -->` block (currently at the bottom) and paste it as the first element, wrapping it responsively:

```html
{% load finance_filters %}
<!-- Summary (top, responsive) -->
<div class="flex flex-wrap gap-x-6 gap-y-1 mb-3 text-sm opacity-70">
    <span>Total gastos: <strong class="text-error whitespace-nowrap">{{ summary.total_expenses|money }}</strong></span>
    <span>Total retornos: <strong class="text-success whitespace-nowrap">{{ summary.total_returns|money }}</strong></span>
    <span>Líquido: <strong class="whitespace-nowrap">{{ summary.net|money }}</strong></span>
    <span>Entradas: <strong>{{ summary.entry_count }}</strong></span>
</div>

<!-- Inline entry form -->
{% include "entries/_inline_entry_form.html" %}
```

Then delete the old `<!-- Summary -->` block at the bottom of the file (now duplicated).

- [ ] **Step 3: Visual check** — order top→bottom: summary, add-form, lançamentos table, parcelamentos, sistemáticos, renda+vencimentos.

- [ ] **Step 4: Commit**

```bash
git add src/backend/templates/entries/entries_page.html src/backend/templates/entries/_entries_table.html
git commit -m "feat(003): reorder entradas — form/summary top, renda/vencimentos last"
```

### Task C3: Responsive add-form

**Files:**
- Modify: `src/backend/templates/entries/_inline_entry_form.html:6`

- [ ] **Step 1:** Change the form's container class from `flex gap-2 ... items-end` to a responsive grid that stacks on mobile:

```html
      class="grid grid-cols-2 md:grid-cols-6 gap-2 p-2 bg-success/10 rounded-lg mb-2 items-end">
```

- [ ] **Step 2:** Make the submit button span full width on mobile. Change the submit button line to:

```html
    <button type="submit" class="btn btn-sm btn-accent col-span-2 md:col-span-1">Salvar</button>
```

- [ ] **Step 3: Visual check** — on mobile (390px) the add-form fields wrap into a 2-column grid instead of overflowing; desktop shows a single row.

- [ ] **Step 4: Commit**

```bash
git add src/backend/templates/entries/_inline_entry_form.html
git commit -m "feat(003): responsive inline entry form"
```

### Task C4: Search + mobile cards for Lançamentos

**Files:**
- Modify: `src/backend/templates/entries/_entries_table.html`

- [ ] **Step 1:** Wrap the table region in an Alpine search scope and add a search input. Immediately above the `<div class="overflow-x-auto">` add:

```html
<div x-data="{ q: '' }">
<input type="search" x-model="q" placeholder="Buscar lançamentos…"
       class="input input-bordered input-sm w-full max-w-xs mb-2">
```

- [ ] **Step 2:** Change the table wrapper so rows can be filtered. Add `min-w-0` to the scroll wrapper and give the tbody rows a filter hook. Replace `<table class="table table-sm">` open through the tbody open with:

```html
<div class="overflow-x-auto min-w-0">
<table class="table table-sm hidden md:table">
```

(The `hidden md:table` makes the table desktop-only; the mobile card list is added in Step 4.)

- [ ] **Step 3:** Close the `x-data` scope: after the existing closing `</div>` of `overflow-x-auto`, the card list (Step 4) and a final `</div>` for the Alpine scope are added.

- [ ] **Step 4:** In `src/backend/templates/entries/_entry_row.html`, add a search key and Alpine filtering so the row hides when it doesn't match `q`. Change the `<tr ...>` opening tag to include `x-show` and a data attribute (note the parent provides `q`):

```html
<tr id="entry-{{ entry.id }}"
    x-show="q === '' || $el.dataset.search.includes(q.toLowerCase())"
    data-search="{{ entry.description|lower }} {{ entry.category.name|lower }} {{ entry.amount }}"
    class="{% if entry.amount < 0 %}text-success{% endif %} {% if entry.entry_type == 'systemic' %}bg-base-200{% endif %}">
```

- [ ] **Step 5:** Add a mobile card list below the table (inside the Alpine scope, after the `overflow-x-auto` div closes). Insert:

```html
<!-- Mobile cards -->
<div class="md:hidden space-y-2">
    {% for entry in entries %}
    <div x-show="q === '' || $el.dataset.search.includes(q.toLowerCase())"
         data-search="{{ entry.description|lower }} {{ entry.category.name|lower }} {{ entry.amount }}"
         class="card card-compact bg-base-100 border border-base-300">
        <div class="card-body">
            <div class="flex justify-between">
                <span class="font-medium">{{ entry.description }}</span>
                <span class="whitespace-nowrap {% if entry.amount < 0 %}text-success{% endif %}">{{ entry.amount|money }}</span>
            </div>
            <div class="flex flex-wrap gap-2 text-xs opacity-70">
                <span>{{ entry.date|date:"d/m" }}</span>
                <span class="badge badge-xs">{{ entry.category.name }}</span>
                <span>{{ entry.payment_method.name }}</span>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
</div>
```

(That final `</div>` closes the `x-data` scope opened in Step 1.)

- [ ] **Step 6: Visual check** — desktop shows the table with a working search box (typing filters rows live); mobile shows cards (no horizontal overflow) and the same search filters them.

- [ ] **Step 7: Commit**

```bash
git add src/backend/templates/entries/_entries_table.html src/backend/templates/entries/_entry_row.html
git commit -m "feat(003): client-side search and mobile cards for lançamentos"
```

### Task C5: Search + responsiveness for Parcelamentos

**Files:**
- Modify: `src/backend/templates/cockpit/_parcelamentos_section.html` (full rewrite)

The loop variable is `row`; fields are `row.plan.description`, `row.parcela_num`/`row.num_installments`, `row.installment_amount`, `row.remaining`.

- [ ] **Step 1:** Replace the file with an Alpine search scope (`x-data`), a search input, a scroll wrapper with `min-w-0`, and per-row `x-show`/`data-search`:

```html
{% load finance_filters %}
<div id="cockpit-parcelamentos" class="card bg-base-100 border border-base-200 shadow-sm mb-4">
  <div class="card-body p-4" x-data="{ q: '' }">
    <h3 class="font-semibold flex items-center gap-2">📦 Parcelamentos do mês</h3>
    <input type="search" x-model="q" placeholder="Buscar parcelamentos…"
           class="input input-bordered input-sm w-full max-w-xs mb-2">
    <div class="overflow-x-auto min-w-0">
    <table class="table table-sm">
      <tbody>
        {% for row in parcelamento_rows %}
        <tr x-show="q === '' || $el.dataset.search.includes(q.toLowerCase())"
            data-search="{{ row.plan.description|lower }} {{ row.installment_amount }}">
          <td>{{ row.plan.description }}</td>
          <td class="text-center whitespace-nowrap">{{ row.parcela_num }}/{{ row.num_installments }}</td>
          <td class="text-right whitespace-nowrap">{{ row.installment_amount|money }}</td>
          <td class="text-right whitespace-nowrap text-xs opacity-70">restante {{ row.remaining|money }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="4" class="text-center opacity-60">Nenhum parcelamento neste mês.</td></tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Visual check** — Parcelamentos has a working search box; no horizontal overflow on mobile.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/cockpit/_parcelamentos_section.html
git commit -m "feat(003): search and responsive parcelamentos"
```

---

## Phase D — Consolidado

### Task D1: Narrow year select

**Files:**
- Modify: `src/backend/templates/consolidated/consolidated_page.html:8`

- [ ] **Step 1:** Change the year `<select class="select select-sm select-bordered" ...>` to `class="select select-sm select-bordered w-24"`.

- [ ] **Step 2: Visual check** — the year select is visibly narrower.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/consolidated/consolidated_page.html
git commit -m "feat(003): narrow consolidado year select"
```

### Task D2: Sticky, opaque total row

**Files:**
- Modify: `src/backend/templates/consolidated/_consolidated_table.html`

- [ ] **Step 1:** Make the scroll container tall enough to scroll vertically and keep the footer pinned. Change the wrapper `<div class="overflow-x-auto">` to:

```html
<div class="overflow-auto max-h-[70vh]" id="consolidated-scroll">
```

- [ ] **Step 2:** Make the `tfoot` total row sticky and opaque. Change the `<tr class="font-bold">` inside `<tfoot>` to:

```html
        <tr class="font-bold sticky bottom-0 bg-base-200 z-10">
```

- [ ] **Step 3: Visual check** — scrolling the table vertically keeps the "Total" row visible at the bottom, with an opaque background (rows don't show through).

- [ ] **Step 4: Commit**

```bash
git add src/backend/templates/consolidated/_consolidated_table.html
git commit -m "feat(003): sticky opaque total row in consolidado"
```

### Task D3: Smooth scroll to current month column

**Files:**
- Modify: `src/backend/templates/consolidated/_consolidated_table.html`

- [ ] **Step 1:** Tag the current month's header cell so JS can find it. In the `<thead>` month loop, change the `<th class="text-right">` to mark the current month (the view exposes the current month as `current_month` is not in this partial — use `now`): add an id keyed by month using Django's loop. Replace the header `<th>` line with:

```html
            <th class="text-right" {% if m == request.resolver_match.kwargs.month %}{% endif %}data-month="{{ m }}">{{ m|stringformat:"02d" }}/{{ current_year }}</th>
```

(Keeping `data-month` on every header; the script picks the current calendar month.)

- [ ] **Step 2:** Append a script at the end of the partial that smooth-scrolls the container to center the current month column on load:

```html
<script>
  (function () {
    var scroller = document.getElementById('consolidated-scroll');
    if (!scroller) return;
    var month = new Date().getMonth() + 1;
    var th = scroller.querySelector('th[data-month="' + month + '"]');
    if (!th) return;
    var left = th.offsetLeft - (scroller.clientWidth / 2) + (th.offsetWidth / 2);
    setTimeout(function () {
      scroller.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
    }, 150);
  })();
</script>
```

- [ ] **Step 3: Visual check** — opening Consolidado animates a smooth horizontal scroll centering the current month; also works after switching the year tab/select (HTMX swap re-runs the script).

- [ ] **Step 4: Commit**

```bash
git add src/backend/templates/consolidated/_consolidated_table.html
git commit -m "feat(003): smooth scroll consolidado to current month"
```

---

## Phase E — Configurações + edit-in-modal

### Task E1: Responsive add-forms in settings tabs

**Files:**
- Modify: `src/backend/templates/settings/_systemics_tab.html`, `_payment_methods_tab.html`, `_categories_tab.html`

All three add-forms currently use `class="flex gap-2 mb-4 items-end"`, which overflows on mobile. Switch each to a responsive grid (cols = fields + button) and add `min-w-0` to the table wrapper.

- [ ] **Step 1 — systemics** (4 fields: name, category, default_amount, payment_method). In `_systemics_tab.html`, change the form container class to:

```html
      class="grid grid-cols-2 md:grid-cols-5 gap-2 mb-4 items-end">
```

and change the submit button to:

```html
    <button type="submit" class="btn btn-sm btn-accent col-span-2 md:col-span-1">Adicionar</button>
```

and change the table wrapper `<div class="overflow-x-auto">` to `<div class="overflow-x-auto min-w-0">`.

- [ ] **Step 2 — payment methods** (3 fields: name, type, closing_day). In `_payment_methods_tab.html`, change the form container class to:

```html
      class="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4 items-end">
```

submit button to:

```html
    <button type="submit" class="btn btn-sm btn-accent col-span-2 md:col-span-1">Adicionar</button>
```

and the table wrapper to `<div class="overflow-x-auto min-w-0">`.

- [ ] **Step 3 — categories** (2 fields: name, budget_ceiling). In `_categories_tab.html`, change the TOP add-form container class (the one posting to `settings_cat_create`, not the per-row edit forms) to:

```html
      class="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4 items-end">
```

submit button to:

```html
    <button type="submit" class="btn btn-sm btn-accent col-span-2 md:col-span-1">Adicionar</button>
```

and the table wrapper to `<div class="overflow-x-auto min-w-0">`.

- [ ] **Step 4: Visual check** — on mobile, the three settings add-forms wrap into a 2-col grid; tables scroll within the viewport instead of pushing the page wide.

- [ ] **Step 5: Commit**

```bash
git add src/backend/templates/settings/_systemics_tab.html src/backend/templates/settings/_payment_methods_tab.html src/backend/templates/settings/_categories_tab.html
git commit -m "feat(003): responsive settings add-forms and tables"
```

### Task E2: Backend — `EntryEditModalView` (TDD)

**Files:**
- Create: `src/backend/finances/tests/test_entry_edit_modal.py`
- Modify: `src/backend/finances/views/entries.py`
- Modify: `src/backend/finances/urls.py`
- Create: `src/backend/templates/partials/_modal_entry_edit_form.html`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/finances/tests/test_entry_edit_modal.py`:

```python
import pytest
from datetime import date
from django.urls import reverse
from model_bakery import baker

from finances.models import Entry
from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return baker.make(django_user_model)


@pytest.fixture
def entry(user):
    return baker.make(
        Entry,
        user=user,
        entry_type=EntryType.REGULAR,
        amount="10.00",
        description="Old desc",
        date=date(2026, 6, 1),
        billing_month=date(2026, 6, 1),
    )


def test_get_returns_prefilled_form(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Old desc" in resp.content
    assert b"entry-edit-form" in resp.content


def test_post_valid_updates_and_returns_row(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.post(
        url,
        {
            "date": "2026-06-02",
            "amount": "25.50",
            "description": "New desc",
            "category": entry.category_id,
            "payment_method": entry.payment_method_id,
        },
    )
    assert resp.status_code == 200
    entry.refresh_from_db()
    assert entry.description == "New desc"
    assert str(entry.amount) == "25.50"
    assert f'id="entry-{entry.id}"'.encode() in resp.content
    assert resp.headers.get("HX-Trigger") and "entry-saved" in resp.headers["HX-Trigger"]


def test_post_invalid_returns_form_with_errors(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.post(url, {"date": "", "amount": "", "description": ""})
    assert resp.status_code == 200
    assert b"entry-edit-form" in resp.content
    entry.refresh_from_db()
    assert entry.description == "Old desc"


def test_cannot_edit_other_users_entry(client, django_user_model, entry):
    other = baker.make(django_user_model)
    client.force_login(other)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    assert client.get(url).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && uv run pytest finances/tests/test_entry_edit_modal.py -v`
Expected: FAIL — `NoReverseMatch` for `entry_edit_modal` (view/route not defined yet).

- [ ] **Step 3: Create the modal edit form template**

Create `src/backend/templates/partials/_modal_entry_edit_form.html`:

```html
<h3 class="font-bold text-lg mb-4">Editar Entrada</h3>
<form id="entry-edit-form"
      hx-post="{% url 'finances:entry_edit_modal' object.id %}"
      hx-target="#entry-{{ object.id }}"
      hx-swap="outerHTML"
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

- [ ] **Step 4: Add the view**

In `src/backend/finances/views/entries.py`, append:

```python
class EntryEditModalView(HtmxLoginRequiredMixin, View):
    """Edit a regular entry inside the shared #entry-modal."""

    def _get_entry(self, request, pk):
        entry = Entry.objects.filter(user=request.user, pk=pk).first()
        if not entry:
            raise Http404
        return entry

    def get(self, request, pk):
        entry = self._get_entry(request, pk)
        form = EntryForm(instance=entry, user=request.user)
        html = render_to_string(
            "partials/_modal_entry_edit_form.html",
            {"form": form, "object": entry},
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, pk):
        entry = self._get_entry(request, pk)
        form = EntryForm(request.POST, instance=entry, user=request.user)
        if form.is_valid():
            entry = form.save()
            html = render_to_string(
                "entries/_entry_row.html", {"entry": entry}, request=request
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = (
                '{"showToast": {"message": "Entrada atualizada!", "type": "success"},'
                ' "entry-saved": true}'
            )
            return response
        html = render_to_string(
            "partials/_modal_entry_edit_form.html",
            {"form": form, "object": entry},
            request=request,
        )
        return HttpResponse(html)
```

- [ ] **Step 5: Wire the route**

In `src/backend/finances/urls.py`, add `EntryEditModalView` to the `finances.views.entries` import block, and add this path in the Entries section:

```python
    path(
        "entries/<uuid:pk>/edit-modal/",
        EntryEditModalView.as_view(),
        name="entry_edit_modal",
    ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src/backend && uv run pytest finances/tests/test_entry_edit_modal.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances/tests/test_entry_edit_modal.py src/backend/finances/views/entries.py src/backend/finances/urls.py src/backend/templates/partials/_modal_entry_edit_form.html
git commit -m "feat(003): entry_edit_modal view with TDD"
```

### Task E3: Entry row edit button → open modal

**Files:**
- Modify: `src/backend/templates/entries/_entry_row.html:13-18`

- [ ] **Step 1:** Change the edit (✏️) button to load the edit modal and open the dialog, instead of swapping the row inline:

```html
        <button class="btn btn-ghost btn-xs"
                hx-get="{% url 'finances:entry_edit_modal' entry.id %}"
                hx-target="#entry-modal-content"
                hx-swap="innerHTML"
                onclick="document.getElementById('entry-modal').showModal()">✏️</button>
```

- [ ] **Step 2: Manual check** — on Entradas, click ✏️ on a row: the modal opens prefilled; saving updates the row in place and closes the modal (the `entry-saved` listener from Task A2); the delete (🗑️) still works.

- [ ] **Step 3: Commit**

```bash
git add src/backend/templates/entries/_entry_row.html
git commit -m "feat(003): edit lançamento opens modal instead of inline row"
```

### Task E4: Remove the now-unused inline edit row template

**Files:**
- Delete: `src/backend/templates/entries/_entry_edit_row.html`

- [ ] **Step 1:** Confirm nothing else references it.

Run: `grep -rn "_entry_edit_row" src/backend --include=*.py --include=*.html`
Expected: no references (the old `EntryUpdateView` still renders it — see Step 2).

- [ ] **Step 2:** The legacy `EntryUpdateView` (route `entry_edit`) is no longer reached from the UI. Leave the view and route in place (harmless, still tested elsewhere) but DELETE the unused template only if Step 1 shows zero references. If `EntryUpdateView` still references it, skip deletion and instead leave a note — do NOT break that view.

Run: `git rm src/backend/templates/entries/_entry_edit_row.html` (only if Step 1 was clean)

- [ ] **Step 3: Commit** (only if a deletion happened)

```bash
git commit -m "chore(003): remove unused inline edit row template"
```

---

## Final verification (after all phases)

- [ ] **Run the full backend test suite**

Run: `cd src/backend && uv run pytest -q`
Expected: all pass (existing 300+ tests plus the 4 new ones).

- [ ] **Lint**

Run: `cd src/backend && uv run ruff check .`
Expected: clean (fix any issues in touched files).

- [ ] **Rebuild the React bundle** (final)

Run: `cd src/backend/frontend && pnpm exec vite build`
Expected: success.

- [ ] **Full visual pass (Playwright, desktop + mobile)** across all four screens, checking every prompt-003 bullet: hamburger nav + brand-in-menu, floating 🤖 chat + "+" FAB on every page, enlarged dashboard selects, entradas selects/reorder/search/mobile-cards, consolidado narrow select + sticky total + scroll-to-month, settings responsive forms + edit-in-modal.

- [ ] **Merge** following the finishing-a-development-branch skill (PR or merge to main). After merge, friday picks up the changes via the existing sync service.

---

## Notes for the implementer

- This codebase uses `entry.id` as a UUID; routes use `<uuid:pk>`.
- `EntryForm(user=..., instance=...)` — the form requires the `user` kwarg; it's used for create, inline edit, and the new modal edit.
- HTMX swaps re-run inline `<script>` tags in swapped content (used in D3); Alpine re-initializes `x-data` on swapped content (used in C4/C5).
- Do not edit files in the main checkout (`/home/bessa/.../expense_tracker_v2`) — work only in the worktree. The main checkout serves the stable app on :8700 and mirrors to friday.
