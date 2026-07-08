# Receipt dedup: evidence-based (verify entries still exist) — design

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation
**Area:** `src/backend/assistant/agents/tools.py`

## Problem (confirmed against prod, user 27)

Re-sending a receipt photo within 48h is treated as "already registered" based
solely on a `ReceiptDraft` row with `status=registered` (matched by store +
amount_paid). But deleting the receipt's entries through the assistant removes
the `Entry` rows and leaves the `ReceiptDraft` as `registered`. So after a
delete, re-sending the same photo is falsely blocked as a duplicate — and,
because the duplicate branch in `views._dispatch_extraction` skips creating a
pending draft, there is then no draft to `propose_receipt`/`commit_receipt`
against, trapping the user ("não há recibo pendente") with no way to register.

Prod evidence: `ReceiptDraft` Drogasil (paid 118.86) and Cosmos (paid 220.05)
are `status=registered` while their entries are gone (`piracanj` → 0 entries).

## Goal

A re-sent receipt is a duplicate **only if its entries actually still exist**.
After the user deletes a receipt's entries, re-sending the photo must flow
normally (create pending draft → propose → confirm → register), so the user can
safely re-register by re-sending. A genuine re-send while the entries are still
present must still be blocked (preserve the anti-double-register protection from
the "PAGUE MENOS" incident).

## Change

`find_registered_duplicate` (tools.py): after it finds a candidate registered
draft (existing store + amount_paid / items match), add an **entries-alive
verification** before returning it. A new helper decides:

```
_plan_entries_alive(user, draft) -> bool
```

- Reads `draft.payload["plan"]` (`lines`, `date`, `payment_method_id`). Each
  committed line has an `amount`; `commit_receipt` created `Entry` rows with
  `date = plan["date"]`, `payment_method_id = plan["payment_method_id"]`,
  `amount = line["amount"]`.
- Returns **True** (entries alive → real duplicate) if **any** plan line still
  has a matching live `Entry` (`user`, `date`, `payment_method_id`, `amount`).
  Matching deliberately excludes `description` because the user edits
  descriptions.
- Returns **False** (entries deleted → not a duplicate) if a usable plan exists
  and **no** line matches a live Entry.
- **Fallback:** if the draft has no usable `plan` (legacy pre-plan drafts, all
  older than the 48h window in practice), returns **True** — preserving the
  current dedup behavior and keeping existing tests valid.

In `find_registered_duplicate`, the loop returns a candidate only when
`_plan_entries_alive(user, candidate)` is True; otherwise it continues scanning.

No change to `views.py` (the duplicate branch), the directive, or the
propose/commit tools — once dedup is evidence-based, a deleted-then-resent
receipt is simply not a duplicate and follows the normal pending-draft flow.

## Out of scope (possible follow-ups, not built here)

- Always creating a pending draft even on a genuine duplicate (escape hatch for
  the true-duplicate case) — would need explicit user confirmation to avoid
  re-introducing double-registration; not needed for the re-send-after-delete
  goal.
- Prompt hardening for the discount/needs_review arithmetic and the
  duplicate-directive "find existing entries" fuzzy match.

## Testing (TDD)

Add to `assistant/tests/test_receipt_date_and_dup.py`:

1. **Deleted entries → not a duplicate:** a `registered` draft WITH a `plan` but
   NO matching `Entry` rows → `find_registered_duplicate` returns `None`
   (the Drogasil/Cosmos re-send case).
2. **Live entries → still a duplicate:** a `registered` draft WITH a `plan` AND
   matching `Entry` rows present → returns the draft (anti-double-register
   preserved).
3. **Legacy draft (no plan) → duplicate (fallback):** existing behavior; the
   current `_registered()` tests (payloads have no `plan`) must stay green.

## Files touched

- Edit: `src/backend/assistant/agents/tools.py` (`_plan_entries_alive` helper +
  guard in `find_registered_duplicate`)
- Edit: `src/backend/assistant/tests/test_receipt_date_and_dup.py` (new cases)
