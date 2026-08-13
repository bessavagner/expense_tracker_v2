---
id: E04
title: Household tenancy
release: R1
status: done
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

### S04-1 · Household and Membership models — **DONE** (phase 1, 2026-08-11)

- **Given** a new `accounts` app
- **When** it is created
- **Then** `Household` exists, and `Membership(user, household, role)` links users to households
- **And** a user may belong to more than one household, with exactly one active at a time
- **And** roles are defined minimally — enough to distinguish who may remove members from who may only edit entries. Do not build a general permission system.
- **And** a data migration creates one `Household` per existing user and a corresponding `Membership`, so no existing data is orphaned
- **And** the migration is reversible, or the plan states explicitly why it cannot be

### S04-2 · Centralized scoping — the single auditable path — **DONE** (phase 1, 2026-08-11)

- **Given** the requirement that no epic after this one writes `filter(user=...)` on a domain model (global constraint 4)
- **When** scoping is implemented
- **Then** a `HouseholdScopedQuerySet` / manager exists and is the only supported way to scope a domain query
- **And** middleware resolves the active household once per request onto `request.household`
- **And** a view mixin provides household-scoped querysets to the HTMX and DRF layers
- **And** a lint rule, test, or CI check fails the build if a domain model is queried with a bare `filter(user=...)` outside the accounts app

> This story is the heart of the epic. Scoping repeated at ~200 call sites is 200 chances to leak. Scoping in one class is one thing to review and one thing to test exhaustively.

### S04-3 · Re-tenant the domain models — **DONE** (phases 2 and 4, 2026-08-13)

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

### S04-6 · Convert isolation tests and prove the boundary — **DONE** (phase 4, 2026-08-13)

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

**All four green, 2026-08-13.** 1166 passed, 3 skipped, 0 failed — at the real
clock and again at `TEST_CLOCK_SHIFT=+1y`. Coverage 90% against a floor of 80.
Ruff, format, `makemigrations --check` and `manage.py check` all clean. The
migration rehearsal is the assertion two items below.

**The grep returns nothing — and that is not the whole story.** The one
legitimate `user=` filter left on a domain model is
`assistant/throttling.py:59-61`, where the rate limit counts per *person*: two
members of a household must not share one budget (E04 decision 1). This regex
never saw it, because its `.filter(` and its `user=` sit on separate lines:

```python
used = await AssistantUsageEvent.objects.filter(
    user=user, kind=kind, created_at__gte=now - rule.window
).acount()
```

So a grep returning zero lines is weaker evidence than it looks, and widening
the regex to catch it would only move the blind spot. The authoritative check is
`accounts/tests/test_scoping_ratchet.py`, whose pattern spans newlines and
therefore does see it: `ACTOR_SCOPED` names `assistant/throttling.py` as the
sole exemption, and `test_actor_scoped_files_still_scope_by_user` fails if that
file ever stops scoping by user. Both `BASELINE` and `E04_TRANSITION_TOOLS` are
gone from that module, and `test_bake_scoping.py`'s `BAKE_BASELINE` is `set()` —
no file is grandfathered anywhere.

Observable assertions:

