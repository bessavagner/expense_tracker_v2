---
id: E04
title: Household tenancy
release: R1
status: ready
depends_on: [E02]
blocks: [E05, E07]
wedge_critical: false
---

# E04 · Household tenancy

## Outcome

A ledger belongs to a **household**, not a person. Two people can see and edit the same finances. Every query in the system is scoped through one auditable code path, and no domain object can be read or written across a household boundary.

## Why now

Review finding **B5** and **ADR-001**. This is decision PD-2 in the backlog index.

Every domain model is `FK(user)` today, and `docs/deploy/production-roadmap.md:4` states the original premise explicitly: *"usuário único (`bessavagner`)"*. The product is family finance. Two people sharing a ledger is the story.

**This is the cheapest it will ever be.** Right now: no customer data, 818 tests that already assert cross-user isolation, and one developer. After launch: a data migration across 10 models on live financial records, with customers watching. The cost curve only goes up.

## Evidence in the codebase

### Models to re-tenant (10)

| App | Models |
|---|---|
| `finances` | `Entry`, `Income`, `Category`, `PaymentMethod`, `Budget`, `InstallmentPlan`, `SystemicExpense` |
| `assistant` | `ChatMessage`, `MemoryRule`, `MemoryEmbedding`, `ReceiptDraft` |

`PaymentMethodClosingDay` is scoped transitively via `PaymentMethod` — confirm it needs no direct tenant column.

### Existing unique constraints that must move to the household

| Constraint | Where |
|---|---|
| `unique_together = ("user", "name")` on `Budget` | `finances/models/budget.py:27` |
| `unique_together = ("user", "name")` on `Category` | `finances/models/category.py:44` |
| `UniqueConstraint(fields=["user", "name"])` on `PaymentMethod` | `finances/models/payment_method.py:38` |
| `unique_together = ("user", "trigger", "field")` on `MemoryRule` | `assistant/models.py` |

### Scoping call sites

| Surface | Where |
|---|---|
| DRF dashboard API — 10 endpoints, all filtering `user=request.user` | `finances/api/views.py` |
| HTMX views — 6 modules | `finances/views/{entries,cockpit,settings,consolidated,projection,importer}.py` |
| Agent tools — ~45 functions, all taking `user` as first parameter | `assistant/agents/tools.py` |
| Agent tool registrations passing `ctx.deps` | `assistant/agents/assistant.py:87-270` |
| Agent dependency type | `assistant/agents/assistant.py:69` — `deps_type=User` |
| Analytics | `assistant/agents/analytics.py:252, 261` |
| Memory | `assistant/agents/memory.py:14, 28` |
| Services | `finances/services/` — `category_stats`, `budget_stats`, `projection`, `daily_trend`, `whatif` |

**Two call sites look like leaks and are not** — verified 2026-08-11, do not
"fix" them into a bare household filter without reading them:
`views/cockpit.py:233` and `:469` do `PaymentMethod.objects.filter(pk=...)`
*unscoped*, but union it onto an already-scoped queryset purely to keep the
entry's or plan's current payment method selectable in the form. The pk comes
from an object that was itself scoped, so re-tenanting the scoped half is
sufficient. A test asserting the union cannot surface a foreign household's
payment method is cheap and worth having.

### Tests that become cross-household tests

These are the epic's safety net. Every one must be converted, not deleted:

```
finances/tests/test_entry_edit_modal.py:71          finances/tests/test_cockpit_income_views.py:39
finances/tests/test_cockpit_vencimentos.py:73       finances/tests/test_installment_preview.py:49
finances/tests/test_views_entries.py:96             finances/tests/test_settings_income_groups.py:73
finances/tests/test_installment_month.py:61         finances/tests/test_cockpit_parcelamentos_views.py:56
finances/tests/test_views_projection.py:56          finances/tests/test_projection_service.py:163
finances/tests/test_category.py:33                  finances/tests/test_api_dashboard.py
```

## Stories

### S04-1 · Household and Membership models

