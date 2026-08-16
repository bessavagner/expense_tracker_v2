# D03 · Bill cached input tokens at the cached rate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `UsageRecord.cost_usd` and the eval harness's `USD` column report what the provider actually charges, so a cost decision is made on the real number instead of one inflated 4× by cache reads billed at full price.

**Architecture:** `ModelPrice` grows a nullable `cached_input_per_mtok` column; `cost_usd_for` splits `input_tokens` into fresh and cached halves and prices each at its own rate, falling back to the full input rate when the column is empty so an unpriced-for-cache model keeps today's (over-)estimate rather than silently reporting a discount nobody verified. `UsageRecord` records `cache_read_tokens` so the discount is auditable after the fact, and the eval harness carries the same field from `RunUsage` through `CallCost` into the comparison table.

**Tech Stack:** Django 5, pydantic-ai 1.73 (`RunUsage.cache_read_tokens`), PostgreSQL + pgvector (port 5433), pytest + model_bakery, OpenAI and OpenRouter providers.

**Spec:** `docs/backlog/D03-cost-report-ignores-cached-input-tokens.md`

## Global Constraints

- **Never write a price from memory.** Every number in Task 3 must be re-read from the provider's live pricing page on the day the migration is written, with `source_url` and `checked_on` set to that page and that date. The table in Task 3 was fetched on **2026-08-15**; if the page disagrees when you run it, **the page wins** and you change the plan's numbers, not the page's.
- **The error may only ever move in the safe direction.** Today the report over-states cost, which is safe for E01's spend ceiling (it trips early) and wrong for E07's report and E09's decisions. A bug that makes the figure *under*-state cost is strictly worse than the one being fixed — hence the clamp in Task 1 Step 3 and the test that pins it.
- **`cost_usd` is frozen at write time.** No task backfills existing `UsageRecord` rows. History stays as it was measured; `ModelPrice.effective_from` exists so a *future* backfill can be honest.
- **Cache writes are out of scope.** `cache_write_tokens` exists on the same usage object and some providers charge a premium. Do not model it and do not guess a rate (D03, "Out of scope").
- **No new absolute cost numbers are to be invented for the evidence documents.** Task 5 adds a pointer note; it does not re-state a figure that was not re-measured.
- Every task ends green: `EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q`, `uv run ruff check src/backend/`, `uv run ruff format --check src/backend/`.
- No AI attribution in commit messages.

## Orientation — what already exists