- [x] A parameterized test covers every domain model for cross-household rejection — *2026-08-13: `accounts/tests/test_cross_household_isolation.py`, parameterized over `household_owned_models()` — `test_model_rejects_rows_from_another_household` and `test_model_with_no_household_returns_nothing_not_everything` (the fail-closed half: an unscoped manager returns nothing, not everything). Backed by `test_every_domain_model_is_household_owned`, which is what catches a model added later without scoping — the parameterized tests can only cover models the list already names. `PaymentMethodClosingDay` is covered through its parent by `test_closing_day_is_unreachable_from_a_foreign_payment_method`, per open question 4.*
- [x] Two users in one household see identical ledger data — *2026-08-13: `accounts/tests/test_shared_household.py` — `test_a_member_sees_the_other_members_entries` and `test_a_member_can_open_the_other_members_entry`, with `test_provenance_survives_the_sharing` asserting `created_by` still names the author and `test_a_stranger_still_gets_a_404` asserting the boundary did not widen.*
- [x] The agent cannot be argument-injected across households — *2026-08-13: `assistant/tests/test_agent_scope.py::test_a_tool_cannot_widen_its_scope_through_an_argument`. `deps_type` is a frozen `AgentScope(household, user)`; an LLM-supplied category name from another household fails to resolve and no entry is written.*
- [x] `created_by` is populated for all back-filled rows — *2026-08-13: `accounts/backfill.py` sets `created_by_id` from `user_id` wherever the model has the field. Note this covers **back-filled** rows only; phase 3's review found new rows written by `apply_income_recurrence` were losing it, fixed in `6d3c1e0`.*
- [x] The data migration has been run against a **copy of the real Supabase data**, and entry counts, balances, and the monthly acumulado match before and after — this project has a documented history of balance reconciliation issues; verify totals, not just row counts — *2026-08-12 (phase 2): 3 users, 2320 entries, sum 344529.48. **Re-run 2026-08-13 across the whole chain**, phases 2 and 4 together: 3 households, **2324 entries, sum 344718.86**, fingerprint identical, `unfilled rows: none`. 17 migrations applied in one pass — `accounts.0001`–`0003`, `assistant.0010`–`0016`, `finances.0013`–`0019` — which is exactly what the next deploy does. Phase 4 drops `user`, so the two sides can no longer share one observer: BEFORE is read by the pinned pre-E04 command and its username keys are normalised to `Casa de <username>`, the rule `accounts/migrations_helpers.py` used to seed them. Both empty households normalised as cleanly as the populated one, so the naming rule holds for every user and not only the busy one. (`scripts/rehearse-e04-migration.sh`, runbook § "Rehearsing the E04 tenancy migration")*
- [x] E03's indexes are re-created with `household` leading, and `EXPLAIN ANALYZE` confirms usage — *2026-08-13: `finances/tests/test_query_indexes.py` asserts the plan by name for each of the five composites at 5,000 rows (`EXPLAIN`, with `ANALYZE` run on the tables first so the planner is not working from defaults) — e.g. `test_entry_recent_ordering_uses_an_index` requires `entry_hh_date_recent_idx` and no `Seq Scan`. `finances/tests/test_household_indexes.py` pins their existence, the absence of the five user-leading originals, and the survival of `usage_user_kind_recent_idx`. Measured at product scale — 100,000 entries, 20 households — in `docs/architecture/query-performance-baseline.md` § "After E04 — household-leading". The rehearsal above re-checks all of it against the real schema after a real migration.*
- [x] `/security-review` passed with no cross-tenant finding — ***2026-08-13, phase 4, the command form: CLEAN. Zero findings at any severity.*** *Scope was `git diff origin/HEAD...`, which covers **all four E04 phases** plus other unpushed `main` work, not phase 4 alone — `origin/main` was 50 commits behind local `main`. That is a wider scope than the plan assumed and the right one for a tenancy epic, since phases 1-3 had never been through the command form either. Coverage recorded rather than just the verdict: unscoped querysets (residue is creates passing `household=` explicitly plus three single-pk unions whose pk comes off an already-scoped row); agent scope (all 33 tool bodies pass `ctx.deps`, none accepts a tenant argument, `AgentScope` is frozen); tampered `active_household_id` (honoured only via `memberships.filter(household_id=...)`, malformed values fall back rather than 500); `created_by` at every write site including the two `bulk_create` paths that bypass `save()`; `AssistantUsageEvent` inference (no view, endpoint, aggregate or error differential exposes another household's counts); raw SQL (no `RunSQL` in this branch's migrations; the `# noqa: S608` sites are ORM-generated SQL in test code with parameters still bound); and the new `resolve_active_household` fallback (its only creation path is a brand-new `Household` plus owner `Membership` — no branch or argument can select a pre-existing one). Also checked: DRF is session-auth-only with a global `IsAuthenticated`, so no token path bypasses the household middleware; middleware ordering is after `AuthenticationMiddleware`; `HX-Trigger` toast interpolation renders through Alpine `x-text`, not `x-html`.*
  <br>*The review also surfaced one **non-security** regression, recorded as follow-on below: `assistant/agents/assistant.py:337` passes `ctx.deps` where a household is expected. It fails closed — it raises on UUID validation rather than returning another household's rows — so it is not a tenancy defect.*
  <br>*Superseded phase-3 note, kept for history — 2026-08-13: a full security review of the phase-3 branch found **no exploitable cross-tenant leak** (unscoped querysets, agent scope widening, write provenance, the cockpit pk union, the throttle's actor column, `dump_ledger_totals` reachability, middleware session tampering). Two LOW defense-in-depth items closed in `6d3c1e0`. Marked `~` not `x` because it was run as a review agent over `git diff main...HEAD`, not the literal `/security-review` command, which needs `origin/HEAD` — main is 28 commits ahead of origin. Re-run the command form after phase 4 drops the `user` columns.*
  <br>**Still `~` as of 2026-08-13, phase 4.** The branch is now pushed
  (`origin/e04-phase4`) and `origin/HEAD` has been set to `origin/main`, so the
  command form runs. It has **not been run yet** — it is user-triggered and the
  session executing this plan cannot launch it. Note the diff base: `origin/main`
  is 50 commits behind local `main`, so `git diff origin/HEAD...` covers all four
  E04 phases plus other unpushed work, not phase 4 alone — a wider scope than the
  plan assumed, and the right one for a tenancy epic, since phases 1-3 have never
  been through the command form either. **Do not tick this without the result.**
  The independent code review recorded below found no cross-tenant defects, which
  is evidence but not this gate.*

## Code review — 2026-08-13

Full review of `git diff main...HEAD` (15 commits, 143 files, +4038/-2168),
pointed at the five places a diff this size hides something.

**No cross-tenant defects.** Every domain queryset in production code goes
through `for_household` / `for_request` / `HouseholdScopedMixin`; the unscoped
`.objects.filter(...)` hits are all keyed off an already-scoped object's pk or
FK, or are cross-household by design in an operator command. No write takes
`household` from user input. `AgentScope` is frozen and built only from
`request.household`. Every `update_or_create` in `agents/tools.py` and
`import_csv.py` carries `household=` in the **lookup**, not the defaults, so
none can reach across and mutate a neighbour's row.

Reviewed and clean, each verified rather than assumed:

- **The codemod's 612 rewrites.** 14 modules spot-checked against `git show`,
  plus two mechanical sweeps over the full 10,592-line test diff — every hunk
  that lost a second identity, and every removed `user=X` whose retained
  `household=Y` did not correspond under the fixture pairing. Three hits, all
  three deliberate. The dangerous shape — both sides of a comparison rewritten
  identically — does not occur. Two rewrites are net strengthenings.
- **The four uniqueness tests hand-fixed outside the codemod.** Each keeps both
  rows in one household, which is the property under test, and each
  `pytest.raises(IntegrityError)` subject is still covered by a live constraint.
  The negative twins raise at their *setup* line if the two households ever
  collapse, so they cannot silently degrade into tautologies.
- **`finances/0018_drop_user` and `assistant/0015_drop_user`.** Dependency graph
  traced rather than file order. Each drop is gated by its own app's
  `refuse_if_any_row_is_tenant_less`, whose `LABELS` cover exactly the models
  that app makes NOT NULL. The guard is a `RunPython` inside the same atomic
  migration as the `AlterField`s, so a raise leaves nothing applied. Uniqueness
  is never unenforced at any point in the chain — the household-scoped
  replacements are live from phase 2 before the old ones are removed.
- **`validate_unique()` → `validate_constraints()`.** Correct: `Budget` has
  exactly one `UniqueConstraint` and no `CheckConstraint`, so the `except`
  cannot mislabel an unrelated violation, and on edit the row is excluded from
  itself. Complete: those two were the only `validate_unique` call sites in
  `src/backend`.

### Findings and disposition

| Sev | Finding | Disposition |
|---|---|---|
| HIGH | A user with no `Membership` could not write anything — 500 on the NOT NULL | **Fixed**, `ff68d9d` |
| — | `/security-review`, command form, all four phases: **zero findings** | Gate green |
| — | `simulate_projection` passed a scope where a household was expected (non-security; fails closed) | **Fixed**, `3ebea6c` |
| MEDIUM | `transfer_entries` round-trip splits a shared household by author | **Follow-on**, below |
| LOW | Duplicate category / payment-method name is a 500 | **Follow-on**, below — pre-existing on `main` |

### Follow-on work, logged not fixed

1. **`transfer_entries` round-trip splits a shared household.** Export moved to
   `created_by` when `user` was dropped; the wire key is still `"user"` but now
   means *author*, while import still resolves the tenant from it
   (`transfer_entries.py:75` and `:125`). A household with two members exported
   and re-imported becomes two households, one per author. Under the old
   semantics `user` *was* the tenant, so the round-trip preserved tenancy
   exactly. Fixing it means adding a household key to the wire format and
   falling back to the author only for old files — a format decision, which is
   why it is not being made inside a gate task. Related: `created_by` is
   `SET_NULL`, so deleting a member makes their rows unexportable — `--user`
   omits them silently, a full export writes `"user": null` rows the importer
   then rejects.
2. **Duplicate category and payment-method names are a 500.** Three sibling
   views (`settings.py:321`, `:341`, `:390`) have no uniqueness guard and never
   had one. A ModelForm cannot supply it: `household` is not a form field, so it
   lands in `exclude` and `UniqueConstraint.validate` returns early. Same
   user-visible bug the budget views were just fixed for. Pre-existing on
   `main`, so not a phase-4 regression.
3. ~~**`simulate_projection` is wired to the wrong argument.**~~ **FIXED in `3ebea6c`**, with a tool-level test verified by reverting the fix and watching it fail.
   `assistant/agents/assistant.py:337` passes `ctx.deps` — an `AgentScope` — to
   `simulate_projection_summary`, whose first parameter became a *household* in
   this epic (`finances/services/whatif.py:92`). Found by the phase-4
   `/security-review` while tracing scope propagation. **Not a tenancy defect:
   it fails closed**, because `for_household` only short-circuits on `None`, so
   an `AgentScope` falls through to `filter(household=<AgentScope>)` and raises
   on UUID validation — no other household's rows can be returned. The
   user-visible effect is that the tool errors on every invocation and the chat
   returns the generic "Erro ao processar mensagem". Fix is
   `ctx.deps.household`. The reason nothing caught it is worth keeping: the
   existing `test_simulate_projection.py` calls the *service* directly with a
   household, so the tool-to-service wiring is untested. Every other
   `ctx.deps` pass-through was enumerated and targets a function that genuinely
   takes a scope.
4. **No operator-reachable way to add a second person to a household.** Only a
   hand-written `Membership` row. This is E05's job per Out of scope — the
   epic creates the tenancy, E05 lets people join one — but it is worth stating
   that the headline capability is not reachable by an operator until then.

## What phase 4 changed that the epic did not anticipate

Seven things, all found by executing rather than by planning. Recorded because
the next re-tenanting epic (E05, E13) will meet the same shapes.

0. **Deleting the transitional bridge and adding NOT NULL in one commit broke a
   user nobody was testing.** Neither change is wrong. Together they removed the
   only path that gave a membership-less user a household *and* made the absence
   fatal, so `createsuperuser` — which the runbook tells the operator to run
   right after deploying — produced a user who could read (empty) but not write
   (500). Fixed in `ff68d9d` by falling back to `household_for_user` in the
   middleware. **The suite could not have caught it**: the `household` fixture
   calls `household_for_user`, so every test user has a membership by
   construction. That is the general shape worth remembering — a fixture that
   guarantees a precondition makes the whole suite blind to its absence. When
   removing a transitional mechanism, ask what it was silently supplying, and to
   whom, before deleting it in the same commit that makes its output mandatory.

1. **The ratchet's own regex had a blind spot, and it hid a real leak.** The
   first version matched `\.get\(`, which does not match `.get_or_create(` —
   nor `.update_or_create(`. `seed_data.py` scoped its catalogue by user through
   phases 2 *and* 3 without the ratchet noticing. Fixed in Task 10. A ratchet is
   only as good as its pattern, and a passing ratchet is not evidence until you
   have tried to sneak something past it.

2. **Four write sites depended on the transitional bridge and were never
   inventoried.** The epic listed *read* call sites thoroughly and *write* sites
   not at all, because phases 2 and 3 had a `user` → `household` bridge quietly
   filling the column in. Deleting the bridge in Task 12 is what surfaced them.

3. **`transfer_entries`' export key moved to `created_by`.** It exported
   `e.user.username`; with `user` dropped, provenance is the only thing left that
   answers "who wrote this", so `--user` now filters on `created_by__username`.
   The export's JSON key is still `"user"` — the file format did not change, only
   where the value comes from.

4. **`validate_unique()` does not check `Meta.constraints`.** `BudgetCreateView`
   and `BudgetEditView` guarded duplicate names with it, and it only covers
   `unique_together` — the very thing Task 13 deleted when it re-scoped the
   constraint to the household. Both now call `validate_constraints()`
   (`finances/views/settings.py:513`, `:571`). Without that change a duplicate
   budget name is a 500 instead of a toast. Nothing in the epic predicted that
   *dropping* a constraint could break an *error* path.

5. **Four redundant FK indexes came back under a new name.** E03 deliberately
   removed Django's implicit per-FK index on `user_id` for `Entry`, `Income`,
   `ChatMessage` and `ReceiptDraft`; E04 phase 2 re-created all four under
   `household_id` simply by declaring an ordinary `ForeignKey`. The unit
   assertion could not see it — it runs at ~4,000 rows, where the planner does
   not care. Task 14's product-scale measurement did. Dropped again in
   `finances/0019` and `assistant/0016`, and now pinned by
   `test_household_indexes.py::test_no_standalone_index_on_household_id`. **A
   re-tenanting migration silently re-creates the indexes the previous
   performance epic removed.** Check for that by default next time.

6. **The site inventory was grep-derived, and grep was not enough.** The epic's
   inventory came from `grep "user="`. Widening it to `user *=` found ten
   attribute assignments (`views/settings.py` ×6, `views/entries.py` ×3,
   `views/cockpit.py` ×1); dict-literal defaults (`"user": self.user`) found five
   more in `import_csv.py`; and `cat.user_id` in
   `recompute_category_averages.py` was invisible to all of them. The suite is
   the inventory. A grep is a starting point for writing tests, not evidence that
   the work is complete — which is the same lesson as item 1, from the other end.

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