- **Given** a new `accounts` app
- **When** it is created
- **Then** `Household` exists, and `Membership(user, household, role)` links users to households
- **And** a user may belong to more than one household, with exactly one active at a time
- **And** roles are defined minimally — enough to distinguish who may remove members from who may only edit entries. Do not build a general permission system.
- **And** a data migration creates one `Household` per existing user and a corresponding `Membership`, so no existing data is orphaned
- **And** the migration is reversible, or the plan states explicitly why it cannot be

### S04-2 · Centralized scoping — the single auditable path

- **Given** the requirement that no epic after this one writes `filter(user=...)` on a domain model (global constraint 4)
- **When** scoping is implemented
- **Then** a `HouseholdScopedQuerySet` / manager exists and is the only supported way to scope a domain query
- **And** middleware resolves the active household once per request onto `request.household`
- **And** a view mixin provides household-scoped querysets to the HTMX and DRF layers
- **And** a lint rule, test, or CI check fails the build if a domain model is queried with a bare `filter(user=...)` outside the accounts app

> This story is the heart of the epic. Scoping repeated at ~200 call sites is 200 chances to leak. Scoping in one class is one thing to review and one thing to test exhaustively.

### S04-3 · Re-tenant the domain models

- **Given** the 10 models listed above
- **When** the tenant column changes
- **Then** each carries `household = FK(Household)` and, where provenance matters, `created_by = FK(User, null=True, on_delete=SET_NULL)`
- **And** every unique constraint listed above is re-scoped from `user` to `household`
- **And** the data migration back-fills `household` from the existing `user` via the Membership created in S04-1
- **And** `created_by` is back-filled from the previous `user` value, preserving history
- **And** the indexes added in E03 are re-created with `household` as the leading column

> `created_by` is not decoration. It delivers review finding M5 (no audit trail) as a side effect of work you are already doing, and E17 surfaces it in the UI.

### S04-4 · Re-scope every read and write path — **DONE** (phase 3, 2026-08-13)

- **Given** the call sites inventoried above
- **When** they are migrated to the household-scoped manager
- **Then** the DRF API, all six HTMX view modules, and all `finances/services/` functions scope by household
- **And** no domain query outside the accounts app references `user` for scoping

### S04-5 · Re-scope the agent — **DONE** (phase 3, 2026-08-13)

- **Given** `deps_type=User` at `assistant/agents/assistant.py:69`
- **When** the agent is re-scoped
- **Then** deps become a small structure carrying both the household (for data scope) and the acting user (for `created_by`)
- **And** every tool in `assistant/agents/tools.py` scopes by household
- **And** the scope still comes from `ctx.deps` and **never** from an LLM-supplied argument — this is the existing discipline and it must survive the refactor intact
- **And** a test asserts that a tool cannot be induced to read another household's data by any tool argument

### S04-6 · Convert isolation tests and prove the boundary

- **Given** the 12 test modules listed above
- **When** they are converted
- **Then** each asserts cross-**household** isolation (404 or equivalent), not merely cross-user
- **And** a systematic test asserts that **every** domain model rejects cross-household access — parameterized over the model list, so a model added later without scoping fails the suite
- **And** a test asserts that two users in the same household *do* see the same data, which is the new capability

## Definition of Done

```bash
# Everything green, gates hold
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run

# Migration round-trips against a COPY of production data, not an empty DB
# (see docs/runbook.md for taking a Supabase copy)

# No bare user-scoping left on domain models
grep -rnE '\.filter\([^)]*user=' src/backend/finances src/backend/assistant --include='*.py' | grep -v tests | grep -v accounts
```

Observable assertions:

