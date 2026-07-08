# Mobile entry edit/delete — design

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan
**Area:** `src/backend/finances` (views, templates)

## Problem

On the Entries month page, each entry renders in **two representations** that both live in the DOM, with CSS choosing one by breakpoint:

- **Desktop:** `<tr id="entry-{id}">` from `entries/_entry_row.html`, inside a `hidden md:block` table. The whole row is `cursor-pointer` and, for regular entries, opens the shared edit modal (`hx-get` the `entry_edit_modal` URL → `#entry-modal-content`, `onclick` `showModal()`). It also has a 🗑️ delete button with `event.stopPropagation()`.
- **Mobile:** a plain `<div>` card rendered inline in `entries/_entries_table.html` (`md:hidden`). It has **no id, no tap handler, no edit, no delete.**

So on mobile there is no way to edit or delete an entry. Simply making the card open the modal is not enough: the edit-modal save (`EntryEditModalView.post`) returns `_entry_row.html` and swaps `#entry-{id}` (`outerHTML`) — i.e. it updates the hidden `<tr>`, leaving the mobile card stale. And the card cannot reuse `id="entry-{id}"` because that id already belongs to the `<tr>`.

## Goal

Tapping a mobile entry card opens the shared edit modal; saving reflects the change on the card; a delete affordance on the card removes the entry — full parity with the desktop row, from either viewport.

## Approach: OOB dual-representation

Give the card its own id and have the edit/delete responses keep **both** representations in sync via htmx out-of-band (OOB) swaps. Surgical, idiomatic htmx, and does not reset the Alpine search state (`q`) or the inline create form (both of which live in `_entries_table.html`).

*Alternative considered and rejected:* reload the whole rows region on `entries-changed`. The search box and inline form share the same partial, so a reload would nuke both — more disruptive for no gain.

### Components

1. **`entries/_entry_card.html` (new)** — the mobile card markup extracted from `_entries_table.html`. Root element `id="entry-card-{{ entry.id }}"` that:
   - keeps the existing `x-show`/`data-search` client-side filter behavior;
   - taps the whole body to open the edit modal, mirroring the desktop row: `hx-get "{% url 'finances:entry_edit_modal' entry.id %}"`, `hx-target="#entry-modal-content"`, `hx-swap="innerHTML"`, `onclick="document.getElementById('entry-modal').showModal()"`;
   - has a corner 🗑️ delete button: `hx-delete` the `entry_delete` URL, `hx-swap="none"`, `hx-confirm`, and `onclick="event.stopPropagation()"` so tapping delete does not also open the modal;
   - accepts an `oob` template flag: when truthy, the root carries `hx-swap-oob="true"` (so the same partial serves both plain render and OOB update).

2. **`entries/_entry_saved.html` (new wrapper)** = `{% include "entries/_entry_row.html" %}` + `{% include "entries/_entry_card.html" with oob=True %}`. `EntryEditModalView.post` renders **this** instead of `_entry_row.html`. One save then updates the `<tr>` (primary swap on `#entry-{id}`) **and** the card (OOB on `#entry-card-{id}`), whether triggered from desktop or mobile.
   - Rationale for a separate wrapper: `_entry_row.html` is also included during **initial full-page render** (the desktop table loop), where htmx does **not** process `hx-swap-oob`; embedding the OOB card directly in `_entry_row.html` would leave a stray duplicate card in the tbody on first load. Keeping the OOB fragment in a response-only wrapper avoids that.

3. **`EntryDeleteView.delete`** returns two OOB-delete stubs — `<tr id="entry-{id}" hx-swap-oob="delete"></tr>` and `<div id="entry-card-{id}" hx-swap-oob="delete"></div>` — and keeps the existing `HX-Trigger` (toast + `entries-changed`). Both delete buttons (desktop row and mobile card) use `hx-swap="none"`, so htmx removes both representations via OOB regardless of which viewport fired the delete, with no primary-target/OOB id conflict.
   - The desktop delete button (`_entry_row.html`) changes from `hx-target="#entry-{id}" hx-swap="outerHTML swap:1s"` to `hx-swap="none"` to match the new symmetric delete contract. (The `swap:1s` fade is dropped; acceptable.)

4. **`entries/_entries_table.html`** — the mobile loop becomes `{% include "entries/_entry_card.html" %}` (no `oob` flag → plain render). The desktop loop is unchanged.

### Data flow

- **Tap card (mobile):** `hx-get entry_edit_modal` → `#entry-modal-content`, dialog opens. Same modal as desktop.
- **Save edit (either viewport):** `EntryEditModalView.post` → `_entry_saved.html`. Primary swap replaces `#entry-{id}` (the `<tr>`); OOB swap replaces `#entry-card-{id}` (the card). Both current. `entry-saved` closes the modal (existing base.html listener); `entries-changed` refreshes the summary (existing).
- **Delete (either viewport):** `EntryDeleteView` → OOB-delete both ids. Both representations removed; summary refreshes.

## Out of scope (pre-existing, unchanged)

Creating an entry does not add a mobile card without a page reload: modal-create (`EntryModalView.post`, regular branch) returns `""`, and inline-create (`EntryCreateView`) appends only a `<tr>` to `#entries-tbody`. This staleness predates this work and is not part of "edit/delete existing entries." Flagged, not fixed here.

## Testing (TDD — write tests first)

All behavior is assertable server-side; no browser needed.

1. `EntryEditModalView.post` with a valid edit returns HTML containing **both** `id="entry-{id}"` (updated `<tr>`) and `id="entry-card-{id}"` carrying `hx-swap-oob`, with the new value reflected in each.
2. `EntryEditModalView.post` with an invalid form still re-renders the modal edit form (unchanged behavior — regression guard).
3. `EntryDeleteView.delete` returns a response containing OOB-delete stubs for both `entry-{id}` and `entry-card-{id}`, preserves the `HX-Trigger` (toast + `entries-changed`), and actually deletes the row.
4. `EntryListView` GET render contains a mobile card with the `entry_edit_modal` `hx-get` URL and a delete button targeting `entry_delete`.
5. Existing entry create/edit/delete tests continue to pass (these views currently have no covering tests — see blast-radius note; add the above as the first coverage).

## Files touched

- New: `src/backend/templates/entries/_entry_card.html`
- New: `src/backend/templates/entries/_entry_saved.html`
- Edit: `src/backend/templates/entries/_entries_table.html` (mobile loop → include card partial)
- Edit: `src/backend/templates/entries/_entry_row.html` (desktop delete button → `hx-swap="none"`)
- Edit: `src/backend/finances/views/entries.py` (`EntryEditModalView.post` → render `_entry_saved.html`; `EntryDeleteView.delete` → OOB-delete stubs)
- New tests: `src/backend/finances/tests/` (per Testing section)
