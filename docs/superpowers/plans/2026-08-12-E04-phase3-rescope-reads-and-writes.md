# E04 Phase 3 — Re-scope Reads and Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert every read path in `finances` and `assistant` — 8 services, `forms.py`, six HTMX view modules, the DRF dashboard API, four management commands, and ~45 agent tools — from `filter(user=...)` to the household-scoped manager phase 1 built, so the ratchet baseline empties from 25 files to zero.

**Architecture:** The services layer is the lever. Nine of the twenty-five files are `finances/services/`, and the views and the DRF API mostly *call* those services rather than query directly — so changing a service's first parameter from `user` to `household` converts its callers transitively. Everything else follows one mechanical rewrite: `Model.objects.filter(user=X, ...)` becomes `Model.objects.for_household(household).filter(...)`, or `Model.objects.for_request(request).filter(...)` inside a view. The agent goes last and separately, because its scope must keep coming from `ctx.deps` and never from an LLM-supplied argument; `deps_type` grows from `User` to a frozen `AgentScope(household, user)` so a tool can scope by household *and* still record who wrote the row.

**Tech Stack:** Django 6, PostgreSQL 17 (pgvector image on `:5433` locally, Supabase in production), pytest + pytest-django + model_bakery, PydanticAI, DRF, ruff, uv.

## Global Constraints

From `docs/backlog/INDEX.md` §7, the E04 epic, and the user's standing preferences. Every task's requirements implicitly include this section.

- **TDD.** Test first, always. Red → green → refactor.
- **Worktrees.** This work happens in an isolated worktree, not on `main`. Base it on **local `HEAD`**, not `origin/main` — origin is 28 commits behind and has no E04 at all.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean.
- **pt-BR in the product UI, English in code, comments, and docs.**
- **No time-bomb tests.** Date-sensitive tests freeze the clock (`time_machine`). The suite runs under `TEST_CLOCK_SHIFT=+1y` in CI and must stay green.
- **One task, one commit.** The epic's own risk note: *"a missed call site is a cross-tenant data leak, not a bug."* Do not batch.
- **No AI attribution in commit messages.** No `Co-Authored-By`, no "Generated with", no mention of Claude/Anthropic.
- **The money boundary holds.** No arithmetic changes anywhere in this phase. Every service returns the same numbers for the same data; only *which rows it selects* changes.

### Decisions already made — do not re-litigate

1. **Writes keep setting `user=`.** `user` is still `NOT NULL` on all 13 models until phase 4. A converted write site sets `household=` **and** `user=` **and** `created_by=` where the model has it. Dropping `user=` from a create will raise `IntegrityError`. This phase converts **reads**; the ratchet's regex only matches `.filter(`/`.get(`/`.exclude(`, so writes keeping `user=` still let the baseline empty.
2. **`assistant/throttling.py` keeps `user=` forever.** `AssistantUsageEvent.user` is the *actor*, not the tenant — phase 2 decided this explicitly, and phase 4 does not drop `user` from that model. Rate limiting is per-person: two people in one household each get their own budget. It moves out of `BASELINE` into a new permanent `ACTOR_SCOPED` set in Task 1, not into `E04_TRANSITION_TOOLS` (which must rot shut).
3. **`dump_ledger_totals.py` stays in `E04_TRANSITION_TOOLS`.** Phase 4 re-points it.
4. **The four management commands are in scope** (decided 2026-08-12). They write real rows — `import_csv` writes thousands — so leaving them user-scoped is a genuine write-path leak the moment two households exist.
5. **The two `PaymentMethod.objects.filter(pk=...)` unions in `views/cockpit.py` are NOT leaks.** The epic verified this on 2026-08-11. They union an unscoped single-pk lookup onto an already-scoped queryset, purely to keep the entry's *current* payment method selectable in the form. The pk comes from an object that was itself scoped. Re-tenant the scoped half; add the cheap test the epic asks for; do **not** rewrite the union into a bare household filter.
6. **`3a → 3b` gate.** One branch, but Task 12 is a hard checkpoint: the whole Django surface converts and the suite goes green before a single line of the agent is touched.

### Corrections applied during execution (2026-08-12)

Found while running the plan. Each is already reflected in the task text above; they are collected here so a reviewer can see what changed and why.

1. **Tasks 2 and 3 are ordered backwards.** `build_projection` calls `monthly_diverse_total_median` and `monthly_diverse_total_ceiling` from `category_stats`, so Task 2 cannot go green until Task 3 has converted them. **Run Task 3 first.** The stats services are a clean leaf — they import nothing from `projection`. Commit contents and messages are unchanged; only the order swaps.

2. **`accounts/tests/` has no conftest**, so Task 1 Step 1's `test_resolution.py` cannot resolve a `user` fixture. Hence `user`/`other_user` move to the root conftest (Step 7).

3. **Task 3 Step 1's test code has two bugs.** `monthly_diverse_total_median(household, as_of=date(2026, 3, 1))` looks at the six months *before* `as_of`, so a March-2026 entry is outside the window and the test passes without proving anything — use `as_of=date(2026, 4, 1)`. And `daily_spend_trend` rows carry `median`/`p25`/`p75`, never `total`, so `row["total"]` raises `KeyError`.

4. **`recompute_category_averages.py` is a missed call site.** It calls `category_moving_averages(cat.user, …)` but never matched the ratchet's `.filter(user=` regex, so it appears in neither `BASELINE` nor the file table. Convert it in Task 3 to `cat.household` — a household's averages must be the same figure whoever wrote the rows.

5. **`SystemicExpenseForm.__init__` has a fourth line inside the `if user:` block** (`self.fields["payment_method"].required = False`) that the Task 5 snippet does not show. The guard was about scoping, not about whether a payment method is mandatory, so it becomes unconditional. A blind three-way replace of the `__init__` body leaves it orphaned at the old indent and `forms.py` stops parsing.

6. **The rehearsal cannot verify this phase, and Task 2 Step 5 is why.** Pointing `dump_ledger_totals` at `build_projection(household, …)` makes the command require a `household` column — but `scripts/rehearse-e04-migration.sh` with `REWIND=1` deliberately rolls the schema back to pre-E04 before taking its BEFORE fingerprint, so it dies on `column finances_income.household_id does not exist`. That script validates the **phase-2 migration**; phase 3 adds no migration, so it is not the question this phase asks anyway.

   Two fixes, both applied: the rehearsal now pins its fingerprint command to `FINGERPRINT_REF` (default `de143a1`) so the schema varies while the observer stays constant; and **`scripts/verify-e04-phase3-money.sh` is the money check for this phase** — same fully-migrated ledger, pre-phase-3 code vs `HEAD`, diff the fingerprint. Substitute it at Task 2 Step 7, Task 12 Step 5 and Task 16 Step 6:

   ```bash
   POSTGRES_PORT=5433 scripts/verify-e04-phase3-money.sh
   ```

   Expected: `OK — counts, sums and acumulado identical across the re-scoping.` A non-empty diff is a conversion bug, not a migration bug. Both scripts are documented in `docs/runbook.md`.

   Note the semantic drift this introduces: `dump_ledger_totals` still keys its report by username, but its acumulado is now the *household's*. Invisible on a single-household ledger; phase 4 re-points the command and should resolve it.

### The conversion pattern — read this before Task 2

Three shapes cover ~95% of the 25 files.

**Shape A — a service or helper that took `user`:**

```python
# BEFORE
def budget_spend_for_month(user, billing_month: date) -> list[dict]:
    for b in Budget.objects.filter(user=user).prefetch_related("categories"):

# AFTER
def budget_spend_for_month(household, billing_month: date) -> list[dict]:
    for b in Budget.objects.for_household(household).prefetch_related("categories"):
```

The parameter is *renamed*, not added. Every caller changes in the same commit. `for_household(None)` returns `none()`, never the full table — that is phase 1's fail-closed guarantee and the reason this rewrite is safe.

**Shape B — a view with a request in hand:**

```python
# BEFORE
income = Income.objects.filter(user=request.user, pk=pk).first()

# AFTER
income = Income.objects.for_request(request).filter(pk=pk).first()
```

`for_request` reads `request.household`, which `accounts.middleware.active_household_middleware` sets on every request (it is installed at `config/settings.py:66`, right after `AuthenticationMiddleware`). It uses `getattr`, so a bare `RequestFactory` request fails closed rather than raising.

**Shape C — a class-based view with `get_queryset`:**

```python
# BEFORE
class EntryListView(HtmxLoginRequiredMixin, ListView):
    model = Entry
    def get_queryset(self):
        return Entry.objects.filter(user=self.request.user, ...)

# AFTER
from accounts.mixins import HouseholdScopedMixin

class EntryListView(HouseholdScopedMixin, HtmxLoginRequiredMixin, ListView):
    model = Entry
    def get_queryset(self):
        return super().get_queryset().filter(...)
```

`HouseholdScopedMixin` (`accounts/mixins.py`) must come **first** in the MRO so its `get_queryset` wraps the generic one. It raises `TypeError` if the model is not household-scoped — a deliberate loud failure, not a silent unscoped queryset.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# One module while iterating
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_entries.py -q

# The ratchet, after every task
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q

# Gates
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

**Do not run two pytest invocations concurrently** — they share `test_expense_tracker` and the second fails with `database ... is being accessed by other users`.

