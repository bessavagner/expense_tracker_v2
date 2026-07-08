# Mobile Entry Edit/Delete Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a mobile entry card be tapped to open the shared edit modal, reflect the edit on the card after save, and delete the entry from the card — full parity with the desktop row.

**Architecture:** Each entry renders twice (desktop `<tr id="entry-{id}">`, mobile `<div id="entry-card-{id}">`), both always in the DOM with CSS choosing one. The edit-save and delete responses keep BOTH representations in sync via htmx out-of-band (OOB) swaps, so a mutation from either viewport updates both. No full-region reload (which would reset the Alpine search state and inline form).

**Tech Stack:** Django templates, htmx (hx-get/hx-delete/hx-swap-oob), Alpine.js (`x-show`/`x-model` search filter), DaisyUI/Tailwind, pytest + model_bakery.

## Global Constraints

- **TDD is non-negotiable.** Every task: write the failing test → run it red → minimal implementation → run it green → commit. (superpowers:test-driven-development)
- **Work in an isolated git worktree** created via superpowers:using-git-worktrees before Task 1. (project non-negotiable)
- **Before claiming done:** run the full new test file + `ruff check` green, and drive the actual mobile view once (superpowers:verification-before-completion). Then superpowers:requesting-code-review.
- **Test DB:** the pgvector container on port `5433` must be running (tests/dev DB, not system Postgres).
- Run backend commands from `src/backend/`. Test runner: `pytest`. Linter: `ruff check`.
- Entry pk is a **UUID** (URLs use `<uuid:pk>`); the entries-month queryset is REGULAR-only, so every card in this list is editable.
- Do NOT touch entry *creation* sync (modal-create returns `""`, inline-create appends only a `<tr>`) — explicitly out of scope.

---

### Task 1: Mobile card partial with tap-to-edit + delete button

**Files:**
- Create: `src/backend/templates/entries/_entry_card.html`
- Modify: `src/backend/templates/entries/_entries_table.html:42-59` (mobile loop → include the new partial)
- Test: `src/backend/finances/tests/test_entry_mobile_card.py`

**Interfaces:**
- Produces: template `entries/_entry_card.html` rendering a root element `id="entry-card-{{ entry.id }}"`; when rendered with `oob=True`, the root also carries `hx-swap-oob="true"`. Consumed by Task 2's `_entry_saved.html`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_entry_mobile_card.py`:

```python
from datetime import date

import pytest
from django.template.loader import render_to_string
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


def test_card_opens_edit_modal_and_has_delete(entry):
    html = render_to_string("entries/_entry_card.html", {"entry": entry})
    edit_url = reverse("finances:entry_edit_modal", args=[entry.id])
    delete_url = reverse("finances:entry_delete", args=[entry.id])
    assert f'id="entry-card-{entry.id}"' in html
    assert f'hx-get="{edit_url}"' in html
    assert "showModal()" in html
    assert f'hx-delete="{delete_url}"' in html
    assert "event.stopPropagation()" in html
    # plain render (no oob flag) must NOT carry the oob attribute
    assert "hx-swap-oob" not in html


def test_card_oob_flag_adds_swap_oob(entry):
    html = render_to_string("entries/_entry_card.html", {"entry": entry, "oob": True})
    assert 'hx-swap-oob="true"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py -v`
Expected: FAIL — `TemplateDoesNotExist: entries/_entry_card.html`.

- [ ] **Step 3: Create the partial**

Create `src/backend/templates/entries/_entry_card.html`:

