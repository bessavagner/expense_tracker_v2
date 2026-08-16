---
id: E14
title: Product analytics
release: R3
status: done
depends_on: [E06, E11]
blocks: []
wedge_critical: false
---

# E14 · Product analytics

## Outcome

The four metrics that decide whether this product works — exposure, activation rate, time-to-value, and D7 retention — are measured on real beta users, so the GA decision is made on evidence rather than optimism.

## Why now

The industry standard for a new product is explicit: **define success metrics before launch day**, and the four that matter most are exposure rate, activation rate, time-to-value, and Day-7 retention. A beta that produces no measurements produces no decision.

Depends on E06 (the event pipeline and infrastructure) and E11 (which defines and emits the activation event). Analytics that measure an undefined activation event measure nothing.

This is also how the **beta → GA decision** in PD-3 gets made. Without it, GA is a date; with it, GA is a threshold.

## Evidence in the codebase

| What | Where |
|---|---|
| No analytics of any kind | no product-event instrumentation anywhere in `src/backend` |
| Operational telemetry arriving in E06 | Sentry + Logfire + structured logs |
| The activation event, defined and emitted in E11 | E11 S11-1 |
| Cost per household, available from E07 | `UsageRecord` |
| Behavioural data already implicitly present | `ChatMessage.created_at`, `Entry.created_at`, `ReceiptDraft.status` |
| Existing engagement signal, unused | `MemoryRule.last_used_at` — `assistant/models.py` |

**Much of what matters is already in the database.** Retention and engagement can be derived from existing timestamps without a third-party analytics vendor. Prefer that to sending user behaviour to another processor — it is cheaper, and it is one fewer sub-processor on E13's inventory.

## Stories

### S14-1 · Define the metrics precisely before measuring them

- **Given** vague metric definitions produce numbers nobody trusts
- **When** the four metrics are defined
- **Then** each has a written, unambiguous definition recorded in this repo: what counts as exposure, what counts as activated (from E11), how time-to-value is measured and from what moment, and what "retained on day 7" means precisely
- **And** edge cases are decided: does an invited household member count as a separate activation, does a user who returns on day 9 count for D7
- **And** the definitions are agreed before the code, so the numbers mean one thing

### S14-2 · Event instrumentation

- **Given** the funnel from arrival to activation
- **When** events are emitted
- **Then** the funnel is instrumented at each step: landing, signup started, signup completed, email verified, each onboarding step, first assistant message, first receipt photo, **activation**
- **And** each event carries household, user, and timestamp, with the same PII discipline as E06
- **And** step-level drop-off is derivable, since knowing *where* users fall out is the point
- **And** events are emitted from the server, not the client, so ad blockers and PWA quirks do not silently lose data

### S14-3 · Retention and engagement from existing data

- **Given** the timestamps already in the database
- **When** retention is computed
- **Then** D1, D7, and D30 retention are derivable per signup cohort
- **And** engagement is measured in terms that reflect the wedge: assistant turns per active household, receipts confirmed per week, and the ratio of AI-captured to manually-entered records
- **And** the computation is a documented, repeatable command rather than an ad-hoc query

> That last ratio is the most important number in the product. If users are typing entries manually rather than photographing receipts, the wedge is not landing and no amount of retention data will explain why.

### S14-4 · The operator dashboard

- **Given** these numbers must be looked at regularly, not computed once
- **When** the dashboard exists
- **Then** it shows the four metrics plus the funnel drop-off and the wedge-adoption ratio
- **And** it shows cost per household from E07 alongside engagement, so unit economics and value are visible together
- **And** it is documented in `docs/runbook.md`

### S14-5 · A feedback channel

- **Given** quantitative data tells you what happened and never why
- **When** a feedback path exists
- **Then** beta users can report a problem or a thought from inside the product with minimal friction
- **And** feedback is stored with enough context to be actionable, respecting the PII rules
- **And** a lightweight process exists for reading it — feedback nobody reads is worse than none, because it implies a promise