**Before Task 1, record the baseline:**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -3
```

Expected today: `1060 passed, 2 skipped`. Every task below expects that number, plus its own new tests, and **zero failures**. This plan adds no migration — if `makemigrations --check` ever reports a change, you have edited a model, which is out of scope.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/backend/accounts/resolution.py` | `household_for_user(user)` — the one permanent answer to "which household does this person write into", outside the bridge that phase 4 deletes | create |
| `src/backend/accounts/bridge.py` | delegate to `resolution.household_for_user`, keep the memoisation | modify |
| `src/backend/accounts/tests/test_resolution.py` | the resolution rule | create |
| `src/backend/accounts/tests/test_scoping_ratchet.py` | strike entries as they convert; add the `ACTOR_SCOPED` set | modify (every task) |
| `src/backend/conftest.py` | the one home for `user`, `other_user`, `household`, `other_household` and `logged_client` | modify |
| `src/backend/finances/tests/conftest.py` | strip the duplicates; leave a "do not shadow `logged_client`" note | modify |
| `src/backend/assistant/tests/conftest.py` | same, keeping `seeded_user` | modify |
| nine test modules with a local `logged_client` | delete the shadowing fixture (Task 1 Step 7b) | modify |
| `src/backend/finances/services/projection.py` | `build_projection(household, ...)` | modify |
| `src/backend/finances/services/whatif.py` | `simulate_projection_summary(household, ...)` | modify |
| `src/backend/finances/services/category_stats.py` | four functions take `household` | modify |
| `src/backend/finances/services/budget_stats.py` | four functions take `household` | modify |
| `src/backend/finances/services/daily_trend.py` | `daily_spend_trend(household, ...)` | modify |
| `src/backend/finances/services/systemic_month.py` | `systemic_rows_for_month(household, ...)` | modify |
| `src/backend/finances/services/installment_month.py` | `installment_rows_for_month(household, ...)` | modify |
| `src/backend/finances/services/income_recurrence.py` | scope from `income.household` | modify |
| `src/backend/finances/services/systemic_recurrence.py` | scope from `template.household` | modify |
| `src/backend/finances/forms.py` | `household=` kwarg; `save_for_household(household, created_by)` | modify |
| `src/backend/finances/views/{entries,cockpit,settings,consolidated,projection,importer}.py` | six HTMX modules | modify |
| `src/backend/finances/api/views.py` | 10 DRF endpoints | modify |
| `src/backend/finances/management/commands/{import_csv,seed_qa_data,transfer_entries}.py` | resolve household from the CLI username | modify |
| `src/backend/assistant/management/commands/seed_category_rules.py` | same | modify |
| `src/backend/assistant/agents/scope.py` | `AgentScope` frozen dataclass | create |
| `src/backend/assistant/agents/{tools,memory,analytics,assistant}.py` | the agent | modify |
| `src/backend/assistant/views.py` | build `AgentScope`, scope chat history | modify |
| `src/backend/assistant/tests/test_agent_scope.py` | the argument-injection assertion (DoD item) | create |
| `src/backend/finances/tests/test_cockpit_pm_union.py` | decision 5's cheap test | create |

**Out of scope, do not touch:** every `models.py`, every `migrations/` directory, `accounts/middleware.py`, `accounts/scoping.py`, `accounts/mixins.py`, `assistant/throttling.py` (beyond the ratchet move), `finances/management/commands/dump_ledger_totals.py`. Phase 4 owns the `NOT NULL` migration, dropping `user`, deleting `bridge.py`, and converting the 12 isolation test modules.

---

### Task 1: Household resolution, test fixtures, and the ratchet's permanent exemption

The riskiest thing in this phase is invisible: **the `user` fixture creates a user with no `Membership`**, so `request.household` resolves to `None` and every converted view returns `.none()`. Today that is harmless because nothing reads by household. From Task 6 onward it would silently empty ~1000 tests' assertions into "passed, because empty". Fix the fixtures before converting anything.

It hides in **two** places, and the second is the one that bites: the fixtures themselves (Step 7) *and* the nine test modules that shadow `logged_client` with a copy that omits the household (Step 7b). Fixing only the conftests leaves ~80 view tests — the entire evidence base for Tasks 6-10 — asserting nothing.

**Files:**
- Create: `src/backend/accounts/resolution.py`
- Modify: `src/backend/accounts/bridge.py:47-54`
- Create: `src/backend/accounts/tests/test_resolution.py`
- Modify: `src/backend/conftest.py` — all five shared fixtures land here
- Modify: `src/backend/finances/tests/conftest.py`, `src/backend/assistant/tests/conftest.py`
- Modify: the nine modules listed in Step 7b
- Modify: `src/backend/accounts/tests/test_scoping_ratchet.py`

**Interfaces:**
- Consumes: `accounts.models.Household`, `accounts.models.Membership`, `accounts.migrations_helpers.seed_household_for_user`.
- Produces:
  - `accounts.resolution.household_for_user(user) -> Household | None` — the household a person writes into. `None` for `None`; otherwise their oldest membership's household, creating one if they have none.
  - pytest fixtures `household` and `other_household`, both `Household` instances, tied to the `user` / `other_user` fixtures.
  - `accounts.tests.test_scoping_ratchet.ACTOR_SCOPED` — files that scope by `user` because `user` is the actor, permanently.

- [x] **Step 1: Write the failing test for resolution**

`src/backend/accounts/tests/test_resolution.py`:

```python
"""Which household does a person write into, when there is no request?

The middleware answers that for a request (honouring the session-selected
household). Management commands, the back-fill and the phase-3 write bridge
have no request, so they need this. Keeping the rule here rather than in
`bridge.py` means phase 4 can delete the bridge without deleting the rule.
"""

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from accounts.resolution import household_for_user

pytestmark = pytest.mark.django_db


def test_none_user_has_no_household():
    assert household_for_user(None) is None


def test_returns_the_existing_membership_household(user):
    household = baker.make(Household, name="Casa de vagner")
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    assert household_for_user(user) == household


def test_creates_a_household_when_the_user_has_none(user):
    """Fail closed: a person with no membership writes into their own new
    ledger. Borrowing an existing household would be the leak."""
    resolved = household_for_user(user)

    assert resolved is not None
    assert Membership.objects.filter(user=user, household=resolved).exists()


def test_is_idempotent(user):
    assert household_for_user(user) == household_for_user(user)
```

- [x] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_resolution.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.resolution'`

- [x] **Step 3: Write the implementation**

`src/backend/accounts/resolution.py`:

```python
"""Which household a person writes into, absent a request.

`accounts.middleware.resolve_active_household` is the *request* answer and
honours the session-selected household. This is the no-request answer: the
oldest membership, which is deterministic because `Membership` orders by
`created_at`. For a multi-household user the two can disagree — a request-
serving path must therefore use the middleware's answer, never this one.
"""

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership


def household_for_user(user):
    """The household ``user`` writes into, creating one if they have none."""
    if user is None:
        return None
    membership = Membership.objects.select_related("household").filter(user=user).first()
    if membership is not None:
        return membership.household
    return seed_household_for_user(Household, Membership, user)
```

Then in `src/backend/accounts/bridge.py`, replace the body of `household_for_writer`'s lookup with a delegation, keeping the memoisation and the docstring:

```python
from accounts.resolution import household_for_user

# ... inside household_for_writer, replacing the membership lookup:
    household = household_for_user(user)
    setattr(user, _CACHE_ATTR, household)
    return household
```

Delete the now-unused `Household`, `Membership` and `seed_household_for_user` imports from `bridge.py` if nothing else uses them. Keep the `select_related` note in the docstring — `household_for_user` does the `select_related`, so the performance claim still holds.

- [x] **Step 4: Run the resolution and bridge tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q`
Expected: PASS, including the existing `test_bridge.py` unchanged.

- [x] **Step 5: Write the failing fixture test**

Add to `src/backend/accounts/tests/test_resolution.py`:

```python
def test_user_fixture_has_a_household(user, household):
    """From phase 3 on, every fixture user must resolve to a household —
    otherwise `for_request` returns none() and a view test passes vacuously."""
    assert household_for_user(user) == household


def test_other_user_is_a_different_household(household, other_household):
    assert household != other_household
```

- [x] **Step 6: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_resolution.py -q`
Expected: FAIL — `fixture 'household' not found`

- [x] **Step 7: Add the fixtures**

Everything goes in the **root** `src/backend/conftest.py`, appended after `shifted_clock` — `user` and `other_user` move here too, because `accounts/tests/` has no conftest of its own and Step 1's `test_resolution.py` cannot otherwise resolve a `user`. Delete the now-duplicate definitions from `finances/tests/conftest.py` and `assistant/tests/conftest.py`; they were byte-identical.

```python
@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    """A second tenant, for asserting that a query stays scoped to one owner."""
    return baker.make("core.CustomUser", username="amanda")


@pytest.fixture
def household(user):
    """The household the `user` fixture writes into.

    Requested eagerly by anything that exercises a household-scoped read: the
    middleware resolves `request.household` from a Membership, and a user
    without one makes every scoped queryset return none().
    """
    from accounts.resolution import household_for_user

    return household_for_user(user)


@pytest.fixture
def other_household(other_user):
    """A second tenant, for asserting a query stays inside one household."""
    from accounts.resolution import household_for_user

    return household_for_user(other_user)
```

The `accounts` imports are function-local on purpose: the root `conftest.py` is imported before Django's app registry is populated, and a module-level `accounts` import raises `AppRegistryNotReady`. `model_bakery` at module level is fine.

Fixture resolution is per-test-node, not lexical, so a `household` defined in the root conftest still resolves `user` from whichever conftest is nearest the test. That is what makes one definition work everywhere.

Leave `user` and `other_user` *behaviourally* alone — they must not seed a household themselves. A test that only needs a user should not pay for one, and requesting `household` explicitly is what makes the dependency visible.

- [x] **Step 7b: Delete every shadowing `logged_client` — the trap Step 7 alone does not close**

**This is the step that decides whether Tasks 6-10 mean anything.** Nine test modules define their own `logged_client`, each byte-identical to the conftest one and each **missing the `household` dependency**:

```bash
grep -rn "def logged_client" src/backend/
```

```
src/backend/finances/tests/test_views_projection.py
src/backend/finances/tests/test_csrf_htmx.py
src/backend/finances/tests/test_systemic_settings_edit.py
src/backend/finances/tests/test_entries_pre_origin.py
src/backend/finances/tests/test_entries_live_summary.py
src/backend/core/tests/test_request_body_limit.py
src/backend/finances/tests/test_views_consolidated.py
src/backend/finances/tests/test_views_settings.py
src/backend/finances/tests/test_views_entries.py
```