| Fact | Where |
|---|---|
| `RunUsage` carries `cache_read_tokens: int = 0` and `cache_write_tokens: int = 0` alongside `input_tokens` | `.venv/.../pydantic_ai/usage.py:27-29` |
| `input_tokens` **includes** the cached tokens — cache reads are a subset, not an extra | same file, `incr` at `:239-241` |
| `cost_usd_for` is the single pricing function; the eval harness reuses it on purpose | `assistant/pricing.py:58`, `assistant/eval/costing.py:16` |
| `record_usage` is the only writer of `UsageRecord`, and never raises | `assistant/metering.py:41` |
| Every eval cost flows through `cost_of`, including per-attempt pipeline pricing | `assistant/eval/report.py:44-45`, `:111` |
| Embedding usage is adapted by `_TokenCounts`, which has no cache attribute — `getattr(..., 0)` covers it | `assistant/services/embedding.py:49` |
| Latest migration is `0025_usagerecord_escalation_reason` | `assistant/migrations/` |

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/assistant/models.py` *(modify)* | `ModelPrice.cached_input_per_mtok`, `UsageRecord.cache_read_tokens` |
| `src/backend/assistant/migrations/0026_modelprice_cached_input_rate.py` *(create)* | The price column |
| `src/backend/assistant/migrations/0027_usagerecord_cache_read_tokens.py` *(create)* | The ledger column |
| `src/backend/assistant/migrations/0028_seed_cached_input_prices.py` *(create)* | The live cached rates, one row per model |
| `src/backend/assistant/pricing.py` *(modify)* | Split the input bill into fresh and cached halves |
| `src/backend/assistant/metering.py` *(modify)* | Persist `cache_read_tokens` |
| `src/backend/assistant/admin.py` *(modify)* | Show the cached rate in the `ModelPrice` list |
| `src/backend/assistant/eval/costing.py` *(modify)* | `CallCost.cache_read_tokens`, `CostTotals.cache_read_tokens` |
| `src/backend/assistant/eval/extraction_runner.py` *(modify)* | `_SummedUsage` carries cache reads across the two attempts |
| `src/backend/assistant/eval/report.py` *(modify)* | A `Cached` column in the table and the JSON twin |
| `src/backend/assistant/tests/test_pricing.py` *(modify)* | The arithmetic, the fallback, the clamp, the seed ratchet |
| `src/backend/assistant/tests/test_metering.py` *(modify)* | The ledger column |
| `src/backend/assistant/tests/test_eval_costing.py` *(modify)* | Harness pricing and totals |
| `docs/runbook.md` *(modify)* | How to re-check a cached rate; what the new column means |
| `docs/superpowers/evidence/eval/baseline-15-cases-2026-08-15.md` *(modify)* | Note pointing at D03 |
| `docs/superpowers/evidence/eval/matrix-2026-08-15.md` *(modify)* | Note pointing at D03 |
| `docs/backlog/D03-cost-report-ignores-cached-input-tokens.md` *(modify)* | Tick the boxes, close it |
| `docs/backlog/INDEX.md` *(modify)* | D03 → done |

---

### Task 1: Price cached input tokens at their own rate

**Files:**
- Modify: `src/backend/assistant/models.py:247-249` (the `ModelPrice` rate columns)
- Create: `src/backend/assistant/migrations/0026_modelprice_cached_input_rate.py`
- Modify: `src/backend/assistant/pricing.py:58-72`
- Test: `src/backend/assistant/tests/test_pricing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ModelPrice.cached_input_per_mtok: Decimal | None` (12 digits, 6 decimal places, nullable) and `cost_usd_for(model_name: str, usage) -> Decimal | None`, which now also reads `usage.cache_read_tokens` (absent attribute → 0). Task 3 seeds the column; Task 4 relies on the new arithmetic without calling anything new.

- [ ] **Step 1: Write the failing tests**

Add to `src/backend/assistant/tests/test_pricing.py`. Replace the existing `FakeUsage` class and the `_price` helper with these versions (both grow one optional argument; every existing call site keeps working):

```python
class FakeUsage:
    def __init__(self, input_tokens, output_tokens, cache_read_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        # `input_tokens` INCLUDES this. pydantic-ai's `RunUsage` reports cache
        # reads as a subset of the prompt, not as an extra bucket.
        self.cache_read_tokens = cache_read_tokens


def _price(name="openai:test", inp="1.00", out="10.00", when=date(2020, 1, 1), cached=None):
    return ModelPrice.objects.create(
        model_name=name,
        input_per_mtok=Decimal(inp),
        output_per_mtok=Decimal(out),
        cached_input_per_mtok=Decimal(cached) if cached is not None else None,
        effective_from=when,
        source_url="https://example.test/pricing",
        checked_on=when,
    )
```

Then append the four new tests:

```python
def test_cached_input_is_billed_at_the_cached_rate():
    """The D03 defect: 1M input tokens of which 400k were cache reads.

    Full price would be $1.00 + $1.00 = $2.00; all-cached would be $0.10 +
    $1.00 = $1.10. The truth is between them, and it is not either endpoint.
    """
    _price(inp="1.00", out="10.00", cached="0.10")
    cost = cost_usd_for("openai:test", FakeUsage(1_000_000, 100_000, cache_read_tokens=400_000))
    # 600k fresh @ $1 = $0.60; 400k cached @ $0.10 = $0.04; 100k out @ $10 = $1.00
    assert cost == Decimal("1.640000")
    assert Decimal("1.100000") < cost < Decimal("2.000000")


def test_a_model_with_no_cached_rate_keeps_the_full_price_estimate():
    """An unfilled column must over-report, never silently discount.

    Reporting zero — or guessing a discount nobody read off the pricing page —
    would turn a missing measurement into an authoritative-looking number.
    """
    _price(inp="1.00", out="10.00", cached=None)
    assert cost_usd_for(
        "openai:test", FakeUsage(1_000_000, 100_000, cache_read_tokens=400_000)
    ) == Decimal("2.000000")


def test_usage_without_a_cache_field_is_priced_as_all_fresh():
    """Embeddings and transcriptions hand over adapters with no cache attribute."""
    _price(inp="1.00", out="10.00", cached="0.10")

    class NoCacheField:
        input_tokens = 1_000_000
        output_tokens = 0

    assert cost_usd_for("openai:test", NoCacheField()) == Decimal("1.000000")


def test_more_cache_reads_than_input_tokens_never_makes_the_bill_negative():
    """A provider that double-counts, or a summed usage across two attempts,
    could report more cache reads than input tokens. Unclamped, the fresh half
    goes negative and the cost is UNDER-stated — the one direction that is
    unsafe: E01's spend ceiling would trip late instead of early.
    """
    _price(inp="1.00", out="10.00", cached="0.10")
    cost = cost_usd_for("openai:test", FakeUsage(1_000, 0, cache_read_tokens=5_000))
    assert cost == Decimal("0.000100")  # all 1000 tokens billed as cached
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py -q
```

Expected: FAIL. `_price` raises `TypeError: ModelPrice() got unexpected keyword arguments: 'cached_input_per_mtok'` — the column does not exist yet, so every test in the file errors.

- [ ] **Step 3: Add the column and the arithmetic**

In `src/backend/assistant/models.py`, inside `class ModelPrice`, directly after `input_per_mtok`:

```python
    input_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
    # Nullable, and NULL means "we have not read a cached rate for this model",
    # never "there is no discount". `cost_usd_for` falls back to the full input
    # rate, so an unfilled row keeps the old over-estimate — the safe direction
    # (E01's ceiling trips early) — instead of inventing a discount. D03.
    cached_input_per_mtok = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Tarifa de tokens de entrada já em cache. Vazio = cobra a tarifa cheia.",
    )
    output_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
