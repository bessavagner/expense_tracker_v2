---
id: D01
title: The behaviour harness omits the ReceiptDraft, making receipt cases unpassable
release: R2
status: ready
depends_on: [E08]
blocks: [E09]
wedge_critical: true
---

# D01 · The behaviour harness omits the `ReceiptDraft`

## Outcome

A behavioural case that opens with a receipt can actually be passed, so the
behavioural baseline measures the assistant rather than a missing fixture.

## Symptom

`hipermacional-six-categories-no-double-count` fails on **every** run, always
identically:

```
hipermacional-six-categories-no-double-count: no row satisfied Alimentacao
(no rows left); no row satisfied Lanche (no rows left); no row satisfied Pets
(no rows left); no row satisfied Casa (no rows left); no row satisfied Limpeza
(no rows left); no row satisfied Perfumaria (no rows left);
ledger total 0 != expected 376.70
```

Three runs on 2026-08-14, `openai:gpt-5.4`, scores 0.857 / 0.714 / 0.857. The
ledger total is **0**: the agent wrote nothing at all, rather than writing the
wrong thing.

## Root cause

The case is unpassable as written. No model can pass it.

`build_opening_prompt` (`assistant/eval/behaviour_runner.py:93-96`) renders the
receipt into prompt text and stops there:

```python
if case.opening == "receipt":
    ext = ReceiptExtraction(**case.world.receipt_payload)
    needs_review = receipt_needs_review(ext, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
    return extraction_to_prompt(ext, "", needs_review=needs_review)
```

Production does more than render text. The image path persists a **PENDING
`ReceiptDraft`**, and two things depend on that row existing:

| Depends on the draft | Behaviour without it |
|---|---|
| `commit_receipt` (`agents/tools.py:593-603`) | Returns `"Não há recibo pendente para registrar."` and writes nothing |
| `build_pending_receipt_directive` (`agents/tools.py:829-846`) | Returns `""`, so the instruction forcing the receipt tools never reaches the agent |

So the harness asks the agent to register a receipt, withholds the directive
telling it to use the receipt tools, and then hands it a `commit_receipt` that
refuses. Writing nothing is the correct behaviour under those conditions.

The docstring on `build_pending_receipt_directive` names this failure mode
exactly, as a **real production bug that was already fixed**: *"sem este aviso o
assistente ainda responde 'registrei' sem gravar nada (bug real do recibo
MATEUS: draft pendente, 0 lançamentos)"*. The harness reproduces the bug by
omitting the fixture that carries the fix.

## Why this blocks E09

E09 chooses production models against behavioural scores. Today that score
carries a constant penalty that belongs to the harness:

| | Score |
|---|---|
| Behavioural baseline as measured | 0.810 (6/7, 5/7, 6/7) |
| Excluding the unpassable case | **0.944** (6/6, 5/6, 6/6) |

A model that handles pending receipts well and one that ignores them entirely
score the same on this case, because neither can pass it. That is the single
case most directly about the wedge (multi-category receipt capture), so E09
would be picking a model with its most relevant signal switched off.

## What to do

- [ ] `build_opening_prompt`'s `receipt` branch creates a PENDING `ReceiptDraft`
      for the household, with the same `payload` shape production writes,
      including the `plan` key that `commit_receipt` reads
- [ ] A test asserts the draft exists and is PENDING before the first turn runs,
      and that `build_pending_receipt_directive` returns non-empty for it
- [ ] A test drives the case with a stub model that calls `commit_receipt` and
      asserts rows land, so the case is provably passable without spending money
- [ ] `hipermacional-six-categories-no-double-count` passes against
      `openai:gpt-5.4`, or fails on the *substance* the case is about (Pets
      double-counted, Lanche merged away) rather than on an empty ledger
- [ ] The behavioural baseline in
      `docs/superpowers/evidence/eval/baseline-2026-08-14.md` is re-run and
      corrected, and the note about this case is replaced with the real number

## Also seen, not explained by this

`billing-month-after-closing-day` failed in **one run of three**, also with
`ledger total 0`. It opens with `text`, not `receipt`, so the missing draft does
not explain it. One in three is inside the noise this dataset shows everywhere
(see `docs/eval-dataset.md` § *Scores move between identical runs*), so it may be
variance rather than a defect. Re-check it once the dataset is wider; if it
persists at a rate the spread cannot account for, it is a real bug about the
credit-card closing day and deserves its own entry.

## Out of scope

- Widening the dataset → that is E09's first task, tracked on `INDEX.md`
- Any change to `commit_receipt` or the directive themselves. Production is
  correct here. The harness is what diverges.