A local fixture wins over a conftest one. So patching only the two conftests leaves ~80 view tests logging in as a user with **no Membership** — `request.household` is `None`, every converted queryset returns `.none()`, and `assert "Compra do vizinho" not in body` passes because the page is *empty*. Task 1's own rationale ("passed, because empty") applies verbatim here, and the two-conftest fix does not reach it.

Delete all nine. Put the single definition in the root `conftest.py` beside the others — **not** in the app conftests, because `core/tests/` has none and would lose the fixture:

```python
@pytest.fixture
def logged_client(user, household):
    """A logged-in client whose user resolves to a household.

    `household` is requested for its side effect, and that is the whole point:
    the middleware reads `request.household` from a Membership, and a user
    without one makes every scoped queryset return none() — which would turn
    "the neighbour's row is absent" into a test that passes because *everything*
    is absent. Nine test modules used to shadow this with their own copy that
    omitted the dependency; keeping one definition here is what stops that
    coming back.
    """
    from django.test import Client

    client = Client()
    client.force_login(user)
    return client
```

Leave a comment in both app conftests saying not to shadow it. Then `uv run ruff check --fix src/backend/` to drop the `django.test.Client` imports the deletions orphan.

> Verify the fix bites rather than trusting it: after Task 6, `test_entry_list_excludes_other_households` must **fail** if you stub `household` out of `logged_client`. A test that passes either way is testing nothing.

- [x] **Step 8: Run the full suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: `1067 passed, 2 skipped` (1060 + 6 resolution tests + 1 ratchet test). Zero failures — nothing reads by household yet, so this step only proves the fixtures do not break anything.

- [x] **Step 9: Add `ACTOR_SCOPED` to the ratchet**

In `src/backend/accounts/tests/test_scoping_ratchet.py`, add the set after `E04_TRANSITION_TOOLS`, remove `assistant/throttling.py` from `BASELINE`, and add one test:

```python
# Files where `user` is the ACTOR, not the tenant — permanently exempt.
# `AssistantUsageEvent.user` is who spent the turn: rate limiting is
# per-person, so two people in one household each get their own budget.
# Phase 2 decided this and phase 4 does not drop `user` from that model.
# This set is permanent; E04_TRANSITION_TOOLS is not.
ACTOR_SCOPED = {
    "src/backend/assistant/throttling.py",
}
```

Update both existing assertions to subtract it:

```python
def test_no_new_file_scopes_a_domain_query_by_user():
    regressions = sorted(
        _files_scoping_by_user() - BASELINE - E04_TRANSITION_TOOLS - ACTOR_SCOPED
    )
```

and add:

```python
def test_actor_scoped_files_still_scope_by_user():
    """If one of these stops scoping by user, the actor/tenant distinction has
    been erased somewhere — check it was deliberate before deleting the entry."""
    stale = sorted(ACTOR_SCOPED - _files_scoping_by_user())
    assert not stale, f"No longer scope by user — remove from ACTOR_SCOPED: {stale}"
```

- [x] **Step 10: Run the ratchet**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`
Expected: 4 passed. `BASELINE` is now 24 entries.

- [x] **Step 11: Commit**

```bash
git add src/backend/accounts src/backend/conftest.py src/backend/finances/tests/conftest.py src/backend/assistant/tests/conftest.py
git commit -m "feat(accounts): one permanent answer for a writer's household, and fixtures that have one"
```

---

### Task 2: The projection keystone — `build_projection` and `whatif`

`build_projection` is called by `views/entries.py`, `views/projection.py`, `api/views.py`, `whatif.py` and `dump_ledger_totals.py`. Convert it first: everything downstream then *has* to be converted, so a missed call site is an immediate `TypeError`, not a silent leak.

`dump_ledger_totals.py` is the one caller that must keep passing a user's rows — it is the migration fingerprint. It stays in `E04_TRANSITION_TOOLS`, and Step 5 shows how it calls the converted service.

**Files:**
- Modify: `src/backend/finances/services/projection.py`
- Modify: `src/backend/finances/services/whatif.py:92-98`
- Modify: `src/backend/finances/management/commands/dump_ledger_totals.py:53-60`
- Modify: `src/backend/finances/tests/test_projection_service.py`
- Test: `src/backend/finances/tests/test_projection_service.py`

**Interfaces:**
- Consumes: `Household` from Task 1's fixtures.
- Produces:
  - `build_projection(household, start_month: date, num_months: int, today=None, overlay=None, diverse_estimator="median") -> list[dict]` — first parameter renamed from `user`; return shape unchanged.
  - `simulate_projection_summary(household, items, start, months, today=None)` — first parameter renamed.
  - `projection_origin()` — unchanged, takes no scope.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_projection_service.py`:

```python
def test_projection_is_scoped_to_the_household(user, household, other_user, other_household):
    """The neighbour's ledger must not appear in this household's projection."""
    baker.make(
        "finances.Entry",
        user=other_user,
        household=other_household,
        amount=Decimal("999.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )
    baker.make(
        "finances.Entry",
        user=user,
        household=household,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    rows = build_projection(household, date(2026, 3, 1), 1, today=date(2026, 3, 15))

    assert rows[0]["total"] == Decimal("10.00")


def test_projection_of_no_household_is_empty_not_everything(user, household):
    """Fail closed. An unresolved tenant must never mean 'the whole table'."""
    baker.make(
        "finances.Entry",
        user=user,
        household=household,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    rows = build_projection(None, date(2026, 3, 1), 1, today=date(2026, 3, 15))

    assert rows[0]["total"] == Decimal("0")
```

- [x] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_projection_service.py -q`
Expected: FAIL — the first test sees `1009.00`, because `build_projection` still filters by `user` and is being handed a `Household`.

- [x] **Step 3: Convert the service**

In `src/backend/finances/services/projection.py`, rename the parameter and every internal query. The mechanical rule: `Entry.objects.filter(user=user, ...)` → `Entry.objects.for_household(household).filter(...)`, same for `Income` and `SystemicExpense`. Update the docstring's first line to say *household*. Do not change any arithmetic, any `Decimal` quantisation, or the past/future split on `today`.

Then `src/backend/finances/services/whatif.py`:

```python
def simulate_projection_summary(household, items, start, months, today=None):
    ...
    base = build_projection(household, start, months, today=today)
    ...
    sim = build_projection(household, start, months, today=today, overlay=overlay)
```

- [x] **Step 4: Run the projection tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_projection_service.py src/backend/finances/tests/test_whatif.py -q`
Expected: PASS. Existing tests that call `build_projection(user, ...)` will fail here — convert them to pass `household`. That is expected work, not a regression.

- [x] **Step 5: Fix the fingerprint command**

`dump_ledger_totals` must keep fingerprinting **per user**, or its before/after comparison compares two different questions. It now resolves each user's household and passes that:

`src/backend/finances/management/commands/dump_ledger_totals.py`, inside the loop:

```python
            household = household_for_user(user)
            months = build_projection(household, start, num_months, today=FIXED_TODAY)
```

with `from accounts.resolution import household_for_user` at the top. The per-user `Entry`/`Income` aggregates above it stay `filter(user=user)` — that is exactly why the file is in `E04_TRANSITION_TOOLS`.

- [x] **Step 6: Run the whole finances suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/ -q`
Expected: failures **only** in modules that call `build_projection` directly and still pass a user — `test_views_entries.py`, `test_views_projection.py`, `test_api_dashboard.py`. Leave those; Tasks 6, 9 and 10 own them. Note which ones fail and move on.

> If a module fails for any *other* reason, stop. A changed number means the arithmetic moved, which this phase forbids.

- [x] **Step 7: Verify the fingerprint is unchanged**

This is the money boundary. Run the credential-free rehearsal against the local ledger:

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres PGSSLMODE=prefer \
SOURCE_DB=expense_tracker REWIND=1 scripts/rehearse-e04-migration.sh
```

Expected: `OK — counts, sums and acumulado identical across the migration.` A changed `acumulado` here means the household scoping selects different rows than the user scoping did — which for a single-household ledger means a bug in this task, not in the migration.

- [x] **Step 8: Commit**

```bash
git add src/backend/finances/services/projection.py src/backend/finances/services/whatif.py \
  src/backend/finances/management/commands/dump_ledger_totals.py src/backend/finances/tests
git commit -m "refactor(finances): the projection is a household's, not a person's"
```

---

### Task 3: The statistics services

`category_stats`, `budget_stats` and `daily_trend` feed the dashboard API and the settings page. Same rename, no arithmetic change.

**Files:**
- Modify: `src/backend/finances/services/category_stats.py`
- Modify: `src/backend/finances/services/budget_stats.py`
- Modify: `src/backend/finances/services/daily_trend.py`
- Test: `src/backend/finances/tests/test_category_stats.py`, `test_budget_stats.py`, `test_daily_trend.py`, `test_diverse_savings.py`

**Interfaces:**
- Consumes: nothing new.
- Produces, all with the first parameter renamed `user` → `household` and return shapes unchanged:
  - `monthly_diverse_total_median(household, window=6, as_of=None) -> Decimal`
  - `diverse_savings_for_month(household, billing_month, window=6) -> dict`
  - `monthly_diverse_total_ceiling(household) -> Decimal`
  - `category_moving_averages(household, window=3, as_of=None, entry_type=None) -> dict`
  - `category_moving_averages_named(household, window=3, as_of=None, entry_type=None) -> list`
  - `budget_spend_for_month(household, billing_month) -> list[dict]`
  - `orphan_category_spend_for_month(household, billing_month) -> list[dict]`
  - `total_diverse_ceiling(household) -> Decimal`
  - `daily_spend_trend(household, period=30, as_of=None) -> list[dict]`

  `_status(spent, cap)`, `_percentile(values, q)`, `_window_months(as_of, window)`, `_median(values)` and `seed_amount_from_ceilings(budget)` take no scope and do not change.

- [x] **Step 1: Write the failing isolation test**

Create `src/backend/finances/tests/test_stats_scoping.py`:

