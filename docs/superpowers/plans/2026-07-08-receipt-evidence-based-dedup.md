# Receipt Evidence-Based Dedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A re-sent receipt counts as "already registered" only if its entries still exist, so a user who deleted a receipt's entries can safely re-register by re-sending the photo.

**Architecture:** Add an entries-alive check to `find_registered_duplicate` in `assistant/agents/tools.py`. A candidate registered `ReceiptDraft` is a real duplicate only if at least one of its saved `plan` lines still has a matching live `Entry`; drafts with no usable plan fall back to the current (dup) behavior.

**Tech Stack:** Django ORM, pytest + model_bakery/plain ORM (existing test file uses `seeded_user` fixture + `ReceiptDraft.objects.create`).

## Global Constraints
- **TDD non-negotiable** (RED→GREEN→commit). **Isolated git worktree**. **Verify** + **code review** before finishing. (project non-negotiables)
- Run backend from `<worktree>/src/backend`; interpreter `/home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest`; DB pgvector on `:5433` (worktree needs `.env` copied from main checkout — no local venv).
- Entry pk is a UUID. `commit_receipt` creates entries with `date=plan["date"]`, `payment_method_id=plan["payment_method_id"]`, `amount=line["amount"]`.
- Preserve anti-double-register: a registered draft whose entries STILL EXIST must remain a duplicate. Legacy drafts with no `plan` must remain duplicates (keep existing tests green).
- `ruff check` clean on touched files.

---

### Task 1: Evidence-based dedup in `find_registered_duplicate`

**Files:**
- Modify: `src/backend/assistant/agents/tools.py` (add `_plan_entries_alive`; guard the return in `find_registered_duplicate`, ~line 665-678)
- Test: `src/backend/assistant/tests/test_receipt_date_and_dup.py`

**Interfaces:**
- Produces: `_plan_entries_alive(user, draft) -> bool` — True if the draft has no usable plan (fallback) OR at least one plan line has a matching live Entry; False if a usable plan exists and no line matches.
- `find_registered_duplicate` returns a candidate only when `_plan_entries_alive` is True.

- [ ] **Step 1: Write failing tests**

Append to `src/backend/assistant/tests/test_receipt_date_and_dup.py` (the module already imports `find_registered_duplicate`, `ReceiptDraft`, `ReceiptDraftStatus`, `Entry`, and has the `seeded_user` fixture and `_registered` helper):

```python
# ── Evidence-based dedup: a registered receipt whose entries were DELETED must
#    NOT count as a duplicate (so the user can safely re-send the photo). ──────

def _plan_payload(**over):
    payload = {
        "store": "Drogasil",
        "date": "2026-07-04",
        "amount_paid": "118.86",
        "items": [
            {"description": "a", "line_total": "20.97", "category": "Alimentação"},
            {"description": "b", "line_total": "97.89", "category": "Saúde"},
        ],
        "plan": {
            "store": "Drogasil",
            "date": "2026-07-04",
            "payment_method_id": None,  # set per-test
            "lines": [
                {"category_name": "Alimentação", "description": "Drogasil - a", "amount": "20.97"},
                {"category_name": "Saúde", "description": "Drogasil - b", "amount": "97.89"},
            ],
            "total": "118.86",
        },
    }
    payload.update(over)
    return payload


def _incoming():
    return {
        "store": "Drogasil",
        "amount_paid": "118.86",
        "items": [
            {"description": "x", "line_total": "20.97"},
            {"description": "y", "line_total": "97.89"},
        ],
    }


def test_deleted_entries_not_a_duplicate(seeded_user):
    """Registered draft WITH a plan but NO live entries → re-send is allowed."""
    from datetime import date
    from finances.models import Category, PaymentMethod

    pm = PaymentMethod.objects.filter(user=seeded_user).first()
    payload = _plan_payload()
    payload["plan"]["payment_method_id"] = str(pm.id)
    ReceiptDraft.objects.create(
        user=seeded_user, payload=payload, status=ReceiptDraftStatus.REGISTERED
    )
    # No Entry rows created (they were "deleted").
    assert find_registered_duplicate(seeded_user, _incoming()) is None


def test_live_entries_still_a_duplicate(seeded_user):
    """Registered draft WITH a plan AND matching live entries → still a dup."""
    from datetime import date
    from finances.models import Category, PaymentMethod

    pm = PaymentMethod.objects.filter(user=seeded_user).first()
    cat = Category.objects.filter(user=seeded_user).first()
    payload = _plan_payload()
    payload["plan"]["payment_method_id"] = str(pm.id)
    ReceiptDraft.objects.create(
        user=seeded_user, payload=payload, status=ReceiptDraftStatus.REGISTERED
    )
    # One matching live entry (date + pm + amount) is enough.
    Entry.objects.create(
        user=seeded_user, date=date(2026, 7, 4), amount="20.97",
        description="Drogasil - a", category=cat, payment_method=pm,
    )
    assert find_registered_duplicate(seeded_user, _incoming()) is not None


def test_legacy_draft_without_plan_still_duplicate(seeded_user):
    """No 'plan' key (pre-plan drafts) → fallback keeps dup behavior."""
    _registered(seeded_user)  # helper payload has NO 'plan'
    incoming = {
        "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
        "amount_paid": "155.90",
        "items": [
            {"description": "x", "line_total": "135.98"},
            {"description": "y", "line_total": "19.92"},
        ],
    }
    assert find_registered_duplicate(seeded_user, incoming) is not None
```