```

Generate the migration:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations assistant \
  --name modelprice_cached_input_rate
```

Expected: `assistant/migrations/0026_modelprice_cached_input_rate.py` created with a single `AddField`. Open it and confirm it is exactly that — if `makemigrations` swept up an unrelated model change, stop and investigate rather than committing it.

Then replace `cost_usd_for` in `src/backend/assistant/pricing.py`:

```python
def cost_usd_for(model_name: str, usage) -> Decimal | None:
    """USD cost of one call, or ``None`` when the model has no price row.

    ``None`` rather than ``Decimal(0)`` on purpose: zero is indistinguishable
    from a genuinely free call, and an unpriced model silently metering at zero
    is exactly how a cost report becomes fiction. The report counts nulls and
    says so.

    Cache reads are billed apart (D03). ``input_tokens`` INCLUDES
    ``cache_read_tokens`` — they are a subset of the prompt, not a second
    bucket — so the fresh half is the difference, and pricing the whole prompt
    at the full rate over-reported by roughly 4x on a repeated workload.
    """
    price = price_for(model_name)
    if price is None:
        return None
    inp = Decimal(getattr(usage, "input_tokens", 0) or 0)
    out = Decimal(getattr(usage, "output_tokens", 0) or 0)
    # Clamped because a negative fresh half would UNDER-state the bill, and
    # under-stating is the one direction that is unsafe here.
    cached = min(Decimal(getattr(usage, "cache_read_tokens", 0) or 0), inp)
    # A row with no cached rate bills cache reads at the full input rate: the
    # old behaviour, which errs high rather than inventing a discount.
    cached_rate = price.cached_input_per_mtok
    if cached_rate is None:
        cached_rate = price.input_per_mtok
    total = (
        ((inp - cached) / MILLION) * price.input_per_mtok
        + (cached / MILLION) * cached_rate
        + (out / MILLION) * price.output_per_mtok
    )
    return total.quantize(QUANTUM)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py -q
```

Expected: PASS, including the pre-existing tests — `test_cost_is_tokens_over_a_million_times_the_rate` still reads `Decimal("2.500000")`, because a usage object with zero cache reads prices exactly as before.

- [ ] **Step 5: Show the rate in the admin**

In `src/backend/assistant/admin.py`, `ModelPriceAdmin.list_display`, insert `"cached_input_per_mtok"` between `"input_per_mtok"` and `"output_per_mtok"`:

```python
    list_display = (
        "model_name",
        "input_per_mtok",
        "cached_input_per_mtok",
        "output_per_mtok",
        "effective_from",
        "checked_on",
    )
```

Prices are corrected from the admin without a deploy (runbook, "Change a model's price"), and a column that cannot be seen there cannot be corrected there.

- [ ] **Step 6: Run the full suite, lint, and commit**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/models.py src/backend/assistant/pricing.py \
        src/backend/assistant/admin.py \
        src/backend/assistant/migrations/0026_modelprice_cached_input_rate.py \
        src/backend/assistant/tests/test_pricing.py
git commit -m "fix(pricing): bill cached input tokens at the cached rate"
```

---

### Task 2: Record `cache_read_tokens` on every usage row

Without this the discount is only ever re-derivable from a provider dashboard. With it, "how much of this household's prompt was cached" is a query.

**Files:**
- Modify: `src/backend/assistant/models.py:319-321` (the `UsageRecord` token columns)
- Create: `src/backend/assistant/migrations/0027_usagerecord_cache_read_tokens.py`
- Modify: `src/backend/assistant/metering.py:71-83`
- Test: `src/backend/assistant/tests/test_metering.py`

**Interfaces:**
- Consumes: `cost_usd_for` from Task 1 (already wired through `record_usage`; no signature change).
- Produces: `UsageRecord.cache_read_tokens: int | None`. NULL means "the provider did not report it"; `0` means "nothing was cached". No later task reads it.

- [ ] **Step 1: Write the failing tests**

Add to `src/backend/assistant/tests/test_metering.py`. First extend the module's `FakeUsage`:

```python
class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50, cache_read_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_tokens = cache_read_tokens
```

Then append:

```python
def test_a_record_captures_the_cached_half_of_the_prompt(household, user, priced):
    """The discount has to be auditable after the fact, not only re-derivable
    from the provider's dashboard — which is how D03 was found in the first
    place, and the only reason anyone noticed."""
    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.CHAT,
        model="openai:test",
        usage=FakeUsage(1_000_000, 0, cache_read_tokens=400_000),
        latency_ms=10,
        ok=True,
    )
    rec = UsageRecord.objects.get()
    assert rec.input_tokens == 1_000_000
    assert rec.cache_read_tokens == 400_000


