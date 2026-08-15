---
id: E07
title: Usage metering & quota
release: R1
status: ready
depends_on: [E04, E06]
blocks: [E09, E15]
wedge_critical: true
---

# E07 · Usage metering & quota

## Outcome

Every LLM call is recorded against a household with its token counts and estimated cost, quotas are enforced at a single chokepoint before any model call, and you can answer "what does this customer cost me?" with a query.

## Why now

Review finding **B2** and **ADR-003**. E01 installed a crude ceiling; this epic makes cost **attributable, enforceable, and priceable**.

It is wedge-critical because the wedge is AI capture (PD-1). If AI is the product, then cost-per-turn is the unit economics of the entire business, and industry data shows LLM spend distributions are heavily skewed — a small fraction of users drive most of the cost. Without per-household attribution you cannot tell a healthy margin from one outlier eating the spread.

It blocks **E09** (you cannot prove a cheaper model saved money without a cost baseline) and **E15** (you cannot price what you cannot measure).

## Evidence in the codebase

> **Re-anchored 2026-08-14 against `075b393` on `main`.** The original table was
> written at `3bbc5ca`; E06 added imports, Sentry `capture_exception` calls and a
> whole Logfire settings block, moving every anchor below by 40–90 lines. Verify
> before trusting — the same drift will happen again.

| What | Where (at `075b393`) |
|---|---|
| The chat entry point — every LLM path passes through here | `assistant/views.py:196` (`chat_view`) |
| The existing pre-call admission gate | `assistant/views.py:162-188` (`throttle_denial`), called at `:228` |
| Text turn path | `assistant/views.py:248-267` (`_handle_json`) |
| Audio path — transcription then agent run | `assistant/views.py:298-336` (`_handle_audio`); the transcription call is `:307` |
| Image path — extraction, possible vision retry, then agent run | `assistant/views.py:379-479` (`_handle_images`) |
| First extraction call | `assistant/views.py:426` |
| The expensive retry: a second extraction with the vision model | `assistant/views.py:438-441` |
| Where an extraction lands, then runs the agent | `assistant/views.py:339-376` (`_dispatch_extraction`) |
| Agent run wrapper where usage is available | `assistant/views.py:110-117` — `agent.run_stream(...)`, `stream.all_messages()`; the whole SSE builder is `:92-159` |
| The actual PydanticAI run for extraction | `assistant/agents/extraction.py:195` — `extraction_agent.run(prompt, model=model)` |
| The two `Agent(...)` constructions to attribute a model against | `assistant/agents/assistant.py:65` (`LLM_ASSISTANT_MODEL`), `assistant/agents/extraction.py:129` (`LLM_VISION_MODEL`) |
| Embeddings — a separate, unmetered OpenAI call | `assistant/services/embedding.py:11-20` (`get_embedding`); its only caller is `assistant/agents/tools.py:1224`, inside the `check_memory` tool |
| Transcription — another unmetered call, with a **fallback loop that can bill twice** | `assistant/services/transcription.py:27-73`; the retry is the `for model in models` loop at `:55-71` |
| Model configuration to attribute against | `config/settings.py:331-347` (`LLM_MODEL`, `LLM_ASSISTANT_MODEL`, `LLM_TRANSCRIBE_MODEL`, `LLM_TRANSCRIBE_FALLBACK_MODEL`, `LLM_VISION_MODEL`) and `assistant/services/embedding.py:5` (`EMBEDDING_MODEL`, hardcoded — not a setting) |
| E01's throttle, the thing S07-3 replaces | `assistant/throttling.py` (whole file, 65 lines) — `rules_for`, `exceeded_rule` |
| E01's throttle limits | `config/settings.py:412-415` |
| **The model this epic collides with** | `assistant/models.py:169-208` (`AssistantUsageEvent`), `:164-167` (`AssistantUsageKind`) — see *The `AssistantUsageEvent` decision* below |
| Logfire instrumentation policy — the usage numbers already flow here | `assistant/tracing.py:21-35` (`instrumentation_settings`), applied globally by `Agent.instrument_all` at `:56` |

**Note the multi-call reality:** a single receipt photo can trigger extraction, a vision retry, and an agent run — three billable calls for one user action. Metering must capture all of them, attributed to one logical interaction, or the numbers will understate cost badly.

**And note a fourth:** `transcribe_audio` retries against `LLM_TRANSCRIBE_FALLBACK_MODEL` when the primary rejects the browser's webm/opus. That failed first attempt still costs money, and S07-2 requires it to produce its own record.

## Decisions taken before planning (2026-08-14)