```django
{% load finance_filters %}
{% url 'finances:entry_delete' entry.id as delete_url %}
<div id="entry-card-{{ entry.id }}"{% if oob %} hx-swap-oob="true"{% endif %}
     x-show="q === '' || $el.dataset.search.includes(q.toLowerCase())"
     data-search="{{ entry.description|lower }} {{ entry.category.name|lower }} {{ entry.amount }}"
     class="card card-compact bg-base-100 border border-base-300 cursor-pointer hover:bg-base-200"
     hx-get="{% url 'finances:entry_edit_modal' entry.id %}"
     hx-target="#entry-modal-content"
     hx-swap="innerHTML"
     onclick="document.getElementById('entry-modal').showModal()">
    <div class="card-body">
        <div class="flex justify-between items-start gap-2">
            <span class="font-medium">{{ entry.description }}</span>
            <div class="flex items-center gap-1 whitespace-nowrap">
                <span class="{% if entry.amount < 0 %}text-success{% endif %}">{{ entry.amount|money }}</span>
                {% if delete_url %}
                <button class="btn btn-ghost btn-xs text-error"
                        hx-delete="{{ delete_url }}"
                        hx-swap="none"
                        hx-confirm="Excluir esta entrada?"
                        onclick="event.stopPropagation()">🗑️</button>
                {% endif %}
            </div>
        </div>
        <div class="flex flex-wrap gap-2 text-xs opacity-70">
            <span>{{ entry.date|date:"d/m" }}</span>
            <span class="badge badge-xs">{{ entry.category.name }}</span>
            <span>{{ entry.payment_method.name }}</span>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Wire the mobile loop to the partial**

In `src/backend/templates/entries/_entries_table.html`, replace the mobile cards block (the `<div class="md:hidden space-y-2">` loop, lines ~42-59) with:

```django
<!-- Mobile cards -->
<div class="md:hidden space-y-2">
    {% for entry in entries %}
    {% include "entries/_entry_card.html" %}
    {% endfor %}
</div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add src/backend/templates/entries/_entry_card.html \
        src/backend/templates/entries/_entries_table.html \
        src/backend/finances/tests/test_entry_mobile_card.py
git commit -m "feat(entries): tappable mobile entry card with edit-modal + delete"
```

---

### Task 2: Sync the mobile card on edit-save via OOB

**Files:**
- Create: `src/backend/templates/entries/_entry_saved.html`
- Modify: `src/backend/finances/views/entries.py` (`EntryEditModalView.post`, ~line 261 — render `_entry_saved.html` instead of `_entry_row.html`)
- Test: `src/backend/finances/tests/test_entry_mobile_card.py` (add a case)

**Interfaces:**
- Consumes: `entries/_entry_card.html with oob=True` (Task 1).
- Produces: `EntryEditModalView.post` success response contains BOTH `id="entry-{id}"` (the `<tr>`) and `id="entry-card-{id}"` with `hx-swap-oob`, each showing the updated value.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/finances/tests/test_entry_mobile_card.py`:

```python
def test_edit_save_syncs_both_row_and_card(client, user, entry):
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
    body = resp.content.decode()
    # desktop row (primary swap target)
    assert f'id="entry-{entry.id}"' in body
    # mobile card, delivered out-of-band
    assert f'id="entry-card-{entry.id}"' in body
    assert 'hx-swap-oob="true"' in body
    # updated value present in the card representation
    assert "New desc" in body
    assert resp.headers.get("HX-Trigger") and "entry-saved" in resp.headers["HX-Trigger"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py::test_edit_save_syncs_both_row_and_card -v`
Expected: FAIL — response has no `entry-card-{id}` / no `hx-swap-oob`.

- [ ] **Step 3: Create the response wrapper partial**

Create `src/backend/templates/entries/_entry_saved.html`:

```django
{% include "entries/_entry_row.html" %}
{% include "entries/_entry_card.html" with oob=True %}
```

- [ ] **Step 4: Render the wrapper from the edit view**

In `src/backend/finances/views/entries.py`, in `EntryEditModalView.post`, change the success render (currently `render_to_string("entries/_entry_row.html", {"entry": entry}, request=request)`) to:

```python
            html = render_to_string(
                "entries/_entry_saved.html", {"entry": entry}, request=request
            )
```

