---
id: D02
title: Name resolution is accent-sensitive, so "Crédito C6" cannot find "Credito C6"
release: R2
status: ready
depends_on: []
blocks: []
wedge_critical: false
---

# D02 · Name resolution is accent-sensitive

## Outcome

A user — or the assistant on their behalf — can name a category or payment
method with its natural Portuguese spelling and have it resolve, whether or not
the row was typed with accents.

## Symptom

`billing-month-after-closing-day` failed **all three** behavioural runs on
2026-08-15 with `ledger total 0`: the agent wrote nothing at all. It failed one
run in three during E08, which was written off as variance.

A live run on `openai:gpt-5.4` (2026-08-15) shows what happens:

```
TURN: "Gastei 120 reais no supermercado hoje, no Credito C6."

>> register_entry(..., payment_method_name: "Crédito C6")
<< Erro: forma de pagamento 'Crédito C6' não encontrada.
   Disponíveis: Credito C6, Dinheiro, Pix

-- "Não consegui registrar ainda porque os nomes exatos cadastrados são sem
    acento. Posso lançar assim?"
```

The user wrote `Credito C6`. The model **added the accent** — which is correct
Portuguese — and the tool rejected its own household's payment method. Given a
second turn the agent recovers by copying the unaccented spelling; the case has
one turn, so the run ends with an empty ledger.

## Root cause

`_resolve_by_name` (`assistant/agents/tools.py:65-81`) matches with `iexact`
then `icontains`. Both are case-insensitive and **accent-sensitive**:
`"Crédito C6"` and `"Credito C6"` are different strings to PostgreSQL.

The function's own docstring gives its example as `"c6" → "Crédito C6"`, spelled
*with* the accent — so the author assumed accented rows throughout. Either
spelling can be stored, and the resolver has to bridge them in both directions.

Every caller inherits it: `create_entry`, `_resolve_receipt_plan` (categories
*and* payment method), and the category tools.

## Why it matters beyond the harness

This is not a harness defect like [D01](D01-behaviour-harness-omits-the-receipt-draft.md).
It is production behaviour on the product's main path: a household that typed
`Alimentação` cannot say "alimentacao" from a phone keyboard without accents,
and a household that typed `Alimentacao` is refused when the assistant writes
the word correctly. The failure is silent to the user — they get an error naming
a list that visibly contains what they asked for.

## Why the behavioural score understates the model

`0.86` (6/7) on 2026-08-15 charges the model for this. The model's read was
right, its arithmetic was right, and it explained the problem accurately; the
tool refused. Note the case IS passable — a model that echoes the user's exact
spelling gets through — so this is not D01's "no model can pass it". Treat 0.86
as a floor and 1.00 as the ceiling until this is fixed.

## What to do

- [ ] `_resolve_by_name` compares accent-folded, case-folded names on both
      sides, for exact and partial matches alike
- [ ] Tests: `Crédito C6` resolves a row stored as `Credito C6`, and
      `alimentacao` resolves a row stored as `Alimentação`
- [ ] The ambiguity path still reports the **stored** names, not the folded ones
- [ ] Re-run the behavioural suite and record whether
      `billing-month-after-closing-day` passes 3/3

Prefer folding in Python over an `unaccent` extension: the comparison set is one
household's categories and payment methods — tens of rows, not thousands — and
the extension needs a migration and a superuser grant on Supabase.

## Out of scope

Fuzzy matching beyond accents. `create_entry_fuzzy` already exists for that and
has its own tests; this is about two spellings of the *same* name.