The epic as originally written left a model collision unnamed and four open
questions. These are settled. An agent must **not** re-litigate them.

### D1 · The `AssistantUsageEvent` decision — two tables, different grains

E01 already ships `AssistantUsageEvent`, written by `throttle_denial` on every
admitted turn and re-tenanted to household by E04. It is **not** the same thing
as `UsageRecord`, and merging them is rejected:

| | `UsageInteraction` (was `AssistantUsageEvent`) | `UsageRecord` (new) |
|---|---|---|
| One row per | **user action** — one turn | **provider call** |
| Written | *before* the model call | *after* it (tokens don't exist yet) |
| Purpose | quota / credit accounting | cost ledger |
| A receipt photo yields | 1 row | 2–4 rows: extraction, vision retry, agent run, maybe an embedding |

A quota decision must happen *before* any call, so it needs a row that exists
pre-call — that is exactly why E01 writes on admission (a stream that dies
halfway still counts against budget). Cost rows cannot serve that purpose.

**Therefore:** `RenameModel` `AssistantUsageEvent` → `UsageInteraction` (no data
moves, fully reversible), and `UsageRecord.interaction` is a **nullable FK** to
it. That FK *is* S07-1's "interaction ID". Nullable because an embedding or a
transcription can be triggered outside a chat turn.

Migration risk is low: `0006_assistant_usage_event` landed 2026-08-08 — days of
single-user rows — and every column `UsageRecord` adds is on a new table.

The rename touches ~6 test files that hardcode the label string
(`accounts/tests/test_tenancy_bases.py`, `test_bake_scoping.py`,
`test_scoping_ratchet.py`, `test_user_column_is_on_its_way_out.py`,
`assistant/tests/test_household_columns.py`,
`finances/tests/test_household_indexes.py`). That is mechanical, and Task 1
does it in one commit.

### D2 · Model tiers and a credit currency (resolves open questions 1, 3 and 4)

Three tiers. **Code and product English use the same words**; pt-BR is the
display layer.

| Enum | English (product) | pt-BR (product) | Credit cost |
|---|---|---|---|
| `Tier.ADVANCED` | Advanced | Avançado | most |
| `Tier.STANDARD` | Standard | Padrão | less |
| `Tier.ESSENTIAL` | Essential | Essencial | **zero** |

- **ADVANCED and STANDARD draw from one shared credit pool.** Not two budgets —
  one balance, spent at different rates. A household chooses how to spend it.
- **Credits are a product currency, deliberately not real tokens.** They are a
  stable unit the user can reason about and we can reprice without changing what
  a customer was promised. Real tokens live in `UsageRecord`; credits live on
  the household.
- **The user may switch tiers freely.** When the balance reaches zero, the
  chokepoint forces `ESSENTIAL` — it does not refuse.
- **`ESSENTIAL` costs zero credits and has no plan quota**, but it is still
  subject to the **abuse ceiling** below. This preserves R0's release gate.
- **Two different refusals, one decision function.** Out of credits → *degrade*.
  Over the abuse ceiling → *429*, and no tier rescues you.

> **Why this does not violate PD-4.** PD-4 forbids a model swap without an eval
> score because you cannot prove the cheaper model is not worse. The
> `ESSENTIAL` tier's baseline is **a 429 and no answer at all**, not `gpt-5.4` —
> so "not worse than the alternative" is trivially true. E09 still owns which
> model sits in ADVANCED and STANDARD, and still needs E08's score to move one.
> **E07 ships with ADVANCED and STANDARD both pointing at today's model**, so no
> unscored swap occurs.

### D3 · `ESSENTIAL`'s model — free first, cheapest paid as fallback

Primary is a free OpenRouter model; on failure it falls back to the cheapest
paid model. This mirrors the transcription fallback already in
`services/transcription.py:55-71`. Adds `OPENROUTER_API_KEY` to Secret Manager.

> **Standing rule — never name "the cheapest model" from memory.** Model
> catalogues and prices churn faster than any training cutoff. Before writing a
> model name or a price into code, a `ModelPrice` row, or this document, **look
> up current provider pricing online and record the date checked.** A remembered
> price becomes a stored cost figure and then an authoritative-looking number in
> the operator's report. This is why D4 puts prices in the database.

### D4 · The price table is a database model (resolves open question 2)

`ModelPrice(model_name, input_per_mtok, output_per_mtok, effective_from)`,
admin-editable, seeded by a data migration, cached so the hot path is not a
query per call. Chosen over settings because D3's rule means prices *will* be
corrected out of band, and a correction should not need a deploy.

Cost is computed and **stored on the `UsageRecord` at write time**, so changing
a price never rewrites history.

### D5 · Still open — the beta grant size

The monthly credit grant per plan is the one number that cannot be decided from
the code. Task 9 runs the query against real data and sets it. Until then the
plan carries a placeholder that is explicitly marked as such.

## Stories

### S07-1 · The `UsageRecord` model

- **Given** the need to attribute cost
- **When** the model is created
- **Then** `UsageRecord` captures at minimum: household, acting user, interaction kind (chat / receipt-extraction / transcription / embedding), model name, input tokens, output tokens, estimated cost, latency, success or failure, and timestamp
- **And** records sharing one user action are correlated by an interaction ID, so a receipt costing three calls is analysable as one event
- **And** cost estimation uses a per-model price table that is configuration, not hardcoded — prices change
- **And** writing a usage record **never** fails the user's request; a metering failure is logged, not propagated

### S07-2 · Meter every LLM call site

- **Given** the call sites in the evidence table
- **When** metering is added
- **Then** chat runs, receipt extraction, the vision retry, transcription, and embedding generation each produce a `UsageRecord`
- **And** token counts come from the provider response via PydanticAI's usage API, not estimated from string length
- **And** failed calls are recorded too — a failed vision call still costs money
- **And** a test asserts that a receipt flow producing an extraction plus an agent run yields the expected number of correlated records

### S07-3 · One enforcement chokepoint

- **Given** the industry pattern of enforcing at a single gateway rather than at each call site
- **When** quota enforcement is implemented
- **Then** a single function is the only place a quota decision is made, and every LLM path calls it **before** invoking a model
- **And** it consumes the E01 throttle logic rather than duplicating it — E01's crude limits are replaced by this, not layered on top. `assistant/throttling.py` is deleted; its rolling-window rules move inside the chokepoint as the **abuse ceiling** (D2)
- **And** it returns a `QuotaDecision` naming the tier to use, so *degrade* and *refuse* are one decision, not two code paths
- **And** running out of credits **degrades to `ESSENTIAL`** with a clear pt-BR message saying what was exhausted and when it renews — it does not refuse (D2)
- **And** exceeding the **abuse ceiling** returns 429 with a pt-BR message, and a test asserts that such a request produces zero model calls and zero cost

> E01 deliberately shipped a blunt per-user throttle with no dependencies. This story is where it becomes household-scoped, credit-aware and tiered. Removing E01's version is expected; leaving both is a bug. Note the two refusals are *different*: out of credits → degrade; abusive → 429.

### S07-4 · Plan credits, enforced but not charged

- **Given** decision PD-3 — free capped beta, paid at GA
- **When** the credit system is configured
- **Then** a plan defines a **monthly credit grant** per household, and a per-`(tier, kind)` credit price (D2)
- **And** beta households get a generous default grant that is enforced — the number comes from real data (D5), not a guess
- **And** the balance, the grant, the renewal date and the **active tier** are visible to the user in the UI, not silently applied
- **And** the user can switch tier freely while they have credits, and is told when they have been forced to `ESSENTIAL`
- **And** grants and credit prices are configurable without a deploy (database, per D4)

### S07-5 · Cost visibility for the operator

- **Given** you need to set a price before GA
- **When** operator reporting exists
- **Then** a management command or admin view reports cost per household over a period, sorted by spend
- **And** it surfaces the p50, p90, and p99 cost per active household — the numbers a price must clear
- **And** it distinguishes cost by interaction kind, so you can see what receipt OCR costs relative to text chat
- **And** the report is documented in `docs/runbook.md`

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Observable assertions:

> **Audited 2026-08-14** against `main` after the E08 merge (`99f623d`). Ten of
> eleven assertions verified against named tests or files; each is annotated with
> what proves it. The eleventh is not a code gap.

- [x] Every LLM call site in the evidence table produces a `UsageRecord` — proven by a test that fails if a new unmetered call site is added
      — `test_no_unmetered_provider_call_site_exists` (`test_metering.py`).
- [x] A receipt-photo interaction produces correlated records for extraction and the agent run, joined by `UsageRecord.interaction`
      — `test_a_receipt_photo_correlates_extraction_and_chat`, plus
      `test_the_vision_retry_produces_a_second_extraction_record` for the third call.
- [x] The transcription fallback loop bills twice and records twice when the primary model rejects the audio
      — `test_the_transcription_fallback_bills_twice`.
- [x] An **abuse-ceiling** refusal makes zero model calls, asserted by test
      — `test_an_abuse_refusal_makes_zero_model_calls` (`test_views.py`), asserting
      429 and no row.
- [x] A household with **zero credits is degraded to `ESSENTIAL`, not refused** — asserted by test, and the response says which tier answered
      — `test_a_household_out_of_credits_is_degraded_not_refused` (decision) and
      `test_a_household_out_of_credits_still_gets_an_answer` (the notice reaches
      the user).
- [x] Only one function makes quota decisions — `grep` proves no second enforcement path, and `assistant/throttling.py` no longer exists
      — the only decision function is `quota.decide` (`quota.py:232`);
      `assistant/throttling.py` is deleted.
- [x] E01's interim throttle has been removed, not left in parallel; its rolling-window limits survive as the abuse ceiling inside the chokepoint
      — `test_the_ceiling_applies_even_on_the_free_tier`.
- [x] `AssistantUsageEvent` is gone and `UsageInteraction` holds its rows — row count before and after the migration is identical
      — `UsageInteraction` at `models.py:170`; the name survives only inside
      `test_usage_interaction_rename.py`, which asserts the row count across the
      migration.
- [ ] The operator report runs and shows p50/p90/p99 cost per household against real beta data
      — **NOT MET, and not a code gap.** `usage_report.py` exists, computes
      nearest-rank p50/p90/p99 and breaks cost down by kind. What does not exist
      is *real beta data*: the product has no external users yet, so the
      percentiles have only this household to describe. Same shape as E06's three
      open boxes. Tick it when the beta has run long enough to make a percentile
      mean something, which is also when the number is needed (to set a price
      before GA).
- [x] A user can see their credit balance, renewal date and active tier in the UI, and can switch tier
      — `test_usage_endpoint_reports_balance_and_tier`, `test_a_user_can_switch_tier`,
      and `test_balance_reports_grant_remaining_and_renewal` for the renewal date.
- [x] `docs/runbook.md` documents the price table, how to change grants and credit prices, how to run the cost report, **and the standing rule that "cheapest model" is always re-checked online (D3)**
      — `docs/runbook.md` § *Usage, credits and cost (E07)*.

**Carried into E09.** E08 measured that model scores swing 0.83–0.97 across
identical runs on the current seven-case set, so the cost baseline E07 provides
is only half of what a routing decision needs. Widening the dataset comes before
any "no regression beyond threshold" claim.

## Out of scope

- Charging money → **E15**
- **Choosing which model sits in ADVANCED or STANDARD → E09**, and it needs E08's score first (PD-4). E07 builds the tier *mechanism* and ships both pointing at today's model. `ESSENTIAL` is the one exception, and D2 explains why it is not a PD-4 swap.
- Product analytics → **E14**
- Rate limiting non-LLM endpoints — E01 covers login and uploads

**Inherited from E06 (2026-08-14):** the golden-signals dashboard is four tiles,
not five. *Assistant turns/day* and *LLM spend/day* could not be built from
Cloud Logging — a successful request emits no application log line, and turn
counts lived only in Postgres. This epic creates the tables that make those
tiles possible; adding them is in scope here (Task 10).

## Open questions

1. ~~**What are the beta allowances?**~~ **Reframed by D2 and still open as D5.** The unit is now a monthly *credit* grant, not a turn count. It cannot be derived from code — Task 9 of the plan queries `ChatMessage` and `UsageInteraction` for the real daily distribution and sets the grant generously above the observed p99. This is the one number the plan carries as an explicit placeholder.
2. ~~**Where does the price table live?**~~ **Resolved by D4: a database model**, admin-editable, seeded by a data migration, cached on the hot path. Chosen against this epic's original recommendation because D3's "always re-check pricing online" rule means prices get corrected out of band, and a correction must not need a deploy.
3. ~~**Per household or per member?**~~ **Resolved by D2: per household.** One shared credit pool is the billing unit and matches E04. The fairness concern the question raised is answered by the per-*user* abuse ceiling surviving inside the same chokepoint — one member cannot burn the household's credits *and* monopolise the ESSENTIAL floor.
4. ~~**Hard block or soft degrade?**~~ **Resolved by D2: degrade, via the tier cascade.** Out of credits forces `ESSENTIAL` rather than refusing. A hard 429 survives only as the *abuse* refusal, which is a different question and keeps R0's gate true. See D2's note on why this does not violate PD-4.

## Skill pipeline

1. ~~`superpowers:brainstorming`~~ — **done 2026-08-14**; results are D1–D5 above
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `/security-review` — quota bypass is an abuse vector; verify no path reaches a model without passing the chokepoint
8. `superpowers:verification-before-completion` — paste the real cost report as evidence
9. `superpowers:finishing-a-development-branch`