(Only that one `render_to_string` call inside the `if form.is_valid():` branch. Leave the invalid-form branch and `HX-Trigger` untouched.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py finances/tests/test_entry_edit_modal.py -v`
Expected: PASS — new case green AND `test_post_valid_updates_and_returns_row` still green (regression guard: `_entry_saved.html` still contains the `<tr id="entry-{id}">`).

- [ ] **Step 6: Commit**

```bash
git add src/backend/templates/entries/_entry_saved.html \
        src/backend/finances/views/entries.py \
        src/backend/finances/tests/test_entry_mobile_card.py
git commit -m "feat(entries): OOB-sync mobile card on edit save"
```

---

### Task 3: Delete removes both representations via OOB

**Files:**
- Modify: `src/backend/finances/views/entries.py` (`EntryDeleteView.delete`, ~lines 200-210)
- Modify: `src/backend/templates/entries/_entry_row.html:26-32` (desktop delete button → `hx-swap="none"`)
- Test: `src/backend/finances/tests/test_entry_mobile_card.py` (add a case)

**Interfaces:**
- Consumes: nothing new.
- Produces: `EntryDeleteView.delete` response body contains OOB-delete stubs for BOTH `entry-{id}` and `entry-card-{id}`; keeps the existing `HX-Trigger` (toast + `entries-changed`).

- [ ] **Step 1: Write the failing test**

Append to `src/backend/finances/tests/test_entry_mobile_card.py`:

```python
def test_delete_removes_both_row_and_card(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_delete", args=[entry.id])
    resp = client.delete(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f'id="entry-{entry.id}"' in body and "hx-swap-oob=\"delete\"" in body
    assert f'id="entry-card-{entry.id}"' in body
    assert not Entry.objects.filter(pk=entry.id).exists()
    assert resp.headers.get("HX-Trigger") and "entries-changed" in resp.headers["HX-Trigger"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py::test_delete_removes_both_row_and_card -v`
Expected: FAIL — current delete returns an empty body (no OOB stubs).

- [ ] **Step 3: Return OOB-delete stubs from the delete view**

In `src/backend/finances/views/entries.py`, replace the body of `EntryDeleteView.delete` after the existence check with:

```python
    def delete(self, request, pk):
        entry = Entry.objects.filter(user=request.user, pk=pk).first()
        if not entry:
            raise Http404
        entry_id = entry.pk
        entry.delete()
        html = (
            f'<tr id="entry-{entry_id}" hx-swap-oob="delete"></tr>'
            f'<div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = (
            '{"showToast": {"message": "Entrada excluída!", "type": "success"},'
            f" {ENTRIES_CHANGED}}}"
        )
        return response
```

- [ ] **Step 4: Point the desktop delete button at the new contract**

In `src/backend/templates/entries/_entry_row.html`, change the delete button (lines ~27-32) from `hx-target="#entry-{{ entry.id }}"` + `hx-swap="outerHTML swap:1s"` to `hx-swap="none"` (remove the `hx-target` line):

```django
        {% if entry.entry_type == 'regular' and delete_url %}
        <button class="btn btn-ghost btn-xs text-error"
                hx-delete="{{ delete_url }}"
                hx-swap="none"
                hx-confirm="Excluir esta entrada?"
                onclick="event.stopPropagation()">🗑️</button>
        {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py finances/tests/test_entry_edit_modal.py -v`
Expected: PASS (all cases, including the existing `_entry_row.html` clickability test).

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances/views/entries.py \
        src/backend/templates/entries/_entry_row.html \
        src/backend/finances/tests/test_entry_mobile_card.py
git commit -m "feat(entries): OOB-delete syncs desktop row and mobile card"
```

---

### Task 4: Verify end-to-end + lint

**Files:** none (verification only).

- [ ] **Step 1: Full targeted test run**

Run: `cd src/backend && pytest finances/tests/test_entry_mobile_card.py finances/tests/test_entry_edit_modal.py finances/tests/test_views_entries.py finances/tests/test_entries_page_sections.py -v`
Expected: all PASS.

- [ ] **Step 2: Lint**

Run: `cd src/backend && ruff check finances/`
Expected: no errors on touched files.

- [ ] **Step 3: Drive the real mobile view** (superpowers:verification-before-completion)

Run the app (see the project `run` skill / systemd `:8700`), open the Entries page in a mobile viewport (DevTools device toolbar), and confirm by observation:
- tapping a card opens the edit modal;
- saving updates the card in place (value changes without full reload);
- the 🗑️ button deletes the card without opening the modal;
- editing/deleting from the desktop table still works.
Note: an htmx OOB response mixing a bare `<tr>` and a `<div>` — confirm the browser applies both swaps (this is the one behavior tests can't fully prove).

- [ ] **Step 4: Request code review** (superpowers:requesting-code-review)

Dispatch a reviewer pass over the diff before finishing the branch.
```

- [ ] **Step 5: Finish the branch** (superpowers:finishing-a-development-branch)

Merge/PR the worktree per the project's flow.
