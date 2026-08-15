# The E08 golden dataset

Ground truth for every scored receipt lives in `src/backend/assistant/eval/cases/*.json`
and **is committed**. The receipt **photos are not**.

## Why the images are not in the repository

`bessavagner/expense_tracker_v2` is a public repository, and these are real
household receipts: they carry a CNPJ, a card's last four digits, dates, and a
list of what someone bought. Three fixtures under
`src/backend/assistant/tests/fixtures/` predate this decision and stay where they
are — deleting them would not un-publish them. Nothing new joins them.

## Running the harness with the images

    mkdir -p ~/ledger-eval-fixtures
    # copy the photos named by `images` in the case files into it
    echo 'EVAL_FIXTURES_DIR=/home/bessa/ledger-eval-fixtures' >> .env

Without it, cases marked `"image_source": "private"` are **skipped with a
warning**. A fresh clone and CI stay green; the comparison table names every
case it skipped so a partial run is never mistaken for a full one.

## What is in the set

Seven receipts, 139 hand-transcribed lines.

| Case | Lines | Paid | What it is there for |
|---|---|---|---|
| `americanas-2026-06-12` | 5 | 42.16 | Two categories on one receipt, with a printed discount. |
| `hipermacional-2026-06-15` | 28 | 376.70 | Six categories — where a weaker model starts merging them. |
| `hipernacional-2026-06-19` | 12 | 76.92 | Rotated 90°, a thumb over the footer, six repeated line pairs. |
| `cosmos-2026-06-19` | 9 | 112.94 | Pale print, and a weighed line: 0,542 kg of beef at R$50,99/kg charged as R$27,64. |
| `hipernacional-2026-07-08` | 19 | 157.97 | Paid by Pix. Four bulk lines priced per kilo, five pet-food lines differing only in flavour. |
| `mateus-2026-06-22` | 62 | 745.85 | The long one: two photos of one till roll, badly faded, twelve weighed lines. |
| `mercadolivre-pedido` | 4 | *(none printed)* | Marketplace order screen. The 2-unit line shows R$66,48 — the total for both units. |

### Receipts that print no total

`mercadolivre-pedido` has `"amount_paid": null` and `"date": null`, because the
order screen shows neither. That is a real expectation, not missing ground truth:
`EXTRACTION_PROMPT` tells the model never to invent a total, so **`null` is the
correct answer** and a model that supplies a number fails the money invariant.
When there is no printed total, the invariant instead asks whether the model's
lines add up to what was actually charged — which is exactly the check that
catches the multi-unit double-count.

### Receipts photographed more than once

`mateus-2026-06-22` is one receipt across two overlapping photos, so `images` is
a list. Production's `extract_receipt` already reads several images as one
document, so this exercises the real code path. Resolution is all-or-nothing: if
either photo is missing, the case is skipped rather than half-read — scoring page
one against the full gabarito would report a perfect model as having missed half
the items.

## Adding a case

1. Put the photo in `$EVAL_FIXTURES_DIR`.
2. Copy an existing case file and fill in every field. Transcribe **every** line;
   `line_total` is the amount actually charged for that line, never a unit price
   you multiplied yourself.
3. Run the gate:

       POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_dataset.py -q

   `test_every_committed_case_is_arithmetically_consistent` requires
   `sum(line_total) - discount == amount_paid` exactly. It is the only automatic
   defence against a typo, and a wrong gabarito silently teaches the harness to
   prefer a worse model. It is also how the 62-line Mateus transcription was
   verified: 38 lines from one photo plus 24 from the other landing on the
   printed R$745,85 to the cent is not something a misreading does by accident.
4. Never `git add` the photo.

## What the set deliberately covers

`test_the_set_covers_every_hard_case_it_claims_to` asserts this table rather than
trusting it to stay true.

| Hard case | Why it is in the set |
|---|---|
| `thermal-print` | Faded thermal paper is the common real input. |
| `rotated` / `low-contrast` | Phone photos are not scans. |
| `multi-category` | Where a weaker model merges categories and loses money. |
| `many-categories` | Six categories on one receipt — the merge trap at full size. |
| `discount` | The discount is re-derived and prorated, not read. |
| `multi-unit-line` | The Mercado Livre bug: a 2-unit line priced as a total. |
| `weighed-item` | Produce priced per kilo — `line_total` is not the shelf price. |
| `fractional-unit` | Priced per square metre, three decimals: 14,140 m². |
| `repeated-lines` | Identical descriptions on separate lines must not be merged. |
| `long-receipt` / `multi-page` | 62 lines over two photos. |
| `no-printed-total` / `no-printed-date` | The correct read is `null`, not a guess. |
| `marketplace-order` | An order screen, not a fiscal cupom: no CNPJ, no printed total. |
| `pix` | Instant payment, so `payment_hint` is not a card brand. |

Added by E09, because seven cases could not separate serious candidates:

| Hard case | Why it is in the set |
|---|---|
| `pharmacy-net-value` | The DROGASIL shape: a gross line, then `Valor Liquido` under it. |
| `embedded-line-discount` | The discount is already inside the line total. Copying the receipt's printed discount total on top of it double-counts, and the ledger comes out short. |
| `percent-discount` | The discount is printed as a percentage of a multi-unit line. |
| `service-charge` | A 10% **surcharge**. The lines are LESS than what was paid — reconciliation runs the other way, and every other case in the set runs the usual way. |
| `single-item` | A one-line receipt. The set had no trivial case, so a score of 0.0 could not be told apart from a provider outage. |
| `non-fiscal-document` | `COMPROVANTE DE VENDA`, `PEDIDO DE VENDA`, `ORCAMENTO` — real purchases on documents that are not an NFC-e and carry none of its structure. |
| `a4-print` | A laser-printed A4 order, not a till roll. Different layout, different failure modes. |
| `thousand-separator` | The only receipt over R$1.000: `1.323,83` can be read as 1,32. |
| `cropped-edge` | The photo cuts the last digit off the totals column. Every value is still recoverable from the unit-price column at quantity 1. |