- [ ] A parameterized test covers every domain model for cross-household rejection
- [ ] Two users in one household see identical ledger data
- [x] The agent cannot be argument-injected across households — *2026-08-13: `assistant/tests/test_agent_scope.py::test_a_tool_cannot_widen_its_scope_through_an_argument`. `deps_type` is a frozen `AgentScope(household, user)`; an LLM-supplied category name from another household fails to resolve and no entry is written.*
- [x] `created_by` is populated for all back-filled rows — *2026-08-13: `accounts/backfill.py` sets `created_by_id` from `user_id` wherever the model has the field. Note this covers **back-filled** rows only; phase 3's review found new rows written by `apply_income_recurrence` were losing it, fixed in `6d3c1e0`.*
- [x] The data migration has been run against a **copy of the real Supabase data**, and entry counts, balances, and the monthly acumulado match before and after — this project has a documented history of balance reconciliation issues; verify totals, not just row counts — *2026-08-12: 3 users, 2320 entries, sum 344529.48; fingerprint identical, no unfilled rows (`scripts/rehearse-e04-migration.sh`, runbook § "Rehearsing the E04 tenancy migration")*
- [ ] E03's indexes are re-created with `household` leading, and `EXPLAIN ANALYZE` confirms usage
- [~] `/security-review` passed with no cross-tenant finding — *2026-08-13: a full security review of the phase-3 branch found **no exploitable cross-tenant leak** (unscoped querysets, agent scope widening, write provenance, the cockpit pk union, the throttle's actor column, `dump_ledger_totals` reachability, middleware session tampering). Two LOW defense-in-depth items closed in `6d3c1e0`. Marked `~` not `x` because it was run as a review agent over `git diff main...HEAD`, not the literal `/security-review` command, which needs `origin/HEAD` — main is 28 commits ahead of origin. Re-run the command form after phase 4 drops the `user` columns.*

## Out of scope

- **Invitation UI and email flows → E05.** This epic creates the tenancy; E05 lets people join one.
- Household-level billing → **E15**
- Per-member permission granularity beyond the minimum roles — YAGNI
- Postgres Row-Level Security — parked (see INDEX §10)
- Changing what the domain models *mean*; this is a re-tenanting refactor, not a redesign

## Open questions — DECIDED 2026-08-11

All four are closed. They are **not** open for re-litigation inside the epic; the
same rule as the backlog's PD-1..PD-5 applies.

1. **Can a user belong to multiple households?** → **Yes in the schema, one
   active at a time in the UI.** `Membership` is a real join table and middleware
   resolves the active household onto `request.household`. Rationale: near-free
   now, needs a second migration over live financial records later.
2. **What roles at MVP?** → **`owner` and `member`, nothing else.** Owner invites
   and removes; both edit entries. No viewer role, no permission framework. If a
   read-only role is ever wanted, it is a new epic, not a widening of this one.
3. **Last owner deletes their account?** → **Promote the longest-standing
   remaining member to owner.** The household and its financial history survive
   for the people still in it; the household is deleted only when the last
   member leaves. Decided here, **implemented in E13** alongside the LGPD
   deletion flow — E04 only needs the schema to make the promotion expressible
   (`Membership.created_at` is the tiebreaker, so it must exist and be indexed).
4. **Does `PaymentMethodClosingDay` need its own household column?** →
   **No — transitive scoping via `PaymentMethod` is sufficient.** Verified at
   `08f4f15`: every read and write of it filters by a `PaymentMethod` *instance*
   that was itself fetched user-scoped (`views/cockpit.py:303`, `:341` — the
   latter 404s on a foreign pk), plus `services/billing.py:24` which traverses
   `payment_method.monthly_closing_days`. No call site reaches the model by bare
   pk. **This holds only while that pattern holds**, so S04-6's parameterized
   test must cover it through its parent rather than assume it.

## Risk notes for the executing agent

This is the largest and highest-risk epic in the backlog. Specifically:

- **A missed call site is a cross-tenant data leak**, not a bug. The parameterized test in S04-6 is what catches misses; write it early, not last.
- **Do not batch this into one commit.** Model + migration, then scoping infrastructure, then one surface at a time (API, then each view module, then agent), each with its tests green.
- **The data migration touches real financial records.** Rehearse against a copy. Compare balances, not row counts.
- If the plan produced from this epic exceeds a comfortable single execution, split it by surface — the story boundaries above are drawn to allow that.

## Skill pipeline

1. `superpowers:brainstorming` — **required**, unusually: open questions 1-3 are genuine design decisions that change the schema
2. `superpowers:writing-plans` — expect to split into multiple plans by surface
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `/security-review` — **mandatory**; the failure mode of this epic is a cross-tenant leak
8. `superpowers:verification-before-completion`
9. `superpowers:finishing-a-development-branch`