```python
"""One isolation assertion per statistics service.

Cheaper than converting each service's own test module to two tenants, and it
is the assertion that actually matters: a neighbour's spend must never reach
this household's dashboard.
"""

from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.budget_stats import total_diverse_ceiling
from finances.services.category_stats import monthly_diverse_total_median
from finances.services.daily_trend import daily_spend_trend

pytestmark = pytest.mark.django_db


@pytest.fixture
def neighbour_spend(other_user, other_household):
    category = baker.make(
        "finances.Category", user=other_user, household=other_household, name="Vizinho"
    )
    baker.make(
        "finances.Entry",
        user=other_user,
        household=other_household,
        category=category,
        amount=Decimal("999.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )
    return category


def test_diverse_median_excludes_other_households(household, neighbour_spend):
    assert monthly_diverse_total_median(household, as_of=date(2026, 3, 1)) == Decimal("0")


def test_daily_trend_excludes_other_households(household, neighbour_spend):
    rows = daily_spend_trend(household, period=30, as_of=date(2026, 3, 15))

    assert all(row["total"] == Decimal("0") for row in rows)


def test_ceiling_excludes_other_households(household, other_user, other_household):
    baker.make(
        "finances.Category",
        user=other_user,
        household=other_household,
        name="Teto do vizinho",
        budget_ceiling=Decimal("500.00"),
    )

    assert total_diverse_ceiling(household) == Decimal("0")
```

- [x] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_stats_scoping.py -q`
Expected: FAIL — the services filter by `user` and receive a `Household`, so Django raises `ValueError: Cannot query "Casa de vagner": Must be "CustomUser" instance.`

- [x] **Step 3: Convert the three services**

Rename the first parameter and rewrite every query with `for_household(household)`. In `category_stats.py`, note that `monthly_diverse_total_ceiling` delegates to `budget_stats.total_diverse_ceiling` — pass the household straight through. In `budget_stats.py`, `_spend_by_category(household, billing_month)` is private and renames too.

- [x] **Step 4: Run the stats tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_stats_scoping.py src/backend/finances/tests/test_category_stats.py src/backend/finances/tests/test_budget_stats.py src/backend/finances/tests/test_daily_trend.py src/backend/finances/tests/test_diverse_savings.py -q`
Expected: PASS, after converting the existing modules' call sites to pass `household`.

- [x] **Step 5: Commit**

```bash
git add src/backend/finances/services src/backend/finances/tests
git commit -m "refactor(finances): category, budget and trend statistics scope by household"
```

---

### Task 4: The month and recurrence services

`systemic_month` and `installment_month` build the cockpit's rows. `income_recurrence` and `systemic_recurrence` derive their scope from an object they are handed, so they change shape slightly differently: `income.user` → `income.household`.

**Files:**
- Modify: `src/backend/finances/services/systemic_month.py`
- Modify: `src/backend/finances/services/installment_month.py`
- Modify: `src/backend/finances/services/income_recurrence.py:25-35`
- Modify: `src/backend/finances/services/systemic_recurrence.py:24`
- Test: `src/backend/finances/tests/test_systemic_month.py`, `test_installment_month.py`, `test_income_recurrence.py`, `test_systemic_recurrence.py`

**Interfaces:**
- Produces:
  - `systemic_rows_for_month(household, year: int, month: int) -> list[dict]`
  - `installment_rows_for_month(household, year: int, month: int) -> list[dict]`
  - `apply_income_recurrence(income) -> int` — signature unchanged; scopes from `income.household` internally.
  - `apply_systemic_recurrence(template, amount, start, end) -> int` — signature unchanged; scopes from `template.household` internally.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_installment_month.py`:

```python
def test_installment_rows_exclude_other_households(household, other_user, other_household):
    category = baker.make(
        "finances.Category", user=other_user, household=other_household, name="Vizinho"
    )
    pm = baker.make(
        "finances.PaymentMethod",
        user=other_user,
        household=other_household,
        name="Cartão do vizinho",
        type="credit",
    )
    baker.make(
        "finances.InstallmentPlan",
        user=other_user,
        household=other_household,
        description="Geladeira do vizinho",
        category=category,
        payment_method=pm,
        total_amount=Decimal("1200.00"),
        installments=12,
    )

    assert installment_rows_for_month(household, 2026, 3) == []
```

And the mirror in `test_systemic_month.py` for `systemic_rows_for_month`.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_installment_month.py src/backend/finances/tests/test_systemic_month.py -q`
Expected: FAIL — `Cannot query "Casa de vagner": Must be "CustomUser" instance.`

- [x] **Step 3: Convert the four services**

`systemic_month.py` and `installment_month.py`: rename the parameter, rewrite each of the four/two queries with `for_household(household)`.

`income_recurrence.py` — the queryset scopes from the object:

```python
        qs = Income.objects.for_household(income.household).filter(name=income.name, month=m)
```

and the `Income.objects.create(...)` below it keeps `user=income.user` **and** gains `household=income.household` (decision 1: `user` is still `NOT NULL`).

`systemic_recurrence.py` — the same shape, from `template.household`, and the created `Entry` keeps `user=template.user` and gains `household=template.household`.

- [x] **Step 4: Run the four modules**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_installment_month.py src/backend/finances/tests/test_systemic_month.py src/backend/finances/tests/test_income_recurrence.py src/backend/finances/tests/test_systemic_recurrence.py -q`
Expected: PASS.

- [x] **Step 5: Confirm nine services have left the ratchet**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`
Expected: FAIL on `test_baseline_has_no_stale_entries`, naming the eight converted service files. That is the ratchet doing its job.

- [x] **Step 6: Strike them from BASELINE**

Delete these eight lines from `BASELINE` in `src/backend/accounts/tests/test_scoping_ratchet.py`:

```
    "src/backend/finances/services/budget_stats.py",
    "src/backend/finances/services/category_stats.py",
    "src/backend/finances/services/daily_trend.py",
    "src/backend/finances/services/income_recurrence.py",
    "src/backend/finances/services/installment_month.py",
    "src/backend/finances/services/projection.py",
    "src/backend/finances/services/systemic_month.py",
    "src/backend/finances/services/systemic_recurrence.py",
```

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`
Expected: 4 passed. `BASELINE` is now 16 entries.

- [x] **Step 7: Commit**

```bash
git add src/backend/finances/services src/backend/finances/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): month rows and recurrence scope by household"
```

---

### Task 5: Forms

Four form classes narrow their `category` and `payment_method` choices by user. A form whose dropdown offers another household's payment method is a leak that ends in a foreign-key write.

**Files:**
- Modify: `src/backend/finances/forms.py:50-56, 101-107, 173-190, 219-225, 284-293, 419-421`
- Test: `src/backend/finances/tests/test_forms.py`

**Interfaces:**
- Produces: every `__init__(self, *args, user=None, **kwargs)` becomes `__init__(self, *args, household=None, **kwargs)`; `save_for_user(self, user)` becomes `save_for_household(self, household, created_by)`. `InstallmentPreviewForm.__init__(self, *args, entry=None, household=None, **kwargs)` keeps `entry`.

> Every caller in `finances/views/` breaks at this step. That is deliberate — Tasks 6-9 convert them, and until then the view tests fail loudly rather than silently rendering the wrong choices. Expect a red suite between this task and Task 9; the commit here is still atomic and reviewable.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_forms.py`:

```python
def test_entry_form_choices_are_household_scoped(
    user, household, other_user, other_household
):
    mine = baker.make("finances.Category", user=user, household=household, name="Minha")
    theirs = baker.make(
        "finances.Category", user=other_user, household=other_household, name="Do vizinho"
    )

    form = EntryForm(household=household)
    choices = list(form.fields["category"].queryset)

    assert mine in choices
    assert theirs not in choices


def test_entry_form_without_a_household_offers_nothing(user, household):
    """Fail closed, exactly as `for_household(None)` does."""
    baker.make("finances.Category", user=user, household=household, name="Minha")

    form = EntryForm(household=None)

    assert list(form.fields["category"].queryset) == []
```

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_forms.py -q`
Expected: FAIL — `EntryForm() got an unexpected keyword argument 'household'`

- [x] **Step 3: Convert the forms**

The repeated block, in all four `__init__`s:

```python
    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.for_household(household)
        self.fields["payment_method"].queryset = PaymentMethod.objects.for_household(
            household
        ).filter(is_active=True)
```

Note the `if user:` guard **disappears**: `for_household(None)` already returns `none()`, which is the correct fail-closed answer and strictly safer than the current behaviour of leaving the unfiltered default queryset in place.

`save_for_user` becomes:

```python
    def save_for_household(self, household, created_by):
        ...
        SystemicExpense.objects.create(
            user=created_by,          # still NOT NULL until phase 4
            household=household,
            created_by=created_by,
            ...
        )
```

- [x] **Step 4: Run the form tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_forms.py -q`
Expected: PASS.

- [x] **Step 5: Strike the entry and commit**

`forms.py` no longer scopes by user, so `test_baseline_has_no_stale_entries` fails until its entry goes. Remove `"src/backend/finances/forms.py"` from `BASELINE` — 15 entries left — then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/forms.py src/backend/finances/tests/test_forms.py src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): form choices come from the household, and fail closed"
```

---

### Task 6: `views/entries.py`

21 call sites. This module also owns `compute_entry_summary`, which `views/cockpit.py` imports.

**Files:**
- Modify: `src/backend/finances/views/entries.py`
- Test: `src/backend/finances/tests/test_views_entries.py`, `test_entry_edit_modal.py`, `test_entries_live_summary.py`, `test_entries_page_sections.py`, `test_entries_pre_origin.py`

**Interfaces:**
- Consumes: `build_projection(household, ...)` (Task 2), `EntryForm(household=...)` (Task 5), `HouseholdScopedMixin` (phase 1).
- Produces: `compute_entry_summary(household, year: int, month: int) -> dict` — first parameter renamed; return shape unchanged, including the `before_origin` and `origin_month` keys.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_views_entries.py`:

