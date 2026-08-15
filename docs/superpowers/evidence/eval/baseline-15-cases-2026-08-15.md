# Baseline on the fifteen-case set — 2026-08-15

The number every E09 candidate is judged against. Supersedes
`baseline-2026-08-14.md` **for decisions**; that file is kept as history.

Suite: `extraction`, **15 receipt cases** (was 7). Suite: `behaviour`, 7
conversations scored on the ledger rows they produced. Three runs each,
`openai:gpt-5.4`, which is what production runs today on every path. Raw output
is in the `baseline-15-*.json` files beside this one.

## Why re-measure

E09's regression threshold is "within one measured spread", and the 0.14 spread
came from seven cases. Carrying it to a different dataset would be quoting a
number about something else. Two things also changed underneath it: the dataset
doubled (E09 Task 2), and D01 was fixed, so a behavioural case that no model
could pass is now passable.

## The production baseline

| | Extraction | Behaviour |
|---|---|---|
| Cases | 15 | 7 |
| Score (mean of 3) | **0.699** | **0.857** |
| Runs | 0.723 / 0.655 / 0.719 | 0.857 / 0.857 / 0.857 |
| Range | 0.655 – 0.723 | — |
| **Spread** | **0.068** | **0.000** |
| `money_ok_rate` | **0.711** (0.667 – 0.733) | — |
| Cost per sweep | **$0.3530** | $0.4623 |
| Input tokens per sweep | 74,881 | 173,960 |
| Latency per call | 7.8 s | 3.9 s |

### The spread halved, which was the point

|  | 7 cases (2026-08-14) | 15 cases (2026-08-15) |
|---|---|---|
| Extraction spread | 0.14 | **0.068** |
| One case is worth | 14% of the score | 6.7% |
| Behaviour spread | 0.14 | **0.000** |

The behavioural spread collapsing to zero is not luck. E08's 0.14 came from two
cases flapping, and both now have a known cause: `hipermacional-six-categories`
was unpassable (D01, fixed) and `billing-month-after-closing-day` fails for a
tool defect (D02, below) rather than at random.

### The score fell, and that is the dataset working

Extraction dropped from 0.886 to 0.699 and `money_ok_rate` from 0.914 to 0.711.
No model changed. The eight new cases were chosen for failure modes the old set
did not contain, and gpt-5.4 fails four of them **identically**, on all three
runs:

| Case | What it prints |
|---|---|
| `drogasil-2026-07-04` | gross line, then `Valor Liquido` under it, plus a printed discount total |
| `ultrafarma-2026-08-12` | one line, 4 units, `Vl. Desc. (%) 20,00 (33,3%)`, Total column already net |
| `nobre-lar-2026-05-18` | a `Desconto` column already subtracted from each line total |
| `casa-do-feijao-verde-2026-07-03` | a 10% service **charge**: the lines are LESS than what was paid |

The first three are one defect, not three: **the model reports the already-net
line total AND the receipt's printed discount**, so `items − discount` lands
below what was actually paid. On the Ultrafarma receipt that is `40 − 20 = 20`
for a purchase of R$40 — a ledger entry half the size of the expense, with
nothing about it that looks wrong. The old seven-case set contained no receipt of
this shape, so this defect was invisible and `money_ok_rate` read 0.914.

This is not a reason to soften the gate. It is the reason the gate exists.

### One behavioural case fails for a tool defect, not a model defect

`billing-month-after-closing-day` fails 3/3 with `ledger total 0`. The model
reads it correctly and calls `register_entry` with `payment_method_name:
"Crédito C6"` — correct Portuguese — against a row stored as `Credito C6`.
`_resolve_by_name` is case-insensitive but accent-**sensitive**, so it refuses,
and the case has one turn in which to recover. Written up as **D02**.

Unlike D01 the case IS passable: a model that echoes the user's unaccented
spelling gets through, and gpt-5.4 did in one of E08's three runs. So **0.857 is
a floor, 1.000 the ceiling** on this suite until D02 lands. Any candidate scored
against this baseline is charged for the same defect, so comparisons between
models stay fair; only the absolute number is depressed.

## The gates E09 is measured against

Fixed here, before any candidate was run, so the decision is read off the table
rather than argued backwards from it.

> **Cost gate.** A candidate mix must cost **≤ $0.1177** per extraction sweep —
> the baseline's $0.3530 ÷ 3. Global Constraints require a 3× reduction, and a
> mix that does not clear it does not ship however good it looks.
>
> **Quality gate.** The **pipeline's** score must be **≥ 0.631**
> (0.699 − 0.068, the mean less one measured spread), and its `money_ok_rate`
> must be **≥ 0.711** — no drop at all. A cheaper model that misprorates a
> discount is not cheaper.
>
> **Escalation gate.** The escalation rate must be materially below 100%. At
> 100% the cheap model is not cheap: every receipt is paid for twice.

Note what the money gate now implies. The baseline itself fails the money
invariant on 4 of 15 receipts, so a candidate does not have to be flawless — it
has to be *no worse*. A cheap model that happens to read net lines without
copying the printed discount would score **better** here than gpt-5.4, and that
would be a real result, not a fluke of the dataset.

## Reproducing

```bash
for i in 1 2 3; do
  RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
  uv run python src/backend/manage.py eval_models \
    --models "openai:gpt-5.4" --suite extraction \
    --out docs/superpowers/evidence/eval/baseline-15-extraction-$i.md
done
```

Same again with `--suite behaviour`. Both sweeps cost about **$0.82** together;
three of each is about **$2.45**.
