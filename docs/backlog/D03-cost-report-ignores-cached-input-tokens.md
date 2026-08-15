---
id: D03
title: The cost report bills cached input tokens at full price, so every USD figure is too high
release: R2
status: done
depends_on: [E07]
blocks: []
wedge_critical: false
---

# D03 · The cost report ignores cached input tokens

## Outcome

`UsageRecord.cost_usd` and the eval harness's `USD` column report what the
provider actually charges, so a cost decision is made on the real number.

## Symptom

The E09 matrix reported roughly **$11** of provider spend for a session whose
actual OpenAI bill was **$2.54** — the reported figure is over 4× the truth.

The session consumed 8.67M input tokens. At `gpt-5.4`'s list price of
$2.50/Mtok that alone would be $21.68, against a real bill of $2.54 for
everything.

## Root cause

`cost_usd_for` (`assistant/pricing.py:57-72`) prices every input token at
`ModelPrice.input_per_mtok`:

```python
inp = Decimal(getattr(usage, "input_tokens", 0) or 0)
total = (inp / MILLION) * price.input_per_mtok + ...
```

Two facts make that wrong:

1. **`input_tokens` INCLUDES cached tokens.** PydanticAI's `RunUsage` carries
   `cache_read_tokens` as a separate field, and we never read it.
2. **Cached input is billed at a large discount** by the provider, and
   `ModelPrice` has no column for that rate — only `input_per_mtok` and
   `output_per_mtok`.

Measured on 2026-08-15, the same receipt read twice with `gpt-5.4-mini`:

```
call 1: input=14108  cache_read=3072  output=3258
call 2: input=14114  cache_read=6656  output=3270   <- 47% of the prompt was cached
```

The prompt is the system prompt, the instruction, the household's category and
payment lists, and the image. Anything repeated across calls is cacheable, and
the eval harness — which sweeps the *same fifteen images* three times per
candidate — is close to the best case for caching. Hence the 4× gap there.

## Where it bites, and where it does not

**The error is always in the same direction: we over-report, never under.** For
E01's spend ceiling that is the safe direction — the ceiling trips early, not
late. For E07's operator report and E09's model decisions it is not: those are
comparisons, and it inflates every absolute figure.

**E09's 3.75× decision stands.** Baseline and pipeline were measured identically
— three repeated sweeps over the same images, priced at the same list rates — so
the *ratio* survives. If anything it is conservative: the cheap model consumes
more input tokens (185k a sweep against gpt-5.4's 75k), so it has more to gain
from caching than the model it is compared with. The absolute $/sweep in
`baseline-15-cases-2026-08-15.md` and `matrix-2026-08-15.md` are the numbers to
distrust, not the factor between them.

**Production over-reports by less than the harness.** Every household's receipt
photo is unique, so image tokens will not cache — but the system prompt,
instruction and catalogue lists repeat on every call and will.

## What to do

- [x] `ModelPrice` grows a `cached_input_per_mtok` column, nullable, defaulting
      to `input_per_mtok` so an unfilled row keeps today's (over-)estimate
      rather than silently reporting zero
- [x] `cost_usd_for` bills `input_tokens - cache_read_tokens` at the input rate
      and `cache_read_tokens` at the cached rate
- [x] `UsageRecord` records `cache_read_tokens`, so the discount is auditable
      after the fact rather than only re-derivable
- [x] Seed the cached rates from the provider's live pricing page, with
      `source_url` and `checked_on` as every other row has
- [x] A test with a usage object carrying cache reads asserts the cost is below
      the all-full-price figure and above the all-cached one
- [x] Re-state the absolute figures in the E08/E09 evidence documents, or add a
      note to each pointing here — the factors do not change

## Out of scope

Cache *writes*. `cache_write_tokens` exists on the same usage object and some
providers charge a premium for them; measure whether it is material before
modelling it. Do not guess a rate.

## Note on provenance

Found because the operator compared the reported spend with the provider's own
usage dashboard. Nothing in the repo could have caught it: every test asserts
our arithmetic against our own inputs, and the arithmetic was self-consistent.
The only check that finds this class of bug is the bill.

## Resolution — 2026-08-15

`ModelPrice.cached_input_per_mtok` (migration 0026), seeded from the live
pricing pages (0028); `cost_usd_for` bills `input_tokens - cache_read_tokens`
at the input rate and the remainder at the cached rate, clamped so a provider
over-reporting cache reads can never produce a negative fresh half — an
under-statement would be worse than the over-statement being fixed.
`UsageRecord.cache_read_tokens` (0027) makes the discount auditable, and the
eval table grew a `Cached` column.

Two things deliberately not done:

- **Existing `UsageRecord` rows were not re-priced.** Costs are frozen at write
  time; a backfill would make the ledger disagree with what was reported at the
  time. Comparisons spanning 2026-08-15 must account for the step change.
- **The E08/E09 evidence figures were not re-measured**, only annotated. The
  ratios those documents argue from are unaffected, and a re-run costs money
  that would buy no new decision.

Checked while seeding, and worth recording because the plan for this defect
assumed otherwise: `nvidia/nemotron-3-super-120b-a12b:free` (`LLM_TIER_ESSENTIAL`)
**is** still in the OpenRouter catalogue on 2026-08-15, at 0/0 prompt and
completion. There is no retired-model defect to file. Like every other `:free`
entry it lists no `input_cache_read`; it is seeded at a zero cached rate, which
cannot mis-state anything when the uncached rate is itself zero.