```python
def test_entry_list_excludes_other_households(
    logged_client, user, household, other_user, other_household
):
    baker.make(
        "finances.Entry",
        user=other_user,
        household=other_household,
        description="Compra do vizinho",
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    response = logged_client.get(reverse("finances:entries_month", args=[2026, 3]))

    assert response.status_code == 200
    assert "Compra do vizinho" not in response.content.decode()


def test_entry_edit_404s_across_households(
    logged_client, other_user, other_household
):
    theirs = baker.make(
        "finances.Entry",
        user=other_user,
        household=other_household,
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    response = logged_client.get(reverse("finances:entry_edit_modal", args=[theirs.pk]))

    assert response.status_code == 404
```

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_entries.py -q`
Expected: FAIL — `compute_entry_summary` raises on the `build_projection` call (Task 2 renamed it), and the edit view still resolves by `user`.

- [x] **Step 3: Convert the module**

`compute_entry_summary` takes `household`:

```python
def compute_entry_summary(household, year, month):
    ...
    lanc = Entry.objects.for_household(household).filter(
        entry_type=EntryType.REGULAR, date__year=year, date__month=month
    ).aggregate(total=Sum("amount"), count=Count("id"))
    ...
    inc_min = Income.objects.for_household(household).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.for_household(household).aggregate(m=Min("billing_month"))["m"]
    ...
    rows = build_projection(household, anchor, num_months, today=date.today())
```

`EntryListView` gains the mixin, per Shape C:

```python
class EntryListView(HouseholdScopedMixin, HtmxLoginRequiredMixin, ListView):
    ...
    def get_queryset(self):
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])
        return (
            super()
            .get_queryset()
            .filter(date__year=year, date__month=month, entry_type=EntryType.REGULAR)
            .select_related("category", "payment_method")
            .order_by("-date", "-created_at")
        )
```

Every other `Entry.objects.filter(user=request.user, ...)` becomes `Entry.objects.for_request(request).filter(...)`. Every `EntryForm(..., user=request.user)` becomes `EntryForm(..., household=request.household)`. Creates keep `user=request.user` and gain `household=request.household, created_by=request.user`.

- [x] **Step 4: Run the entries tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_entries.py src/backend/finances/tests/test_entry_edit_modal.py src/backend/finances/tests/test_entries_live_summary.py src/backend/finances/tests/test_entries_page_sections.py src/backend/finances/tests/test_entries_pre_origin.py -q`
Expected: PASS.

- [x] **Step 5: Strike the entry and commit**