def test_a_provider_that_reports_no_cache_field_records_null_not_zero(household, user, priced):
    """NULL is "not reported"; 0 is "nothing was cached". Collapsing them would
    make an unmeasured provider look like a provider with no cache hits."""

    class NoCacheField:
        input_tokens = 500
        output_tokens = 5

    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.EMBEDDING,
        model="openai:test",
        usage=NoCacheField(),
        latency_ms=10,
        ok=True,
    )
    assert UsageRecord.objects.get().cache_read_tokens is None


def test_a_failed_call_records_null_cache_tokens(household, user, priced):
    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.EXTRACTION,
        model="openai:test",
        usage=None,
        latency_ms=10,
        ok=False,
    )
    assert UsageRecord.objects.get().cache_read_tokens is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -q
```

Expected: FAIL with `AttributeError: 'UsageRecord' object has no attribute 'cache_read_tokens'`.

- [ ] **Step 3: Add the column and write it**

In `src/backend/assistant/models.py`, inside `class UsageRecord`, between `input_tokens` and `output_tokens`:

```python
    input_tokens = models.IntegerField(null=True, blank=True)
    # A SUBSET of input_tokens, not an addition — the provider reports cache
    # reads as part of the prompt. NULL means the provider reported nothing;
    # 0 means nothing was cached. Recorded so the discount `cost_usd` already
    # applied is auditable months later (D03), rather than only visible on the
    # provider's own dashboard.
    cache_read_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
```

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations assistant \
  --name usagerecord_cache_read_tokens
```

Expected: `assistant/migrations/0027_usagerecord_cache_read_tokens.py`, one `AddField`.

In `src/backend/assistant/metering.py`, inside the `UsageRecord.objects.acreate(...)` call, add one line after `input_tokens=`:

```python
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            cache_read_tokens=getattr(usage, "cache_read_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the full suite, lint, and commit**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/models.py src/backend/assistant/metering.py \
        src/backend/assistant/migrations/0027_usagerecord_cache_read_tokens.py \
        src/backend/assistant/tests/test_metering.py
git commit -m "feat(metering): record the cached half of each prompt"
```

---

### Task 3: Seed the cached rates from the live pricing pages

The column from Task 1 is inert until it has numbers. Until then every model still bills cache reads at full price, which is the defect.

**Files:**
- Create: `src/backend/assistant/migrations/0028_seed_cached_input_prices.py`
- Test: `src/backend/assistant/tests/test_pricing.py`

**Interfaces:**
- Consumes: `ModelPrice.cached_input_per_mtok` from Task 1.
- Produces: one `ModelPrice` row per priced model with `effective_from = checked_on = 2026-08-15` (or the day you actually check), each carrying all three rates. Nothing later depends on the values.

- [ ] **Step 1: Re-read the live pricing pages**

Do this first, before writing a line of the migration. Fetch both:

- `https://developers.openai.com/api/docs/pricing` — the input, **cached input**, and output rate per million tokens for `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.6-sol`, `text-embedding-3-small`.
- `https://openrouter.ai/api/v1/models` — the `pricing.prompt`, `pricing.completion` and `pricing.input_cache_read` fields (per **token**; multiply by 1,000,000) for `qwen/qwen3.7-flash` and `nvidia/nemotron-3-super-120b-a12b:free`.

The table below was read on **2026-08-15**. Treat it as a claim to verify, not a source: if today's page differs, use the page's numbers and update `CHECKED_ON` to today.

| `model_name` | input | **cached input** | output | source |
|---|---|---|---|---|
| `openai:gpt-5.4` | 2.500000 | **0.250000** | 15.000000 | OpenAI |
| `openai:gpt-5.4-mini` | 0.750000 | **0.075000** | 4.500000 | OpenAI |
| `openai:gpt-5.6-terra` | 2.000000 | **0.200000** | 12.000000 | OpenAI |
| `openai:gpt-5.6-luna` | 0.200000 | **0.020000** | 1.200000 | OpenAI |
| `openai:gpt-5.6-sol` | 5.000000 | **0.500000** | 30.000000 | OpenAI |
| `openai-responses:gpt-5.6-terra` | 2.000000 | **0.200000** | 12.000000 | OpenAI |
| `openai-responses:gpt-5.6-luna` | 0.200000 | **0.020000** | 1.200000 | OpenAI |
| `openai-responses:gpt-5.6-sol` | 5.000000 | **0.500000** | 30.000000 | OpenAI |
| `openrouter:qwen/qwen3.7-flash` | 0.030000 | **0.006000** | 0.130000 | OpenRouter |
| `openrouter:nvidia/nemotron-3-super-120b-a12b:free` | 0.000000 | **0.000000** | 0.000000 | OpenRouter |
| `text-embedding-3-small` | 0.020000 | *(not listed — leave NULL)* | 0.000000 | OpenAI |

