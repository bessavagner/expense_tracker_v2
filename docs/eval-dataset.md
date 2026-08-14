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
| `discount` | The discount is re-derived and prorated, not read. |
| `multi-unit-line` | The Mercado Livre bug: a 2-unit line priced as a total. |
| `weighed-item` | Produce priced per kilo — `line_total` is not the shelf price. |
| `repeated-lines` | Identical descriptions on separate lines must not be merged. |
| `long-receipt` / `multi-page` | 62 lines over two photos. |
| `no-printed-total` / `no-printed-date` | The correct read is `null`, not a guess. |

`already-registered` is covered by a **behavioural** case
(`refuses-to-double-register-a-known-receipt`), not by a receipt to read.

## Known shortfall: seven cases, not ten

The epic's Definition of Done asks for **≥10** receipt cases. The set stands at
**7**, and no more can be added honestly from the photos that exist:

- Of the seven photos originally earmarked as "private",
  `IMG_20260612_174310143_HDR.jpg` and `IMG_20260615_072007792_HDR.jpg` turned
  out to be **byte-identical** (same md5) to the already-committed
  `receipt_americanas.jpg` and `receipt_hipermacional.jpg`. They are the same two
  receipts, not new ones.
- `IMG_20260622_191443851_HDR.jpg` and `IMG_20260622_191450110_HDR.jpg` are two
  photos of **one** receipt, now the single `mateus-2026-06-22` case.

That leaves five distinct new receipts on top of the two already committed. The
gap is recorded here rather than closed with invented data: a case with no photo
behind it can never be run against a vision model, and would make the set look
larger than it is while contributing nothing to a score.

To close it, photograph three more receipts, drop them in `$EVAL_FIXTURES_DIR`
and follow *Adding a case* above. The loader picks up new files with no code
change, and the hard-case table above shows which kinds are already well covered.

## Categories and memory

Each case declares its own `categories` and `payment_methods`, and the harness
seeds exactly those. It never seeds a `MemoryRule`. A score that moves when the
operator's personal rules change is not a baseline; memory-driven resolution
stays covered by `test_category_memory.py` and `test_memory_tools.py`.