Remove `"src/backend/finances/views/entries.py"` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/views/entries.py src/backend/finances/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): the entries page reads the household's ledger"
```

---

### Task 7: `views/cockpit.py`, and the payment-method union

20 call sites, plus decision 5's two unions.

**Files:**
- Modify: `src/backend/finances/views/cockpit.py`
- Create: `src/backend/finances/tests/test_cockpit_pm_union.py`
- Test: the eight `test_cockpit_*.py` modules

**Interfaces:**
- Consumes: `systemic_rows_for_month(household, ...)`, `installment_rows_for_month(household, ...)` (Task 4), `compute_entry_summary(household, ...)` (Task 6), the converted forms (Task 5).
- Produces: no new public names.

- [x] **Step 1: Write the failing union test**

Create `src/backend/finances/tests/test_cockpit_pm_union.py`:

```python
"""The two `PaymentMethod.objects.filter(pk=...)` unions are NOT leaks.

`views/cockpit.py` unions an unscoped single-pk lookup onto an already-scoped
queryset, so the entry's current payment method stays selectable in the form
even if it was later deactivated. The pk comes from an object that was itself
household-scoped, so the union cannot reach another household — but nothing
asserted that until now. The epic asked for this test by name.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from model_bakery import baker

from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


def test_edit_modal_union_cannot_surface_a_foreign_payment_method(
    logged_client, user, household, other_user, other_household
):
    theirs = baker.make(
        "finances.PaymentMethod",
        user=other_user,
        household=other_household,
        name="Cartão do vizinho",
        type="credit",
    )
    mine = baker.make(
        "finances.PaymentMethod",
        user=user,
        household=household,
        name="Meu Pix",
        type="pix",
        is_active=False,
    )
    category = baker.make("finances.Category", user=user, household=household, name="Minha")
    entry = baker.make(
        "finances.Entry",
        user=user,
        household=household,
        category=category,
        payment_method=mine,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    response = logged_client.get(
        reverse("finances:cockpit_entry_edit_modal", args=[2026, 3, entry.pk])
    )
    body = response.content.decode()

    assert response.status_code == 200
    # The union's whole purpose: the entry's own (deactivated) method is offered.
    assert "Meu Pix" in body
    # And the neighbour's is not.
    assert "Cartão do vizinho" not in body
```

> Check the exact url name and its arguments in `finances/urls.py` before running — the modal route may take `(year, month, pk)` or just `(pk)`. Fix the `reverse()` call to match; do not change `urls.py`.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_cockpit_pm_union.py -q`
Expected: FAIL — the view still calls the forms with `user=`, which Task 5 removed.

- [x] **Step 3: Convert the module**

Apply Shape B throughout. Leave both `_patch_*_querysets` helpers' union lines **exactly as they are** — `Category.objects.filter(pk=entry.category_id)` and `PaymentMethod.objects.filter(pk=entry.payment_method_id)` stay unscoped by design. Only the form construction above them changes to `household=request.household`.

- [x] **Step 4: Run the cockpit tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -k cockpit -q`
Expected: PASS across all eight cockpit modules plus the new union test.

- [x] **Step 5: Strike the entry and commit**

Remove `"src/backend/finances/views/cockpit.py"` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/views/cockpit.py src/backend/finances/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): the cockpit reads the household, and the pm union is pinned by a test"
```

---

### Task 8: `views/settings.py`

38 call sites — the largest single file in the phase, and the one where a missed site is most visible: settings is where categories, payment methods and budgets are *created*.

**Files:**
- Modify: `src/backend/finances/views/settings.py`
- Test: `src/backend/finances/tests/test_views_settings.py`, `test_settings_income_groups.py`, `test_category.py`, `test_budget_model.py`

**Interfaces:**
- Consumes: `budget_spend_for_month(household, ...)`, `orphan_category_spend_for_month(household, ...)` (Task 3), the converted forms (Task 5).
- Produces: the module-level helpers rename their first parameter — `_settings_context(household)`, `_income_groups(household)`, `_budget_rows(household)`. Confirm the actual names at lines 29, 63 and 455 before editing; the plan does not rename them beyond the parameter.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_views_settings.py`:

```python
def test_settings_lists_only_this_households_categories(
    logged_client, user, household, other_user, other_household
):
    baker.make("finances.Category", user=user, household=household, name="Minha categoria")
    baker.make(
        "finances.Category",
        user=other_user,
        household=other_household,
        name="Categoria do vizinho",
    )

    body = logged_client.get(reverse("finances:settings")).content.decode()

    assert "Minha categoria" in body
    assert "Categoria do vizinho" not in body


def test_deleting_a_foreign_payment_method_404s(
    logged_client, other_user, other_household
):
    theirs = baker.make(
        "finances.PaymentMethod",
        user=other_user,
        household=other_household,
        name="Cartão do vizinho",
        type="credit",
    )

    response = logged_client.post(
        reverse("finances:payment_method_delete", args=[theirs.pk])
    )

    assert response.status_code == 404
    assert PaymentMethod.objects.filter(pk=theirs.pk).exists()
```

> Confirm the url names against `finances/urls.py`. If the delete view currently returns a re-rendered list rather than 404 for a missing pk, assert *that* behaviour plus `.exists()` — the invariant that matters is that the foreign row survives.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_settings.py -q`
Expected: FAIL — form kwarg errors from Task 5, and the neighbour's category rendering.

- [x] **Step 3: Convert the module**

Shape B for all 38 sites. `SystemicExpenseForm(user=...)` → `SystemicExpenseForm(household=request.household)`; `form.save_for_user(request.user)` → `form.save_for_household(request.household, request.user)`. Creates keep `user=request.user` and gain `household=request.household, created_by=request.user`.

- [x] **Step 4: Run the settings tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_settings.py src/backend/finances/tests/test_settings_income_groups.py src/backend/finances/tests/test_category.py src/backend/finances/tests/test_budget_model.py -q`
Expected: PASS.

- [x] **Step 5: Strike the entry and commit**

Remove `"src/backend/finances/views/settings.py"` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/views/settings.py src/backend/finances/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): settings reads and writes the household's catalogue"
```

---

### Task 9: `views/consolidated.py`, `views/projection.py`, `views/importer.py`

3 + 2 + 16 call sites. Grouped because they are small and share one shape; `importer.py` is the largest and writes rows through `ImportBatch`.

**Files:**
- Modify: `src/backend/finances/views/consolidated.py`
- Modify: `src/backend/finances/views/projection.py`
- Modify: `src/backend/finances/views/importer.py`
- Test: `test_consolidated_detail_filter.py`, `test_consolidated_dropdown.py`, `test_views_projection.py`, `finances/tests/features/test_import.py`, `test_import_double_submit.py`, `test_import_query_count.py`

**Interfaces:**
- Consumes: `build_projection(household, ...)` (Task 2), `simulate_projection_summary(household, ...)` (Task 2).
- Produces: no new public names.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_views_projection.py`:

```python
def test_projection_page_excludes_other_households(
    logged_client, other_user, other_household
):
    baker.make(
        "finances.Income",
        user=other_user,
        household=other_household,
        name="Salário do vizinho",
        amount=Decimal("9999.00"),
        month=date(2026, 3, 1),
    )

    body = logged_client.get(reverse("finances:projection")).content.decode()

    assert "9999" not in body
```

And to `src/backend/finances/tests/features/test_import.py`:

```python
def test_import_batch_belongs_to_the_household(logged_client, user, household):
    """The importer writes rows; an ImportBatch with no household would be a
    row the family cannot see."""
    from finances.models import ImportBatch

    # ... drive the wizard through to execution exactly as the existing
    # happy-path test in this module does, then:
    batch = ImportBatch.objects.latest("created_at")

    assert batch.household == household
    assert batch.created_by == user
```

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_projection.py -q`
Expected: FAIL — `build_projection` receives a user.

- [x] **Step 3: Convert the three modules**

Shape B throughout. In `importer.py`, the `ImportBatch` create and every `Entry` create gain `household=request.household, created_by=request.user` alongside the existing `user=request.user`.

> `test_import_query_count.py` enforces an O(N) ceiling of 1.5 queries per imported row. `for_household()` adds no query — it is the same single `WHERE` clause — but the bridge's `household_for_writer` memoisation is what keeps creates cheap. If the ceiling breaks here, the cause is a create that lost its `user=` (forcing a fresh resolution per row), not the read conversion.

- [x] **Step 4: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_consolidated_detail_filter.py src/backend/finances/tests/test_consolidated_dropdown.py src/backend/finances/tests/test_views_projection.py src/backend/finances/tests/features/test_import.py src/backend/finances/tests/test_import_double_submit.py src/backend/finances/tests/test_import_query_count.py -q`
Expected: PASS.

- [x] **Step 5: Strike three entries and commit**

Remove `consolidated.py`, `projection.py` and `importer.py` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/views src/backend/finances/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): consolidated, projection and the importer scope by household"
```

---

### Task 10: The DRF dashboard API

10 endpoints. These are plain `APIView`s, **not** DRF generics — `HouseholdScopedMixin` hooks `get_queryset()` and therefore does **not** apply here. Convert them by hand with Shape B, using `request.household`.

**Files:**
- Modify: `src/backend/finances/api/views.py`
- Test: `src/backend/finances/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: every converted service from Tasks 2-4.
- Produces: `SummaryView._month_totals(household, billing_month) -> dict` — the one `@staticmethod` that takes a scope; first parameter renamed. `_get_month_params(request)` is unchanged.

- [x] **Step 1: Write the failing test**

Add to `src/backend/finances/tests/test_api_dashboard.py`:

```python
def test_summary_excludes_other_households(
    logged_client, user, household, other_user, other_household
):
    baker.make(
        "finances.Income",
        user=other_user,
        household=other_household,
        amount=Decimal("9999.00"),
        month=date(2026, 3, 1),
    )
    baker.make(
        "finances.Income",
        user=user,
        household=household,
        amount=Decimal("100.00"),
        month=date(2026, 3, 1),
    )

    response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")

    assert response.status_code == 200
    assert response.json()["income"] == "100.00"


def test_api_without_a_household_returns_zeroes_not_everything(client, user):
    """A user with no Membership must see an empty dashboard, never the table.
    Note: `user`, not `logged_client` — this test needs a household-less user."""
    client.force_login(user)
    baker.make(
        "finances.Income",
        user=user,
        household=None,
        amount=Decimal("100.00"),
        month=date(2026, 3, 1),
    )

    response = client.get("/api/dashboard/summary/?year=2026&month=3")

    assert response.json()["income"] == "0.00"
```

> The second test writes `household=None` explicitly, which the phase 2 bridge would otherwise fill. If the bridge overrides it, create the row and then `Income.objects.filter(pk=...).update(household=None)` — `.update()` bypasses signals, which is the same technique phase 2's own tests used.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_api_dashboard.py -q`
Expected: FAIL — the services receive a user.

- [x] **Step 3: Convert the module**

Every `user = request.user` becomes `household = request.household`, every service call passes it, every direct query uses `for_request(request)`:

```python
    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        household = request.household

        cur = self._month_totals(household, billing_month)
        prev = self._month_totals(household, add_months(billing_month, -1))

        total_ceiling = Category.objects.for_household(household).aggregate(
            total=Sum("budget_ceiling")
        )["total"] or Decimal("0")
```

- [x] **Step 4: Run the API tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_api_dashboard.py -q`
Expected: PASS.

- [x] **Step 5: Strike the entry and commit**

Remove `"src/backend/finances/api/views.py"` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/api src/backend/finances/tests/test_api_dashboard.py src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(finances): the dashboard API answers for a household"
```

---

### Task 11: The four management commands

Each takes a username on the CLI. Each resolves the household once, then scopes by it. `transfer_entries` is the odd one: it is an export/import tool keyed on username across machines, so its `--user` argument and its `filter(user__username=...)` **stay** — only the `Category`/`PaymentMethod` resolution inside the import loop converts.

**Files:**
- Modify: `src/backend/finances/management/commands/import_csv.py`
- Modify: `src/backend/finances/management/commands/seed_qa_data.py`
- Modify: `src/backend/finances/management/commands/transfer_entries.py:114-115`
- Modify: `src/backend/assistant/management/commands/seed_category_rules.py:47`
- Test: `src/backend/finances/tests/features/test_import_command.py` (confirm the real name with `ls src/backend/finances/tests/`), `src/backend/assistant/tests/test_seed_category_rules.py`

**Interfaces:**
- Consumes: `accounts.resolution.household_for_user` (Task 1).
- Produces: no new public names. Every command gains one line after resolving the user.

- [x] **Step 1: Write the failing test**

Add to the `import_csv` test module:

```python
def test_import_csv_writes_into_the_users_household(user, household, tmp_path):
    csv_path = tmp_path / "gastos.csv"
    csv_path.write_text(
        "data;descricao;valor;categoria;forma\n"
        "10/03/2026;Feira;50,00;Alimentação;Pix\n",
        encoding="utf-8",
    )
    baker.make("finances.Category", user=user, household=household, name="Alimentação")
    baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )

    call_command("import_csv", "--user", user.username, str(csv_path))

    entry = Entry.objects.get(description="Feira")
    assert entry.household == household
    assert entry.created_by == user
```

> Read the command's actual argument names and CSV dialect first — `import_csv` reads Brazilian-format files from `.data/imports/` and its flags may differ. Match the existing happy-path test in the module rather than inventing an invocation.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -k import_command -q`
Expected: FAIL — `created_by` is None, or the assertion on `household` fails.

- [x] **Step 3: Convert the four commands**

The shared shape, right after the user lookup:

```python
from accounts.resolution import household_for_user

        user = User.objects.get(username=username)
        household = household_for_user(user)
```

then `Category.objects.filter(user=user)` → `Category.objects.for_household(household)`, and every create gains `household=household, created_by=user` beside its existing `user=user`.

In `transfer_entries.py` the import loop resolves per row, because each row names its own user:

```python
            u = User.objects.filter(username=r["user"]).first()
            if u is None:
                errors.append(f"no user '{r['user']}' | {r['description'][:50]}")
                continue
            hh = household_for_user(u)
            cat = _resolve(Category.objects.for_household(hh), r["category"] or "")
            pm = _resolve(
                PaymentMethod.objects.for_household(hh).filter(is_active=True),
                r["payment"] or "",
            )
```

Leave the export half (`qs.filter(user__username=...)`) alone — it selects *whose* rows to export, which is a person question, and the ratchet's regex does not match it.

- [x] **Step 4: Run the command tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ src/backend/assistant/tests/ -k "import or seed or transfer" -q`
Expected: PASS.

- [x] **Step 5: Strike four entries and commit**

Remove `import_csv.py`, `seed_qa_data.py`, `transfer_entries.py` and `seed_category_rules.py` from `BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/finances/management src/backend/assistant/management src/backend/finances/tests src/backend/assistant/tests src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor: the CLI commands write into a household, not a person"
```

---

### Task 12: Gate 3a — the Django surface is converted

No files created. This is the checkpoint before the agent is touched. If phase 3b goes badly, this is the commit you ship.

- [x] **Step 1: Full suite under the real clock**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: the Task 1 baseline (1066) plus roughly 20 new tests, **0 failed**.

- [x] **Step 2: Full suite under a shifted clock**

Run: `POSTGRES_PORT=5433 TEST_CLOCK_SHIFT=+1y uv run pytest src/backend/ -q -m "not current_date"`
Expected: same counts. Run **serially** after Step 1.

- [x] **Step 3: Gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run python src/backend/manage.py check
```

Expected: coverage ≥ 80, lint clean, **`No changes detected`** (this phase adds no migration — a change here means a model was edited, which is out of scope), system check clean.

- [x] **Step 4: The ratchet has shrunk to four**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`

Expected: 4 passed, and `BASELINE` now holds exactly these four files — the agent, and nothing else:

```
src/backend/assistant/agents/analytics.py
src/backend/assistant/agents/memory.py
src/backend/assistant/agents/tools.py
src/backend/assistant/views.py
```

> The invariant that matters: **every remaining entry is under `assistant/`**. Anything in `finances/` here means a Task 2-11 conversion was missed. The running count was 25 → 24 (Task 1) → 16 (Task 4) → 15 (Task 5) → 14, 13, 12 (Tasks 6-8) → 9 (Task 9) → 8 (Task 10) → 4 (Task 11).

- [x] **Step 5: The money boundary held**

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres PGSSLMODE=prefer \
SOURCE_DB=expense_tracker REWIND=1 scripts/rehearse-e04-migration.sh
```

Expected: `OK — counts, sums and acumulado identical across the migration.`

- [x] **Step 6: Commit the gate**

```bash
git commit --allow-empty -m "chore(finances): E04 phase 3a gate — every Django read path scopes by household"
```

---

### Task 13: `AgentScope`, memory, and analytics

The agent's deps type carries `User` today. It becomes a frozen dataclass carrying both the household (data scope) and the acting user (`created_by`, and the throttle's actor). Convert the two small agent modules in the same commit so `tools.py` has something to stand on.

**Files:**
- Create: `src/backend/assistant/agents/scope.py`
- Modify: `src/backend/assistant/agents/memory.py:12-41`
- Modify: `src/backend/assistant/agents/analytics.py`
- Create: `src/backend/assistant/tests/test_agent_scope.py`

**Interfaces:**
- Consumes: `accounts.models.Household`, `accounts.resolution.household_for_user`.
- Produces:
  - `assistant.agents.scope.AgentScope` — frozen dataclass with fields `household` and `user`, and a classmethod `AgentScope.for_request(request) -> AgentScope`.
  - `find_matching_rules(scope: AgentScope, message: str) -> list[MemoryRule]`
  - `find_semantic_matches(scope: AgentScope, query_vector: list[float], threshold: float = 0.8, limit: int = 5)`
  - every public function in `analytics.py` takes `scope` as its first parameter, renamed from `user`.

> **Why the whole scope, not just the household:** memory and analytics only read, so they could take a bare household. Passing `AgentScope` uniformly means every tool has one signature shape, and a tool that later needs `created_by` does not force a second signature change. The cost is one attribute access.

- [x] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_agent_scope.py`:

```python
"""The agent's scope comes from deps, never from a tool argument.