- [ ] **Step 2: Run tests, verify the two new plan-based tests fail**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_receipt_date_and_dup.py -v`
Expected: `test_deleted_entries_not_a_duplicate` FAILS (current code returns the draft ignoring entries). `test_live_entries_still_a_duplicate` and `test_legacy_draft_without_plan_still_duplicate` PASS already. Existing tests PASS.

- [ ] **Step 3: Implement the helper + guard**

In `src/backend/assistant/agents/tools.py`, add this helper immediately ABOVE `find_registered_duplicate` (imports `date`, `Decimal`/`_to_decimal`, `Entry` are already at module top):

```python
def _plan_entries_alive(user, draft) -> bool:
    """True if this registered draft's entries still exist (a real duplicate).

    ``commit_receipt`` creates one Entry per plan line with the plan's date,
    payment method, and the line amount. If the user later deleted those
    entries, re-sending the photo must NOT be treated as a duplicate. Matching
    excludes description (the user edits descriptions). Drafts with no usable
    plan (legacy, pre-plan) fall back to True to preserve the old dedup.
    """
    plan = (draft.payload or {}).get("plan") or {}
    lines = plan.get("lines") or []
    pm_id = plan.get("payment_method_id")
    date_str = plan.get("date")
    if not lines or not pm_id or not date_str:
        return True
    try:
        entry_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return True
    for line in lines:
        amount = _to_decimal(line.get("amount"))
        if amount is None:
            continue
        if Entry.objects.filter(
            user=user,
            date=entry_date,
            payment_method_id=pm_id,
            amount=amount,
        ).exists():
            return True
    return False
```

Then in `find_registered_duplicate`, change each `return draft` inside the candidate loop so the candidate is only returned when its entries are alive. Concretely, replace the two `return draft` statements in the loop body with a guarded return, e.g. introduce at the point a match is decided:

```python
        # ... inside the for-draft loop, where a store+paid or items match is found:
        if paid is not None and cpaid is not None:
            if paid == cpaid and _plan_entries_alive(user, draft):
                return draft
            continue
        citems = p.get("items") or []
        ctotal = _items_total(citems)
        if len(citems) == n and items_total > 0 and ctotal == items_total \
                and _plan_entries_alive(user, draft):
            return draft
```

(Keep the existing `continue` after a paid-equal-but... case so scanning proceeds. Do not change the candidate query or the store filter.)

- [ ] **Step 4: Run tests, verify all green**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_receipt_date_and_dup.py -v`
Expected: all PASS (3 new + all existing).

- [ ] **Step 5: Broader receipt-suite regression**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m ruff check assistant/agents/tools.py assistant/tests/test_receipt_date_and_dup.py
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_date_and_dup.py
git commit -m "fix(receipt): evidence-based dedup — re-send allowed after entries deleted"
```

---

### Task 2: Verify against the real prod scenario + deploy

**Files:** none (verification + deploy).

- [ ] **Step 1: Simulate the exact prod scenario in a test-shell (dev DB :5433)** — a registered Drogasil draft (with plan) + no entries → `find_registered_duplicate` returns None; add matching entry → returns the draft. (Covered by Task 1 tests; no extra code.)

- [ ] **Step 2: Full assistant + finances suite green, ruff clean.**

- [ ] **Step 3: Merge to main, push** (finishing-a-development-branch, option merge+push).

- [ ] **Step 4: Deploy to Cloud Run** (no migration, Python-only):
```bash
gcloud run deploy expense-tracker --source . --project expense-tracker-482807 --region southamerica-east1 --quiet
```
Smoke: `/healthz` 200, root 302, assetlinks fingerprint intact.

- [ ] **Step 5: Confirm to user** they can now re-send the Drogasil + Cosmos photos to register them.
