# E04 Phase 4 — Prove the Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish E04 — make `household` NOT NULL, drop `user` from the twelve domain models that no longer need it, delete the write bridge, convert 612 test call sites from `user=` to `household=`, and land the systematic cross-household isolation test that makes a future unscoped model fail the suite instead of leaking.

**Architecture:** The safety net comes first and the destructive schema change comes last. A parameterized test over `accounts.models.household_owned_models()` — discovered, not hand-listed — asserts every domain model rejects cross-household access before anything is dropped. Then a three-beat schema dance keeps the suite green at every commit: `user` becomes **nullable**, ~612 test and production write sites move from `user=` to `household=` under a static ratchet that counts what is left, and only then does `household` become NOT NULL and `user` disappear. The codemod is an AST-driven script, not a hand edit, because 612 sites edited by hand is 612 chances to typo a fixture name into a silently-empty queryset.

**Tech Stack:** Django 6, PostgreSQL 17 (pgvector image on `:5433` locally, Supabase in production), pytest + pytest-django + model_bakery, PydanticAI, DRF, ruff, uv.

## Global Constraints

From `docs/backlog/INDEX.md` §7, the E04 epic, and the user's standing preferences. Every task's requirements implicitly include this section.

- **TDD.** Test first, always. Red → green → refactor. The codemod tasks are the one structured exception: their "test" is the existing suite, which must stay green across a mechanical rewrite.
- **Worktrees.** This work happens in an isolated worktree, not on `main`. Base it on **local `HEAD`**, not `origin/main` — origin is 28+ commits behind and has no E04 at all.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean.
- **pt-BR in the product UI, English in code, comments, and docs.**
- **No time-bomb tests.** Date-sensitive tests freeze the clock (`time_machine`). The suite runs under `TEST_CLOCK_SHIFT=+1y` in CI and must stay green.
- **One task, one commit.** The epic's risk note: *"a missed call site is a cross-tenant data leak, not a bug."* Do not batch.
- **No AI attribution in commit messages.** No `Co-Authored-By`, no "Generated with", no mention of Claude/Anthropic.
- **The money boundary holds.** No arithmetic changes anywhere in this phase. Task 15 proves it against a copy of the real Supabase ledger.
- **Never lose data.** Task 13 drops columns. It runs against a rehearsed copy first (Task 15 is the rehearsal against production data, and it gates the deploy, not this branch's merge).

### Decisions already made — do not re-litigate

1. **`AssistantUsageEvent` keeps its `user` column, forever.** `user` there is the *actor*, not the tenant: rate limiting is per-person, so two people in one household each get their own budget. Phase 2 decided it, phase 3 encoded it in the ratchet's `ACTOR_SCOPED` set, and this phase does not revisit it. It does gain an explicit `household=` at its one write site (Task 10) because it inherits `HouseholdOwnedModel` and phase 4 makes that column NOT NULL.
2. **`PaymentMethodClosingDay` gets no household column.** Epic decision 4. It is scoped transitively through `PaymentMethod`. Task 1 asserts that transitive path rather than assuming it.
3. **`created_by` is nullable and stays nullable.** `SET_NULL`, so a member leaving does not delete the household's financial history. A row written by a management command or by the system legitimately has no author.
4. **The three-beat schema dance is the plan's spine.** `user` nullable (Task 2) → 612 sites converted (Tasks 4-11) → `household` NOT NULL + bridge deleted (Task 12) → `user` dropped (Task 13). Do not collapse it. Making `user` nullable first is what lets a single mechanical pass *replace* `user=` with `household=` instead of two passes that first add and later remove.
5. **The codemod is a script, committed to `scripts/`, and deleted in Task 16.** Not a sed, not a hand edit. It identifies call sites through the AST so it cannot accidentally rewrite `Membership(user=…)`, `client.force_login(user)`, `AgentScope(…, user=user)` or `baker.make("core.CustomUser", …)`.
6. **`dump_ledger_totals` is re-pointed at household in Task 13**, which is the commit that removes its `E04_TRANSITION_TOOLS` exemption and empties that set for good. Phase 3 promised exactly this.
7. **`transfer_entries` export moves to `created_by`, not household.** Phase 3's self-review kept `filter(user__username=…)` on the grounds that "whose rows to export" is a person question. That lookup stops existing when `Entry.user` is dropped, so the person question is answered by `created_by` from Task 13 on. The JSON wire format keeps its `"user"` key so an export taken today still imports tomorrow.

### The measured inventory — read this before Task 4

Everything below was counted by AST over the tree at `a51348a`, not estimated.

| Fact | Number |
|---|---|
| Concrete models carrying `household` | 13 |
| Of those, models losing `user` in Task 13 | 12 (all but `AssistantUsageEvent`) |
| Test call sites passing `user=` to a household-owned model without `household=` | **612** |
| Test files containing at least one | **79** |
| Test call sites already passing both `user=` and `household=` | 76 |
| Production write sites that still rely on the bridge to fill `household` | **4** |
| Baseline suite, `POSTGRES_PORT=5433 uv run pytest src/backend/ -q` | **1100 passed, 2 skipped** |

The 612 sites use only seven distinct expressions for the user:

| Expression | Sites | Rewrites to |
|---|---|---|
| `user=user` | 439 | `household=household` (fixture) |
| `user=self.user` | 37 | `household=household_for_user(self.user)` |
| `user=other_user` | 24 | `household=other_household` (fixture) |
| `user=seeded_user` | 16 | `household=household` — `seeded_user` *is* the `user` fixture |
| `user=other` | 12 | `household=household_for_user(other)` |
| `user=self.other_user` | 3 | `household=household_for_user(self.other_user)` |
| `user=context["user"]` | 1 | `household=household_for_user(context["user"])` |

`household_for_user` is idempotent and returns the same object the `household` fixture returns, so the inline form and the fixture form agree by construction. That is why the class-based `TestCase` modules need **no `setUp` surgery at all** — the inline call works from any method.

### The four production write sites that lean on the bridge

Found by AST, not by grep — a bare grep for `household=` misses them because they never mention it:

| Site | What it writes | Why it matters |
|---|---|---|
| `finances/models/systemic_expense.py:42` | `Entry.objects.create(user=self.user, …)` | Every generated systemic entry |
| `assistant/views.py:161` | `AssistantUsageEvent.objects.acreate(user=user, kind=kind)` | Every admitted assistant turn |
| `finances/management/commands/seed_data.py:61,74` | `Category`/`PaymentMethod.get_or_create(user=user, name=…)` | The onboarding seed. Its `get_or_create` never matched the ratchet's regex — see Task 10 |
| `finances/management/commands/seed_perf_data.py:104-106` | `Category`/`PaymentMethod.objects.create(user=user, …)` | The E03 benchmark harness |

Each becomes an `IntegrityError` the moment Task 12 lands. Task 10 converts them first.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# One module while iterating
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_entries.py -q

# The two ratchets, after every task
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py src/backend/accounts/tests/test_bake_scoping.py -q

# Gates
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

**Do not run two pytest invocations concurrently** — they share `test_expense_tracker` and the second dies with `database "test_expense_tracker" is being accessed by other users`. This was re-confirmed on 2026-08-13: a concurrent run reported 28 spurious errors.

**Before Task 1, record the baseline:**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -3
```

Expected today: `1100 passed, 2 skipped`. Every task below expects that number plus its own new tests, and **zero failures**.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/backend/accounts/tests/test_cross_household_isolation.py` | S04-6's systematic assertion: every *discovered* domain model rejects cross-household access; every finances/assistant model is either household-owned or explicitly exempt | create |
| `src/backend/accounts/tests/test_shared_household.py` | The new capability: two users in one household see identical ledger data, through the real HTTP path | create |
| `src/backend/accounts/tests/test_bake_scoping.py` | The bake ratchet — no test may create a household-owned row without saying which household | create, then shrink each task |
| `scripts/e04-retenant-tests.py` | The AST codemod that rewrites `user=` to `household=` at 612 sites | create (Task 4), delete (Task 16) |
| `src/backend/accounts/models.py` | `HouseholdOwnedModel.household` → NOT NULL | modify (Task 12) |
| `src/backend/accounts/bridge.py`, `src/backend/accounts/tests/test_bridge.py` | delete | delete (Task 12) |
| `src/backend/accounts/apps.py` | stop wiring the bridge | modify (Task 12) |
| `src/backend/accounts/tests/test_scoping_ratchet.py` | tighten the regex (Task 10); flatten to the plain assertion S04-2 asked for (Task 13) | modify |
| `src/backend/finances/models/*.py`, `src/backend/assistant/models.py` | `user` nullable (Task 2), then removed with its constraints and indexes (Task 13) | modify |
| `src/backend/*/migrations/` | three migrations: `user` nullable, `household` NOT NULL, drop `user` | create |
| 79 test modules | `user=` → `household=` | modify (Tasks 4-9, 11) |
| `src/backend/finances/models/systemic_expense.py`, `src/backend/assistant/views.py`, two seed commands | set `household` explicitly | modify (Task 10) |
| `src/backend/finances/tests/test_query_indexes.py` | assert the *household*-leading indexes are chosen by the planner | modify (Task 11) |
| `src/backend/finances/management/commands/{dump_ledger_totals,transfer_entries}.py` | re-point at household / `created_by` | modify (Task 13) |
| `src/backend/finances/admin.py`, `src/backend/assistant/admin.py` | `user` columns → `household` | modify (Task 13) |
| `scripts/rehearse-e04-migration.sh` | teach it the phase-4 schema | modify (Task 15) |
| `docs/architecture/query-performance-baseline.md` | the "After E04" measurement | modify (Task 14) |
| `docs/backlog/E04-household-tenancy.md`, `docs/runbook.md` | tick the DoD, document the rehearsal | modify (Task 16) |

**Out of scope, do not touch:** `accounts/middleware.py`, `accounts/scoping.py`, `accounts/mixins.py`, `accounts/resolution.py` (all correct as they stand), invitation flows (E05), `Membership` role logic beyond what exists, and Postgres RLS (parked).

---

### Task 1: The systematic cross-household isolation test

The epic's own risk note says to write this early, not last: *"a missed call site is a cross-tenant data leak, not a bug. The parameterized test in S04-6 is what catches misses; write it early."* It goes green immediately against today's schema, and then guards every destructive step that follows.

Phase 2 left two hand-written parameterized files (`finances/tests/test_household_columns.py`, `assistant/tests/test_household_columns.py`). Those stay — they assert *column* facts per app. This task adds the thing neither of them is: one test **discovered** from `household_owned_models()`, so a model added in E07 or E12 without a household column fails the suite rather than shipping.

**Files:**
- Create: `src/backend/accounts/tests/test_cross_household_isolation.py`
- Create: `src/backend/accounts/tests/test_shared_household.py`

**Interfaces:**
- Consumes: `accounts.models.household_owned_models()`, `accounts.models.Household`, `accounts.models.Membership`, `accounts.models.Role`, `accounts.resolution.household_for_user`, the root conftest's `user` / `other_user` / `household` / `other_household` / `logged_client` fixtures.
- Produces: nothing importable. These are assertions, not building blocks.

- [ ] **Step 1: Write the isolation test**

`src/backend/accounts/tests/test_cross_household_isolation.py`:

```python
"""S04-6: no domain model can be read across a household boundary.

Parameterized over ``household_owned_models()`` — *discovered* from the base
class, never a hand-written list. A model added later that inherits the base
is covered here automatically; one that forgets to inherit it fails
``test_every_domain_model_is_household_owned``. That pair is the whole point:
the epic's failure mode is a model nobody remembered to scope.

``PaymentMethodClosingDay`` has no household column by decision 4 of the epic.
It is covered through its parent instead, at the bottom of this file.
"""

import pytest
from model_bakery import baker

from accounts.models import Household, household_owned_models

pytestmark = pytest.mark.django_db

# Models in the domain apps that deliberately carry no household column.
# Adding to this set is a decision, not a convenience — every entry needs a
# reason recorded in the epic.
EXEMPT = {
    # Epic decision 4: scoped transitively through PaymentMethod.
    "finances.PaymentMethodClosingDay",
}


def _extras(model):
    """Fields model_bakery cannot invent.

    pgvector's ``VectorField`` has no baker generator, so the embedding has to
    be handed over explicitly.
    """
    if model._meta.label == "assistant.MemoryEmbedding":
        return {"embedding": [0.1] * 1536}
    return {}


def _labels():
    return sorted(m._meta.label for m in household_owned_models())


@pytest.mark.parametrize("label", _labels())
def test_model_rejects_rows_from_another_household(label):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    extras = _extras(model)
    mine = baker.make(model, household=ours, **extras)
    baker.make(model, household=theirs, **extras)

    scoped = model.objects.for_household(ours)

    assert list(scoped) == [mine]


@pytest.mark.parametrize("label", _labels())
def test_model_with_no_household_returns_nothing_not_everything(label):
    """Fail closed. An unresolved tenant must never mean 'the whole table'."""
    from django.apps import apps

    model = apps.get_model(label)
    baker.make(model, household=baker.make(Household), **_extras(model))

    assert model.objects.for_household(None).count() == 0


def test_every_domain_model_is_household_owned():
    """The counterpart that catches a model added *without* the base class."""
    from django.apps import apps

    owned = {m._meta.label for m in household_owned_models()}
    domain = {
        m._meta.label
        for app in ("finances", "assistant")
        for m in apps.get_app_config(app).get_models()
    }

    unscoped = sorted(domain - owned - EXEMPT)

    assert not unscoped, (
        "These domain models carry no household column. Inherit "
        f"HouseholdOwnedModel, or add them to EXEMPT with a reason: {unscoped}"
    )


def test_closing_day_is_unreachable_from_a_foreign_payment_method(
    user, household, other_user, other_household
):
    """Decision 4, asserted rather than assumed: the only route to a closing
    day is through a PaymentMethod, so scoping the parent scopes the child."""
    from finances.models import PaymentMethod, PaymentMethodClosingDay

    theirs = baker.make(
        PaymentMethod,
        user=other_user,
        household=other_household,
        name="Cartao do vizinho",
        type="credit_card",
    )
    baker.make(
        PaymentMethodClosingDay,
        payment_method=theirs,
        month="2026-03-01",
        closing_day=12,
    )

    reachable = PaymentMethodClosingDay.objects.filter(
        payment_method__in=PaymentMethod.objects.for_household(household)
    )

    assert reachable.count() == 0
```

> `baker.make(model, household=ours)` with no `user=` works today because `user` is still NOT NULL and model_bakery invents one. That is deliberate: this test must not depend on the column it is about to outlive.

- [ ] **Step 2: Run it**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_cross_household_isolation.py -q`
Expected: PASS — 27 tests (13 models × 2 parameterized + 2 flat). If `test_every_domain_model_is_household_owned` fails, a model was added since 2026-08-13 without a household; stop and decide, do not add it to `EXEMPT` reflexively.

- [ ] **Step 3: Write the shared-household test**

This is the *capability* half of the epic, and nothing has asserted it yet. `src/backend/accounts/tests/test_shared_household.py`:

```python
"""The point of the whole epic: two people, one ledger.

Every other test in this branch asserts a boundary holds. This one asserts the
boundary is in the right place — Amanda, a member of Vagner's household, sees
Vagner's entries. Through the real HTTP path, because the middleware resolving
`request.household` is the part that has to work.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.models import Membership, Role
from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


@pytest.fixture
def amanda(user, household):
    """A second person in the *same* household."""
    person = baker.make("core.CustomUser", username="amanda")
    baker.make(Membership, user=person, household=household, role=Role.MEMBER)
    return person


@pytest.fixture
def amandas_client(amanda):
    client = Client()
    client.force_login(amanda)
    return client


@pytest.fixture
def vagners_entry(user, household):
    category = baker.make("finances.Category", user=user, household=household, name="Mercado")
    pm = baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )
    return baker.make(
        "finances.Entry",
        user=user,
        household=household,
        created_by=user,
        category=category,
        payment_method=pm,
        amount=Decimal("42.00"),
        description="Feira da semana",
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )


def test_a_member_sees_the_other_members_entries(amandas_client, vagners_entry):
    response = amandas_client.get(reverse("finances:entries_month", args=[2026, 3]))

    assert response.status_code == 200
    assert "Feira da semana" in response.content.decode()


def test_a_member_can_open_the_other_members_entry(amandas_client, vagners_entry):
    """Not merely visible in a list — editable. Shared ledger, not shared view."""
    response = amandas_client.get(
        reverse("finances:entry_edit_modal", args=[vagners_entry.pk])
    )

    assert response.status_code == 200


def test_provenance_survives_the_sharing(vagners_entry, user):
    """Shared does not mean anonymous — E17 surfaces who wrote a row."""
    assert vagners_entry.created_by == user


def test_a_stranger_still_gets_a_404(logged_client, other_user, other_household):
    """The control: membership is what grants access, not being logged in."""
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

> Check the two url names against `src/backend/finances/urls.py` before running — `entries_month` and `entry_edit_modal` are the names phase 3's tests used, but confirm the argument signature rather than assuming it.

- [ ] **Step 4: Run it**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_shared_household.py -q`
Expected: PASS, 4 tests.

If `test_a_member_sees_the_other_members_entries` fails with an empty page, the middleware is not resolving Amanda's household — check that the `Membership` fixture ran before `force_login`, and read `accounts/middleware.py:resolve_active_household`. Do **not** "fix" it by giving Amanda her own household; that is the bug this test exists to find.

- [ ] **Step 5: Run the full suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: `1132 passed, 2 skipped` — 1100 baseline + 28 (13 models x 2 parameterized, plus the two flat tests) + 4. Zero failures.

- [ ] **Step 6: Commit**

```bash
git add src/backend/accounts/tests/test_cross_household_isolation.py \
        src/backend/accounts/tests/test_shared_household.py
git commit -m "test(accounts): every domain model rejects a foreign household, and one household is shared"
```

---

### Task 2: `user` becomes nullable

The enabling move. Twelve models get `null=True` on `user` so that the 612 test sites can *replace* `user=` with `household=` in one pass instead of adding `household=` now and removing `user=` later. Nothing behavioural changes: every write site still sets `user`.

`AssistantUsageEvent.user` is **not** touched — decision 1.

**Files:**
- Modify: `src/backend/finances/models/{entry,income,category,payment_method,budget,installment_plan,systemic_expense,import_batch}.py`
- Modify: `src/backend/assistant/models.py` — `ChatMessage`, `MemoryRule`, `ReceiptDraft`, `MemoryEmbedding`
- Create: `src/backend/finances/migrations/0016_user_nullable.py`
- Create: `src/backend/assistant/migrations/0013_user_nullable.py`
- Create: `src/backend/accounts/tests/test_user_column_is_on_its_way_out.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing importable. The observable change is that `Model._meta.get_field("user").null` is `True` for twelve models.

- [ ] **Step 1: Write the failing test**

`src/backend/accounts/tests/test_user_column_is_on_its_way_out.py`:

```python
"""`user` is nullable on the twelve models that lose it in Task 13.

A three-beat schema dance: nullable here, every write site converted, then the
column dropped. This test pins beat one so that beat two can rewrite ~612 test
call sites in a single mechanical pass rather than two.

`AssistantUsageEvent` is absent on purpose — its `user` is the acting member,
not the tenant, and it stays NOT NULL forever.
"""

import pytest
from django.apps import apps

LOSING_USER = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
]


@pytest.mark.parametrize("label", LOSING_USER)
def test_user_is_nullable(label):
    assert apps.get_model(label)._meta.get_field("user").null is True


def test_the_actor_column_is_not_nullable():
    """AssistantUsageEvent.user is who spent the turn. A usage event with no
    actor is meaningless, so it stays required — and it survives Task 13."""
    assert apps.get_model("assistant.AssistantUsageEvent")._meta.get_field("user").null is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_user_column_is_on_its_way_out.py -q`
Expected: FAIL — 12 failures, `assert False is True`.

- [ ] **Step 3: Make the field nullable on all twelve models**

In each model, add `null=True, blank=True` to the `user` ForeignKey and a one-line comment. For example, `src/backend/finances/models/entry.py`:

```python
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="entries",
        # E04 phase 4, beat one: nullable so the test suite can move from
        # `user=` to `household=` in one pass. The column goes entirely once
        # every write site sets a household. Do not start relying on it again.
        null=True,
        blank=True,
        # No standalone index on user_id: it is the leading column of BOTH
        # indexes in Meta, so those already serve every user-only lookup (an
        # Index Only Scan, measured). Keeping Django's default FK index here is
        # not free — it is a strict prefix of entry_user_billing_type_idx, and
        # because it is the narrower index the planner costs it lower and picks
        # it for filter(user, billing_month), then discards 96% of the rows it
        # read. Measured at 5,000 entries for one user: 1.698 ms reading 5,000
        # rows with the FK index present, 0.422 ms reading 189 without it.
        db_index=False,
    )
```

Keep every existing keyword exactly as it is — in particular `db_index=False` on `Entry.user`, `Income.user`, `ChatMessage.user` and `ReceiptDraft.user`, and every `related_name`. The only edit is the two new keywords and the comment. The comment may be shortened to one line on the other eleven; the long index note above is Entry's alone and must survive.

- [ ] **Step 4: Generate the migrations**

```bash
uv run python src/backend/manage.py makemigrations finances assistant \
  -n user_nullable
```

Expected: `finances/migrations/0016_user_nullable.py` and `assistant/migrations/0013_user_nullable.py`, each a list of `AlterField` operations and nothing else. **Read both files.** If either contains an `AddField`, `RemoveField`, `AddIndex` or `AddConstraint`, you edited something beyond the two keywords — revert and redo.

- [ ] **Step 5: Run the new test and the full suite**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_user_column_is_on_its_way_out.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: 13 passed, then `1145 passed, 2 skipped` (1132 + 13). Zero failures — nothing behavioural moved.

- [ ] **Step 6: Confirm the migration is reversible**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0015
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0012
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
```
Expected: all three succeed against the local dev database. `AlterField` back to NOT NULL only works while no row has a NULL user, which is true today — that is exactly why this migration is safe *now* and not later.

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances/models src/backend/assistant/models.py \
        src/backend/finances/migrations src/backend/assistant/migrations \
        src/backend/accounts/tests/test_user_column_is_on_its_way_out.py
git commit -m "refactor(models): user becomes nullable on the twelve models that are about to lose it"
```

---

### Task 3: The bake ratchet

Once `user` is gone, `baker.make("finances.Entry", …)` with no `household=` does not fail — model_bakery **invents a Household** to satisfy the required FK. The row lands in a household no fixture knows about, `for_household(household)` returns nothing, and `assert "Compra do vizinho" not in body` passes because the page is empty. That is phase 3's Step 7b failure mode returning in a new costume, and the fix is the same shape: catch it statically, not by hope.

This task adds the checker, seeded with the 79 files that violate it today. Tasks 4-9 and 11 empty it.

**Files:**
- Create: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Produces: `accounts.tests.test_bake_scoping.BAKE_BASELINE` — the set of test files that still create a household-owned row without naming its household. May shrink, never grow.

- [ ] **Step 1: Write the checker with an empty baseline**

`src/backend/accounts/tests/test_bake_scoping.py`:

```python
"""No test may create a household-owned row without saying which household.

The trap this closes: once `user` is dropped, `household` is a required FK, and
model_bakery satisfies a required FK by *inventing* a related object. A bake
that names no household therefore lands in a brand-new one, `for_household()`
returns nothing, and every "the neighbour's row is absent" assertion passes
because *everything* is absent. Phase 3 hit the same class of bug through
shadowed `logged_client` fixtures; the lesson was to catch it statically.

A ratchet, like `test_scoping_ratchet.py`: BAKE_BASELINE may shrink and never
grow, and Task 16 deletes it once it is empty.
"""

import ast
from pathlib import Path

# tests → accounts → backend → src → repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND = REPO_ROOT / "src" / "backend"

# The concrete models carrying a household column. Spelled out rather than
# discovered because this check parses source, and importing Django's app
# registry to decide what a *string* in someone else's file means would be
# reading the code twice with two different answers.
HOUSEHOLD_OWNED = {
    "Entry",
    "Income",
    "Category",
    "PaymentMethod",
    "Budget",
    "InstallmentPlan",
    "SystemicExpense",
    "ImportBatch",
    "ChatMessage",
    "MemoryRule",
    "ReceiptDraft",
    "MemoryEmbedding",
    "AssistantUsageEvent",
}

BAKE_BASELINE = set()  # seeded in Step 3


def _model_name(call):
    """The model a `baker.make(...)` call targets, or None."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split(".")[-1]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return first.attr
    return None


def _violations_in(tree):
    """Calls that build a household-owned row without a `household=` keyword."""
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        keywords = {kw.arg for kw in node.keywords if kw.arg}
        if "household" in keywords:
            continue

        if isinstance(func, ast.Attribute) and func.attr in {"make", "prepare"}:
            if _model_name(node) in HOUSEHOLD_OWNED:
                found += 1
        elif isinstance(func, ast.Attribute) and func.attr in {"create", "acreate"}:
            target = ast.unparse(func.value)
            if any(target.startswith(model) for model in HOUSEHOLD_OWNED):
                found += 1
        elif isinstance(func, ast.Name) and func.id in HOUSEHOLD_OWNED:
            # A bare constructor, e.g. inside a bulk_create list comprehension.
            found += 1
    return found


def _files_baking_without_a_household():
    offenders = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/tests/" not in rel and not rel.endswith("conftest.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        if _violations_in(tree):
            offenders.add(rel)
    return offenders


def test_no_new_test_bakes_a_row_without_a_household():
    regressions = sorted(_files_baking_without_a_household() - BAKE_BASELINE)
    assert not regressions, (
        "These tests create a household-owned row without saying which "
        "household. model_bakery will invent one, and the assertion will pass "
        f"against an empty queryset: {regressions}"
    )


def test_bake_baseline_has_no_stale_entries():
    stale = sorted(BAKE_BASELINE - _files_baking_without_a_household())
    assert not stale, f"These files are clean — remove them from BAKE_BASELINE: {stale}"
```

- [ ] **Step 2: Run it to see the violations**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q`
Expected: FAIL on `test_no_new_test_bakes_a_row_without_a_household`, listing 79 files.

- [ ] **Step 3: Seed the baseline from that failure**

Paste the 79 paths from the failure message into `BAKE_BASELINE` as a sorted set literal, replacing `set()`. They are, at `a51348a` (already sorted — this is the authoritative list Tasks 4-9 and 11 strike from):

```python
BAKE_BASELINE = {
    "src/backend/accounts/tests/test_backfill.py",
    "src/backend/accounts/tests/test_bridge.py",
    "src/backend/assistant/tests/test_analytics.py",
    "src/backend/assistant/tests/test_assistant.py",
    "src/backend/assistant/tests/test_category_memory.py",
    "src/backend/assistant/tests/test_create_entry_fuzzy.py",
    "src/backend/assistant/tests/test_image_extraction_regression.py",
    "src/backend/assistant/tests/test_memory_models.py",
    "src/backend/assistant/tests/test_memory_tools.py",
    "src/backend/assistant/tests/test_models.py",
    "src/backend/assistant/tests/test_receipt_date_and_dup.py",
    "src/backend/assistant/tests/test_receipt_discount_reconcile.py",
    "src/backend/assistant/tests/test_receipt_flow.py",
    "src/backend/assistant/tests/test_receipt_prompts.py",
    "src/backend/assistant/tests/test_semantic_memory.py",
    "src/backend/assistant/tests/test_simulate_projection.py",
    "src/backend/assistant/tests/test_throttling.py",
    "src/backend/assistant/tests/test_tools.py",
    "src/backend/assistant/tests/test_views.py",
    "src/backend/finances/tests/features/test_billing_cycle.py",
    "src/backend/finances/tests/features/test_installments.py",
    "src/backend/finances/tests/features/test_views.py",
    "src/backend/finances/tests/test_api_dashboard.py",
    "src/backend/finances/tests/test_backfill_billing_months.py",
    "src/backend/finances/tests/test_budget_model.py",
    "src/backend/finances/tests/test_budget_stats.py",
    "src/backend/finances/tests/test_category.py",
    "src/backend/finances/tests/test_category_stats.py",
    "src/backend/finances/tests/test_cockpit_income_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_income_views.py",
    "src/backend/finances/tests/test_cockpit_parcelamento_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_parcelamento_manage.py",
    "src/backend/finances/tests/test_cockpit_parcelamentos_views.py",
    "src/backend/finances/tests/test_cockpit_systemic_create.py",
    "src/backend/finances/tests/test_cockpit_systemic_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_systemic_views.py",
    "src/backend/finances/tests/test_cockpit_vencimentos.py",
    "src/backend/finances/tests/test_consolidated_detail_filter.py",
    "src/backend/finances/tests/test_consolidated_dropdown.py",
    "src/backend/finances/tests/test_csrf_htmx.py",
    "src/backend/finances/tests/test_daily_trend.py",
    "src/backend/finances/tests/test_diverse_savings.py",
    "src/backend/finances/tests/test_dump_ledger_totals.py",
    "src/backend/finances/tests/test_entries_live_summary.py",
    "src/backend/finances/tests/test_entries_pre_origin.py",
    "src/backend/finances/tests/test_entry.py",
    "src/backend/finances/tests/test_entry_edit_modal.py",
    "src/backend/finances/tests/test_entry_mobile_card.py",
    "src/backend/finances/tests/test_fix_misdated_entries.py",
    "src/backend/finances/tests/test_forms.py",
    "src/backend/finances/tests/test_hot_path_query_counts.py",
    "src/backend/finances/tests/test_household_columns.py",
    "src/backend/finances/tests/test_import_double_submit.py",
    "src/backend/finances/tests/test_import_query_count.py",
    "src/backend/finances/tests/test_income.py",
    "src/backend/finances/tests/test_income_recurrence.py",
    "src/backend/finances/tests/test_installment_billing_months.py",
    "src/backend/finances/tests/test_installment_month.py",
    "src/backend/finances/tests/test_installment_plan.py",
    "src/backend/finances/tests/test_installment_plan_management.py",
    "src/backend/finances/tests/test_installment_preview.py",
    "src/backend/finances/tests/test_migration_freeze_billing_month.py",
    "src/backend/finances/tests/test_payment_method.py",
    "src/backend/finances/tests/test_payment_method_closing_day.py",
    "src/backend/finances/tests/test_projection_estimated.py",
    "src/backend/finances/tests/test_projection_service.py",
    "src/backend/finances/tests/test_query_indexes.py",
    "src/backend/finances/tests/test_recompute_category_averages.py",
    "src/backend/finances/tests/test_seed_data.py",
    "src/backend/finances/tests/test_settings_income_groups.py",
    "src/backend/finances/tests/test_systemic_expense.py",
    "src/backend/finances/tests/test_systemic_month.py",
    "src/backend/finances/tests/test_systemic_recurrence.py",
    "src/backend/finances/tests/test_transfer_entries.py",
    "src/backend/finances/tests/test_views_consolidated.py",
    "src/backend/finances/tests/test_views_entries.py",
    "src/backend/finances/tests/test_views_importer.py",
    "src/backend/finances/tests/test_views_projection.py",
    "src/backend/finances/tests/test_views_settings.py",
}
```

If the failure message lists a file that is not here, add it — the tree has moved since this plan was written, and the ratchet is right.

- [ ] **Step 4: Run it green**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(accounts): a ratchet for tests that create a row without naming its household"
```

---

### Task 4: The codemod, and the finances service tests

The tool plus its first real workload. Thirteen modules, 101 call sites — the services layer, where an unscoped read is a wrong *number* rather than a wrong page, so it is the group where a mistake is most visible.

**Files:**
- Create: `scripts/e04-retenant-tests.py`
- Modify (13): `src/backend/finances/tests/` — `test_projection_service.py`, `test_budget_stats.py`, `test_category_stats.py`, `test_systemic_month.py`, `test_income_recurrence.py`, `test_dump_ledger_totals.py`, `test_projection_estimated.py`, `test_recompute_category_averages.py`, `test_installment_month.py`, `test_diverse_savings.py`, `test_systemic_recurrence.py`, `test_daily_trend.py`, `test_installment_billing_months.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py` — strike those 13

**Interfaces:**
- Produces: `scripts/e04-retenant-tests.py`, a CLI taking file paths. It rewrites, in place, the `user=` keyword of any call that builds a household-owned row, and reports what it could not decide. It is idempotent: a second run over the same file changes nothing.

- [ ] **Step 1: Write the codemod**

`scripts/e04-retenant-tests.py`:

```python
#!/usr/bin/env python3
"""Rewrite `user=` to `household=` at E04 phase 4's test call sites.

612 call sites across 79 files build a household-owned row and name only the
user. Hand-editing them is 612 chances to typo a fixture name into a silently
empty queryset, so this does it structurally: the AST decides *which* keyword
to touch, and only its exact source span is rewritten, leaving formatting,
comments and every other argument untouched.

Two shapes come out:

    user=user          ->  household=household          (the root conftest fixture)
    user=<anything>    ->  household=household_for_user(<anything>)

`household_for_user` is idempotent and returns the same object the `household`
fixture returns, so the two forms agree by construction — which is why class-
based TestCase modules need no setUp surgery: the inline call works from any
method.

Where the call already passes `household=`, the `user=` keyword is deleted
instead, together with its trailing comma and whitespace.

`AssistantUsageEvent` is never touched: its `user` is the acting member and
survives phase 4. Those call sites are listed for manual handling.

Usage:
    uv run python scripts/e04-retenant-tests.py src/backend/finances/tests/test_entry.py ...
    uv run ruff format <the same paths>
"""

import ast
import sys
from pathlib import Path

HOUSEHOLD_OWNED = {
    "Entry",
    "Income",
    "Category",
    "PaymentMethod",
    "Budget",
    "InstallmentPlan",
    "SystemicExpense",
    "ImportBatch",
    "ChatMessage",
    "MemoryRule",
    "ReceiptDraft",
    "MemoryEmbedding",
}
KEEPS_USER = {"AssistantUsageEvent"}

# Expressions that map onto a fixture rather than a lookup. `seeded_user` is
# the `user` fixture with a catalogue attached, so its household is `household`.
FIXTURE_MAP = {
    "user": "household",
    "other_user": "other_household",
    "seeded_user": "household",
}

IMPORT_LINE = "from accounts.resolution import household_for_user\n"


def _model_name(call):
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split(".")[-1]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return first.attr
    return None


def _target_model(call):
    """The household-owned model this call builds, or None."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in {"make", "prepare"}:
        return _model_name(call)
    if isinstance(func, ast.Attribute) and func.attr in {"create", "acreate"}:
        target = ast.unparse(func.value)
        for model in HOUSEHOLD_OWNED | KEEPS_USER:
            if target.startswith(model):
                return model
        return None
    if isinstance(func, ast.Name):
        return func.id
    return None


def _offset(lines, lineno, col):
    """Absolute character offset of (1-based lineno, 0-based col)."""
    return sum(len(line) for line in lines[: lineno - 1]) + col


def _span(source, lines, keyword):
    start = _offset(lines, keyword.lineno, keyword.col_offset)
    end = _offset(lines, keyword.value.end_lineno, keyword.value.end_col_offset)
    return start, end


def _eat_trailing_comma(source, end):
    """Extend a deletion span past `, ` or `,\n    ` so the call still parses."""
    i = end
    while i < len(source) and source[i] in " \t":
        i += 1
    if i < len(source) and source[i] == ",":
        i += 1
        while i < len(source) and source[i] in " \t":
            i += 1
        if i < len(source) and source[i] == "\n":
            i += 1
            while i < len(source) and source[i] in " \t":
                i += 1
    return i


def rewrite(path):
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    edits = []          # (start, end, replacement)
    needs_import = False
    manual = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        model = _target_model(node)
        if model is None:
            continue
        user_kw = next((kw for kw in node.keywords if kw.arg == "user"), None)
        if user_kw is None:
            continue
        has_household = any(kw.arg == "household" for kw in node.keywords)

        if model in KEEPS_USER:
            if not has_household:
                manual.append((node.lineno, f"{model}: add household= by hand"))
            continue
        if model not in HOUSEHOLD_OWNED:
            continue

        start, end = _span(source, lines, user_kw)
        if has_household:
            edits.append((start, _eat_trailing_comma(source, end), ""))
            continue

        expression = ast.unparse(user_kw.value)
        if expression in FIXTURE_MAP:
            replacement = f"household={FIXTURE_MAP[expression]}"
        else:
            replacement = f"household=household_for_user({expression})"
            needs_import = True
        edits.append((start, end, replacement))

    if not edits:
        return 0, manual

    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]

    if needs_import and IMPORT_LINE not in source:
        source = _insert_import(source)

    path.write_text(source, encoding="utf-8")
    return len(edits), manual


def _insert_import(source):
    """Put the import after the last existing top-level import line.

    Deliberately crude: `ruff format` and `ruff check --fix` sort and dedupe
    imports afterwards, so getting the position roughly right is enough.
    """
    lines = source.splitlines(keepends=True)
    last = 0
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            last = i
    lines.insert(last + 1, IMPORT_LINE)
    return "".join(lines)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    total = 0
    for raw in argv:
        path = Path(raw)
        count, manual = rewrite(path)
        total += count
        print(f"{count:4d}  {path}")
        for lineno, note in manual:
            print(f"      !! {path}:{lineno} {note}")
    print(f"---- {total} call sites rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Dry-run it on one small file and read the diff**

```bash
uv run python scripts/e04-retenant-tests.py src/backend/finances/tests/test_daily_trend.py
git diff src/backend/finances/tests/test_daily_trend.py
```

Expected: exactly one hunk, `user=user` → `household=household`, nothing else moved. **Read the diff before running the tool on 13 files.** If it touched a `baker.make("core.CustomUser", …)` call or a `client.force_login`, stop — the AST predicate is wrong and every later task inherits the bug.

- [ ] **Step 3: Run it over the group**

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
uv run python scripts/e04-retenant-tests.py \
  src/backend/finances/tests/test_projection_service.py \
  src/backend/finances/tests/test_budget_stats.py \
  src/backend/finances/tests/test_category_stats.py \
  src/backend/finances/tests/test_systemic_month.py \
  src/backend/finances/tests/test_income_recurrence.py \
  src/backend/finances/tests/test_dump_ledger_totals.py \
  src/backend/finances/tests/test_projection_estimated.py \
  src/backend/finances/tests/test_recompute_category_averages.py \
  src/backend/finances/tests/test_installment_month.py \
  src/backend/finances/tests/test_diverse_savings.py \
  src/backend/finances/tests/test_systemic_recurrence.py \
  src/backend/finances/tests/test_installment_billing_months.py
uv run ruff check --fix src/backend/finances/tests/
uv run ruff format src/backend/finances/tests/
```

Expected: about 100 call sites rewritten across the twelve files (`test_daily_trend.py` was done in Step 2). Zero `!!` lines — no `AssistantUsageEvent` in this group.

- [ ] **Step 4: Add the missing fixture parameters**

The rewrite introduces `household` and `other_household` into function bodies that may not request them. Those are `NameError`s, which is the point — they are loud. Run the group and fix each one by adding the fixture to the test's signature:

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_projection_service.py \
  src/backend/finances/tests/test_budget_stats.py \
  src/backend/finances/tests/test_category_stats.py \
  src/backend/finances/tests/test_systemic_month.py \
  src/backend/finances/tests/test_income_recurrence.py \
  src/backend/finances/tests/test_dump_ledger_totals.py \
  src/backend/finances/tests/test_projection_estimated.py \
  src/backend/finances/tests/test_recompute_category_averages.py \
  src/backend/finances/tests/test_installment_month.py \
  src/backend/finances/tests/test_diverse_savings.py \
  src/backend/finances/tests/test_systemic_recurrence.py \
  src/backend/finances/tests/test_daily_trend.py \
  src/backend/finances/tests/test_installment_billing_months.py -q
```

The pattern, in both directions:

```python
# BEFORE
def test_something(user):
    baker.make("finances.Entry", household=household, ...)   # NameError

# AFTER
def test_something(user, household):
    baker.make("finances.Entry", household=household, ...)
```

A test whose `user` parameter is now unused entirely: **delete the parameter**. `ruff` will not flag an unused pytest fixture argument, so this is a judgement call — remove it when the body no longer mentions `user`, keep it when it does (a `created_by=user` or a `force_login(user)`).

> `test_dump_ledger_totals.py` is the one to read rather than skim. It asserts on the fingerprint command's output, keyed by username. That command is not converted until Task 13, so its assertions must still hold here. If a test in it fails on *values* rather than a `NameError`, stop and read: a changed total is the money boundary moving, which this phase forbids.

- [ ] **Step 5: Run the group green**

Re-run the command from Step 4.
Expected: PASS, all thirteen modules.

- [ ] **Step 6: Strike the thirteen from the ratchet**

Delete these lines from `BAKE_BASELINE` in `src/backend/accounts/tests/test_bake_scoping.py`:

```
    "src/backend/finances/tests/test_budget_stats.py",
    "src/backend/finances/tests/test_category_stats.py",
    "src/backend/finances/tests/test_daily_trend.py",
    "src/backend/finances/tests/test_diverse_savings.py",
    "src/backend/finances/tests/test_dump_ledger_totals.py",
    "src/backend/finances/tests/test_income_recurrence.py",
    "src/backend/finances/tests/test_installment_billing_months.py",
    "src/backend/finances/tests/test_installment_month.py",
    "src/backend/finances/tests/test_projection_estimated.py",
    "src/backend/finances/tests/test_projection_service.py",
    "src/backend/finances/tests/test_recompute_category_averages.py",
    "src/backend/finances/tests/test_systemic_month.py",
    "src/backend/finances/tests/test_systemic_recurrence.py",
```

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q`
Expected: 2 passed. `BAKE_BASELINE` is now 66 entries.

- [ ] **Step 7: Run the full suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: `1147 passed, 2 skipped` (1145 + Task 3's two ratchet tests). Zero failures.

- [ ] **Step 8: Commit**

```bash
git add scripts/e04-retenant-tests.py src/backend/finances/tests \
        src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): the service tests name their household, and a codemod to say it once"
```

---

### Task 5: Model and management-command tests

Fifteen modules, 98 call sites. Mechanically identical to Task 4 — same tool, same three follow-up shapes — with two files that need reading rather than running.

**Files:**
- Modify (15): `src/backend/finances/tests/` — `test_entry.py`, `test_installment_plan.py`, `test_category.py`, `test_payment_method_closing_day.py`, `test_systemic_expense.py`, `test_budget_model.py`, `test_income.py`, `test_payment_method.py`, `test_migration_freeze_billing_month.py`, `test_backfill_billing_months.py`, `test_fix_misdated_entries.py`, `test_transfer_entries.py`, `test_installment_plan_management.py`, `test_seed_data.py`, `test_household_columns.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: `scripts/e04-retenant-tests.py` from Task 4.
- Produces: nothing importable.

- [ ] **Step 1: Run the codemod**

```bash
uv run python scripts/e04-retenant-tests.py \
  src/backend/finances/tests/test_entry.py \
  src/backend/finances/tests/test_installment_plan.py \
  src/backend/finances/tests/test_category.py \
  src/backend/finances/tests/test_payment_method_closing_day.py \
  src/backend/finances/tests/test_systemic_expense.py \
  src/backend/finances/tests/test_budget_model.py \
  src/backend/finances/tests/test_income.py \
  src/backend/finances/tests/test_payment_method.py \
  src/backend/finances/tests/test_migration_freeze_billing_month.py \
  src/backend/finances/tests/test_backfill_billing_months.py \
  src/backend/finances/tests/test_fix_misdated_entries.py \
  src/backend/finances/tests/test_transfer_entries.py \
  src/backend/finances/tests/test_installment_plan_management.py \
  src/backend/finances/tests/test_seed_data.py \
  src/backend/finances/tests/test_household_columns.py
uv run ruff check --fix src/backend/finances/tests/
uv run ruff format src/backend/finances/tests/
```

Expected: ~98 call sites rewritten, no `!!` lines.

- [ ] **Step 2: Read the two files that are about their tenancy, not merely using it**

**`test_household_columns.py`** — phase 2 wrote it to assert the *columns exist*, and several of its tests pass `user=` on purpose. After the codemod, check that:

- `test_model_carries_household_and_created_by` still passes `created_by=user` — that assertion is about provenance and must not become `household_for_user(user)`.
- `test_entry_household_may_be_null_during_the_transition` **still passes here** (the column is nullable until Task 12) and is **deleted in Task 12**. Add a marker comment now so the later task finds it:

```python
def test_entry_household_may_be_null_during_the_transition(user):
    """Phases 2 and 3 run with both columns and a partially-converted app.

    E04 PHASE 4, TASK 12 DELETES THIS TEST — it asserts the exact property the
    NOT NULL migration removes. Its replacement is
    `test_household_is_required` in the same file.
    """
```

- `test_two_members_cannot_create_the_same_category_twice` and its three siblings assert the *household* uniqueness constraints. They pass two different users into one household deliberately. The codemod maps both `user=user` and `user=amanda` onto the same household only if you check: `user=amanda` becomes `household=household_for_user(amanda)`, which is **amanda's own** household, and the test stops asserting anything. **Fix these four by hand** — pass `household=household` explicitly for both rows and drop the `user=` kwarg:

```python
def test_two_members_cannot_create_the_same_category_twice(user):
    """The new capability's sharp edge: two people in one household share a
    category list, so the second person adding 'Alimentação' must collide."""
    from django.db import IntegrityError

    household = baker.make(Household)
    baker.make("finances.Category", household=household, name="Alimentação")

    with pytest.raises(IntegrityError):
        baker.make("finances.Category", household=household, name="Alimentação")
```

The same shape for `..._budget_twice`, `..._payment_method_twice` in this file and `..._memory_rule_twice` in `assistant/tests/test_household_columns.py` (Task 9).

**`test_transfer_entries.py`** — the command's export half still filters `user__username` until Task 13. Its tests must keep working across both. If a test asserts on the exported `"user"` key, leave it: the key survives, only its source changes.

- [ ] **Step 3: Fix the fixture parameters and run the group**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_entry.py \
  src/backend/finances/tests/test_installment_plan.py \
  src/backend/finances/tests/test_category.py \
  src/backend/finances/tests/test_payment_method_closing_day.py \
  src/backend/finances/tests/test_systemic_expense.py \
  src/backend/finances/tests/test_budget_model.py \
  src/backend/finances/tests/test_income.py \
  src/backend/finances/tests/test_payment_method.py \
  src/backend/finances/tests/test_migration_freeze_billing_month.py \
  src/backend/finances/tests/test_backfill_billing_months.py \
  src/backend/finances/tests/test_fix_misdated_entries.py \
  src/backend/finances/tests/test_transfer_entries.py \
  src/backend/finances/tests/test_installment_plan_management.py \
  src/backend/finances/tests/test_seed_data.py \
  src/backend/finances/tests/test_household_columns.py -q
```
Expected: PASS. Add `household` / `other_household` to signatures wherever a `NameError` says so.

> `test_category.py:33 test_same_name_different_users` is one of the epic's twelve isolation modules. It must end up asserting *households*, not users: two categories with the same name in two different households is fine, in one household is an `IntegrityError`. If the codemod left it asserting something weaker, rewrite it — this is the conversion S04-6 asks for, not a mechanical pass.

- [ ] **Step 4: Strike the fifteen and run the ratchets**

Remove the fifteen paths from `BAKE_BASELINE`, then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py src/backend/accounts/tests/test_scoping_ratchet.py -q
```
Expected: 6 passed. `BAKE_BASELINE` is now 51 entries.

- [ ] **Step 5: Run the full suite and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/tests src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): the model and command tests name their household"
```
Expected: `1147 passed, 2 skipped` before the commit.

---

### Task 6: The entries and cockpit view tests

Sixteen modules, 108 call sites — the largest group, and the one holding six of the epic's twelve isolation modules (`test_views_entries.py`, `test_entry_edit_modal.py`, `test_cockpit_income_views.py`, `test_cockpit_vencimentos.py`, `test_cockpit_parcelamentos_views.py`, `test_installment_preview.py`).

**Files:**
- Modify (16): `src/backend/finances/tests/` — `test_views_entries.py`, `test_entries_live_summary.py`, `test_entries_pre_origin.py`, `test_cockpit_parcelamentos_views.py`, `test_cockpit_income_views.py`, `test_cockpit_systemic_create.py`, `test_cockpit_systemic_edit_modal.py`, `test_cockpit_systemic_views.py`, `test_cockpit_vencimentos.py`, `test_cockpit_parcelamento_edit_modal.py`, `test_cockpit_parcelamento_manage.py`, `test_installment_preview.py`, `test_entry_mobile_card.py`, `test_entry_edit_modal.py`, `test_cockpit_income_edit_modal.py`, `test_csrf_htmx.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: the codemod, the root conftest's `logged_client`.
- Produces: nothing importable.

- [ ] **Step 1: Run the codemod over the sixteen**

```bash
uv run python scripts/e04-retenant-tests.py \
  src/backend/finances/tests/test_views_entries.py \
  src/backend/finances/tests/test_entries_live_summary.py \
  src/backend/finances/tests/test_entries_pre_origin.py \
  src/backend/finances/tests/test_cockpit_parcelamentos_views.py \
  src/backend/finances/tests/test_cockpit_income_views.py \
  src/backend/finances/tests/test_cockpit_systemic_create.py \
  src/backend/finances/tests/test_cockpit_systemic_edit_modal.py \
  src/backend/finances/tests/test_cockpit_systemic_views.py \
  src/backend/finances/tests/test_cockpit_vencimentos.py \
  src/backend/finances/tests/test_cockpit_parcelamento_edit_modal.py \
  src/backend/finances/tests/test_cockpit_parcelamento_manage.py \
  src/backend/finances/tests/test_installment_preview.py \
  src/backend/finances/tests/test_entry_mobile_card.py \
  src/backend/finances/tests/test_entry_edit_modal.py \
  src/backend/finances/tests/test_cockpit_income_edit_modal.py \
  src/backend/finances/tests/test_csrf_htmx.py
uv run ruff check --fix src/backend/finances/tests/
uv run ruff format src/backend/finances/tests/
```

Expected: ~108 call sites rewritten.

- [ ] **Step 2: Convert the six isolation modules from cross-user to cross-household**

This is S04-6's core clause and the codemod cannot do it — it changes what the tests *mean*. Each of the six has a test that creates a foreign user and asserts a 404 or an absence. The codemod turns `user=other` into `household=household_for_user(other)`, which is already a different household, so the test still passes. **Rename it and say what it now asserts**, so a reader six months from now knows the boundary is tenancy and not identity:

| Module | Old name | New name |
|---|---|---|
| `test_entry_edit_modal.py:71` | `test_cannot_edit_other_users_entry` | `test_cannot_edit_another_households_entry` |
| `test_cockpit_income_views.py:42` | `test_user_cannot_touch_another_users_income` | `test_cannot_touch_another_households_income` |
| `test_cockpit_vencimentos.py:67` | `test_cannot_set_another_users_payment_method` | `test_cannot_set_another_households_payment_method` |
| `test_installment_preview.py:47` | `test_preview_other_user_pm_rejected` | `test_preview_rejects_another_households_payment_method` |
| `test_views_entries.py:90` | `test_other_user_entries_not_visible` | `test_another_households_entries_are_not_visible` |
| `test_cockpit_parcelamentos_views.py:56` | `test_other_user_plan_not_shown` | `test_another_households_plan_is_not_shown` |

And in each, add the positive half if it is missing. A negative-only assertion passes just as well against an empty page:

```python
    # BEFORE — passes if the whole page is empty
    assert "Compra do vizinho" not in body

    # AFTER — pins that the page rendered *our* data as well
    assert "Feira da semana" in body
    assert "Compra do vizinho" not in body
```

`test_views_entries.py:259 test_cannot_edit_other_user_entry` and `:291 test_cannot_delete_other_user_entry` get the same rename treatment.

- [ ] **Step 3: Fix the fixture parameters and run the group**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -k "entries or cockpit or entry or installment_preview or csrf" -q
```
Expected: PASS across all sixteen modules.

- [ ] **Step 4: Prove the fixtures still bite**

Phase 3 asked for this check and it applies again, because this task is where a vacuous pass would hide:

```bash
# Temporarily break it, on purpose:
#   edit conftest.py's `logged_client` to take (user) instead of (user, household)
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_entries.py -k another_households -q
# then put it back
```
Expected: the isolation tests **FAIL** with the dependency removed. A test that passes either way is testing nothing, and the fix is a positive assertion (Step 2), not a shrug.

- [ ] **Step 5: Strike the sixteen, run the suite, commit**

Remove the sixteen paths from `BAKE_BASELINE` — 35 entries left — then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/tests src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): the entries and cockpit tests assert a household boundary, not a user one"
```
Expected: `1147 passed, 2 skipped`.

---

### Task 7: Settings, consolidated, projection, importer and form tests

Ten modules, 94 call sites, including two more of the epic's twelve isolation modules (`test_views_projection.py`, `test_settings_income_groups.py`) and the three reverse-accessor uses that stop compiling when `user` goes.

**Files:**
- Modify (10): `src/backend/finances/tests/` — `test_views_settings.py`, `test_forms.py`, `test_views_consolidated.py`, `test_views_importer.py`, `test_views_projection.py`, `test_consolidated_detail_filter.py`, `test_settings_income_groups.py`, `test_consolidated_dropdown.py`, `test_import_double_submit.py`, `test_import_query_count.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: the codemod.
- Produces: nothing importable.

- [ ] **Step 1: Run the codemod**

```bash
uv run python scripts/e04-retenant-tests.py \
  src/backend/finances/tests/test_views_settings.py \
  src/backend/finances/tests/test_forms.py \
  src/backend/finances/tests/test_views_consolidated.py \
  src/backend/finances/tests/test_views_importer.py \
  src/backend/finances/tests/test_views_projection.py \
  src/backend/finances/tests/test_consolidated_detail_filter.py \
  src/backend/finances/tests/test_settings_income_groups.py \
  src/backend/finances/tests/test_consolidated_dropdown.py \
  src/backend/finances/tests/test_import_double_submit.py \
  src/backend/finances/tests/test_import_query_count.py
uv run ruff check --fix src/backend/finances/tests/
uv run ruff format src/backend/finances/tests/
```

- [ ] **Step 2: Replace the three reverse-accessor assertions**

`user.budgets` is the reverse of `Budget.user`, and it stops existing in Task 13. The codemod does not see it — it is an attribute chain, not a keyword. Three sites in `src/backend/finances/tests/test_views_settings.py`:

```python
# BEFORE — line 201
        assert user.budgets.filter(name="Casa", amount=Decimal("1000")).exists()
# AFTER
        assert Budget.objects.for_household(household).filter(
            name="Casa", amount=Decimal("1000")
        ).exists()

# BEFORE — line 223
        assert not user.budgets.filter(id=b.id).exists()
# AFTER
        assert not Budget.objects.for_household(household).filter(id=b.id).exists()

# BEFORE — line 233
        assert user.budgets.filter(name="Casa").count() == 1
# AFTER
        assert Budget.objects.for_household(household).filter(name="Casa").count() == 1
```

Add `from finances.models import Budget` if it is not already imported, and `household` to the three test signatures.

Then confirm nothing else in the tree reaches a domain model through a user:

```bash
grep -rnE "\.(entries|incomes|categories|budgets|payment_methods|installment_plans|systemic_expenses|import_batches|chat_messages|memory_rules|receipt_drafts|memory_embeddings)\b" \
  --include="*.py" src/backend | grep -E "user\.|self\.user\.|other\.|amanda\."
```
Expected: no output.

- [ ] **Step 3: Convert the two isolation modules**

| Module | Old name | New name |
|---|---|---|
| `test_views_projection.py:49` | `test_scoped_to_user` | `test_scoped_to_household` |
| `test_settings_income_groups.py:82` | `test_does_not_touch_other_households` | already correct — verify it asserts the positive half too |

`test_views_projection.py:207 test_projection_page_excludes_other_households` already asserts the right thing; leave it.

- [ ] **Step 4: Fix the fixture parameters and run the group**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_views_settings.py \
  src/backend/finances/tests/test_forms.py \
  src/backend/finances/tests/test_views_consolidated.py \
  src/backend/finances/tests/test_views_importer.py \
  src/backend/finances/tests/test_views_projection.py \
  src/backend/finances/tests/test_consolidated_detail_filter.py \
  src/backend/finances/tests/test_settings_income_groups.py \
  src/backend/finances/tests/test_consolidated_dropdown.py \
  src/backend/finances/tests/test_import_double_submit.py \
  src/backend/finances/tests/test_import_query_count.py -q
```
Expected: PASS.

> `test_import_query_count.py` asserts an upper bound on queries during a CSV import. The bridge's memoisation is what keeps that bound flat, and Task 12 deletes the bridge. If the number moves *here*, it is the codemod's `household_for_user(...)` calls being made per row — hoist them out of the loop in the test rather than raising the bound.

- [ ] **Step 5: Strike the ten, run the suite, commit**

Remove the ten paths from `BAKE_BASELINE` — 25 entries left — then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/tests src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): settings, projection and the importer read a household's rows"
```
Expected: `1147 passed, 2 skipped`.

---

### Task 8: The dashboard API, feature tests and query-count tests

Five modules, 98 call sites, 68 of them in one file. `test_api_dashboard.py` is the last of the epic's twelve isolation modules.

**Files:**
- Modify: `src/backend/finances/tests/test_api_dashboard.py`
- Modify: `src/backend/finances/tests/features/test_views.py`, `features/test_billing_cycle.py`, `features/test_installments.py`
- Modify: `src/backend/finances/tests/test_hot_path_query_counts.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: the codemod.
- Produces: nothing importable.

- [ ] **Step 1: Run the codemod**

```bash
uv run python scripts/e04-retenant-tests.py \
  src/backend/finances/tests/test_api_dashboard.py \
  src/backend/finances/tests/features/test_views.py \
  src/backend/finances/tests/features/test_billing_cycle.py \
  src/backend/finances/tests/features/test_installments.py \
  src/backend/finances/tests/test_hot_path_query_counts.py
uv run ruff check --fix src/backend/finances/tests/
uv run ruff format src/backend/finances/tests/
```

Expected: ~98 rewritten. The two `features/` modules carry the `context["user"]` shape — the codemod turns it into `household=household_for_user(context["user"])`, which is correct but wordy. Optionally set `context["household"] = household_for_user(user)` beside the existing `context["user"] = user` line and simplify; it is a readability call, not a correctness one.

- [ ] **Step 2: Give `test_api_dashboard.py` a real cross-household test**

Check what it has. If it only asserts totals for one user, add one test that pins the boundary at the DRF layer — the API is the surface where a leak is quietest, because it returns JSON nobody reads by eye:

```python
def test_dashboard_excludes_another_households_entries(
    logged_client, user, household, other_user, other_household
):
    """The API is where a leak is quietest — a wrong number, not a wrong page."""
    baker.make(
        "finances.Entry",
        household=other_household,
        amount=Decimal("9999.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )
    baker.make(
        "finances.Entry",
        household=household,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    payload = logged_client.get("/api/dashboard/summary/?year=2026&month=3").json()

    assert Decimal(str(payload["total"])) == Decimal("10.00")
```

> Check the actual endpoint path and the response key against `src/backend/finances/api/urls.py` and `api/views.py` before running — `/api/dashboard/summary/` and `total` are the plausible names, not verified ones. Fix the test to match the API; do not change the API.

- [ ] **Step 3: Fix the fixture parameters and run the group**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_api_dashboard.py \
  src/backend/finances/tests/features/ \
  src/backend/finances/tests/test_hot_path_query_counts.py -q
```
Expected: PASS.

> `test_hot_path_query_counts.py` asserts query-count ceilings on the dashboard. Every `household_for_user(...)` the codemod inserted in a *fixture* costs one query at setup, which does not count; one inserted inside an assertion block does. If a ceiling is breached, hoist the call, do not raise the ceiling.

- [ ] **Step 4: Strike the five, run the suite, commit**

Remove the five paths from `BAKE_BASELINE` — 20 entries left — then:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/tests src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): the dashboard API and the feature suite are household-scoped"
```
Expected: `1148 passed, 2 skipped` (1147 + the new API test).

---

### Task 9: The assistant tests

Seventeen modules, 99 call sites. One special case: `test_throttling.py` builds an `AssistantUsageEvent`, which keeps its `user` and needs `household=` **added** rather than substituted. The codemod prints it as a `!!` line and skips it.

**Files:**
- Modify (17): `src/backend/assistant/tests/` — `test_tools.py`, `test_memory_models.py`, `test_models.py`, `test_views.py`, `test_memory_tools.py`, `test_receipt_flow.py`, `test_receipt_date_and_dup.py`, `test_category_memory.py`, `test_receipt_discount_reconcile.py`, `test_image_extraction_regression.py`, `test_receipt_prompts.py`, `test_semantic_memory.py`, `test_analytics.py`, `test_assistant.py`, `test_create_entry_fuzzy.py`, `test_simulate_projection.py`, `test_throttling.py`
- Modify: `src/backend/assistant/tests/test_household_columns.py` if it appears in the codemod's output
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: the codemod; the `scope` / `other_scope` / `seeded_scope` fixtures in `assistant/tests/conftest.py`.
- Produces: nothing importable.

- [ ] **Step 1: Run the codemod over the whole directory**

```bash
uv run python scripts/e04-retenant-tests.py src/backend/assistant/tests/*.py src/backend/assistant/tests/conftest.py
uv run ruff check --fix src/backend/assistant/tests/
uv run ruff format src/backend/assistant/tests/
```

Expected: ~99 rewritten, plus one `!!` line naming `test_throttling.py` and `AssistantUsageEvent`.

`conftest.py`'s `seeded_user` fixture is in the pass: its five `baker.make(..., user=user, household=household, ...)` calls already carry a household, so the codemod **deletes** the `user=` keyword from each. Read the diff — the fixture must still `return user`.

- [ ] **Step 2: Handle the usage event by hand**

In `src/backend/assistant/tests/test_throttling.py`, the event keeps its actor and gains its tenant:

```python
    baker.make(
        "assistant.AssistantUsageEvent",
        user=user,
        household=household,
        kind=AssistantUsageKind.TEXT,
    )
```

Add `household` to the test's signature. Do **not** replace `user=` here — the throttle counts per person, and a test that scopes the event by household alone stops testing the rule (decision 1).

- [ ] **Step 3: Fix the four uniqueness tests in `test_household_columns.py`**

Same trap as Task 5 Step 2: `test_two_members_cannot_create_the_same_memory_rule_twice` passes `user=user` and `user=amanda` into one household on purpose. If the codemod split them into two households, the `pytest.raises(IntegrityError)` never fires and the test silently inverts. Restore it by hand:

```python
def test_two_members_cannot_create_the_same_memory_rule_twice(user):
    from django.db import IntegrityError

    household = baker.make(Household)
    baker.make(
        "assistant.MemoryRule", household=household, trigger="pague menos", field="category"
    )

    with pytest.raises(IntegrityError):
        baker.make(
            "assistant.MemoryRule", household=household, trigger="pague menos", field="category"
        )
```

- [ ] **Step 4: Run the assistant suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q`
Expected: PASS. Add fixture parameters where a `NameError` says so.

> `test_agent_scope.py` (phase 3's argument-injection test) does not appear in the baseline because it already names its households. Read it anyway before finishing: it is the DoD item that says a tool cannot be argument-injected across households, and this is the last task that touches its neighbourhood.

- [ ] **Step 5: Strike the seventeen, run the suite, commit**

Remove the seventeen assistant paths from `BAKE_BASELINE` — **3 entries left**: `accounts/tests/test_backfill.py`, `accounts/tests/test_bridge.py`, `finances/tests/test_query_indexes.py`.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/assistant/tests src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(assistant): the agent's tests name their household, and the throttle keeps its actor"
```
Expected: `1148 passed, 2 skipped`.

---

### Task 10: The four production write sites that still lean on the bridge

Everything the bridge silently fills becomes an `IntegrityError` two tasks from now. These four are the whole list, found by AST rather than grep — none of them mentions `household` at all, so no text search for it would surface them.

This task also closes the hole that let one of them hide: the scoping ratchet's regex matches `.filter(`, `.get(` and `.exclude(`, so `Category.objects.get_or_create(user=user, …)` in `seed_data.py` never registered as a user-scoped read. It is one.

**Files:**
- Modify: `src/backend/finances/models/systemic_expense.py:38-52`
- Modify: `src/backend/assistant/views.py:152-162`
- Modify: `src/backend/finances/management/commands/seed_data.py:53-80`
- Modify: `src/backend/finances/management/commands/seed_perf_data.py:104-107`
- Modify: `src/backend/accounts/tests/test_scoping_ratchet.py`
- Create: `src/backend/accounts/tests/test_no_write_needs_the_bridge.py`

**Interfaces:**
- Consumes: `accounts.resolution.household_for_user`.
- Produces:
  - `SystemicExpense.create_monthly_entry(month, amount=None, payment_method=None) -> Entry` — signature unchanged; it now carries its own household and author down to the entry.
  - `assistant.views.throttle_denial(scope, kind)` — first parameter changes from `user` to `AgentScope`, because the usage event now needs both the actor and the tenant.

- [ ] **Step 1: Write the failing test**

`src/backend/accounts/tests/test_no_write_needs_the_bridge.py`:

```python
"""Every write path sets `household` itself, with the bridge disconnected.

The bridge is a pre_save receiver that fills a missing household from the
writer's user. Task 12 deletes it, and at that moment any write site that was
leaning on it starts producing tenant-less rows — which the NOT NULL migration
in the same task turns into an IntegrityError in production.

Rather than wait for that, this disconnects the receiver and exercises the four
sites that were still leaning on it as of 2026-08-13.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db.models.signals import pre_save
from model_bakery import baker

from accounts.bridge import fill_household
from accounts.models import household_owned_models

pytestmark = pytest.mark.django_db


@pytest.fixture
def without_the_bridge():
    """Phase 4's end state, one task early."""
    for model in household_owned_models():
        pre_save.disconnect(
            fill_household, sender=model, dispatch_uid=f"e04_bridge_{model._meta.label_lower}"
        )
    yield
    from accounts.bridge import connect

    connect()


def test_a_systemic_expense_carries_its_household_into_its_entries(
    without_the_bridge, user, household
):
    category = baker.make("finances.Category", household=household, name="Casa")
    pm = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    template = baker.make(
        "finances.SystemicExpense",
        household=household,
        created_by=user,
        category=category,
        payment_method=pm,
        default_amount=Decimal("100.00"),
    )

    entry = template.create_monthly_entry(date(2026, 3, 1))

    assert entry.household == household
    assert entry.created_by == user


def test_seed_data_writes_into_a_household(without_the_bridge, user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).exists()
    assert not Category.objects.filter(household__isnull=True).exists()


def test_seed_data_is_idempotent_per_household(without_the_bridge, user, household):
    from django.core.management import call_command

    from finances.models import Category

    call_command("seed_data", user=user.get_username())
    before = Category.objects.for_household(household).count()
    call_command("seed_data", user=user.get_username())

    assert Category.objects.for_household(household).count() == before
```

And, for the assistant's usage event, add to `src/backend/assistant/tests/test_throttling.py`:

```python
@pytest.mark.django_db(transaction=True)
async def test_an_admitted_turn_records_its_household(user, household):
    """The usage event is household-owned even though it counts per person."""
    from assistant.agents.scope import AgentScope
    from assistant.models import AssistantUsageEvent
    from assistant.views import throttle_denial

    scope = AgentScope(household=household, user=user)

    assert await throttle_denial(scope, "text") is None

    event = await AssistantUsageEvent.objects.aget(user=user)
    assert event.household == household
```

> Check how the existing async tests in that module are marked before copying this — the repo may use `pytest.mark.asyncio`, `anyio`, or Django's own async test support. Match the file, do not introduce a new plugin.

- [ ] **Step 2: Run to verify failure**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_no_write_needs_the_bridge.py src/backend/assistant/tests/test_throttling.py -q
```
Expected: FAIL — `entry.household is None`, `Category.objects.filter(household__isnull=True).exists()`, and the usage event's household is `None`.

- [ ] **Step 3: Convert the four sites**

`src/backend/finances/models/systemic_expense.py`:

```python
    def create_monthly_entry(self, month: date_type, amount=None, payment_method=None):
        from finances.models.entry import Entry, EntryType

        return Entry.objects.create(
            # The template carries its own tenancy down. Until phase 4 this
            # relied on the write bridge filling household from user; the
            # bridge is gone and a generated entry must not be tenant-less.
            household=self.household,
            created_by=self.created_by,
            date=month,
            amount=amount if amount is not None else self.default_amount,
            description=self.name,
            category=self.category,
            payment_method=payment_method or self.payment_method,
            entry_type=EntryType.SYSTEMIC,
            billing_month=month,
            billing_month_override=True,
            systemic_expense=self,
        )
```

`src/backend/assistant/views.py` — `throttle_denial` takes the scope it already has at every call site:

```python
async def throttle_denial(scope, kind: str):
    """Refuse an over-budget turn, or admit it and record the spend.

    Returns a 429 ``JsonResponse`` when blocked and ``None`` when admitted. The
    usage event is written on admission — before any model call — so a request
    that dies mid-stream still counts against the budget it was going to spend.

    The event is charged to the household and attributed to the person: the
    quota is the household's to fill, but two members each get their own
    budget, which is why `user` stays on this model (E04 decision 1).
    """
    rule = await exceeded_rule(scope.user, kind)
    if rule is None:
        await AssistantUsageEvent.objects.acreate(
            user=scope.user, household=scope.household, kind=kind
        )
        return None
```

Then update every caller of `throttle_denial` in that module to pass `scope` instead of `user`. Find them with `grep -n "throttle_denial" src/backend/assistant/views.py`. Where a caller builds its scope *after* the throttle check, move the `AgentScope(...)` construction above it — it only reads attributes off the request and is free.

`src/backend/finances/management/commands/seed_data.py`:

```python
        household = household_for_user(user)
        cat_created = 0
        for name, ceiling, is_system in CATEGORIES:
            category, created = Category.objects.get_or_create(
                household=household,
                name=name,
                defaults={
                    "budget_ceiling": ceiling,
                    "is_system": is_system,
                    "created_by": user,
                },
            )
```

and the same shape for `PaymentMethod.get_or_create`, with `"created_by": user` added to its `defaults`. Add `from accounts.resolution import household_for_user` at the top. Note the lookup key changes from `(user, name)` to `(household, name)` — that is the point: re-running the seed after a second person joins must not create a duplicate catalogue.

`src/backend/finances/management/commands/seed_perf_data.py` — the three non-bulk creates near line 104 gain the household that is already resolved two lines above them:

```python
        categories = [
            Category.objects.create(household=household, created_by=user, name=name)
            for name in CATEGORY_NAMES
        ]
        pix = PaymentMethod.objects.create(
            household=household, created_by=user, name="Pix", type="pix"
        )
        card = PaymentMethod.objects.create(
            household=household, created_by=user, name="Crédito", type="credit_card", closing_day=25
        )
```

and change `household = household_for_writer(user)` to `household = household_for_user(user)` with the matching import, so this command does not import the module Task 12 deletes.

- [ ] **Step 4: Run the new tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_no_write_needs_the_bridge.py src/backend/assistant/tests/test_throttling.py -q
```
Expected: PASS.

- [ ] **Step 5: Tighten the scoping ratchet's regex**

`seed_data.py` scoped a query by user for two phases without the ratchet noticing, because `get_or_create` does not match `\.(filter|get|exclude)\(`. Close it in `src/backend/accounts/tests/test_scoping_ratchet.py`:

```python
# `get_or_create` and `update_or_create` were invisible to the first version of
# this pattern: `\.get\(` does not match `.get_or_create(`. That blind spot let
# `seed_data.py` scope its catalogue by user through phases 2 and 3.
PATTERN = re.compile(r"\.(filter|get|exclude|get_or_create|update_or_create)\([^)]*user=")
```

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`
Expected: 4 passed. If the wider pattern surfaces a file that is not in `ACTOR_SCOPED` or `E04_TRANSITION_TOOLS`, convert it now — that is a genuine find, not noise.

- [ ] **Step 6: Run the full suite and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/models/systemic_expense.py src/backend/assistant/views.py \
        src/backend/finances/management/commands/seed_data.py \
        src/backend/finances/management/commands/seed_perf_data.py \
        src/backend/accounts/tests src/backend/assistant/tests/test_throttling.py
git commit -m "fix(writes): the last four write paths name their household instead of inheriting one"
```
Expected: `1152 passed, 2 skipped` (1148 + 3 bridge-free tests + 1 usage-event test).

---

### Task 11: The indexes become household-leading, provably

DoD item: *"E03's indexes are re-created with `household` leading, and `EXPLAIN ANALYZE` confirms usage."* Phase 2 created the household twins in `finances/0015` and `assistant/0012`. Nothing has ever asserted the planner *chooses* them — `test_query_indexes.py` still asks about the user-leading pair, which Task 13 drops.

Converting this file before the drop is deliberate: if the planner will not use the household index, you want to know while the old one still exists.

**Files:**
- Modify: `src/backend/finances/tests/test_query_indexes.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py`

**Interfaces:**
- Consumes: the six household-leading indexes created by `finances/0015` and `assistant/0012`: `entry_hh_billing_type_idx`, `entry_hh_date_recent_idx`, `income_hh_month_idx`, `chat_hh_recent_idx`, `draft_hh_status_recent_idx`, `usage_hh_kind_recent_idx`.
- Produces: nothing importable.

- [ ] **Step 1: Rewrite the expectations**

In `src/backend/finances/tests/test_query_indexes.py`, replace the index map:

```python
EXPECTED_INDEXES = {
    "finances_entry": {"entry_hh_billing_type_idx", "entry_hh_date_recent_idx"},
    "finances_income": {"income_hh_month_idx"},
    "assistant_chatmessage": {"chat_hh_recent_idx"},
    "assistant_receiptdraft": {"draft_hh_status_recent_idx"},
    "assistant_assistantusageevent": {"usage_hh_kind_recent_idx", "usage_user_kind_recent_idx"},
}
```

`assistant_assistantusageevent` keeps **both**: the throttle asks "how many turns has this person spent", which is a user-leading question, and E07 will ask the household-leading one. That is the only table where the user index survives Task 13.

- [ ] **Step 2: Rewrite the bulk fixture to carry a household**

The `bulk_user` fixture uses `bulk_create`, which bypasses `pre_save`, so those 12,000 rows have a NULL household today and would be invisible to a scoped query. That is why this file is the last one in the bake ratchet.

```python
    @pytest.fixture
    def bulk_household(self, user, household):
        """bulk_create bypasses pre_save, so tenancy is carried in by hand."""
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household, type="pix")
        Entry.objects.bulk_create(
            [
                Entry(
                    household=household,
                    created_by=user,
                    date=date(2026, 1 + (i % 12), 1 + (i % 28)),
                    amount=Decimal("10.00"),
                    description=f"e{i}",
                    category=category,
                    payment_method=pm,
                    billing_month=date(2026, 1 + (i % 12), 1),
                    billing_month_override=True,
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        Income.objects.bulk_create(
            [
                Income(
                    household=household,
                    created_by=user,
                    name=f"i{i}",
                    amount=Decimal("100.00"),
                    month=date(2026, 1 + (i % 12), 1),
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        ChatMessage.objects.bulk_create(
            [
                ChatMessage(household=household, created_by=user, role=MessageRole.USER, content=f"m{i}")
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        with connection.cursor() as cursor:
            # Without fresh statistics the planner works from defaults and may
            # choose a seq scan on a table it has never seen.
            cursor.execute("ANALYZE finances_entry, finances_income, assistant_chatmessage;")
        return household
```

- [ ] **Step 3: Rewrite the five plan assertions**

```python
    def test_entry_billing_month_predicate_uses_an_index(self, bulk_household):
        plan = self._plan(
            Entry.objects.for_household(bulk_household).filter(billing_month=date(2026, 3, 1))
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_billing_type_idx" in plan, plan

    def test_entry_type_predicate_uses_the_same_index(self, bulk_household):
        plan = self._plan(
            Entry.objects.for_household(bulk_household).filter(
                billing_month=date(2026, 3, 1), entry_type="installment"
            )
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_billing_type_idx" in plan, plan

    def test_entry_recent_ordering_uses_an_index(self, bulk_household):
        plan = self._plan(Entry.objects.for_household(bulk_household)[:50])
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_date_recent_idx" in plan, plan

    def test_income_month_predicate_uses_an_index(self, bulk_household):
        plan = self._plan(
            Income.objects.for_household(bulk_household).filter(month=date(2026, 3, 1))
        )
        assert "Seq Scan" not in plan, plan
        assert "income_hh_month_idx" in plan, plan

    def test_chat_history_load_uses_an_index(self, bulk_household):
        plan = self._plan(
            ChatMessage.objects.for_household(bulk_household).order_by("-created_at")[:20]
        )
        assert "Seq Scan" not in plan, plan
        assert "chat_hh_recent_idx" in plan, plan
```

and the module-level draft test:

```python
@pytest.mark.django_db
def test_pending_draft_lookup_uses_an_index(user, household):
    """The lookup ``assistant/views.py`` runs on every chat turn."""
    ReceiptDraft.objects.bulk_create(
        [
            ReceiptDraft(household=household, created_by=user, payload={}, status="discarded")
            for _ in range(3000)
        ],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_receiptdraft;")
    queryset = (
        ReceiptDraft.objects.for_household(household)
        .filter(status="pending")
        .order_by("-created_at")[:1]
    )
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)  # noqa: S608 — ORM-built SQL
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Seq Scan" not in plan, plan
    assert "draft_hh_status_recent_idx" in plan, plan
```

- [ ] **Step 4: Run it**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_query_indexes.py -q`
Expected: PASS.

If a plan shows the planner picking the plain `household_id` FK index instead of the composite, that is a real finding, not a test bug: report the plan verbatim, and check whether the composite's column order matches the predicate. Believe `EXPLAIN`, not this plan — E03's own note says so.

- [ ] **Step 5: Strike it and commit**

Remove `"src/backend/finances/tests/test_query_indexes.py"` from `BAKE_BASELINE` — 2 entries left, both in `accounts/tests/` and both handled in Task 12.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/finances/tests/test_query_indexes.py src/backend/accounts/tests/test_bake_scoping.py
git commit -m "test(finances): the planner picks the household-leading indexes, asserted not assumed"
```
Expected: `1153 passed, 2 skipped` (1152 + the usage-event row in `EXPECTED_INDEXES`, one more parameterized case).

---

### Task 12: `household` becomes NOT NULL, and the bridge is deleted

The moment the database itself starts enforcing tenancy. Everything before this was the application being careful; from here a tenant-less row is impossible.

The bridge and the constraint must land in **one commit**. Deleting the bridge without the constraint leaves a window where a missed write site produces silent NULLs; adding the constraint without deleting the bridge leaves a receiver that can only ever mask the next mistake.

**Files:**
- Modify: `src/backend/accounts/models.py` — `HouseholdOwnedModel.household`
- Delete: `src/backend/accounts/bridge.py`, `src/backend/accounts/tests/test_bridge.py`
- Modify: `src/backend/accounts/apps.py`
- Modify: `src/backend/accounts/tests/test_backfill.py`
- Modify: `src/backend/accounts/tests/test_tenancy_bases.py`
- Modify: `src/backend/finances/tests/test_household_columns.py`
- Modify: `src/backend/accounts/tests/test_no_write_needs_the_bridge.py`
- Create: `src/backend/finances/migrations/0017_household_required.py`
- Create: `src/backend/assistant/migrations/0014_household_required.py`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py` — the baseline empties

**Interfaces:**
- Consumes: nothing new.
- Produces: `HouseholdOwnedModel.household` is `null=False`. `accounts.bridge` no longer exists — an import of it is an `ImportError`, deliberately.

- [ ] **Step 1: Write the failing test**

Replace the transition test in `src/backend/finances/tests/test_household_columns.py` (the one Task 5 marked) with its inverse:

```python
def test_household_is_required():
    """Phase 4: the database enforces tenancy, not just the application.

    Replaces `test_entry_household_may_be_null_during_the_transition`, which
    asserted exactly the property this migration removes.
    """
    from finances.models import Entry

    assert Entry._meta.get_field("household").null is False


def test_a_tenant_less_row_cannot_be_written(user):
    from django.db import IntegrityError, transaction

    from finances.models import Entry

    with pytest.raises(IntegrityError), transaction.atomic():
        Entry.objects.create(
            household=None,
            date=date(2026, 3, 10),
            amount=Decimal("10.00"),
            description="sem casa",
            category=baker.make("finances.Category", household=baker.make(Household)),
            payment_method=baker.make(
                "finances.PaymentMethod", household=baker.make(Household), type="pix"
            ),
            billing_month=date(2026, 3, 1),
            billing_month_override=True,
        )
```

And in `src/backend/accounts/tests/test_tenancy_bases.py`, flip the assertion:

```python
def test_household_fk_cascades_and_is_required():
    field = HouseholdOwnedModel._meta.get_field("household")
    assert field.null is False  # phase 4: the database enforces tenancy
    assert field.remote_field.on_delete is models.CASCADE
```

- [ ] **Step 2: Run to verify failure**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_columns.py src/backend/accounts/tests/test_tenancy_bases.py -q
```
Expected: FAIL — `assert True is False`, and no `IntegrityError` raised.

- [ ] **Step 3: Make the column required**

`src/backend/accounts/models.py`:

```python
    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        # E04 phase 4: NOT NULL. Every write path sets it explicitly, and from
        # here the database is what enforces tenancy — not a signal, not a
        # convention. A row with no household is now impossible rather than
        # merely unintended.
        related_name="%(app_label)s_%(class)s",
    )
```

Delete `null=True, blank=True` and rewrite the class docstring's third paragraph, which still describes the nullable transition.

- [ ] **Step 4: Generate the migrations and add the guard**

```bash
uv run python src/backend/manage.py makemigrations finances assistant -n household_required
```

Then hand-edit **both** generated files to run a pre-flight check before the `AlterField`s. A NOT NULL migration that fails halfway through on production data is the worst outcome available, and this makes it fail *first*, loudly, with the count:

```python
"""E04 phase 4: household becomes NOT NULL.

The back-fill (0014) filled every row whose user held an owner membership, and
accounts.0003 seeded a household for every user that existed. Anything still
NULL here is a row the back-fill deliberately skipped — see accounts/backfill.py
— and it must be looked at by a person, not invented by a migration.
"""

from django.db import migrations, models
import django.db.models.deletion

LABELS = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
]


def refuse_if_any_row_is_tenant_less(apps, schema_editor):
    unfilled = {}
    for label in LABELS:
        count = apps.get_model(label).objects.filter(household__isnull=True).count()
        if count:
            unfilled[label] = count
    if unfilled:
        raise RuntimeError(
            "Refusing to add NOT NULL: these rows have no household. Run the "
            "back-fill, or decide who owns them, then re-run this migration. "
            f"{unfilled}"
        )


def noop(apps, schema_editor):
    """Reversing NOT NULL loses nothing; there is nothing to undo here."""


class Migration(migrations.Migration):
    dependencies = [
        ("finances", "0016_user_nullable"),
        ("accounts", "0003_household_per_existing_user"),
    ]

    operations = [
        migrations.RunPython(refuse_if_any_row_is_tenant_less, noop),
        # ... the generated AlterField operations, unchanged ...
    ]
```

The assistant migration is the same with its own five labels (`ChatMessage`, `MemoryRule`, `ReceiptDraft`, `MemoryEmbedding`, `AssistantUsageEvent`) and a dependency on `assistant.0013_user_nullable`.

- [ ] **Step 5: Delete the bridge**

```bash
git rm src/backend/accounts/bridge.py src/backend/accounts/tests/test_bridge.py
```

In `src/backend/accounts/apps.py`, delete the `ready()` hook that calls `bridge.connect()` — read the file first; if `ready()` does nothing else afterwards, delete the method, not just its body.

In `src/backend/accounts/tests/test_no_write_needs_the_bridge.py`, the `without_the_bridge` fixture now has no bridge to disconnect. Simplify it away and rename the module to `test_writes_set_their_household.py`, keeping every test body:

```python
"""Every write path sets `household` itself.

Written in Task 10 against a still-present bridge; the bridge is gone, so these
now exercise the real thing rather than a simulation of it. Keep them: they are
the four sites that were leaning on it, and the ones a future refactor is most
likely to break.
"""
```

`src/backend/accounts/tests/test_backfill.py` bakes a row without a household — it is testing the back-fill, so its rows must start tenant-less. With NOT NULL it can no longer create one through the ORM. Convert it to build the row with a household and then `.update(household=None)`... which the constraint also refuses. Instead, keep it honest: the back-fill's unit under test is `accounts.backfill.backfill_household_columns`, which takes *model classes* — so the test can pass a stub or use the historical models via `django_test_migrations` if that is already a dependency. If neither is available, **assert the function's behaviour on rows that already have a household** (it must not move them) and delete the NULL-row case with a comment saying the migration's own guard now covers it. Record which route you took in the commit message.

- [ ] **Step 6: Run the migrations and the suite**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: migrate succeeds; suite passes. An `IntegrityError` in a test at this point names a write site that Task 10 missed — fix the site, do not relax the constraint.

- [ ] **Step 7: The bake ratchet empties**

Remove the last two entries from `BAKE_BASELINE`, leaving `BAKE_BASELINE = set()` with a comment:

```python
# Empty as of phase 4: every test names the household it writes into. The
# assignment stays so `test_bake_baseline_has_no_stale_entries` keeps meaning
# something and a regression cannot quietly re-add a file.
BAKE_BASELINE = set()
```

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bake_scoping.py -q`
Expected: 2 passed.

- [ ] **Step 8: Confirm nothing imports the bridge**

```bash
grep -rn "accounts.bridge\|household_for_writer" --include="*.py" src/ scripts/ docs/
```
Expected: no hits in `src/`. Hits in `docs/superpowers/plans/` are historical records and stay.

- [ ] **Step 9: Commit**

```bash
git add -A src/backend/accounts src/backend/finances src/backend/assistant
git commit -m "feat(accounts): household is NOT NULL, and the write bridge is gone"
```

---

### Task 13: `user` is dropped from the twelve models

The last destructive step. Twelve columns, four user-leading indexes, four user-leading unique constraints, and the two commands and two admin modules that still read them.

**Files:**
- Modify: `src/backend/finances/models/{entry,income,category,payment_method,budget,installment_plan,systemic_expense,import_batch}.py`
- Modify: `src/backend/assistant/models.py` — `ChatMessage`, `MemoryRule`, `ReceiptDraft`, `MemoryEmbedding`
- Modify: `src/backend/finances/admin.py`, `src/backend/assistant/admin.py`
- Modify: `src/backend/finances/management/commands/dump_ledger_totals.py`
- Modify: `src/backend/finances/management/commands/transfer_entries.py`
- Modify: `src/backend/finances/services/income_recurrence.py`, `src/backend/finances/forms.py`
- Modify: `src/backend/finances/views/importer.py`, `src/backend/finances/management/commands/{import_csv,seed_qa_data}.py`, `src/backend/assistant/views.py`, `src/backend/assistant/agents/tools.py`, `src/backend/finances/models/installment_plan.py`
- Modify: `src/backend/accounts/tests/test_scoping_ratchet.py`, `src/backend/accounts/tests/test_user_column_is_on_its_way_out.py`
- Create: `src/backend/finances/migrations/0018_drop_user.py`
- Create: `src/backend/assistant/migrations/0015_drop_user.py`

**Interfaces:**
- Consumes: `accounts.resolution.household_for_user`.
- Produces:
  - `dump_ledger_totals` keys its JSON report by **household name** instead of username. The per-tenant aggregates use `for_household`. Task 15 depends on this exact shape.
  - `transfer_entries --user <username>` filters on `created_by__username`; the exported JSON keeps its `"user"` key.

- [ ] **Step 1: Write the failing test**

Replace the body of `src/backend/accounts/tests/test_user_column_is_on_its_way_out.py` — the file name is now literally true:

```python
"""`user` is gone from the twelve models that only ever used it as a tenant.

`AssistantUsageEvent` keeps it: that column is the acting member, and the
throttle counts per person so that two people in one household each get their
own budget (E04 decision 1).
"""

import pytest
from django.apps import apps

LOST_USER = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
]


@pytest.mark.parametrize("label", LOST_USER)
def test_the_tenant_column_is_gone(label):
    field_names = {f.name for f in apps.get_model(label)._meta.get_fields()}

    assert "user" not in field_names
    assert "household" in field_names


@pytest.mark.parametrize("label", LOST_USER)
def test_provenance_survived_it(label):
    """`user` split into household + created_by. Dropping the first half
    without keeping the second would have thrown away review finding M5."""
    model = apps.get_model(label)
    if model._meta.label == "assistant.MemoryEmbedding":
        pytest.skip("machine-derived: no human author, asserted in test_household_columns")
    assert "created_by" in {f.name for f in model._meta.get_fields()}


def test_the_actor_column_survives():
    field_names = {
        f.name for f in apps.get_model("assistant.AssistantUsageEvent")._meta.get_fields()
    }

    assert "user" in field_names
    assert "household" in field_names


@pytest.mark.parametrize(
    "label,constraint",
    [
        ("finances.Category", "unique_category_per_household"),
        ("finances.Budget", "unique_budget_per_household"),
        ("finances.PaymentMethod", "unique_payment_method_per_household"),
        ("assistant.MemoryRule", "unique_memory_rule_per_household"),
    ],
)
def test_uniqueness_is_scoped_to_the_household(label, constraint):
    model = apps.get_model(label)
    names = {c.name for c in model._meta.constraints}

    assert constraint in names
    assert model._meta.unique_together == ()
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_user_column_is_on_its_way_out.py -q`
Expected: FAIL on every parameterized case.

- [ ] **Step 3: Edit the twelve models**

For each, delete the whole `user = models.ForeignKey(...)` block, and:

- `Category`: delete `unique_together = ("user", "name")` and the comment above it that explains the transition.
- `Budget`: delete `unique_together = ("user", "name")`.
- `PaymentMethod`: delete the `UniqueConstraint(fields=["user", "name"], name="unique_payment_method_per_user")` entry.
- `MemoryRule`: delete `unique_together = ("user", "trigger", "field")`.
- `Entry`: delete the two user-leading `Index` entries (`entry_user_billing_type_idx`, `entry_user_date_recent_idx`) and move Entry's long index-cost comment onto the household pair, since it is the reasoning that still applies:

```python
        indexes = [
            # The dashboard's core predicate. One composite instead of two
            # indexes: a B-tree serves any query with equality on a prefix, so
            # this answers filter(household, billing_month) and
            # filter(household, billing_month, entry_type) alike.
            models.Index(
                fields=["household", "billing_month", "entry_type"],
                name="entry_hh_billing_type_idx",
            ),
            # Matches Meta.ordering exactly, so the planner can skip the sort as
            # well as the scan on every unordered Entry queryset.
            models.Index(
                fields=["household", "-date", "-created_at"],
                name="entry_hh_date_recent_idx",
            ),
        ]
```

- `Income`: delete `income_user_month_idx`.
- `ChatMessage`: delete `chat_user_recent_idx`.
- `ReceiptDraft`: delete `draft_user_status_recent_idx`.
- `AssistantUsageEvent`: **change nothing**. Both of its indexes stay.

`db_index=False` disappears with the columns it was attached to. The comments explaining it go with them — but the *measurement* they record is worth keeping, so leave the Entry version as rewritten above.

- [ ] **Step 4: Fix the write sites that still name a user**

```bash
grep -rn "user=" --include="*.py" src/backend/finances src/backend/assistant \
  | grep -v "/tests/" | grep -v "/migrations/" \
  | grep -vE "\.filter\(|\.get\(|\.exclude\(|AgentScope|force_login"
```

Every hit with a `# still NOT NULL until phase 4` comment loses the whole line — that comment was written for this moment. The complete list at `a51348a`:

| File | Lines |
|---|---|
| `finances/forms.py` | 190, and `systemic.user = created_by` at 442 |
| `finances/views/importer.py` | 195, 354, 364, 412, 432 |
| `finances/services/income_recurrence.py` | 37 (keep `created_by` at 43, simplifying `income.created_by or income.user` to `income.created_by`) |
| `finances/management/commands/seed_qa_data.py` | 233, 269 |
| `finances/management/commands/import_csv.py` | 242, 282 |
| `finances/management/commands/transfer_entries.py` | 148 |
| `finances/models/installment_plan.py` | 53, and `created_by=self.created_by or self.user` at 57 → `created_by=self.created_by` |
| `assistant/views.py` | 125, 243, 272, 307, 353, 388, 441 |
| `assistant/agents/tools.py` | 137, 618, 1052, 1096 |

`assistant/views.py:161`'s `AssistantUsageEvent.objects.acreate(user=scope.user, household=scope.household, kind=kind)` **stays** — Task 10 wrote it that way on purpose.

- [ ] **Step 5: Re-point `dump_ledger_totals`**

Phase 3 promised this in the same commit that drops the columns.

```python
"""Fingerprint the ledger's money, for before/after comparison across a migration.

Row counts do not prove a migration was lossless — this project has a
documented history of reconciliation issues where the counts matched and the
balances did not. This dumps the numbers that actually matter: per-household
entry and income sums, and the running acumulado per month straight out of the
projection service.

Keyed by household name since E04 phase 4. Before that it was keyed by
username, and `scripts/rehearse-e04-migration.sh` normalises across the change
so a pre-E04 fingerprint still compares to a post-E04 one — see the runbook.
"""
```

and the loop:

```python
        report = {}
        for household in Household.objects.order_by("name"):
            entries = Entry.objects.for_household(household).aggregate(
                n=Count("id"),
                total=Sum("amount"),
                first=Min("billing_month"),
                last=Max("billing_month"),
            )
            incomes = Income.objects.for_household(household).aggregate(
                total=Sum("amount"), last=Max("month")
            )
            ...
            months = build_projection(household, start, num_months, today=FIXED_TODAY)
            report[household.name] = { ... }
```

with `from accounts.models import Household` replacing the `get_user_model` and `household_for_user` imports. Everything between `start = ...` and the `report[...] = {...}` literal is unchanged — no arithmetic moves.

- [ ] **Step 6: Re-point `transfer_entries`**

```python
        qs = Entry.objects.select_related("category", "payment_method", "created_by")
        ...
        if options["user"]:
            # `created_by`, not `user`: E04 phase 4 dropped the tenant column,
            # and "whose rows are these" is now a provenance question. Rows with
            # no author — written by a command or by the system — are excluded
            # by this filter, which is the honest answer to "--user amanda".
            qs = qs.filter(created_by__username=options["user"])
        rows = [
            {
                # Wire format unchanged, so an export taken before this commit
                # still imports after it.
                "user": e.created_by.username if e.created_by else None,
                ...
            }
```

and in `_import`, reject an authorless row with a clear message rather than a `TypeError`:

```python
        for r in rows:
            if not r.get("user"):
                errors.append(f"row has no author | {r['description'][:50]}")
                continue
```

- [ ] **Step 7: Fix the admin modules**

`src/backend/finances/admin.py` — replace `"user"` with `"household"` in every `list_display` and `list_filter` (lines 16-17, 24-25, 32-33, 39-40). `src/backend/assistant/admin.py` — the same at lines 8 and 20. Add `"created_by"` to `list_display` where the model has it; that is the audit trail E17 will surface and it costs nothing here.

- [ ] **Step 8: Generate the migrations**

```bash
uv run python src/backend/manage.py makemigrations finances assistant -n drop_user
```

**Read both files.** Each must contain, in order: `RemoveConstraint` / `AlterUniqueTogether`, `RemoveIndex`, then `RemoveField`. Django orders these correctly on its own, but a `RemoveField` before the index that references it fails at runtime — if the order is wrong, reorder by hand.

Both are irreversible in practice: reversing restores the column as NULL and nothing refills it. Say so at the top of each file:

```python
"""E04 phase 4: drop the tenant column.

NOT reversible in any useful sense. The auto-generated reverse re-adds a NULL
`user` column and nothing refills it, because the information needed to do so
— which person owned which row — was exactly what `created_by` preserved and
`user` duplicated. To go back, restore from a dump; see docs/runbook.md,
"Applying a migration to Supabase".
"""
```

- [ ] **Step 9: Flatten the scoping ratchet**

`src/backend/accounts/tests/test_scoping_ratchet.py` becomes the flat assertion S04-2 asked for. Delete `BASELINE`, delete `E04_TRANSITION_TOOLS` and its test (`dump_ledger_totals` no longer scopes by user, so the set has rotted shut exactly as phase 3 intended), keep `ACTOR_SCOPED` and its test, and rewrite the module docstring:

```python
"""Global constraint 4: no domain query scopes by user.

E04 is complete, so this is no longer a ratchet — it is the rule. The only
exemption is `ACTOR_SCOPED`, where `user` is the person acting rather than the
tenant owning, and that distinction is permanent.
"""
```

```python
def test_no_domain_query_scopes_by_user():
    offenders = sorted(_files_scoping_by_user() - ACTOR_SCOPED)
    assert not offenders, (
        "These files scope a domain query by user=. Use the household-scoped "
        f"manager (accounts.scoping) instead: {offenders}"
    )
```

- [ ] **Step 10: Migrate, run everything, and check the DoD grep**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run

grep -rnE '\.filter\([^)]*user=' src/backend/finances src/backend/assistant --include='*.py' \
  | grep -v tests | grep -v accounts
```
Expected: suite green; `makemigrations --check` reports no changes; the grep returns **only** `assistant/throttling.py:60`, which is the actor lookup and is the epic's intended end state. `dump_ledger_totals` is gone from that output — that is the phase-3 promise discharged.

- [ ] **Step 11: Commit**

```bash
git add -A src/backend
git commit -m "feat(models): the tenant column is the household, and user is gone from the twelve"
```

---

### Task 14: Re-measure the indexes at scale

DoD item, second half: `EXPLAIN ANALYZE` confirming usage — not in a 4,000-row test database, but at the synthetic product scale E03 used, so the "after E04" numbers sit beside E03's "after" numbers in the same document and are comparable.

**Files:**
- Modify: `docs/architecture/query-performance-baseline.md`

**Interfaces:**
- Consumes: `manage.py seed_perf_data`, converted in Task 10.
- Produces: a new "After E04 — household-leading" section in the baseline document.

- [ ] **Step 1: Build the measurement database**

```bash
PGPASSWORD=postgres createdb -h localhost -p 5433 -U postgres expense_tracker_perf_e04
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf_e04 \
  uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf_e04 \
  uv run python src/backend/manage.py seed_perf_data --yes --users 20 --entries-per-user 5000
```

Shape B — 20 households, 5,000 entries each. E03's document explains why shape B is the one that matters: every hot query filters by one tenant, so what a single tenant's slice costs is set by *their* history, not the table's size.

Expected: `Seeded 20 users, 100000 entries, ...`. If it dies on a NOT NULL household, Task 10 missed a site in that command — fix it there, not here.

- [ ] **Step 2: Capture the plans**

```bash
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d expense_tracker_perf_e04 <<'SQL' > /tmp/e04-after.txt
\timing on
\echo '--- Entry: (household, billing_month) — the dashboard core predicate'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
    AND billing_month = DATE '2026-08-01';

\echo '--- Entry: (household, billing_month, entry_type)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
    AND billing_month = DATE '2026-08-01' AND entry_type = 'installment';

\echo '--- Entry: (household, billing_month IN 6 months)'
EXPLAIN (ANALYZE, BUFFERS) SELECT billing_month, sum(amount) FROM finances_entry
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
    AND billing_month IN (DATE '2026-08-01', DATE '2026-07-01', DATE '2026-06-01',
                          DATE '2026-05-01', DATE '2026-04-01', DATE '2026-03-01')
  GROUP BY billing_month;

\echo '--- Entry: recent list (household, -date)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
  ORDER BY date DESC, created_at DESC LIMIT 50;

\echo '--- Income: (household, month)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_income
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
    AND month = DATE '2026-08-01';

\echo '--- ChatMessage: history load'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM assistant_chatmessage
  WHERE household_id = (SELECT id FROM accounts_household ORDER BY name LIMIT 1)
  ORDER BY created_at DESC LIMIT 20;

\echo '--- MemoryEmbedding: cosine nearest neighbours (unchanged by E04)'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, text FROM assistant_memoryembedding
  ORDER BY embedding <=> (SELECT embedding FROM assistant_memoryembedding LIMIT 1)
  LIMIT 5;
SQL

grep -c "Seq Scan" /tmp/e04-after.txt
grep -n "Index Scan\|Index Only Scan\|Bitmap Index Scan" /tmp/e04-after.txt
```

Expected: the same plan *shapes* E03 recorded after its indexes landed, with `entry_hh_billing_type_idx`, `entry_hh_date_recent_idx`, `income_hh_month_idx` and `chat_hh_recent_idx` named instead of their user-leading twins. `Seq Scan` should appear only on `accounts_household` (the script's own sub-select, which is fine — it is a 20-row table) and possibly `assistant_memoryembedding`, exactly as E03 recorded.

- [ ] **Step 3: Write it up**

Append to `docs/architecture/query-performance-baseline.md` a section titled `## After E04 — household-leading`, containing:

- one sentence on what changed (the leading column, nothing else),
- the same table shape E03 used — query, rows returned, rows read then discarded, time — filled from `/tmp/e04-after.txt`,
- a `<details><summary>Raw EXPLAIN output — after E04, shape B</summary>` block with the file's contents,
- and an honest note if any number moved by more than noise. A household with one member holds exactly the rows that user held, so a materially different figure means the index is not equivalent and needs saying, not smoothing.

Update the document's header line — it currently says "Measured for **E03**, at `0e616e6` on 2026-08-09" — to note the E04 re-measurement, its commit and its date.

- [ ] **Step 4: Drop the measurement database and commit**

```bash
PGPASSWORD=postgres dropdb -h localhost -p 5433 -U postgres expense_tracker_perf_e04
git add docs/architecture/query-performance-baseline.md
git commit -m "docs(perf): the household-leading indexes measured at product scale"
```

---

### Task 15: Rehearse the whole E04 chain against a copy of production

The epic's hardest DoD item, and the one this project has history behind: *"verify totals, not just row counts."* Production is still pre-E04 — no `household` column exists there at all — so a deploy applies **every** E04 migration at once, phases 2 and 4 together. That whole chain is what has to be rehearsed, on real data, before it is applied.

Phase 2's rehearsal ran against the same data and passed (2320 entries, 344529.48). This is the same experiment with a longer migration chain and a fingerprint command that changed its key.

**Files:**
- Modify: `scripts/rehearse-e04-migration.sh`
- Modify: `docs/runbook.md` — the "Rehearsing the E04 tenancy migration" section

**Interfaces:**
- Consumes: `dump_ledger_totals --json`, keyed by household name from Task 13; the pinned pre-E04 version at `de143a1`, keyed by username.
- Produces: an updated rehearsal script whose before/after comparison spans the key change.

- [ ] **Step 1: Teach the script to normalise across the key change**

The script pins its observer to `FINGERPRINT_REF=de143a1` so the schema varies while the observer stays constant. That stops working here: the pinned command reads `finances_entry.user_id`, which the migration under test removes, so the AFTER fingerprint dies.

The fix is to run each side with the observer that fits its schema, and normalise the keys. `accounts.migrations_helpers._household_name_for` names a seeded household `Casa de <username>`, so the mapping is exact and mechanical.

Replace the `fingerprint` function and its `FINGERPRINT_REF` preamble with:

```bash
# Phase 4 removes the `user` column, so a single pinned observer cannot read
# both sides any more. Instead each side is read by the observer that fits its
# schema, and the BEFORE keys are mapped through the same rule the seed
# migration used — accounts/migrations_helpers.py, `Casa de <username>` — so
# the two reports are comparable. If that naming rule ever changes, this
# normalisation changes with it.
BEFORE_REF="${BEFORE_REF-de143a1}"

normalise_before() {  # username-keyed JSON on stdin -> household-name-keyed on stdout
  python3 -c '
import json, sys
report = json.load(sys.stdin)
print(json.dumps({f"Casa de {k}"[:120]: v for k, v in report.items()},
                 indent=2, sort_keys=True))
'
}

fingerprint_before() { on_copy_at "$FP_TREE" dump_ledger_totals --json | normalise_before; }
fingerprint_after()  { on_copy    dump_ledger_totals --json; }
```

and use them at the two call sites:

```bash
echo "==> BEFORE fingerprint (pre-E04 schema, user-keyed, normalised)"
fingerprint_before > "$BEFORE"
...
echo "==> AFTER fingerprint (post-E04 schema, household-keyed)"
fingerprint_after > "$AFTER"
```

Update the "household-leading indexes present" check at the bottom to also assert the user-leading ones are **gone**:

```bash
echo "==> the user-leading indexes are gone"
local_pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE indexname IN ('entry_user_billing_type_idx','entry_user_date_recent_idx',
                       'income_user_month_idx','chat_user_recent_idx',
                       'draft_user_status_recent_idx');"
echo "   (expect NO rows — usage_user_kind_recent_idx survives and is not listed)"
```

and rewrite the script's header comment: it still says "Rehearse E04 phase 2", and it now rehearses the whole chain.

- [ ] **Step 2: Dry-run it against the local dev ledger first**

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres PGSSLMODE=prefer \
SOURCE_DB=expense_tracker REWIND=1 scripts/rehearse-e04-migration.sh
```

`REWIND=1` rolls the already-migrated dev copy back to pre-E04 before taking the BEFORE fingerprint, so this exercises the full chain without touching production. Expected: `OK — counts, sums and acumulado identical across the migration.`

A diff here is a bug in *this branch*, and the balances are where to look first — the acumulado is the number this project has burned on before.

- [ ] **Step 3: Rehearse against the real Supabase copy**

Read `docs/runbook.md` § "Applying a migration to Supabase" for the credentials. The password contains a space, so use `PG*` variables and never a URL.

```bash
PGHOST=<pooler host> PGPORT=5432 PGUSER=<user> PGPASSWORD=<password> PGSSLMODE=require \
  scripts/rehearse-e04-migration.sh
```

No `REWIND` — production is pre-E04 already. Production is touched exactly once, read-only, by `pg_dump`; everything else happens in a throwaway local container that the script's `EXIT` trap removes.

Expected, and **record the actual numbers in the commit message**:
- `OK — counts, sums and acumulado identical across the migration.`
- `unfilled rows: none`
- six household-leading indexes present, zero user-leading ones.

Compare the entry count and sum against phase 2's recorded rehearsal (2320 entries, 344529.48). They will differ if the ledger has grown since 2026-08-12 — that is fine and expected. What must not differ is BEFORE versus AFTER *within this run*.

> If the fingerprint changes, **do not deploy**. The two likeliest causes, in order: a household whose name does not match `Casa de <username>` (someone renamed one, and the normalisation is wrong, not the data), and a row the back-fill skipped because its user held no owner membership (the NOT NULL guard from Task 12 will have said so first).

- [ ] **Step 4: Update the runbook**

In `docs/runbook.md` § "Rehearsing the E04 tenancy migration", replace the phase-2 framing with what the script now does, and add the key-normalisation explanation — a future reader hitting a fingerprint diff needs to know that the two sides are keyed differently by design. Add the `BEFORE_REF` variable to the documented environment.

- [ ] **Step 5: Commit**

```bash
git add scripts/rehearse-e04-migration.sh docs/runbook.md
git commit -m "chore(scripts): the rehearsal spans the whole E04 chain, keys normalised across the drop"
```

---

### Task 16: Gate — E04 is done

No new behaviour. This is the evidence-collection task, and it is where the epic's Definition of Done is either ticked with a citation or left unticked with a reason.

**Files:**
- Delete: `scripts/e04-retenant-tests.py`
- Modify: `docs/backlog/E04-household-tenancy.md`
- Modify: `docs/backlog/INDEX.md` if it carries an epic status

- [ ] **Step 1: Full suite, real clock**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: roughly `1164 passed, 2 skipped`, **0 failed**. The derivation from 1153: Task 12 removes `test_bridge.py`'s 6 and replaces one transition test with two; Task 13 grows `test_user_column_is_on_its_way_out.py` from 13 cases to 29. Counts drift as tests are renamed and parameters dropped, so **treat the derivation as a sanity check and `0 failed` as the gate** — a count that is off by three is bookkeeping, a single failure is not.

- [ ] **Step 2: Full suite, shifted clock**

Run: `POSTGRES_PORT=5433 TEST_CLOCK_SHIFT=+1y uv run pytest src/backend/ -q -m "not current_date"`
Expected: the same counts. Serially, after Step 1 — never concurrently.

- [ ] **Step 3: Gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run python src/backend/manage.py check
```

- [ ] **Step 4: The epic's own DoD grep**

```bash
grep -rnE '\.filter\([^)]*user=' src/backend/finances src/backend/assistant --include='*.py' \
  | grep -v tests | grep -v accounts
```
Expected: one line, `assistant/throttling.py:60`. Say so explicitly when reporting — a reader of the epic sees a grep that is meant to return nothing, and the actor exemption is the reason it returns one thing.

- [ ] **Step 5: Both ratchets, and the sets that remain**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q
grep -A 3 "^ACTOR_SCOPED" src/backend/accounts/tests/test_scoping_ratchet.py
grep -n "BASELINE\|E04_TRANSITION_TOOLS" src/backend/accounts/tests/test_scoping_ratchet.py
grep -n "^BAKE_BASELINE" -A 2 src/backend/accounts/tests/test_bake_scoping.py
```
Expected: `ACTOR_SCOPED = {assistant/throttling.py}` and nothing else; no `BASELINE`, no `E04_TRANSITION_TOOLS`; `BAKE_BASELINE = set()`.

- [ ] **Step 6: Delete the codemod**

```bash
git rm scripts/e04-retenant-tests.py
```

It rewrote 612 call sites and has no second job. Leaving a script that rewrites `user=` into `household=` in a repository where `user=` no longer means a tenant is an invitation to run it on something it should not touch.

- [ ] **Step 7: Security review**

The epic makes this mandatory: *"the failure mode of this epic is a cross-tenant leak."*

```bash
git push -u origin HEAD    # /security-review needs origin/HEAD to diff against
```

Then run `/security-review`. Phase 3 could only run it as a review *agent* over `git diff main...HEAD` because main was 28 commits ahead of origin; pushing this branch fixes that, and the phase-3 DoD note explicitly asks for the command form to be re-run "after phase 4 drops the `user` columns". This is that moment.

Ask it for, at minimum: any queryset on a domain model reachable without a household; the agent's scope path (`ctx.deps` → `AgentScope`, never an LLM argument); the middleware's handling of a tampered `active_household_id` session value; write provenance (`created_by`) on every create; and whether `AssistantUsageEvent`'s actor column can be used to infer another household's activity.

Record the finding count and disposition in the epic. A LOW defense-in-depth item may be deferred with a note; a cross-tenant finding of any severity blocks the merge.

- [ ] **Step 8: Request a human-facing code review**

Follow `superpowers:requesting-code-review`. Point the reviewer at the three things a diff of this size hides:

1. The codemod's 612 rewrites — spot-check ten at random against `git show`, not all of them.
2. The four uniqueness tests hand-fixed in Tasks 5 and 9. They are the ones the codemod would silently invert, and a silently inverted `pytest.raises` is a test that passes forever.
3. `migrations/0018_drop_user.py` and `assistant/0015_drop_user.py` — irreversible, and applied to real financial records at the next deploy.

- [ ] **Step 9: Tick the epic**

In `docs/backlog/E04-household-tenancy.md`:

- Mark S04-1, S04-2, S04-3 and S04-6 as **DONE** with the date, in the same style phase 3 used on S04-4 and S04-5.
- Tick the observable assertions, each with its citation:
  - *A parameterized test covers every domain model for cross-household rejection* → `accounts/tests/test_cross_household_isolation.py`, parameterized over `household_owned_models()`, plus `test_every_domain_model_is_household_owned` for the model nobody remembered to scope.
  - *Two users in one household see identical ledger data* → `accounts/tests/test_shared_household.py`.
  - *E03's indexes are re-created with `household` leading, and `EXPLAIN ANALYZE` confirms usage* → `finances/tests/test_query_indexes.py` for the automated assertion and `docs/architecture/query-performance-baseline.md` § "After E04" for the measured plans at shape B.
  - *The data migration has been run against a copy of the real Supabase data* → the Task 15 run, with its actual counts and sums.
  - *`/security-review` passed with no cross-tenant finding* → the Step 7 result, with the finding count.
- Change `status: ready` to `status: done` in the front matter.
- Add a short "What phase 4 changed that the epic did not anticipate" note, listing at minimum: the ratchet regex blind spot on `get_or_create` (Task 10), the four bridge-dependent write sites the epic never inventoried, and `transfer_entries`' export moving to `created_by`.

- [ ] **Step 10: Commit**

```bash
git add -A docs scripts
git commit -m "docs(backlog): E04 is done — the ledger belongs to a household"
```

- [ ] **Step 11: Finish the branch**

Follow `superpowers:finishing-a-development-branch`. Before merging, confirm with the user how the migration reaches production: the whole E04 chain (`accounts/0001-0003`, `finances/0013-0018`, `assistant/0010-0015`) applies at once on the next deploy, against live financial records, and `docs/runbook.md` § "Applying a migration to Supabase" is the procedure. **Do not deploy as part of this task** — the rehearsal is evidence that the deploy is safe, not permission to perform it.

---

## Follow-on — NOT part of this plan

| Epic | What it picks up |
|---|---|
| **E05** | Invitations: the UI and email flow that lets a second person actually join a household. This phase makes the schema and the middleware ready for it; nothing in the product yet creates a `Membership` except the seed migration. |
| **E13** | The last-owner-leaves promotion rule (epic decision 3). The schema expresses it — `Membership.created_at` exists and is indexed — and E13 implements it alongside the LGPD deletion flow. |
| **E17** | Surfacing `created_by` in the UI. The column is populated from this phase on; nothing displays it. |

---

## Self-Review

**Spec coverage.** Against the epic's stories and DoD:

| Clause | Task |
|---|---|
| S04-6: the 12 isolation modules assert cross-**household** isolation | 5 (`test_category`), 6 (six modules), 7 (two modules), 8 (`test_api_dashboard`), plus the three already converted in phase 3 |
| S04-6: a parameterized test over every domain model | 1 |
| S04-6: reaching `PaymentMethodClosingDay` through its parent | 1, Step 1's last test |
| S04-6: two users in one household see the same data | 1, Step 3 |
| S04-3: unique constraints re-scoped from `user` to `household` | 13, Step 3 and its parameterized test in Step 1 |
| S04-3: E03's indexes re-created with `household` leading | 11 (asserted), 13 (the user twins dropped), 14 (measured) |
| DoD: `household` NOT NULL, `user` dropped, bridge deleted | 12, 13 |
| DoD: migration run against a copy of real Supabase data, totals compared | 15 |
| DoD: `/security-review` with no cross-tenant finding | 16, Step 7 |
| Global constraint 4: no bare `filter(user=…)` outside accounts | 13, Step 9 — the ratchet becomes the rule, not a baseline |

Two DoD items were already discharged in phase 3 and are re-verified rather than re-done: the agent cannot be argument-injected across households (`assistant/tests/test_agent_scope.py`), and `created_by` is populated for back-filled rows.

**One deliberate deviation from the epic's letter.** The epic's DoD grep is written to return nothing. It returns one line — `assistant/throttling.py:60` — because `AssistantUsageEvent.user` is the acting member and not the tenant. That was phase 2's decision, phase 3 encoded it in `ACTOR_SCOPED`, and this plan neither revisits nor hides it: Task 16 Step 4 requires it to be reported explicitly.

**Placeholder scan.** No TBDs. Every code step carries real code. Seven places name a check rather than asserting a fact the plan cannot verify: the two url names in Task 1 Step 3, the async test marker style in Task 10 Step 1, the dashboard endpoint path and response key in Task 8 Step 2, the `ready()` hook's other contents in Task 12 Step 5, `test_backfill.py`'s route forward in Task 12 Step 5, the generated migration operation order in Task 13 Step 8, and whether the planner picks the composite or the plain FK index in Task 11 Step 4.

**Type consistency.** `household_for_user(user) -> Household | None` is phase 3's, imported by the codemod's output, by `seed_data`, by `seed_perf_data` and by `transfer_entries`. `for_household(household)` and `for_request(request)` are phase 1's spellings throughout. `AgentScope(household=…, user=…)` is phase 3's frozen dataclass; Task 10 changes `throttle_denial`'s first parameter to one and Task 13 leaves it alone. `household_owned_models()` is phase 2's, and Task 1's parameterization is the first thing to depend on it being *discovered* rather than listed. `BAKE_BASELINE` is introduced in Task 3 and struck from in Tasks 4-9, 11 and 12; `ACTOR_SCOPED` is phase 3's and survives; `BASELINE` and `E04_TRANSITION_TOOLS` are phase 3's and are deleted in Task 13.

**The structural risk, stated rather than hidden.** The suite is green at every commit, which is a deliberate design: the three-beat schema dance exists precisely so that no task leaves the tree red. The cost is two extra migrations (`user_nullable`, then `drop_user`) where one would have done. On a database that has not yet had E04 applied at all, two extra `ALTER TABLE` statements against a 2,320-row ledger are free, and the alternative — one migration with 612 test sites converted in the same commit — is a diff nobody can review.

**The failure this plan is most worried about,** and where it is handled: a test that passes because its queryset is empty. It has three separate guards, because phase 3 proved one is not enough — the bake ratchet catches it statically (Task 3), the positive-assertion rule catches it semantically (Task 6 Step 2), and Task 6 Step 4 requires actually breaking the fixture to confirm the tests bite. If a reviewer has time for one thing, it is those.