`already-registered` is covered by a **behavioural** case
(`refuses-to-double-register-a-known-receipt`), not by a receipt to read.

## The shortfall is closed: fifteen cases (E09, 2026-08-15)

E08 recorded a shortfall of seven cases against a Definition of Done asking for
ten. E09 needed the set wider for a harder reason than a checkbox: E08 measured a
**run-to-run score spread of 0.14** on seven cases, wider than the gap between
the models E09 exists to choose between. One receipt was 14% of the score. At
fifteen it is 6.7%.

Eight new cases were added from 74 previously untouched photos in
`.data/receipts/extracted/` (gitignored). They were picked for **failure modes
the set did not cover**, not at random — see the second hard-case table above.
The two documents that could not become cases are recorded below rather than
forced.

### How the eight were chosen

Every candidate photo was first read by the extraction model, and the result used
**only to shortlist** — to find the drugstore receipts, the restaurant bill, the
longest receipt, the one-line receipts. Ground truth was then transcribed from
the photographs themselves.

Each case's arithmetic is its own check: `items_total - discount == amount_paid`
holds **exactly** for all eight, and for the forty-line Cosmos receipt the
transcribed lines sum to 359,38, the figure printed on the paper. A misread line
does not balance.

### What still cannot be covered

Two documents in the photo set are real household spending and still cannot
become cases, because `ReceiptCase` requires at least one item and
`arithmetic_error` refuses a case without one:

- **A card-terminal slip** (`IMG_20260506_074224167_HDR.jpg`, O Boticário,
  R$167,65 in 3 instalments). It prints a total and a card, and **no items at
  all**. Production has to do something sensible with these; the harness cannot
  score them.
- **A PIX transfer receipt** (`650142893994608.png`, R$37,00 to a person). Same
  shape, plus a third party's name and partial CPF.

A **handwritten** case is also still missing. The one handwritten form in the set
(`IMG_20170923_113425393_HDR.jpg`, a pousada service slip) has amounts and
quantities but **no descriptions written in at all**, and its handwritten
"VALOR 137.00" does not agree with its own lines. There is no honest gabarito to
type; inventing descriptions would score models against fiction.

To add more, photograph the receipts, drop them in `$EVAL_FIXTURES_DIR` and
follow *Adding a case* above. The loader picks up new files with no code change.

## Provider quirks: models that refuse the request outright

Before a model can score badly it has to answer at all, and two of the three
challengers first pointed at this dataset returned HTTP 400 on **every** case.
Both refusals are about *tool calling*, which every agent here does — an
`output_type=` compiles to a function tool — so neither is avoidable by
rewording a prompt.

| Model family | What the provider says | What makes it work |
|---|---|---|
| `openai:gpt-5.6-*` | "Function tools with reasoning_effort are not supported ... in /v1/chat/completions" | `openai_reasoning_effort: "none"`, or move to `openai-responses:` and keep reasoning on |
| `openrouter:qwen/*` | "The tool_choice parameter does not support being set to required or object in thinking mode" (provider: Alibaba) | `openrouter_reasoning: {"enabled": False}` |

The table lives in code, in `assistant/agents/model_compat.py`, because
production needs it too — `LLM_TIER_ESSENTIAL_FALLBACK` is a qwen model. Each
entry was found by a live 400 and confirmed by a live success, not read off a
changelog. `gpt-5.4` is deliberately not in it.

The unified `thinking: False` does **not** substitute for either: pydantic-ai
documents it as silently ignored on always-on reasoning models, and both
providers still refused with it set.

**When adding a model to a comparison, run one case first.** A whole-suite run
against a model that cannot answer costs time and reports a table of zeroes, and
the failure is in the per-model *failures* list rather than the summary row.

## Scores move between identical runs

The same model, the same seven cases, the same code, minutes apart:

| Run | `openai:gpt-5.4` score | `money_ok_rate` |
|---|---|---|
| control | 0.97 | 1.00 |
| head-to-head | 0.83 | 0.86 |
| repeat 1 | 0.84 | 0.86 |

One case is 14% of a seven-case score, and the money invariant is pass/fail per
case, so a single receipt read differently moves the headline number by more
than the gap between two candidate models. In the first head-to-head
`gpt-5.6-terra` led `gpt-5.4` 0.94 to 0.83; in the next run the order reversed.

**A single run does not rank two models.** Run each candidate at least three
times and compare the spread, not one number — and treat any gap narrower than
the spread as "not measured", not as a tie broken by preference. The dataset
being seven cases rather than the DoD's ten (above) makes this worse, and is the
strongest argument for closing that shortfall.

## Categories and memory

Each case declares its own `categories` and `payment_methods`, and the harness
seeds exactly those. It never seeds a `MemoryRule`. A score that moves when the
operator's personal rules change is not a baseline; memory-driven resolution
stays covered by `test_category_memory.py` and `test_memory_tools.py`.