Two things found during that lookup, both worth carrying into the migration's docstring:

- OpenAI lists cached input at exactly **10% of input** across the whole gpt-5.x family. Do not encode that as a formula — the next model that breaks the pattern would be silently mispriced. One literal per row.
- `nvidia/nemotron-3-super-120b-a12b:free` was **not in the OpenRouter catalogue** on 2026-08-15 (`nvidia/nemotron-3.5-lightning:free` was). That is a separate defect about `LLM_TIER_ESSENTIAL` pointing at a possibly-retired model, not D03's. Seed it at 0/0/0 as today (a free model's cached rate is zero either way) and file the finding rather than fixing it here.

- [ ] **Step 2: Write the failing ratchet test**

Add to `src/backend/assistant/tests/test_pricing.py`:

```python
@pytest.mark.parametrize(
    "setting_name",
    [
        "LLM_MODEL",
        "LLM_ASSISTANT_MODEL",
        "LLM_VISION_MODEL",
        "LLM_TIER_ADVANCED",
        "LLM_TIER_STANDARD",
        "LLM_TIER_ESSENTIAL",
        "LLM_TIER_ESSENTIAL_FALLBACK",
    ],
)
def test_every_configured_chat_model_has_a_cached_input_rate(setting_name):
    """The D03 ratchet, twin to `test_every_configured_chat_model_has_a_seeded_price`.

    A model priced without its cached rate is not broken — it falls back to the
    full input rate and over-reports, exactly as before D03. But over-reporting
    is the bug, so a new model arriving without a cached rate has to fail here
    rather than quietly re-introduce it. Embeddings are excluded: the provider
    lists no cached rate for them, and an embedding prompt is not reused.
    """
    name = getattr(settings, setting_name, "")
    if not name:
        pytest.skip(f"{setting_name} is not configured")
    row = price_for(name)
    assert row is not None, f"{setting_name}={name} has no ModelPrice row at all"
    assert row.cached_input_per_mtok is not None, (
        f"{setting_name}={name} has no cached input rate. Read it off the "
        f"provider's live pricing page (never from memory) and add a seed row."
    )
```

- [ ] **Step 3: Run it to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py \
  -k cached_input_rate -q
