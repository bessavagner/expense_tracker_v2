# Baseline on the fifteen-case set — 2026-08-15

The number every E09 candidate is judged against. Supersedes
`baseline-2026-08-14.md` **for decisions**; that file is kept as history.

Suite: `extraction`, **15 receipt cases** (was 7). Suite: `behaviour`, 7
conversations scored on the ledger rows they produced. Three runs each,
`openai:gpt-5.4`, which is what production runs today on every path. Raw output
is in the `baseline-15-*.json` files beside this one.

> **The absolute USD figures below are over-stated — see
> [D03](../../../backlog/D03-cost-report-ignores-cached-input-tokens.md).** They
> were computed before cached input tokens were billed at the cached rate, so
> every dollar figure on this page prices a cache read at up to 10× what the
> provider charged. The real bill for the session behind these runs was $2.54
> against roughly $11 reported.
>
> **The ratios are unaffected and still stand.** Every candidate here was
> measured the same way — three sweeps over the same fifteen images, priced at
> the same list rates — so the factor between two rows survives. If anything the
> 3.75× is conservative: the cheap model consumes more input tokens per sweep
> and therefore has more to gain from caching than the model it is compared
> with. These numbers have deliberately **not** been re-run: a re-measurement
> costs real money and would not change any decision made from this page.

## Why re-measure

E09's regression threshold is "within one measured spread", and the 0.14 spread
came from seven cases. Carrying it to a different dataset would be quoting a
number about something else. Two things also changed underneath it: the dataset
doubled (E09 Task 2), and two defects were fixed — D01, a fixture no model could
pass, and D02, an accent-sensitive name resolver in production.

## The production baseline

| | Extraction | Behaviour |
|---|---|---|
| Cases | 15 | 7 |
| Score (mean of 3) | **0.699** | **1.000** |
| Runs | 0.723 / 0.655 / 0.719 | 1.000 / 1.000 / 1.000 |
| Range | 0.655 – 0.723 | — |
| **Spread** | **0.068** | **0.000** |
| `money_ok_rate` | **0.711** (0.667 – 0.733) | — |
| Cases passed | — | 7 of 7, every run |
| Cost per sweep | **$0.3530** | $0.4272 |
| Input tokens per sweep | 74,881 | ~150,000 |
| Latency per call | 7.8 s | 3.4 s |

The behavioural suite was measured **after** D02 was fixed. Before the fix it
read 0.857 (6/7) on all three runs, and the missing case was the accent defect
below, not the model.

### The spread halved, which was the point

|  | 7 cases (2026-08-14) | 15 cases (2026-08-15) |
|---|---|---|
| Extraction spread | 0.14 | **0.068** |
| One case is worth | 14% of the score | 6.7% |
| Behaviour spread | 0.14 | **0.000** |

The behavioural spread collapsing to zero is not luck. E08's 0.14 came from two
cases flapping, and both had a cause rather than being noise: D01 and D02, both
now fixed. See *The behavioural score was never about the model* below.

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

### The behavioural score was never about the model

The behavioural suite now scores **1.000 — 7 of 7, three runs, zero spread**.
E08 measured 0.810 on the same model and the same cases. Nothing about gpt-5.4
changed. Both missing cases were defects on our side:

| | Cause | Fixed |
|---|---|---|
| `hipermacional-six-categories-no-double-count` | The fixture's items carried no category, so `propose_receipt` refused the very tool the photo turn instructs the agent to call. No model could pass it. | **D01** |
| `billing-month-after-closing-day` | The model called `register_entry` with `payment_method_name: "Crédito C6"` — correct Portuguese — against a row stored `Credito C6`. `_resolve_by_name` was case-insensitive but accent-**sensitive**, so the tool refused a method its own error message then listed. | **D02** |

That is worth stating plainly, because E09 exists to choose a model on these
numbers: **0.810 was a measurement of our harness and our tools, not of the
model.** A cheaper candidate scored against 0.810 could have looked adequate
while genuinely regressing, since a fifth of the deficit was ours and would not
have moved when the model did.

D02 was a real production bug on the main path, not only a harness artefact: a
household that stored `Alimentação` could not type `alimentacao` from a phone
keyboard, and one that stored `Alimentacao` was refused whenever anything wrote
the word properly.

**A perfect behavioural baseline changes what that suite can now tell us.** At
1.000 it can no longer separate good candidates from excellent ones — it can
only detect a candidate that is *worse*. For E09 that is exactly its job: the
question is whether a cheaper text model regresses, and any drop from 1.000 is
now unambiguous rather than lost in noise.

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
> **Behavioural gate.** A candidate text model must stay at **1.000** on the
> behavioural suite. The spread there is 0.000 over three runs, so any drop is a
> real regression and not variance.
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

Same again with `--suite behaviour`. Both sweeps cost about **$0.78** together;
three of each is about **$2.34**. The behavioural figures here were measured
after the D02 fix; the pre-fix run is in this directory's git history.