### S14-6 · The GA decision criteria

- **Given** PD-3 defers monetization to GA
- **When** criteria are set
- **Then** the thresholds that would justify moving from free beta to paid are written down **before** the data arrives: activation rate, D7 retention, and cost per household versus the intended price
- **And** the criteria include a stop condition — what result would mean the wedge is not working and the product needs rethinking rather than launching

> Writing thresholds after seeing the data is how every result becomes a good result. Write them first.

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Observable assertions:

- [x] All four metric definitions are written down and unambiguous — `docs/architecture/product-metrics.md`, and `core/tests/test_metrics_doc.py` fails if the funnel grows an event the document never explains
- [x] The full funnel is instrumented, with drop-off derivable per step — E11's six events plus `email_verified`, `receipt_photo` and `entry_created`; `core.metrics.funnel_counts`
- [x] Retention is computed per cohort by a repeatable, documented command — `manage.py retention_report`, documented in `docs/runbook.md`
- [x] The AI-captured versus manual-entry ratio is measured — `entry_created.metadata.source` at all four write paths, `core.metrics.wedge_ratio`
- [x] The dashboard shows metrics and cost per household side by side — `/metricas/`, staff-only
- [x] Beta users can submit feedback from inside the product — `core.Feedback`, a drawer item on every page
- [x] GA criteria — including a stop condition — are written down before beta data arrives — `docs/architecture/ga-criteria.md`
- [ ] **Real numbers from actual beta users are visible, not just an empty dashboard** — *waits on beta traffic, not on code.* Every surface above runs and reports today; what it reports is one household, because that is who has used it. This assertion cannot be satisfied by writing anything, which is the point the spec's own skill pipeline makes: *the evidence is real beta numbers, not a working dashboard.*

## Out of scope

- A third-party analytics vendor — prefer deriving from the database; adding a vendor means another sub-processor on E13's inventory and another PII surface
- Marketing attribution and acquisition-channel tracking → post-MVP
- A/B testing infrastructure — no traffic to test with
- Session recording or heatmaps — disproportionate for a financial product

## Open questions — answered 2026-08-16

Kept rather than deleted; the reasoning is worth more than the tidiness.

1. **Build on the database, or adopt a vendor?** → **Database-derived.** `ProductEvent` already existed from E11, "no vendor" is in Out of scope, and a vendor's pipeline cannot recompute history when a definition changes — which `product-metrics.md` guarantees will eventually happen. It also keeps one more sub-processor off E13's inventory.
2. **What are the GA thresholds?** → **Activation ≥ 25%, D7 rolling retention ≥ 15%, cost per household ≤ R$ 5,00/month** against a ~R$ 10/month intended price, with a stop condition on the AI:manual ratio below 1:1 after 30 days. Written in `docs/architecture/ga-criteria.md` before any beta data existed, deliberately in learning mode — and that file names the risk that follows from low thresholds, which the stop condition exists to catch.
3. **How is "exposure" measured** with no marketing site? → **Defined now, measured when E17 ships a landing page**, at the edge from Cloud Run request counts on the signup URL. It is explicitly *not* a `ProductEvent`: `ProductEvent.household` is non-null and a visitor who has not signed up has no household, so modelling pre-signup steps would mean nullable-household events and would break the scoping base class every other read depends on. Recorded as knowingly unmeasured rather than reported as zero.
4. **Does instrumentation need consent under LGPD?** → **Proceeds under legitimate interest**: first-party, server-side, household-scoped, and carrying no user content — the same PII discipline as `core.observability.scrub_event`. It is added to E13's processing inventory as a processing activity; E13 owns the privacy notice. `Feedback` *does* hold user-authored text on purpose and is inventoried separately.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1 and 2 shape both what is built and what "success" means
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion` — the evidence is real beta numbers, not a working dashboard
8. `superpowers:finishing-a-development-branch`