```

Expected: FAIL — `has no cached input rate` for every configured setting, because migration 0028 does not exist.

- [ ] **Step 4: Write the seed migration**

Create `src/backend/assistant/migrations/0028_seed_cached_input_prices.py`. Replace every number below with what Step 1's fetch returned:

```python
"""Price the cached half of a prompt, per D03.

Every rate here was read off the provider's live pricing page on `CHECKED_ON`,
not recalled and not derived from the uncached rate. OpenAI happened to list
cached input at 10% of input across the gpt-5.x family on that date; that is an
observation, not a rule, so each row carries its own literal.

New rows rather than an edit of the 2026-08-14 ones: `effective_from` is how
this table keeps history, and rows predating this date deliberately keep a NULL
cached rate — `cost_usd_for` falls back to the full input rate for them, which
is exactly the (over-)estimate under which those `UsageRecord` costs were
frozen. Backfilling the old rows would make a historical re-price disagree with
what the ledger actually says.

`text-embedding-3-small` is absent on purpose: the pricing page lists no cached
rate for embeddings, and an embedding prompt is not reused across calls. It
keeps the full-price fallback, and `test_every_configured_chat_model_has_a_cached_input_rate`
excludes it because it is a module constant, not a chat setting.

Note recorded during the lookup: `nvidia/nemotron-3-super-120b-a12b:free`
(`LLM_TIER_ESSENTIAL`) was NOT in the OpenRouter catalogue on CHECKED_ON. It is
seeded at zero here because a free model's cached rate is zero either way; the
question of whether that model still exists is a separate defect.

Sources consulted on 2026-08-15:
  * https://developers.openai.com/api/docs/pricing
  * https://openrouter.ai/api/v1/models

Reversible: the reverse deletes exactly the rows this migration inserted, and
the previous rows — with their NULL cached rate — take over again.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 15)

OPENAI = "https://developers.openai.com/api/docs/pricing"
OPENROUTER = "https://openrouter.ai/api/v1/models"

# (model_name, input_per_mtok, cached_input_per_mtok, output_per_mtok, source_url)
PRICES = [
    ("openai:gpt-5.4", "2.500000", "0.250000", "15.000000", OPENAI),
    ("openai:gpt-5.4-mini", "0.750000", "0.075000", "4.500000", OPENAI),
    ("openai:gpt-5.6-terra", "2.000000", "0.200000", "12.000000", OPENAI),
    ("openai:gpt-5.6-luna", "0.200000", "0.020000", "1.200000", OPENAI),
    ("openai:gpt-5.6-sol", "5.000000", "0.500000", "30.000000", OPENAI),
    ("openai-responses:gpt-5.6-terra", "2.000000", "0.200000", "12.000000", OPENAI),
    ("openai-responses:gpt-5.6-luna", "0.200000", "0.020000", "1.200000", OPENAI),
    ("openai-responses:gpt-5.6-sol", "5.000000", "0.500000", "30.000000", OPENAI),
    ("openrouter:qwen/qwen3.7-flash", "0.030000", "0.006000", "0.130000", OPENROUTER),
    (
        "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
        "0.000000",
        "0.000000",
        "0.000000",
        OPENROUTER,
    ),
]


def seed(apps, schema_editor):
    ModelPrice = apps.get_model("assistant", "ModelPrice")
    for name, inp, cached, out, url in PRICES:
        ModelPrice.objects.update_or_create(
            model_name=name,
            effective_from=CHECKED_ON,
            defaults={
                "input_per_mtok": inp,
                "cached_input_per_mtok": cached,
                "output_per_mtok": out,
                "source_url": url,
                "checked_on": CHECKED_ON,
            },
        )


def unseed(apps, schema_editor):
    ModelPrice = apps.get_model("assistant", "ModelPrice")
    ModelPrice.objects.filter(
        model_name__in=[p[0] for p in PRICES], effective_from=CHECKED_ON
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("assistant", "0027_usagerecord_cache_read_tokens")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Run the ratchet and the round trip**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py -q
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0027
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant
```

Expected: the test file passes (both ratchets), and the migrate down/up pair completes without error — the reverse has to be clean, like every other seed migration in this app.

- [ ] **Step 6: Run the full suite, lint, and commit**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/migrations/0028_seed_cached_input_prices.py \
        src/backend/assistant/tests/test_pricing.py
git commit -m "feat(pricing): seed cached input rates from the live pricing pages"
```

---

### Task 4: Carry cache reads through the eval harness

The harness reuses `cost_usd_for`, so its `USD` column is already correct after Tasks 1–3 for single calls. What is still missing: the pipeline runner drops the field when it sums two attempts, and the table shows no cached-token count, so a reader cannot tell a genuinely cheap model from a well-cached one.

**Files:**
- Modify: `src/backend/assistant/eval/costing.py:19-45` and `:48-75`
- Modify: `src/backend/assistant/eval/extraction_runner.py:98-115`
- Modify: `src/backend/assistant/eval/report.py:158-176` and `:211-218`
- Test: `src/backend/assistant/tests/test_eval_costing.py`

**Interfaces:**
- Consumes: `cost_usd_for` from Task 1.
- Produces: `CallCost.cache_read_tokens: int` and `CostTotals.cache_read_tokens: int`, both defaulting to `0` so existing positional constructions keep working; a `Cached` column in the markdown table and a `cache_read_tokens` key under `totals` in the JSON.

- [ ] **Step 1: Write the failing tests**

Add to `src/backend/assistant/tests/test_eval_costing.py`, and extend its helper:

```python
def usage(inp, out, cached=0):
    return SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_tokens=cached)
```

Then append:

```python
@pytest.mark.django_db
def test_cost_of_prices_the_cached_half_at_the_cached_rate():
    """The harness and the operator report must agree to the cent — same
    function, same arithmetic. D03."""
    baker.make(
        "assistant.ModelPrice",
        model_name="fake:cheap",
        input_per_mtok=Decimal("1.000000"),
        cached_input_per_mtok=Decimal("0.100000"),
        output_per_mtok=Decimal("2.000000"),
        effective_from="2020-01-01",
    )
    call = cost_of("fake:cheap", usage(1_000_000, 500_000, cached=500_000), latency_ms=1)
    assert call.cache_read_tokens == 500_000
    # 500k fresh @ $1 = $0.50; 500k cached @ $0.10 = $0.05; 500k out @ $2 = $1.00
    assert call.cost_usd == Decimal("1.550000")


@pytest.mark.django_db
def test_usage_none_records_zero_cache_reads():
    assert cost_of("fake:unpriced", None, latency_ms=1).cache_read_tokens == 0


def test_total_sums_cache_reads():
    costs = [
        CallCost("m", 100, 50, 1000, Decimal("0.001000"), 40),
        CallCost("m", 200, 60, 3000, Decimal("0.002000"), 60),
    ]
    assert total(costs).cache_read_tokens == 100
```

And in `src/backend/assistant/tests/test_eval_report.py`, extend the local `_Usage` helper so the pipeline case exercises the same path:

```python
    class _Usage:
        def __init__(self, i, o, cached=0):
            self.input_tokens = i
            self.output_tokens = o
            self.cache_read_tokens = cached
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_costing.py -q
```

Expected: FAIL — `TypeError: CallCost.__init__() takes 6 positional arguments but 7 were given`, and `AttributeError: 'CallCost' object has no attribute 'cache_read_tokens'`.

- [ ] **Step 3: Thread the field through**

In `src/backend/assistant/eval/costing.py`:

```python
@dataclass(frozen=True)
class CallCost:
    """One provider call inside the harness."""

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal | None
    # A SUBSET of input_tokens. Last, with a default, so the field can be added
    # without rewriting every positional construction. D03.
    cache_read_tokens: int = 0


def cost_of(model: str, usage, latency_ms: int) -> CallCost:
    """Price one call. ``usage=None`` means the call failed before reporting any.

    Synchronous and hits the database (``ModelPrice``). Call it from the command,
    never from inside an async runner.
    """
    inp = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
    out = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
    cached = int(getattr(usage, "cache_read_tokens", 0) or 0) if usage is not None else 0
    cost = cost_usd_for(model, usage) if usage is not None else None
    return CallCost(
        model=model,
        input_tokens=inp,
        output_tokens=out,
        latency_ms=latency_ms,
        cost_usd=cost,
        cache_read_tokens=cached,
    )


@dataclass(frozen=True)
class CostTotals:
    """What a whole suite cost on one model."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced_calls: int
    latency_ms_total: int
    cache_read_tokens: int = 0

    @property
    def avg_latency_ms(self) -> int:
        return int(self.latency_ms_total / self.calls) if self.calls else 0