This is the epic's DoD item: "a test asserts that a tool cannot be induced to
read another household's data by any tool argument". The discipline exists
today with `deps_type=User`; it must survive becoming a structure.
"""

import pytest
from model_bakery import baker

from assistant.agents.scope import AgentScope

pytestmark = pytest.mark.django_db


def test_scope_is_frozen(user, household):
    """An LLM-driven tool must not be able to reassign its own scope."""
    scope = AgentScope(household=household, user=user)

    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        scope.household = None


def test_for_request_reads_the_middlewares_household(rf, user, household):
    request = rf.get("/")
    request.user = user
    request.household = household

    scope = AgentScope.for_request(request)

    assert scope.household == household
    assert scope.user == user


def test_for_request_without_middleware_fails_closed(rf, user):
    """A request built without the middleware has no `household` attribute.
    It must yield None — which every scoped queryset turns into none() —
    rather than raising or defaulting to something."""
    request = rf.get("/")
    request.user = user

    assert AgentScope.for_request(request).household is None


def test_memory_rules_are_household_scoped(user, household, other_user, other_household):
    from assistant.agents.memory import find_matching_rules

    baker.make(
        "assistant.MemoryRule",
        user=other_user,
        household=other_household,
        trigger="cerveja",
        field="category",
        value="Álcool",
    )

    scope = AgentScope(household=household, user=user)

    assert find_matching_rules(scope, "comprei cerveja") == []
```

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_agent_scope.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.agents.scope'`

- [x] **Step 3: Write `AgentScope`**

`src/backend/assistant/agents/scope.py`:

```python
"""What the agent is allowed to see, and who is asking.

`deps_type` was the acting `User`, which conflated two questions the tenancy
split apart: *whose data* (the household) and *who wrote this row*
(`created_by`, and the throttle's actor). Frozen, because a tool body runs on
LLM-chosen arguments and must not be able to widen its own scope.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentScope:
    """The household a tool may read, and the person on the other end."""

    household: object | None
    user: object

    @classmethod
    def for_request(cls, request):
        """Build a scope from a request the middleware has already seen.

        `getattr` rather than `request.household`: a request built without the
        middleware must fail closed to `None` — which every scoped queryset
        turns into `none()` — rather than raise.
        """
        return cls(household=getattr(request, "household", None), user=request.user)
```

- [x] **Step 4: Convert memory and analytics**

`memory.py`:

```python
def find_matching_rules(scope, message: str) -> list[MemoryRule]:
    rules = MemoryRule.objects.for_household(scope.household)
    ...


def find_semantic_matches(scope, query_vector, threshold=0.8, limit=5):
    ...
    MemoryEmbedding.objects.for_household(scope.household)
```

`analytics.py`: rename the first parameter of every public function from `user` to `scope`, and rewrite each query — including lines 247 and 254's `Entry.objects.filter(user=user, billing_month=bm, ...)` — as `Entry.objects.for_household(scope.household).filter(billing_month=bm, ...)`.

- [x] **Step 5: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_agent_scope.py src/backend/assistant/tests/ -k "memory or analytics" -q`
Expected: PASS, after converting the existing modules' call sites.

- [x] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/scope.py src/backend/assistant/agents/memory.py \
  src/backend/assistant/agents/analytics.py src/backend/assistant/tests
git commit -m "feat(assistant): the agent's scope is a household plus an actor"
```

---

### Task 14: `tools.py` — the ~45 tool functions

41 call sites in one module. Every tool takes `user` as its first parameter today; every one takes `scope: AgentScope` after this task. **Nothing about where the scope comes from changes** — it is still `ctx.deps`, never an LLM argument. That property is what Task 13's test pins.

**Files:**
- Modify: `src/backend/assistant/agents/tools.py`
- Test: `src/backend/assistant/tests/test_tools.py` and the other agent test modules

**Interfaces:**
- Consumes: `AgentScope` (Task 13), `find_matching_rules(scope, ...)`, `find_semantic_matches(scope, ...)` (Task 13).
- Produces: every public tool function's first parameter renamed `user` → `scope`. Examples, spelled out because Task 15 imports these by name:
  - `list_categories(scope) -> list[str]`
  - `list_payment_methods(scope) -> list[str]`
  - `register_entry(scope, date, amount, description, category_name, payment_method_name) -> str`
  - `update_entry(scope, ...) -> str`
  - `set_systemic_amount(scope, ...) -> str`
  - `list_systemic_expenses(scope) -> str`
  - `propose_receipt(scope, ...)`, `commit_receipt(scope, ...)`, `discard_receipt(scope, ...)`
  - `build_pending_receipt_directive(scope) -> str`

  The private helpers `_parse_receipt_date(value)` and `_resolve_by_name(queryset, raw_name)` take no scope and do not change.

- [x] **Step 1: Write the failing test**

Add to `src/backend/assistant/tests/test_agent_scope.py`:

```python
def test_list_categories_is_household_scoped(user, household, other_user, other_household):
    from assistant.agents.tools import list_categories

    baker.make("finances.Category", user=user, household=household, name="Minha")
    baker.make(
        "finances.Category", user=other_user, household=other_household, name="Do vizinho"
    )

    names = list_categories(AgentScope(household=household, user=user))

    assert names == ["Minha"]


def test_register_entry_records_the_household_and_the_author(user, household):
    from assistant.agents.tools import register_entry
    from finances.models import Entry

    baker.make("finances.Category", user=user, household=household, name="Alimentação")
    baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )

    register_entry(
        AgentScope(household=household, user=user),
        "2026-03-10",
        "50,00",
        "Feira",
        "Alimentação",
        "Pix",
    )

    entry = Entry.objects.get(description="Feira")
    assert entry.household == household
    assert entry.created_by == user
    assert entry.user == user  # still NOT NULL until phase 4


def test_a_tool_cannot_widen_its_scope_through_an_argument(
    user, household, other_user, other_household
):
    """The DoD's argument-injection assertion. `category_name` is LLM-supplied;
    naming another household's category must fail to resolve, not reach it."""
    from assistant.agents.tools import register_entry

    baker.make(
        "finances.Category", user=other_user, household=other_household, name="Segredo"
    )
    baker.make("finances.PaymentMethod", user=user, household=household, name="Pix", type="pix")

    result = register_entry(
        AgentScope(household=household, user=user),
        "2026-03-10",
        "50,00",
        "Feira",
        "Segredo",
        "Pix",
    )

    from finances.models import Entry

    assert not Entry.objects.filter(description="Feira").exists()
    assert "Segredo" in result  # the tool reports the category was not found
```

> The third test's final assertion depends on the tool's actual pt-BR error string. Read `register_entry`'s not-found branch and assert on what it really returns; the invariant that must hold is that **no entry is created**.

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_agent_scope.py -q`
Expected: FAIL — `list_categories` receives an `AgentScope` and passes it to `filter(user=...)`.

- [x] **Step 3: Convert the module**

Mechanical, 41 sites. `Category.objects.filter(user=user)` → `Category.objects.for_household(scope.household)`. `PaymentMethod.objects.filter(user=user, is_active=True)` → `PaymentMethod.objects.for_household(scope.household).filter(is_active=True)`. Every create gains `household=scope.household, created_by=scope.user` beside its existing `user=scope.user`.

Work through it in one pass and let the test suite find what you missed — the parameter rename means a missed site raises `ValueError: Cannot query "AgentScope"`, never a silent leak. That is the whole reason this task renames rather than adds.

- [x] **Step 4: Run the agent tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q`
Expected: failures only in `assistant.py`'s registrations and `views.py` — Task 15 owns those. Everything in `tools.py`'s own modules passes.

- [x] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests
git commit -m "refactor(assistant): every tool reads the household from its scope"
```

---

### Task 15: The orchestrator and the chat view

`deps_type=User` becomes `deps_type=AgentScope`; every `ctx.deps` passed to a tool is already the right shape. The chat view builds the scope and scopes the chat history.

**Files:**
- Modify: `src/backend/assistant/agents/assistant.py:66-70` and every `RunContext[User]` annotation
- Modify: `src/backend/assistant/views.py:74, 109, 124, 215, 231, 254, 283, 321, 351, 400, 426`
- Test: `src/backend/assistant/tests/test_chat_view.py`, `test_orchestrator.py` (confirm names with `ls src/backend/assistant/tests/`)

**Interfaces:**
- Consumes: `AgentScope` (Task 13), every converted tool (Task 14).
- Produces: no new public names. `assistant_agent` keeps its name; its `deps_type` changes.

- [x] **Step 1: Write the failing test**

Add to `src/backend/assistant/tests/test_agent_scope.py`:

```python
def test_agent_deps_type_is_the_scope():
    """Pinned deliberately: if someone reverts deps to a User, every tool
    silently starts scoping by the actor again."""
    from assistant.agents.assistant import assistant_agent
    from assistant.agents.scope import AgentScope

    assert assistant_agent._deps_type is AgentScope
```

> `_deps_type` is PydanticAI-internal. If the attribute name differs in the installed version, find the public accessor with `uv run python -c "from assistant.agents.assistant import assistant_agent; print([a for a in dir(assistant_agent) if 'dep' in a.lower()])"` and assert on that instead. Do not delete the test — it is the guard against a silent revert.

