---
id: E07
title: Usage metering & quota
release: R1
status: blocked
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

| What | Where |
|---|---|
| The chat entry point — every LLM path passes through here | `assistant/views.py:140` (`chat_view`) |
| Text turn path | `assistant/views.py:164-201` |
| Audio path — transcription then agent run | `assistant/views.py:204-232` |
| Image path — extraction, possible vision retry, then agent run | `assistant/views.py:274-362` |
| The expensive retry: a second extraction with the vision model | `assistant/views.py:327-330` |
| Embeddings — a separate, unmetered OpenAI call | `assistant/services/embedding.py:11-22` |
| Transcription — another unmetered call | `assistant/services/transcription.py` |
| Agent run wrapper where usage is available | `assistant/views.py:94-101` — `agent.run_stream(...)`, `stream.all_messages()` |
| Model configuration to attribute against | `config/settings.py:171-192` |

**Note the multi-call reality:** a single receipt photo can trigger extraction, a vision retry, and an agent run — three billable calls for one user action. Metering must capture all of them, attributed to one logical interaction, or the numbers will understate cost badly.

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
- **And** it consumes the E01 throttle logic rather than duplicating it — E01's crude limits are replaced by this, not layered on top
- **And** exceeding quota returns a clear pt-BR message explaining what was exhausted and when it resets
- **And** a test asserts that a quota-exceeded request produces zero model calls and zero cost

> E01 deliberately shipped a blunt per-user throttle with no dependencies. This story is where it becomes household-scoped and quota-aware. Removing E01's version is expected; leaving both is a bug.

### S07-4 · Plan allowances, enforced but not charged

- **Given** decision PD-3 — free capped beta, paid at GA
- **When** allowances are configured
- **Then** a plan defines monthly allowances (assistant turns, receipt extractions) per household
- **And** beta households get a generous default allowance that is enforced
- **And** the allowance and the current consumption are visible to the user in the UI, not silently applied
- **And** allowances are configurable without a deploy

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

- [ ] Every LLM call site in the evidence table produces a `UsageRecord` — proven by a test that fails if a new unmetered call site is added
- [ ] A receipt-photo interaction produces correlated records for extraction and the agent run
- [ ] A quota-exceeded request makes zero model calls, asserted by test
- [ ] Only one function makes quota decisions — `grep` proves no second enforcement path
- [ ] E01's interim throttle has been removed, not left in parallel
- [ ] The operator report runs and shows p50/p90/p99 cost per household against real beta data
- [ ] A user can see their remaining allowance in the UI
- [ ] `docs/runbook.md` documents the price table, how to change allowances, and how to run the cost report

## Out of scope

- Charging money → **E15**
- Choosing cheaper models → **E09**; this epic measures, E09 optimizes
- Product analytics → **E14**
- Rate limiting non-LLM endpoints — E01 covers login and uploads

## Open questions

1. **What are the beta allowances?** Derive from real data: the existing single user's `ChatMessage` history gives a realistic daily distribution. Set generously above the observed p99.
2. **Where does the price table live** — settings, database, or a config file? Database allows changes without deploy; settings is simpler. Recommendation: settings-based with an override, revisit at E15.
3. **Should quota be per household or per member?** Per household is the natural billing unit and matches E04. Confirm it does not create an unfair experience where one member exhausts the other's allowance.
4. **Is a hard block right, or a soft degrade** — e.g. falling back to a cheaper model at quota rather than refusing? Interacts with E09. A soft degrade is a better experience and a better story; decide the two together.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1 and 4 are product decisions that shape the UX
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `/security-review` — quota bypass is an abuse vector; verify no path reaches a model without passing the chokepoint
8. `superpowers:verification-before-completion` — paste the real cost report as evidence
9. `superpowers:finishing-a-development-branch`