```

and inside `total(...)`, add one line to the constructor:

```python
        latency_ms_total=sum(c.latency_ms for c in costs),
        cache_read_tokens=sum(c.cache_read_tokens for c in costs),
```

In `src/backend/assistant/eval/extraction_runner.py`, `_SummedUsage` and `_sum_usage`:

```python
@dataclass(frozen=True)
class _SummedUsage:
    """Both attempts' tokens as one usage object.

    `cost_of` reads `input_tokens` / `output_tokens` / `cache_read_tokens` by
    attribute, and a pipeline that reported only the cheap call's tokens would
    price the retry at zero — making every escalating pipeline look cheaper
    than the model it escalates to.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0


def _sum_usage(*usages) -> _SummedUsage:
    return _SummedUsage(
        input_tokens=sum(getattr(u, "input_tokens", 0) or 0 for u in usages if u),
        output_tokens=sum(getattr(u, "output_tokens", 0) or 0 for u in usages if u),
        cache_read_tokens=sum(getattr(u, "cache_read_tokens", 0) or 0 for u in usages if u),
    )
```

In `src/backend/assistant/eval/report.py`, `render_markdown` — the header and the row:

```python
        header = ["Model", "n", "Score", *keys, "In tok", "Cached", "Out tok", "USD", "Avg ms"]
```

```python
                str(r.totals.input_tokens),
                str(r.totals.cache_read_tokens),
                str(r.totals.output_tokens),
```

and `render_json`, inside `"totals"`:

```python
                    "input_tokens": r.totals.input_tokens,
                    "cache_read_tokens": r.totals.cache_read_tokens,
                    "output_tokens": r.totals.output_tokens,
```

- [ ] **Step 4: Run the eval tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_eval_costing.py \
  src/backend/assistant/tests/test_eval_report.py \
  src/backend/assistant/tests/test_eval_runners.py -q
```

Expected: PASS. `test_the_cost_of_both_attempts_is_counted` still holds — summing an extra field does not change what the two attempts cost.

- [ ] **Step 5: Prove it end to end against the stub runner**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 \
  uv run python src/backend/manage.py eval_models --stub --suite extraction
```

Expected: the table prints with a `Cached` column between `In tok` and `Out tok`. Stub runs report `0` there and are unpriced — that is correct, not a failure.

- [ ] **Step 6: Run the full suite, lint, and commit**

```bash
EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/eval/ src/backend/assistant/tests/test_eval_costing.py \
        src/backend/assistant/tests/test_eval_report.py
git commit -m "feat(eval): report cached input tokens in the comparison table"
```

---

### Task 5: Say so in the documents the decisions were made from

The figures in the E08/E09 evidence documents were computed by the broken arithmetic and are not being re-measured — a re-run costs real money and, per D03, the *ratios* those documents argue from survive unchanged. So each gets a note rather than a new number.

**Files:**
- Modify: `docs/runbook.md` (the "Change a model's price" section, around `:1477-1495`)
- Modify: `docs/superpowers/evidence/eval/baseline-15-cases-2026-08-15.md` (after the front matter, before "## The production baseline")
- Modify: `docs/superpowers/evidence/eval/matrix-2026-08-15.md` (same position — near the top, before the first table)
- Modify: `docs/backlog/D03-cost-report-ignores-cached-input-tokens.md`
- Modify: `docs/backlog/INDEX.md:96` and its footnote ⁷

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: nothing code-facing.

- [ ] **Step 1: Extend the runbook's pricing section**

In `docs/runbook.md`, immediately after the paragraph beginning "**Always re-check the provider's live pricing page first**", insert:

```markdown
A price row has **three** rates, not two: `input_per_mtok`, `output_per_mtok`,
and `cached_input_per_mtok`. Providers bill tokens they served from their
prompt cache at a large discount — OpenAI listed 10% of the input rate across
the gpt-5.x family on 2026-08-15 — and `input_tokens` already **includes** those
tokens, so pricing the whole prompt at the full rate over-reports. It over-
reported by roughly 4× on the E09 matrix, which is how D03 was found.

Leaving `cached_input_per_mtok` empty is safe but wrong-ish: the call is billed
entirely at the full input rate, exactly as before D03, so the figure errs high.
`test_every_configured_chat_model_has_a_cached_input_rate` fails when a model in
settings has a price row without one, so this cannot be forgotten silently.

`UsageRecord.cache_read_tokens` records how much of each prompt was served from
cache. To see the discount a household is actually getting:

```sql
SELECT model,
       SUM(input_tokens) AS input_tokens,
       SUM(cache_read_tokens) AS cached,
       ROUND(100.0 * SUM(cache_read_tokens) / NULLIF(SUM(input_tokens), 0), 1) AS pct_cached
FROM assistant_usagerecord
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY model ORDER BY input_tokens DESC;
```

Costs already written are **not** re-priced when a cached rate is added:
`cost_usd` is frozen at write time by design, so rows created before
2026-08-15 keep the old over-estimate. Compare periods across that date with
that in mind.
```

- [ ] **Step 2: Note the caveat on both evidence documents**

Insert this block near the top of **both** `baseline-15-cases-2026-08-15.md` and `matrix-2026-08-15.md` — after the opening paragraph, before the first table:

```markdown
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
```

Verify the relative link depth by opening the rendered path from the file's own directory — the evidence files live at `docs/superpowers/evidence/eval/`, so `../../../backlog/...` resolves to `docs/backlog/...`.

- [ ] **Step 3: Close the defect**

In `docs/backlog/D03-cost-report-ignores-cached-input-tokens.md`:

- Tick all six boxes under "What to do".
- Change the front-matter `status: ready` to `status: done`.
- Append this section at the end:

```markdown
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

Found while seeding: `nvidia/nemotron-3-super-120b-a12b:free`
(`LLM_TIER_ESSENTIAL`) was not in the OpenRouter catalogue on 2026-08-15.
Unrelated to D03 and filed separately.
```

- [ ] **Step 4: Update the backlog index**

In `docs/backlog/INDEX.md:96`, change the D03 status cell from `ready⁷` to `**done** (2026-08-15)⁷`, and extend footnote ⁷ with one sentence: what shipped, and that the ratios in the E09 evidence were unaffected.

- [ ] **Step 5: Check the links and commit**

```bash
grep -n "cached_input_per_mtok\|cache_read_tokens" docs/runbook.md
grep -rn "D03" docs/backlog/INDEX.md docs/superpowers/evidence/eval/*.md
git add docs/
git commit -m "docs(pricing): the cached-rate column, and what it means for the E09 figures"
```

---

## Verification — the whole change

- [ ] `EVAL_FIXTURES_DIR=~/ledger-eval-fixtures POSTGRES_PORT=5433 uv run pytest src/backend/ -q` — green.
- [ ] `uv run ruff check src/backend/ && uv run ruff format --check src/backend/` — clean.
- [ ] `POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0025` then `migrate assistant` — the three new migrations reverse and re-apply cleanly.
- [ ] `POSTGRES_PORT=5433 uv run python src/backend/manage.py usage_report --by-kind` — still runs; totals for periods before today are unchanged (costs are frozen), and any row written after the deploy carries a `cache_read_tokens` value.

## Deliberately not in this plan

- **Cache writes.** `cache_write_tokens` is on the same usage object and some providers charge a premium for it. D03 says measure before modelling; nothing here guesses a rate.
- **Backfilling historical `UsageRecord.cost_usd`.** Frozen at write time by design.
- **Re-running the E08/E09 evals.** Annotated instead — see Task 5.
- **`LLM_TIER_ESSENTIAL` pointing at a model missing from the OpenRouter catalogue.** Found while looking up prices on 2026-08-15; a real question about the free tier's degrade path, and not this defect. File it as its own D-number.