And to the chat-view test module:

```python
def test_chat_history_is_household_scoped(
    logged_client, user, household, other_user, other_household
):
    baker.make(
        "assistant.ChatMessage",
        user=other_user,
        household=other_household,
        role="user",
        content="segredo do vizinho",
    )

    body = logged_client.get(reverse("assistant:chat")).content.decode()

    assert "segredo do vizinho" not in body
```

- [x] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/ -q`
Expected: FAIL on both.

- [x] **Step 3: Convert the orchestrator**

In `assistant/agents/assistant.py`, replace the `User = get_user_model()` deps usage:

```python
from assistant.agents.scope import AgentScope

assistant_agent = Agent(
    settings.LLM_ASSISTANT_MODEL,
    deps_type=AgentScope,
    system_prompt=ASSISTANT_PROMPT,
)
```

and change every `RunContext[User]` annotation to `RunContext[AgentScope]`. The tool bodies do not change at all — they already forward `ctx.deps` to the converted functions:

```python
@assistant_agent.tool
async def get_categories(ctx: RunContext[AgentScope]) -> list[str]:
    """Lista as categorias de despesa disponíveis do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)
```

Keep the pt-BR docstrings exactly as they are — they are the tool descriptions the model reads, and rewording them changes agent behaviour.

Do the same for the three worker agents in `registrar.py`, `analyst.py` and `planner.py` if they declare their own `deps_type`; grep for `deps_type=` across `assistant/agents/` and convert every hit.

- [x] **Step 4: Convert the chat view**

In `assistant/views.py`, build the scope once and use it for both the agent run and the queries:

```python
    scope = AgentScope.for_request(request)
    ...
    ChatMessage.objects.for_household(scope.household)
    ...
        result = await agent.run(
            prompt, deps=scope, message_history=message_history, model=model
        )
```

Every `ChatMessage.objects.acreate(user=user, ...)` gains `household=scope.household, created_by=user`. `ReceiptDraft.objects.filter(user=user, ...)` becomes `ReceiptDraft.objects.for_household(scope.household).filter(...)`.

**Leave `AssistantUsageEvent.objects.acreate(user=user, kind=kind)` at line 158 exactly as it is** — decision 2: that row's `user` is the actor, and the throttle counts per person.

> `views.py` is async. `AgentScope.for_request` only reads attributes, so it is safe to call directly; the ORM calls around it are already `await`ed or wrapped in `sync_to_async`. Do not add a `sync_to_async` around `for_request`.

- [x] **Step 5: Run the assistant suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q`
Expected: PASS.

- [x] **Step 6: Strike the last four entries and commit**

Remove `analytics.py`, `memory.py`, `tools.py` and `views.py` from `BASELINE` — it is now **empty**. Leave the `BASELINE = set()` assignment in place with a comment saying phase 4 turns the ratchet into a flat assertion.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git add src/backend/assistant src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "refactor(assistant): the orchestrator and the chat view speak in households"
```

---

### Task 16: Gate 3b — phase 3 complete

No files created.

- [x] **Step 1: Full suite under the real clock**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: roughly 1090 passed, 2 skipped, **0 failed**.

- [x] **Step 2: Full suite under a shifted clock**

Run: `POSTGRES_PORT=5433 TEST_CLOCK_SHIFT=+1y uv run pytest src/backend/ -q -m "not current_date"`
Expected: same counts. Serially, after Step 1.

- [x] **Step 3: Gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run python src/backend/manage.py check
```

- [x] **Step 4: The baseline is empty**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`

Then confirm by eye that only the two exempt sets remain:

```bash
grep -A 3 "^BASELINE" src/backend/accounts/tests/test_scoping_ratchet.py
grep -A 3 "^ACTOR_SCOPED\|^E04_TRANSITION_TOOLS" src/backend/accounts/tests/test_scoping_ratchet.py
```

Expected: `BASELINE` empty; `ACTOR_SCOPED` = `{assistant/throttling.py}`; `E04_TRANSITION_TOOLS` = `{dump_ledger_totals.py}`.

- [x] **Step 5: No model or migration was touched**

```bash
git diff main --stat -- "src/backend/*/models.py" "src/backend/*/models/" "src/backend/*/migrations/"
```

Expected: **empty**. Phase 3 changes no schema. Anything here belongs to phase 4.

- [x] **Step 6: The money boundary held**

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres PGSSLMODE=prefer \
SOURCE_DB=expense_tracker REWIND=1 scripts/rehearse-e04-migration.sh
```

Expected: `OK — counts, sums and acumulado identical across the migration.`

- [x] **Step 7: Commit and open for review**

```bash
git commit --allow-empty -m "chore(accounts): E04 phase 3 gate — the scoping baseline is empty"
```

Then request review per `superpowers:requesting-code-review`, and run `/security-review` — this branch changes every read path in the product, and the epic makes that review mandatory.

**Do not start phase 4 in the same session.** Phase 4 converts the 12 isolation test modules, makes `household` NOT NULL, drops `user` from 12 of 13 models, deletes `accounts/bridge.py`, and turns this ratchet into the flat assertion S04-2 asked for. It needs a fresh reviewer and a plan of its own.

---

## Follow-on — NOT part of this plan

| Phase | Epic stories | Deliverable | Why it waits |
|---|---|---|---|
| **4 · Prove the boundary** | S04-6 | The 12 isolation modules convert from cross-user to cross-household; a parameterized test over `household_owned_models()` asserts every model rejects cross-household access, reaching `PaymentMethodClosingDay` through its parent; a test asserts two users in one household see identical data; `household` becomes NOT NULL; `user` is dropped from 12 of 13 models (**not** `AssistantUsageEvent`); the user-leading constraints and indexes are dropped; `bridge.py`, `test_bridge.py` and `E04_TRANSITION_TOOLS` are deleted, and `dump_ledger_totals` re-points at household. | The epic's risk note: a missed call site is a leak, not a bug. Phase 3 must be reviewed by someone who did not write it before the safety net that would have caught its mistakes is rewritten. |

---

## Self-Review

**Spec coverage.** This plan covers S04-4 and S04-5 clause by clause:

| Clause | Task |
|---|---|
| the DRF API scopes by household | 10 |
| all six HTMX view modules scope by household | 6, 7, 8, 9 |
| all `finances/services/` functions scope by household | 2, 3, 4 |
| no domain query outside `accounts` references `user` for scoping | 12 Step 4, 16 Step 4 — enforced by the ratchet, not by inspection |
| agent deps become a structure carrying household **and** acting user | 13 |
| every tool in `tools.py` scopes by household | 14 |
| scope comes from `ctx.deps`, never an LLM argument | 13 Step 1 (frozen dataclass), 14 Step 1 (the injection test) |
| a test asserts a tool cannot be induced to read another household's data | 14 Step 1 |

DoD items discharged here: *"the agent cannot be argument-injected across households"* (14). The epic's *"a test asserting the cockpit union cannot surface a foreign household's payment method"* is Task 7. The remaining DoD items — the parameterized cross-household test, two users in one household seeing identical data, `/security-review` clean — belong to phase 4 and the review at Task 16.

**Two deliberate deviations from the epic's letter,** both stated where an executor meets them: `assistant/throttling.py` is exempted permanently rather than converted (decision 2 — `user` there is the actor, and phase 2 already decided `AssistantUsageEvent` keeps its `user` column), and `transfer_entries.py`'s export half keeps `filter(user__username=...)` because it selects *whose* rows to export, which is a person question.

**Placeholder scan.** No TBDs. Every code step carries real code. Six places where reality may differ from the plan name the check rather than hand-waving: the cockpit modal's URL signature (Task 7 Step 1), the settings delete view's 404-vs-rerender behaviour (Task 8 Step 1), `import_csv`'s actual flags and CSV dialect (Task 11 Step 1), the bridge overriding an explicit `household=None` (Task 10 Step 1), `register_entry`'s pt-BR not-found string (Task 14 Step 1), and PydanticAI's `_deps_type` attribute name (Task 15 Step 1).

**Type consistency.** `household_for_user(user)` is defined in Task 1 and imported by Tasks 2, 11 and 13. `AgentScope` is defined in Task 13 Step 3 with fields `household` and `user` and the classmethod `for_request`; Tasks 14 and 15 use exactly those names. `for_household(household)` and `for_request(request)` are phase 1's existing `HouseholdScopedQuerySet` methods, spelled identically throughout. `save_for_household(household, created_by)` is defined in Task 5 and called in Task 8. `compute_entry_summary(household, year, month)` is defined in Task 6 and consumed by Task 7. `_month_totals(household, billing_month)` is defined and used inside Task 10 only.

**The one structural risk, stated rather than hidden.** Between Task 5 and Task 9 the suite is red: `forms.py` changes its keyword argument, and the six view modules that call it convert one at a time afterwards. This is deliberate — the alternative is a compatibility shim accepting both `user=` and `household=`, which is exactly the kind of thing that survives a phase and becomes permanent. Each commit is still atomic and reviewable; only the *sequence* passes through red. If a reviewer needs green at every commit, merge Tasks 5-9 into one commit rather than adding the shim.

**Why the fixtures come first.** The `user` fixture creates a user with **no `Membership`**, so `resolve_active_household` returns `None` and every converted read returns `.none()`. Nothing catches that today, because a test asserting "the neighbour's row is absent" passes just as well when *everything* is absent. Task 1 seeds the household before any read path converts, and Task 2's `test_projection_of_no_household_is_empty_not_everything` pins the fail-closed behaviour so it stays a decision rather than an accident.

**And why Step 7b exists.** An earlier draft of this plan patched `logged_client` in the two app conftests and stopped there. That is not enough: nine test modules define their own `logged_client`, a local fixture beats a conftest one, and those nine cover roughly 80 of the view tests that Tasks 6-10 rely on as proof. The failure is silent in the worst way — the suite goes green, the ratchet empties, every isolation assertion holds, and none of them is testing tenancy. Grep for the shadow, do not assume the conftest wins.
