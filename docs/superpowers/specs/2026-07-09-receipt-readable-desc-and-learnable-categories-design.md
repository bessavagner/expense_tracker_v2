# Receipt: readable descriptions + learnable categories — design

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Area:** `src/backend/assistant` (agents/tools.py, agents/extraction.py, agents/assistant.py prompts)

## Problem (confirmed against prod, user 27)

Registering from receipt photos has two recurring pains:

1. **Descriptions are too verbose.** The saved `Entry.description` is
   `"LOJA - <raw NF product names joined by '; '>"` — e.g.
   `SUPERMERCADO COSMOS LTDA - ENERG MONSTER 473ML ULTRA PEACHY; ENERGY MONSTER
   473ML ULTRA FIEST; REFRIG LARANJA SJ 350ML PCT LT; BROCOLIS ESP KG; ...`.
   This comes from `_product_summary` (raw names), and the prompt tells the model
   NOT to produce a readable summary ("NO CASO NORMAL não passe summaries").
   The user wants readable groupings like
   `Cosmos - bolachas, energéticos e refrigerantes` /
   `Cosmos - legumes e verduras, leite, flocão`.

2. **Category assignment is imprecise and non-deterministic.** The vision model
   categorizes each item independently. The SAME Cosmos receipt (R$220,05) was
   registered twice with different results: on 08/07 the Monster energéticos +
   refrigerantes went to **Lanche** (correct); on 09/07 the identical items went
   to **Alimentação** (wrong). The user's rule "energético e refrigerante são
   Lanche" is never remembered or applied.

## Existing plumbing (reuse, don't rebuild)

- `MemoryRule(user, trigger, field, value, confidence, source)` already supports
  `field="category"`, with `unique_together (user, trigger, field)`. The
  `save_memory_rule(trigger, field, value)` agent tool already exists and can
  save category rules. **Gap:** the receipt flow never consults category rules
  when categorizing items.
- `_resolve_receipt_plan` already accepts `summaries={category: text}` and uses
  it as the line description when present (tools.py ~481). **Gap:** the prompt
  discourages the model from passing summaries.

## Design

### Part 1 — Readable descriptions (prompt change)

Change the prompts so the assistant **generates a short, human-readable pt-BR
summary per category** and passes it in `summaries`:

- `extraction_to_prompt` (extraction.py, both the `needs_review` and normal
  `head`): replace "NO CASO NORMAL não passe summaries / NUNCA inclua o nome da
  loja no summary" guidance with an instruction to build, for each category, a
  concise natural-language summary that GROUPS product types (e.g. `Lanche →
  "bolachas, energéticos e refrigerantes"`, `Alimentação → "legumes e verduras,
  leite, flocão"`), and pass it via `summaries={categoria: texto}`. Keep: do not
  repeat the store name in the summary (the line description is already
  `"LOJA - <summary>"`); the table's "Itens" column still shows product names for
  conferência.
- `build_pending_receipt_directive` (tools.py): mirror the same summaries
  guidance for the confirmation turn.

No code change to `_resolve_receipt_plan` for Part 1 — the explicit-summaries
path already produces `"LOJA - <summary>"`. This REVERSES the earlier
"keep full product names in the saved description" decision (commit `ce803d6`):
the user now prefers readability over raw NF names. (Table already truncates; the
saved description now carries the readable summary.)

### Part 2 — Learnable, deterministic categories

**Apply (deterministic override):** new helper

```
_apply_category_memory(user, items) -> None   # mutates items in place
```

- Loads the user's category rules once
  (`MemoryRule.objects.filter(user=user, field="category")`).
- For each item, if any rule's `trigger` is a case-insensitive substring of the
  item's `description`, sets `item["category"]` to that rule's `value`
  (overriding the vision model). Longest trigger wins on ties (most specific).
- Called inside `_resolve_receipt_plan` **only in the auto-derive path** (when
  `items_by_category is None`), immediately before
  `_items_by_category_from_items(items)`. When the caller passes an explicit
  `items_by_category` (the user is correcting categories in this turn), the
  explicit assignment wins and rules are NOT re-applied.

**Learn (save rule on correction):** prompt change in
`build_pending_receipt_directive` so that when the user corrects an item's
category, the assistant calls `save_memory_rule(trigger=<NF token>,
field="category", value=<Categoria>)` in addition to re-proposing.

**Critical trigger rule:** NF item names are abbreviated (`ENERG MONSTER`,
`REFRIG LARANJA SJ 350ML`), NOT colloquial words. So a rule with
`trigger="energético"` would never substring-match `ENERG MONSTER`. The prompt
MUST instruct: when saving a category rule from a receipt, choose a `trigger`
that literally appears in the item's NF description (e.g. `"ENERG"`, `"REFRIG"`,
`"MONSTER"`), so it matches future receipts. Matching is case-insensitive.

### Resulting flow

photo → extract → **apply learned category rules** → propose table with
**readable descriptions** → user confirms, or corrects a category → assistant
re-proposes AND **saves a category rule** (NF-matching trigger) → next receipt
lands correctly on its own.

## Out of scope

- Semantic (embedding) category matching — keep the simple substring rule engine.
- The other receipt follow-ups already logged (views duplicate-branch draft, fuzzy
  entry match, discount-in-chat arithmetic).

## Testing (TDD)

`assistant/tests/` (new file or extend `test_tools.py`):

1. `_apply_category_memory`: item `{"description": "ENERG MONSTER 473ML",
   "category": "Alimentação"}` + rule `trigger="ENERG", field="category",
   value="Lanche"` → item category becomes `"Lanche"`. `REFRIG LARANJA` +
   `trigger="REFRIG"→Lanche` → `"Lanche"`. Item with no matching rule → category
   unchanged. Longest-trigger-wins on overlapping triggers.
2. `propose_receipt` auto path (items_by_category=None) applies rules: a pending
   draft whose items are all `Alimentação` but with an `ENERG→Lanche` rule →
   the produced plan has a `Lanche` line. Explicit `items_by_category` path does
   NOT apply rules (user correction wins).
3. `propose_receipt` with `summaries={cat: "texto"}` → line description is
   `"Loja - texto"` (readable path; likely already covered — assert explicitly).
4. Prompt-content guards: `extraction_to_prompt` and
   `build_pending_receipt_directive` now instruct generating readable `summaries`
   and, for the directive, saving a category rule with an NF-matching trigger on
   correction (string assertions, like the existing directive tests).

## Files touched

- Edit: `src/backend/assistant/agents/tools.py` (`_apply_category_memory` +
  call in `_resolve_receipt_plan`; `build_pending_receipt_directive` prompt)
- Edit: `src/backend/assistant/agents/extraction.py` (`extraction_to_prompt`
  summaries guidance)
- New/extend tests under `src/backend/assistant/tests/`
