---
id: D01
title: The behaviour harness omits the ReceiptDraft, making receipt cases unpassable
release: R2
status: done
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

## Root cause — corrected 2026-08-15, the first diagnosis below was wrong

The case is unpassable as written. No model can pass it. But **not** for the
reason first written up here, and the difference matters because the first
diagnosis would have been "fixed" by pre-seeding a plan the agent is supposed to
compute itself — scoring a pipeline production does not run.

`build_world` (`eval/behaviour_runner.py:67-73`) **already creates** the PENDING
`ReceiptDraft` whenever the case declares `world.receipt_payload`, and
`build_pending_receipt_directive` only needs that row, so it fires correctly.
Both claims in the table below were false.

The real blocker is one field. `HIPERMACIONAL_PAYLOAD`'s items carried **no
`category`**, while the photo turn instructs the agent:

> *"Cada item já carrega sua categoria. Chame propose_receipt() — SEM passar
> items_by_category, pois as categorias já estão nos itens."*

`propose_receipt` derives `items_by_category` from the items and refuses when
they have none: *"Itens sem categoria definida pela leitura."* A live run on
`openai:gpt-5.4` confirms it — the agent obeys the instruction, the tool refuses,
and the agent can only ask the user to categorise 28 items by hand:

```
>> TOOL CALL propose_receipt({"payment_method_name":"Credito C6", ...})
<< TOOL RETURN Itens sem categoria definida pela leitura — me diga a categoria de cada um
```

A production extraction always carries categories: the vision agent is handed
the household catalogue for exactly that purpose. The fixture described a read
production cannot produce, and `commit_receipt` then had no `payload["plan"]`
to register because `propose_receipt` never got to write one.

**Secondary cause, same symptom.** The case gave one turn after the opening
(`"Paguei no Credito C6. Confirma, pode registrar."`), and the agent spends that
turn resolving which card was used — as production does. Even with a working
`propose_receipt`, the run ended on the proposal with nothing committed. The
sibling case `americanas-split-on-request` gets two turns for the same reason.

### The original, incorrect diagnosis

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

- [x] Every item in `HIPERMACIONAL_PAYLOAD` carries the `category` a real
      extraction would assign, summing to the case's `expected_entries`
- [x] The case gets a separate confirmation turn, matching
      `americanas-split-on-request` and matching how the confirmation actually
      reaches production (a second message, through the text path)
- [x] A test asserts the PENDING draft exists before the first turn, that its
      items carry categories, and that `build_pending_receipt_directive` returns
      non-empty for it
- [x] A test walks `propose_receipt` → `commit_receipt` with no provider and
      asserts the six expected rows land, so the case is provably passable for
      free and the guard runs in normal CI
- [x] A test asserts no case declares a payload category its world never creates
- [x] `hipermacional-six-categories-no-double-count` passes against
      `openai:gpt-5.4`: 6 rows, R$376.70, every category exact (live run
      2026-08-15)
- [ ] The behavioural baseline is re-run and corrected — done by E09 Task 3,
      which re-baselines on the wider dataset rather than patching the
      seven-case numbers in `baseline-2026-08-14.md`

**Not done, deliberately:** the draft is *not* pre-seeded with a `plan`.
Production writes the draft with the raw extraction payload and lets the agent
call `propose_receipt` itself; a harness that pre-computed the plan would hand
every model a correct categorisation for free and score a pipeline nobody runs.

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
