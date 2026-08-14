# E04 Phase 2 — Re-tenant the Domain Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give all 13 domain models a `household` FK (and `created_by` where a human authored the row), back-fill both from the existing `user` via phase 1's `Membership`, and re-scope every unique constraint and E03 index to lead with `household` — without changing a single read path, so the suite stays green throughout.

**Architecture:** Two abstract base models in `accounts` carry the new columns and phase 1's `HouseholdScopedManager`, so re-tenanting a model is a one-line change to its base class instead of a copy-pasted field. `household` is **nullable** through phases 2–3 and becomes `NOT NULL` in phase 4; a temporary `pre_save` bridge fills it from the writer's `user` so that the ~970 existing tests and every not-yet-converted write site keep producing coherent rows. Old `user`-scoped constraints and indexes are **kept alongside** the new household ones — there is never a window where the data is less protected than it is today. The `user` columns, the bridge, and the old constraints all die in phase 4.

**Tech Stack:** Django 6, PostgreSQL 17 (pgvector image on `:5433` locally, Supabase in production), pytest + pytest-django + model_bakery, ruff, uv.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7 and the E04 epic. Every task's requirements implicitly include this section.

- **TDD.** Test first, always. Red → green → refactor. Project convention, not a preference.
- **Worktrees.** This work happens in an isolated worktree, not on `main`.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean.
- **Migrations are reversible**, or the task states explicitly why not.
- **pt-BR in the product UI, English in code, comments, and docs.** `verbose_name` is UI-facing → pt-BR.
- **No time-bomb tests.** Any date-sensitive test freezes the clock (`time_machine`). The suite runs under `TEST_CLOCK_SHIFT=+1y` in CI and must stay green.
- **No new secret in git.** The Supabase password contains a space — never put it in a URL or a file.
- **UUID primary keys** on domain models. All 13 already have them; no change.
- **The money boundary holds.** Not exercised in this phase — no arithmetic changes. That is precisely why the rehearsal in Task 8 can compare `acumulado` byte-for-byte.
- **Do not batch this into one commit.** The epic's own risk note. One task, one commit.

### Decisions already made — do not re-litigate

From `docs/backlog/E04-household-tenancy.md` § "Open questions — DECIDED 2026-08-11", and two settled while writing this plan:

1. Multi-household **yes in the schema**, one active at a time in the UI.
2. Roles are **`owner` and `member`, nothing else.**
3. Last owner deleting their account → promote the longest-standing member. **E13**, not here.
4. `PaymentMethodClosingDay` stays **transitively scoped** via `PaymentMethod`. **No household column** — it is the one model in `finances` that is deliberately left alone. Phase 4's parameterized test must reach it through its parent.
5. **13 models, not the epic's "10".** The epic's own table lists 11 (7 in `finances`, 4 in `assistant`) — the "10" in its prose is an off-by-one. Two further models carry `FK(user)` and are added here by decision on 2026-08-12: `ImportBatch` (an import belongs to the ledger, not to the person who ran it) and `AssistantUsageEvent` (its docstring already says "E07 will extend this row with … a household FK"; one column now costs less than a second migration over live rows later).
6. **`household` is nullable in phase 2**, with a temporary `pre_save` bridge. `NOT NULL` is phase 4 work, after every write path sets it explicitly.

### The 13 models, and which base each takes

| App | Model | Base class | Why |
|---|---|---|---|
| `finances` | `Entry` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `Income` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `Category` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `PaymentMethod` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `Budget` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `InstallmentPlan` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `SystemicExpense` | `AuthoredHouseholdModel` | human-authored |
| `finances` | `ImportBatch` | `AuthoredHouseholdModel` | human-authored |
| `assistant` | `ChatMessage` | `AuthoredHouseholdModel` | two people share one chat history; "who asked this" matters |
| `assistant` | `MemoryRule` | `AuthoredHouseholdModel` | human-authored |
| `assistant` | `ReceiptDraft` | `AuthoredHouseholdModel` | human-authored |
| `assistant` | `MemoryEmbedding` | `HouseholdOwnedModel` | machine-derived; no human author to record |
| `assistant` | `AssistantUsageEvent` | `HouseholdOwnedModel` | its `user` column **is** the actor, not the tenant. Keep `user`, add `household`. Phase 4 does **not** drop `user` here. |

**Not re-tenanted:** `PaymentMethodClosingDay` (decision 4), and everything in `core`.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# One app while iterating
POSTGRES_PORT=5433 uv run pytest src/backend/finances/ -q

# Gates
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

**Do not run two pytest invocations concurrently** — they share the `test_expense_tracker` database and the second fails with `database ... is being accessed by other users`.

**Before Task 1, record the baseline** so every later step has something to compare against:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -3
```

Write the passed/skipped counts down. Every task below expects **that number, plus its own new tests, and zero failures**. A pre-existing failure at this point means phase 1 regressed — stop and fix that first.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/backend/accounts/models.py` | add `HouseholdOwnedModel`, `AuthoredHouseholdModel`, `household_owned_models()` | modify |
| `src/backend/accounts/bridge.py` | the temporary `pre_save` fill — **deleted in phase 4** | create |
| `src/backend/accounts/apps.py` | connect the bridge in `ready()` | modify |
| `src/backend/accounts/tests/test_tenancy_bases.py` | the bases and the registry | create |
| `src/backend/accounts/tests/test_bridge.py` | the bridge's behaviour and its limits | create |
| `src/backend/finances/models/*.py` | 8 models change base class | modify |
| `src/backend/assistant/models.py` | 5 models change base class | modify |
| `src/backend/finances/models/installment_plan.py` | `bulk_create` must set `household` itself | modify |
| `src/backend/finances/migrations/0013_household_and_created_by.py` | schema | create (generated) |
| `src/backend/finances/migrations/0014_backfill_household.py` | data, reversible | create |
| `src/backend/finances/migrations/0015_household_constraints_and_indexes.py` | schema | create (generated) |
| `src/backend/assistant/migrations/0010_household_and_created_by.py` | schema | create (generated) |
| `src/backend/assistant/migrations/0011_backfill_household.py` | data, reversible | create |
| `src/backend/assistant/migrations/0012_household_constraints_and_indexes.py` | schema | create (generated) |
| `src/backend/finances/tests/test_household_columns.py` | the finances models carry the columns and the scoped manager | create |
| `src/backend/assistant/tests/test_household_columns.py` | same, for assistant | create |
| `src/backend/accounts/tests/test_backfill.py` | the back-fill rule | create |
| `scripts/rehearse-e04-migration.sh` | the production-copy rehearsal | create |
| `docs/runbook.md` | a section for that rehearsal | modify |

**No read path is modified in this phase.** `finances/views/`, `finances/api/`, `finances/services/`, `assistant/agents/` are untouched — that is phase 3. If a task tempts you into one of those files, you have gone out of scope, with the single stated exception of `installment_plan.py`'s `bulk_create` (Task 5), which is a *write* path that signals cannot reach.

---

### Task 1: The tenancy base models, proven on `Entry`

`Entry` first, deliberately: it is the model with two indexes, a `save()` override, and the most rows in production. If the pattern works here it works everywhere.

**Files:**
- Modify: `src/backend/accounts/models.py`
- Create: `src/backend/accounts/tests/test_tenancy_bases.py`
- Modify: `src/backend/finances/models/entry.py`
- Create: `src/backend/finances/tests/test_household_columns.py`
- Create: `src/backend/finances/migrations/0013_household_and_created_by.py` (generated)

**Interfaces:**
- Consumes: `accounts.models.Household`, `accounts.scoping.HouseholdScopedManager` (phase 1).
- Produces:
  - `accounts.models.HouseholdOwnedModel` — abstract, adds `household: FK(Household, null=True, blank=True, on_delete=CASCADE, related_name="%(app_label)s_%(class)s")` and `objects = HouseholdScopedManager()`.
  - `accounts.models.AuthoredHouseholdModel(HouseholdOwnedModel)` — abstract, adds `created_by: FK(AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name="+")`.
  - `accounts.models.household_owned_models() -> list[type[models.Model]]` — every concrete model inheriting `HouseholdOwnedModel`. Phase 4's parameterized test enumerates from this, so a model added later without a base class fails the suite.

- [ ] **Step 1: Write the failing test for the bases**

`src/backend/accounts/tests/test_tenancy_bases.py`:

```python
"""The abstract bases every re-tenanted domain model inherits.

Re-tenanting a model is a change to its base class, not a copy-pasted field —
so there is one definition of what "belongs to a household" means, and phase 4
can enumerate the models rather than maintain a list by hand.
"""

import pytest
from django.db import models
from model_bakery import baker

from accounts.models import (
    AuthoredHouseholdModel,
    Household,
    HouseholdOwnedModel,
    household_owned_models,
)
from accounts.scoping import HouseholdScopedQuerySet

pytestmark = pytest.mark.django_db


def test_bases_are_abstract():
    """Abstract, or Django would build two pointless tables."""
    assert HouseholdOwnedModel._meta.abstract
    assert AuthoredHouseholdModel._meta.abstract


def test_registry_finds_entry():
    from finances.models import Entry

    assert Entry in household_owned_models()


def test_registry_excludes_the_abstract_bases():
    for model in household_owned_models():
        assert not model._meta.abstract


def test_registry_excludes_payment_method_closing_day():
    """Decision 4: it is scoped transitively through PaymentMethod and must
    NOT grow a household column. If it appears here, someone re-tenanted it."""
    from finances.models import PaymentMethodClosingDay

    assert PaymentMethodClosingDay not in household_owned_models()


def test_every_registered_model_has_a_scoped_manager():
    for model in household_owned_models():
        assert isinstance(model.objects.all(), HouseholdScopedQuerySet), (
            f"{model.__name__} inherits the base but lost the scoped manager"
        )


def test_household_fk_cascades_and_is_nullable_for_now():
    field = HouseholdOwnedModel._meta.get_field("household")
    assert field.null is True  # NOT NULL is phase 4
    assert field.remote_field.on_delete is models.CASCADE


def test_created_by_survives_the_author_leaving_the_household():
    """SET_NULL, not CASCADE: deleting a person must never delete the family's
    financial history. This is the whole point of splitting user into
    household + created_by."""
    field = AuthoredHouseholdModel._meta.get_field("created_by")
    assert field.null is True
    assert field.remote_field.on_delete is models.SET_NULL


def test_household_deletion_takes_its_rows_with_it(user):
    from finances.models import Entry

    household = baker.make(Household)
    baker.make(Entry, user=user, household=household)

    household.delete()

    assert Entry.objects.count() == 0
```

`user` is the fixture from `src/backend/finances/tests/conftest.py`; `accounts/tests/` does not currently see it. Add a local fixture at the top of this module rather than moving the shared one:

```python
@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_tenancy_bases.py -q`
Expected: FAIL — `ImportError: cannot import name 'HouseholdOwnedModel' from 'accounts.models'`

- [ ] **Step 3: Write the bases**

Append to `src/backend/accounts/models.py`:

```python
class HouseholdOwnedModel(models.Model):
    """A domain row that belongs to a household.

    Abstract on purpose: re-tenanting a model is a change to its base class,
    so there is exactly one definition of the tenant column and phase 4 can
    enumerate the models instead of trusting a hand-maintained list.

    ``household`` is nullable through E04 phases 2 and 3 because the rows that
    exist today have no household until the back-fill runs, and because every
    not-yet-converted write site still sets only ``user``. Phase 4 makes it
    NOT NULL once every write path sets it explicitly — that is the point at
    which the database itself starts enforcing tenancy.
    """

    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s",
    )

    objects = HouseholdScopedManager()

    class Meta:
        abstract = True


class AuthoredHouseholdModel(HouseholdOwnedModel):
    """A household row a person wrote.

    ``created_by`` is not decoration — it delivers review finding M5 (no audit
    trail) as a side effect of work we are doing anyway, and E17 surfaces it.

    SET_NULL rather than CASCADE: when a member leaves or deletes their
    account, the household's financial history must survive. That distinction
    is the entire reason ``user`` splits into two columns instead of being
    renamed.
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True


def household_owned_models():
    """Every concrete model carrying a household column.

    Discovered, not listed. A model added later that inherits the base is
    covered by phase 4's isolation test automatically; a model added later
    that *forgets* to inherit it is caught by the same test's counterpart.
    """
    from django.apps import apps

    return [
        model
        for model in apps.get_models()
        if issubclass(model, HouseholdOwnedModel) and not model._meta.abstract
    ]
```

Add `from accounts.scoping import HouseholdScopedManager` at the top if phase 1 did not already import it there (it did — phase 1 attached the manager to `Membership`).

> **Note on `related_name`.** `%(app_label)s_%(class)s` gives `household.finances_entry`, `household.assistant_chatmessage`, and so on — distinct per model, so 13 models can share one abstract base. These reverse accessors are **not** the supported scoping path; `Model.objects.for_household(...)` is. `created_by` uses `related_name="+"` so 11 models do not each hang an accessor off `CustomUser`.

- [ ] **Step 4: Put `Entry` on the base**

In `src/backend/finances/models/entry.py`, change the import and the class statement. Keep the `user` field exactly as it is — including its long `db_index=False` comment, which is still true and still load-bearing in phases 2–3:

```python
from accounts.models import AuthoredHouseholdModel


class Entry(AuthoredHouseholdModel):
```

Nothing else in the file changes. `save()`, `Meta`, and the two indexes stay as they are; Task 7 adds the household-leading twins.

- [ ] **Step 5: Write the model-level test**

`src/backend/finances/tests/test_household_columns.py`:

```python
"""E04 phase 2: the finances domain models carry a household.

Deliberately narrow. This phase adds columns and does not change a single
read path, so these tests assert the columns exist, default to NULL, and route
through the scoped manager — nothing about views or services.
"""

import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


def test_entry_carries_household_and_created_by(user):
    household = baker.make(Household, name="Casa Bessa")
    entry = baker.make("finances.Entry", user=user, household=household, created_by=user)

    assert entry.household == household
    assert entry.created_by == user


def test_entry_scopes_through_the_household_manager(user):
    from finances.models import Entry

    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make("finances.Entry", user=user, household=ours)
    baker.make("finances.Entry", user=user, household=theirs)

    assert Entry.objects.for_household(ours).count() == 1
    assert Entry.objects.for_household(None).count() == 0


def test_entry_household_may_be_null_during_the_transition(user):
    """Phases 2 and 3 run with both columns and a partially-converted app.
    NOT NULL arrives in phase 4, once every write path sets it."""
    entry = baker.make("finances.Entry", user=user, household=None)

    assert entry.household_id is None
```

- [ ] **Step 6: Generate the migration and run both test modules**

```bash
uv run python src/backend/manage.py makemigrations finances --name household_and_created_by
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_tenancy_bases.py src/backend/finances/tests/test_household_columns.py -q
```

Expected: `finances/migrations/0013_household_and_created_by.py` created with two `AddField` operations on `entry`; all tests PASS.

Open the generated migration and confirm both fields are `null=True`. If Django emitted a prompt about a non-nullable field, the base class is wrong — fix the base, delete the migration, regenerate.

- [ ] **Step 7: Run the whole suite — a base class changed under 970 tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: the baseline count plus the new tests, 0 failed.

If `Entry` tests fail with a manager error, the abstract base's `objects` shadowed something — but `Entry` had no custom manager before, so this should not happen. If it does, fix the base, not the test.

- [ ] **Step 8: Commit**

```bash
git add src/backend/accounts src/backend/finances
git commit -m "feat(accounts): abstract bases that make a model household-owned"
```

---

### Task 2: The remaining seven `finances` models

Mechanical, and worth one commit precisely because it is mechanical — a reviewer can read it in a minute.

**Files:**
- Modify: `src/backend/finances/models/{income,category,payment_method,budget,installment_plan,systemic_expense,import_batch}.py`
- Modify: `src/backend/finances/tests/test_household_columns.py`
- Modify: `src/backend/finances/migrations/0013_household_and_created_by.py` (regenerated)

**Interfaces:**
- Consumes: `accounts.models.AuthoredHouseholdModel` (Task 1).
- Produces: all 8 `finances` domain models inherit `AuthoredHouseholdModel`. `PaymentMethodClosingDay` does **not**.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/finances/tests/test_household_columns.py`:

```python
FINANCES_HOUSEHOLD_MODELS = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
]


@pytest.mark.parametrize("label", FINANCES_HOUSEHOLD_MODELS)
def test_model_carries_household_and_created_by(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    household = baker.make(Household)
    row = baker.make(model, user=user, household=household, created_by=user)

    assert row.household == household
    assert row.created_by == user


@pytest.mark.parametrize("label", FINANCES_HOUSEHOLD_MODELS)
def test_model_scopes_through_the_household_manager(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household)
    theirs = baker.make(Household)
    baker.make(model, user=user, household=ours)
    baker.make(model, user=user, household=theirs)

    assert model.objects.for_household(ours).count() == 1


def test_closing_day_is_scoped_through_its_payment_method_only(user):
    """Decision 4, asserted rather than assumed: PaymentMethodClosingDay has
    no household of its own, and must reach one only via its parent."""
    from finances.models import PaymentMethodClosingDay

    field_names = {f.name for f in PaymentMethodClosingDay._meta.get_fields()}
    assert "household" not in field_names
    assert "payment_method" in field_names
```

`baker.make(model, user=user, ...)` works for all eight: every one still has a required `user` FK, and baker fills the rest. `InstallmentPlan` and `SystemicExpense` pull in a `Category` and `PaymentMethod` automatically.

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_columns.py -q`
Expected: FAIL for the seven models that are not yet on the base — `TypeError: Income() got unexpected keyword arguments: 'household'` (or `'created_by'`).

- [ ] **Step 3: Change the seven base classes**

In each file, add the import and swap the base. Nothing else changes — no field is moved, no `Meta` is touched.

`src/backend/finances/models/income.py`:

```python
from accounts.models import AuthoredHouseholdModel


class Income(AuthoredHouseholdModel):
```

`src/backend/finances/models/category.py`:

```python
from accounts.models import AuthoredHouseholdModel


class Category(AuthoredHouseholdModel):
```

`src/backend/finances/models/payment_method.py`:

```python
from accounts.models import AuthoredHouseholdModel


class PaymentMethod(AuthoredHouseholdModel):
```

`src/backend/finances/models/budget.py`:

```python
from accounts.models import AuthoredHouseholdModel


class Budget(AuthoredHouseholdModel):
```

`src/backend/finances/models/installment_plan.py`:

```python
from accounts.models import AuthoredHouseholdModel


class InstallmentPlan(AuthoredHouseholdModel):
```

`src/backend/finances/models/systemic_expense.py`:

```python
from accounts.models import AuthoredHouseholdModel


class SystemicExpense(AuthoredHouseholdModel):
```

`src/backend/finances/models/import_batch.py`:

```python
from accounts.models import AuthoredHouseholdModel


class ImportBatch(AuthoredHouseholdModel):
```

`PaymentType` in `payment_method.py` and `EntryType` in `entry.py` are `TextChoices`, not models — leave them alone.

- [ ] **Step 4: Regenerate the migration**

Task 1's `0013` covers `Entry` only. Delete it and regenerate so phase 2 ships one schema migration per app rather than eight:

```bash
rm src/backend/finances/migrations/0013_household_and_created_by.py
uv run python src/backend/manage.py makemigrations finances --name household_and_created_by
```

Expected: a single `0013_household_and_created_by.py` with 16 `AddField` operations (8 models × 2 fields). Confirm `paymentmethodclosingday` appears **nowhere** in it.

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_columns.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

Expected: the new parameterized tests PASS (17 of them), and the full suite holds at baseline + new tests, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances
git commit -m "feat(finances): every domain model belongs to a household"
```

---

### Task 3: The five `assistant` models

**Files:**
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/assistant/tests/test_household_columns.py`
- Create: `src/backend/assistant/migrations/0010_household_and_created_by.py` (generated)
- Modify: `src/backend/accounts/tests/test_tenancy_bases.py`

**Interfaces:**
- Consumes: `AuthoredHouseholdModel`, `HouseholdOwnedModel` (Task 1).
- Produces: all 13 models registered. `household_owned_models()` returns exactly 13 entries from here on, which Task 3 Step 5 pins.

- [ ] **Step 1: Write the failing test**

`src/backend/assistant/tests/test_household_columns.py`:

```python
"""E04 phase 2: the assistant domain models carry a household.

Two of the five take household without created_by — see the base-class table
in the plan. MemoryEmbedding is machine-derived, and AssistantUsageEvent's
`user` column is already the actor rather than the tenant.
"""

import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


AUTHORED = [
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
]
OWNED_ONLY = [
    "assistant.MemoryEmbedding",
    "assistant.AssistantUsageEvent",
]


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.mark.parametrize("label", AUTHORED + OWNED_ONLY)
def test_model_carries_household(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    household = baker.make(Household)
    row = baker.make(model, user=user, household=household)

    assert row.household == household


@pytest.mark.parametrize("label", AUTHORED)
def test_authored_model_records_who_wrote_it(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    row = baker.make(model, user=user, household=baker.make(Household), created_by=user)

    assert row.created_by == user


@pytest.mark.parametrize("label", OWNED_ONLY)
def test_machine_written_model_has_no_created_by(label):
    """Not an oversight — asserted, so nobody 'fixes' it later. An embedding
    has no human author, and a usage event's `user` IS its author."""
    from django.apps import apps

    model = apps.get_model(label)
    field_names = {f.name for f in model._meta.get_fields()}

    assert "household" in field_names
    assert "created_by" not in field_names


@pytest.mark.parametrize("label", AUTHORED + OWNED_ONLY)
def test_model_scopes_through_the_household_manager(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household)
    theirs = baker.make(Household)
    baker.make(model, user=user, household=ours)
    baker.make(model, user=user, household=theirs)

    assert model.objects.for_household(ours).count() == 1
```

`baker.make("assistant.MemoryEmbedding")` fills the 1536-dimension `VectorField` automatically; the existing `assistant` tests already rely on that.

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_household_columns.py -q`
Expected: FAIL — `TypeError: ChatMessage() got unexpected keyword arguments: 'household'`

- [ ] **Step 3: Change the five base classes**

In `src/backend/assistant/models.py`, add to the imports:

```python
from accounts.models import AuthoredHouseholdModel, HouseholdOwnedModel
```

Then change five class statements, leaving every field, `Meta`, and method exactly as it is:

```python
class ChatMessage(AuthoredHouseholdModel):
```
```python
class MemoryRule(AuthoredHouseholdModel):
```
```python
class ReceiptDraft(AuthoredHouseholdModel):
```
```python
class MemoryEmbedding(HouseholdOwnedModel):
```
```python
class AssistantUsageEvent(HouseholdOwnedModel):
```

`MessageRole`, `MemorySource`, `ReceiptDraftStatus`, and `AssistantUsageKind` are `TextChoices` — leave them alone.

While you are in `AssistantUsageEvent`, update its docstring, which now describes work that is done:

```python
    E07 will extend this row with token counts. The household FK it wanted
    landed in E04 phase 2; `user` stays as the acting member, since a quota is
    charged to a household but attributed to a person. Keep it append-only and
    cheap to write.
```

- [ ] **Step 4: Pin the registry at 13**

Append to `src/backend/accounts/tests/test_tenancy_bases.py`:

```python
def test_registry_holds_exactly_the_thirteen_re_tenanted_models():
    """A model that grows a household column without a decision, or loses one,
    changes this number. That is the point — it should be a conversation, not
    a silent diff."""
    expected = {
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
        "assistant.AssistantUsageEvent",
    }
    actual = {m._meta.label for m in household_owned_models()}

    assert actual == expected
```

- [ ] **Step 5: Generate the migration and run the tests**

```bash
uv run python src/backend/manage.py makemigrations assistant --name household_and_created_by
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_household_columns.py src/backend/accounts/ -q
```

Expected: `assistant/migrations/0010_household_and_created_by.py` with 8 `AddField` operations (5 households + 3 `created_by`); all tests PASS.

- [ ] **Step 6: Full suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: baseline + new tests, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add src/backend/assistant src/backend/accounts
git commit -m "feat(assistant): chat, memory and drafts belong to a household"
```

---

### Task 4: Back-fill `household` and `created_by` from `user`

Every row that exists today gets its household from the owner `Membership` phase 1 seeded. This migration runs over real financial records in production; Task 8 rehearses it against a copy before it goes anywhere near Supabase.

**Files:**
- Create: `src/backend/accounts/backfill.py`
- Create: `src/backend/accounts/tests/test_backfill.py`
- Create: `src/backend/finances/migrations/0014_backfill_household.py`
- Create: `src/backend/assistant/migrations/0011_backfill_household.py`

**Interfaces:**
- Consumes: `Household`, `Membership` and the invariant phase 1's gate proved — **every user has exactly one `role="owner"` membership**.
- Produces: `accounts.backfill.backfill_household_columns(Membership, models_by_label, apps) -> dict[str, int]` — maps each model label to the number of rows it filled. Takes historical model classes so the migration and its test share one implementation.

- [ ] **Step 1: Write the failing test**

`src/backend/accounts/tests/test_backfill.py`:

```python
"""The back-fill's *rule*, tested against the live models.

Same approach as phase 1's test_migration_seed: replaying a historical
migration is heavier than this project needs. What matters is that every
pre-existing row lands in its author's household with its author recorded,
and that re-running changes nothing.
"""

import pytest
from django.apps import apps as django_apps
from model_bakery import baker

from accounts.backfill import backfill_household_columns
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def owned_household(user):
    household = baker.make(Household, name="Casa de vagner")
    baker.make(Membership, user=user, household=household, role=Role.OWNER)
    return household


def _run():
    return backfill_household_columns(
        Membership,
        {"finances.Entry": django_apps.get_model("finances.Entry")},
        django_apps,
    )


def test_backfill_sets_household_from_the_owner_membership(user, owned_household):
    entry = baker.make("finances.Entry", user=user, household=None, created_by=None)

    _run()

    entry.refresh_from_db()
    assert entry.household == owned_household
    assert entry.created_by == user


def test_backfill_leaves_already_filled_rows_alone(user, owned_household):
    """Idempotence, and the safety property that matters: a row already
    assigned to a household must never be moved to another one."""
    other = baker.make(Household, name="Outra")
    entry = baker.make("finances.Entry", user=user, household=other)

    _run()
    _run()

    entry.refresh_from_db()
    assert entry.household == other


def test_backfill_skips_a_user_with_no_membership(user):
    """Fails closed. A user with no household leaves their rows NULL rather
    than borrowing somebody's ledger — phase 4's NOT NULL will surface it."""
    entry = baker.make("finances.Entry", user=user, household=None)

    _run()

    entry.refresh_from_db()
    assert entry.household_id is None


def test_backfill_reports_what_it_touched(user, owned_household):
    baker.make("finances.Entry", user=user, household=None, _quantity=3)

    counts = _run()

    assert counts["finances.Entry"] == 3
```

> `baker.make("finances.Entry", household=None)` only stays `None` until Task 5 installs the bridge. That is why Task 4 comes first, and why Task 5 Step 6 revisits this file.

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_backfill.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.backfill'`

- [ ] **Step 3: Write the back-fill**

`src/backend/accounts/backfill.py`:

```python
"""E04 phase 2's back-fill, shared by two data migrations and their test.

Migrations receive *historical* model classes from ``apps.get_model``, so
everything here takes model classes as arguments rather than importing them.

The work is a bulk UPDATE per (user, model), not a row loop: production holds
thousands of entries and one user, so one statement per model is the whole
job. Rows that already have a household are never touched — re-running must
not move a row between households.
"""


def backfill_household_columns(Membership, models_by_label, apps):
    """Fill ``household`` (and ``created_by`` where present) from ``user``.

    Returns ``{label: rows_filled}``. A user with no owner membership is
    skipped and their rows stay NULL — failing closed, so phase 4's NOT NULL
    surfaces the gap instead of the back-fill inventing a tenant.
    """
    owners = Membership.objects.filter(role="owner").values_list("user_id", "household_id")

    counts = {}
    for label, model in models_by_label.items():
        has_created_by = any(f.name == "created_by" for f in model._meta.get_fields())
        filled = 0
        for user_id, household_id in owners:
            updates = {"household_id": household_id}
            if has_created_by:
                updates["created_by_id"] = user_id
            filled += model.objects.filter(
                user_id=user_id, household__isnull=True
            ).update(**updates)
        counts[label] = filled
    return counts
```

> `Membership.objects.filter(role="owner")` and `model.objects.filter(user_id=...)` are bare user-scoped queries. Both are correct here and neither trips the ratchet: the file lives in `accounts`, which the ratchet does not walk, and a back-fill *from* `user` is by definition the one place that must read it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_backfill.py -q`
Expected: all 4 PASS.

- [ ] **Step 5: Write the `finances` data migration**

`src/backend/finances/migrations/0014_backfill_household.py`:

```python
"""Give every existing finances row the household of the user who owns it.

Forward: household from the user's owner Membership (seeded by
accounts.0003), created_by from the user. Rows whose user has no membership
are left NULL deliberately — see accounts/backfill.py.

Reverse: NULL both columns again. Safe and lossless *because* `user` is still
present in phases 2 and 3 and remains the source of truth; once phase 4 drops
`user`, reversing past this migration means restoring from a dump.
"""

from django.db import migrations

from accounts.backfill import backfill_household_columns

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


def fill(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    models_by_label = {label: apps.get_model(label) for label in LABELS}
    backfill_household_columns(Membership, models_by_label, apps)


def unfill(apps, schema_editor):
    for label in LABELS:
        model = apps.get_model(label)
        updates = {"household_id": None}
        if any(f.name == "created_by" for f in model._meta.get_fields()):
            updates["created_by_id"] = None
        model.objects.update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("finances", "0013_household_and_created_by"),
        ("accounts", "0003_household_per_existing_user"),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
```

- [ ] **Step 6: Write the `assistant` data migration**

`src/backend/assistant/migrations/0011_backfill_household.py`:

```python
"""Give every existing assistant row the household of the user who owns it.

See finances/migrations/0014_backfill_household.py for the shape and the
reversibility note. AssistantUsageEvent and MemoryEmbedding take household
only — neither has a created_by column.
"""

from django.db import migrations

from accounts.backfill import backfill_household_columns

LABELS = [
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
    "assistant.AssistantUsageEvent",
]


def fill(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    models_by_label = {label: apps.get_model(label) for label in LABELS}
    backfill_household_columns(Membership, models_by_label, apps)


def unfill(apps, schema_editor):
    for label in LABELS:
        model = apps.get_model(label)
        updates = {"household_id": None}
        if any(f.name == "created_by" for f in model._meta.get_fields()):
            updates["created_by_id"] = None
        model.objects.update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0010_household_and_created_by"),
        ("accounts", "0003_household_per_existing_user"),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
```

- [ ] **Step 7: Run both migrations forwards and backwards on the dev database**

```bash
uv run python src/backend/manage.py migrate
uv run python src/backend/manage.py shell -c "
from finances.models import Entry
from assistant.models import ChatMessage
print('entries no household:', Entry.objects.filter(household__isnull=True).count())
print('entries no created_by:', Entry.objects.filter(created_by__isnull=True).count())
print('chat no household:', ChatMessage.objects.filter(household__isnull=True).count())
"
uv run python src/backend/manage.py migrate finances 0013
uv run python src/backend/manage.py shell -c "
from finances.models import Entry
print('after reverse, filled:', Entry.objects.filter(household__isnull=False).count())
"
uv run python src/backend/manage.py migrate
```

Expected: after the forward run, all three counts are **0**. After the reverse, `filled` is **0**. After the final forward run, 0 again.

If any count is non-zero, some user has no owner membership — re-run phase 1's gate check before going further:

```bash
uv run python src/backend/manage.py shell -c "
from django.contrib.auth import get_user_model
from accounts.models import Membership
print(get_user_model().objects.count(), Membership.objects.filter(role='owner').values('user').distinct().count())
"
```

- [ ] **Step 8: Full suite and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
git add src/backend/accounts src/backend/finances src/backend/assistant
git commit -m "feat(accounts): back-fill household and created_by from user"
```

---

### Task 5: The temporary write bridge

Phase 3 converts one surface at a time. Between now and then, every unconverted write site — and every one of the ~970 existing tests — sets only `user`. Without a bridge, those rows land with `household = NULL`, and phase 3 would be converting reads against a half-null table.

This module is **temporary and marked as such**. Phase 4 deletes it in the same commit that makes `household` NOT NULL.

**Files:**
- Create: `src/backend/accounts/bridge.py`
- Modify: `src/backend/accounts/apps.py`
- Create: `src/backend/accounts/tests/test_bridge.py`
- Modify: `src/backend/finances/models/installment_plan.py`
- Modify: `src/backend/accounts/tests/test_backfill.py`

**Interfaces:**
- Consumes: `household_owned_models()` (Task 1), `seed_household_for_user` (phase 1's `accounts/migrations_helpers.py`).
- Produces:
  - `accounts.bridge.household_for_writer(user) -> Household | None`
  - `accounts.bridge.fill_household(sender, instance, **kwargs)` — the `pre_save` receiver
  - `accounts.bridge.connect(**kwargs)` — wires the receiver to all 13 models; called from `AccountsConfig.ready()`

- [ ] **Step 1: Write the failing test**

`src/backend/accounts/tests/test_bridge.py`:

```python
"""The phase 2-3 write bridge, and — just as important — its limits.

DELETE THIS FILE IN PHASE 4, together with accounts/bridge.py.
"""

import pytest
from model_bakery import baker

from accounts.bridge import household_for_writer
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


def test_a_saved_row_gets_its_writers_household(user):
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    entry = baker.make("finances.Entry", user=user)

    assert entry.household == household
    assert entry.created_by == user


def test_an_explicit_household_is_never_overwritten(user):
    """The bridge fills a gap; it does not have an opinion. A write site that
    has been converted in phase 3 must win."""
    mine = baker.make(Household, name="Minha")
    theirs = baker.make(Household, name="Alheia")
    baker.make(Membership, user=user, household=mine, role=Role.OWNER)

    entry = baker.make("finances.Entry", user=user, household=theirs)

    assert entry.household == theirs


def test_a_user_with_no_membership_gets_one(user):
    """Tests build users with baker and never create a Membership. Rather than
    leave those rows tenant-less, give the user their own household by the same
    rule the seed migration used — so test data is coherent, and a production
    user who somehow has no membership writes into their own ledger rather
    than somebody else's."""
    entry = baker.make("finances.Entry", user=user)

    assert entry.household is not None
    assert Membership.objects.filter(user=user, role=Role.OWNER).count() == 1


def test_two_users_do_not_share_a_bridged_household(user):
    other = baker.make("core.CustomUser", username="amanda")

    mine = baker.make("finances.Entry", user=user)
    theirs = baker.make("finances.Entry", user=other)

    assert mine.household != theirs.household


def test_household_for_writer_of_none_is_none():
    assert household_for_writer(None) is None


def test_bulk_create_is_not_bridged(user):
    """Stated, not hidden: pre_save does not fire for bulk_create. Every bulk
    write site must set household itself — Task 5 Step 5 fixes the only one in
    production code, and this test is the reason a future one gets caught."""
    from finances.models import Entry

    category = baker.make("finances.Category", user=user)
    method = baker.make("finances.PaymentMethod", user=user, type="pix")
    Entry.objects.bulk_create(
        [
            Entry(
                user=user,
                date="2026-03-01",
                amount="10.00",
                description="bulk",
                category=category,
                payment_method=method,
                billing_month="2026-03-01",
                billing_month_override=True,
            )
        ]
    )

    assert Entry.objects.filter(description="bulk", household__isnull=True).count() == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_bridge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.bridge'`

- [ ] **Step 3: Write the bridge**

`src/backend/accounts/bridge.py`:

```python
"""TEMPORARY — delete in E04 phase 4, with accounts/tests/test_bridge.py.

Phases 2 and 3 run with both `user` and `household` on every domain model,
and with the app only partly converted: an unconverted view still writes rows
that set `user` alone, as do the ~970 tests written before tenancy existed.

This receiver fills the gap so that no row is ever written tenant-less, which
is what lets phase 3 convert one surface per commit instead of all at once.

It fills only what is missing — a converted write site's explicit household
always wins. It cannot help `bulk_create` or `bulk_update`, which bypass
signals entirely; those call sites set household themselves.

Phase 4 makes `household` NOT NULL and drops `user`. At that point every write
path sets household explicitly, this module has nothing left to do, and
keeping it would only hide the next mistake.
"""

from django.db.models.signals import pre_save

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership, household_owned_models


def household_for_writer(user):
    """The household a row written by ``user`` belongs to.

    Falls back to creating the user their own household — the same rule the
    seed migration applied — rather than returning None and letting the row
    land tenant-less. A user with no membership writing into their own new
    ledger is the fail-closed outcome; borrowing an existing household would
    be the leak.
    """
    if user is None:
        return None
    membership = Membership.objects.filter(user=user).first()
    if membership is not None:
        return membership.household
    return seed_household_for_user(Household, Membership, user)


def fill_household(sender, instance, **kwargs):
    if instance.household_id is not None:
        return
    user = instance.user
    if user is None:
        return
    instance.household = household_for_writer(user)
    if hasattr(instance, "created_by_id") and instance.created_by_id is None:
        instance.created_by = user


def connect(**kwargs):
    """Wire the receiver to every household-owned model. Idempotent via
    dispatch_uid, so a double ``ready()`` in tests is harmless."""
    for model in household_owned_models():
        pre_save.connect(
            fill_household,
            sender=model,
            dispatch_uid=f"e04_bridge_{model._meta.label_lower}",
        )
```

> `Membership.objects.filter(user=user)` is another deliberate bare user query in `accounts` — the same seam phase 1 documented in `resolve_active_household`. The ratchet walks only `finances` and `assistant`.

- [ ] **Step 4: Connect it in `AppConfig.ready()`**

`src/backend/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # E04 phase 2-3 only. Removed in phase 4 — see accounts/bridge.py.
        from accounts import bridge

        bridge.connect()
```

- [ ] **Step 5: Fix the one production bulk write**

`InstallmentPlan.generate_entries` builds `Entry` objects and `bulk_create`s them, which no signal reaches. In `src/backend/finances/models/installment_plan.py`, add `household` and `created_by` to the `Entry(...)` constructor inside the loop:

```python
            entries.append(
                Entry(
                    user=self.user,
                    household=self.household,
                    created_by=self.created_by or self.user,
                    date=self.date,
                    amount=amount,
                    description=f"{self.description} ({i + 1}/{self.num_installments})",
                    category=self.category,
                    payment_method=self.payment_method,
                    entry_type=EntryType.INSTALLMENT,
                    billing_month=billing_month,
                    billing_month_override=True,
                    installment_plan=self,
                )
            )
```

The plan itself is saved through `save()`, so the bridge has already given it a household by the time `generate_entries` runs. `bulk_update` at line 93 writes only `billing_month` and needs no change.

`src/backend/finances/management/commands/seed_perf_data.py` also bulk-creates (`Entry`, `Income`, `ChatMessage`, `MemoryEmbedding`). It is a developer command for E03 benchmarking, not production code. Give its four `bulk_create` calls `household=household` where `household` is resolved once at the top of the command:

```python
from accounts.bridge import household_for_writer

# ...near where the command resolves its user:
household = household_for_writer(user)
```

Then pass `household=household` into each constructed object. Without this, phase 4's NOT NULL breaks the perf harness at exactly the moment you want to re-measure the indexes.

- [ ] **Step 6: Fix the back-fill test the bridge just invalidated**

Task 4's tests pass `household=None` to `baker.make`, which the bridge now overrides. Change those three call sites in `src/backend/accounts/tests/test_backfill.py` to write the NULL after creation, so the test still exercises what the migration will actually meet in production:

```python
def _make_unfilled_entry(user):
    """A row as it exists in production before the back-fill: the bridge is a
    phase 2 invention, so pre-E04 rows have no household at all."""
    from finances.models import Entry

    entry = baker.make("finances.Entry", user=user)
    Entry.objects.filter(pk=entry.pk).update(household=None, created_by=None)
    entry.refresh_from_db()
    return entry
```

Replace `baker.make("finances.Entry", user=user, household=None, created_by=None)` with `_make_unfilled_entry(user)` in `test_backfill_sets_household_from_the_owner_membership`, `test_backfill_skips_a_user_with_no_membership`, and the `_quantity=3` case in `test_backfill_reports_what_it_touched` (call it three times). `test_backfill_leaves_already_filled_rows_alone` passes an explicit household and needs no change.

A queryset `.update()` bypasses signals, which is exactly why it is the right tool here.

- [ ] **Step 7: Run the bridge tests, then the full suite**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

Expected: all accounts tests PASS; the full suite holds at baseline + new tests, 0 failed.

**Watch for query-count tests.** `finances/tests/` guards hot read paths with `django_assert_num_queries` (E03). The bridge fires on writes only, so read-path counts are unchanged — but if a guarded block *creates* data inside the assertion, the bridge adds one SELECT (and, for a membership-less user, one INSERT pair) per distinct user. If a count test fails, move the fixture setup outside the assertion rather than raising the expected number: the extra query is a phase 2 artefact and would have to be lowered again in phase 4.

- [ ] **Step 8: Commit**

```bash
git add src/backend/accounts src/backend/finances
git commit -m "feat(accounts): temporary bridge so no row is written tenant-less"
```

---

### Task 6: Re-scope the unique constraints to the household

Four constraints scope uniqueness by user today. Each gains a household twin. **The user constraint is kept**, so there is no window in which uniqueness is weaker than it is now; phase 4 drops the user half together with the column.

**Files:**
- Modify: `src/backend/finances/models/{category,budget,payment_method}.py`
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/finances/migrations/0015_household_constraints_and_indexes.py` (generated, completed in Task 7)
- Create: `src/backend/assistant/migrations/0012_household_constraints_and_indexes.py` (generated, completed in Task 7)
- Modify: `src/backend/finances/tests/test_household_columns.py`
- Modify: `src/backend/assistant/tests/test_household_columns.py`

**Interfaces:**
- Consumes: the `household` column (Tasks 1–3), populated rows (Task 4), the bridge (Task 5).
- Produces: constraints `unique_category_per_household`, `unique_budget_per_household`, `unique_payment_method_per_household`, `unique_memory_rule_per_household`.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/finances/tests/test_household_columns.py`:

```python
def test_two_members_cannot_create_the_same_category_twice(user):
    """The new capability's sharp edge: two people in one household share a
    category list, so the second person adding 'Alimentação' must collide."""
    from django.db import IntegrityError

    household = baker.make(Household)
    amanda = baker.make("core.CustomUser", username="amanda")
    baker.make("finances.Category", user=user, household=household, name="Alimentação")

    with pytest.raises(IntegrityError):
        baker.make("finances.Category", user=amanda, household=household, name="Alimentação")


def test_the_same_category_name_in_two_households_is_fine(user):
    amanda = baker.make("core.CustomUser", username="amanda")
    ours = baker.make(Household)
    theirs = baker.make(Household)
    baker.make("finances.Category", user=user, household=ours, name="Alimentação")

    other = baker.make("finances.Category", user=amanda, household=theirs, name="Alimentação")

    assert other.name == "Alimentação"


def test_two_members_cannot_create_the_same_budget_twice(user):
    from django.db import IntegrityError

    household = baker.make(Household)
    amanda = baker.make("core.CustomUser", username="amanda")
    baker.make("finances.Budget", user=user, household=household, name="Custeio")

    with pytest.raises(IntegrityError):
        baker.make("finances.Budget", user=amanda, household=household, name="Custeio")


def test_two_members_cannot_create_the_same_payment_method_twice(user):
    from django.db import IntegrityError

    household = baker.make(Household)
    amanda = baker.make("core.CustomUser", username="amanda")
    baker.make("finances.PaymentMethod", user=user, household=household, name="Nubank")

    with pytest.raises(IntegrityError):
        baker.make("finances.PaymentMethod", user=amanda, household=household, name="Nubank")
```

Append to `src/backend/assistant/tests/test_household_columns.py`:

```python
def test_two_members_cannot_create_the_same_memory_rule_twice(user):
    from django.db import IntegrityError

    household = baker.make(Household)
    amanda = baker.make("core.CustomUser", username="amanda")
    baker.make(
        "assistant.MemoryRule",
        user=user,
        household=household,
        trigger="pague menos",
        field="category",
    )

    with pytest.raises(IntegrityError):
        baker.make(
            "assistant.MemoryRule",
            user=amanda,
            household=household,
            trigger="pague menos",
            field="category",
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_columns.py src/backend/assistant/tests/test_household_columns.py -q -k "same"`
Expected: the four `cannot_create_the_same_*_twice` tests FAIL with `DID NOT RAISE IntegrityError` — the household constraints do not exist yet. `test_the_same_category_name_in_two_households_is_fine` passes already.

- [ ] **Step 3: Add the household constraints**

`src/backend/finances/models/category.py`, in `Meta` — keep `unique_together` as it is and add `constraints`:

```python
    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        # Both hold during phases 2 and 3. The user constraint goes away in
        # phase 4 with the column, and this becomes the only one.
        unique_together = ("user", "name")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_category_per_household"
            ),
        ]
```

`src/backend/finances/models/budget.py`:

```python
    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        unique_together = ("user", "name")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_budget_per_household"
            ),
        ]
```

`src/backend/finances/models/payment_method.py` — append to the existing `constraints` list:

```python
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_payment_method_per_user"),
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_payment_method_per_household"
            ),
        ]
```

`src/backend/assistant/models.py`, `MemoryRule.Meta`:

```python
    class Meta:
        verbose_name = "regra de memória"
        verbose_name_plural = "regras de memória"
        unique_together = ("user", "trigger", "field")
        constraints = [
            models.UniqueConstraint(
                fields=["household", "trigger", "field"],
                name="unique_memory_rule_per_household",
            ),
        ]
```

> A `UniqueConstraint` over a nullable column lets many NULL rows coexist, because Postgres treats NULLs as distinct. That is harmless here: Task 4 filled every existing row and Task 5 stops new NULLs appearing, and phase 4's NOT NULL closes the theoretical gap for good.

- [ ] **Step 4: Generate the migrations and run the tests**

```bash
uv run python src/backend/manage.py makemigrations finances --name household_constraints_and_indexes
uv run python src/backend/manage.py makemigrations assistant --name household_constraints_and_indexes
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_columns.py src/backend/assistant/tests/test_household_columns.py -q
```

Expected: `finances/0015` with three `AddConstraint`, `assistant/0012` with one; all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances src/backend/assistant
git commit -m "feat(finances): uniqueness is per household, not per person"
```

---

### Task 7: Re-create E03's indexes with `household` leading

E03 measured six indexes into existence, five of which lead with `user`. Each gains a household-leading twin in the same migration files Task 6 created. The `user` ones stay until phase 4, because phase 3's queries still use them right up to the commit that converts each surface.

`memory_embed_hnsw_cosine_idx` is on the vector column alone and needs no change.

**Files:**
- Modify: `src/backend/finances/models/{entry,income}.py`
- Modify: `src/backend/assistant/models.py`
- Modify: `src/backend/finances/migrations/0015_household_constraints_and_indexes.py` (regenerated)
- Modify: `src/backend/assistant/migrations/0012_household_constraints_and_indexes.py` (regenerated)
- Create: `src/backend/finances/tests/test_household_indexes.py`

**Interfaces:**
- Consumes: the `household` column.
- Produces: `entry_hh_billing_type_idx`, `entry_hh_date_recent_idx`, `income_hh_month_idx`, `chat_hh_recent_idx`, `draft_hh_status_recent_idx`, `usage_hh_kind_recent_idx`.

> Index names must stay under Django's 30-character limit — `hh` rather than `household` is the reason, and the E03 plan already hit this wall once (see `docs/runbook.md`, "Verifying the E03 indexes landed").

- [ ] **Step 1: Write the failing test**

`src/backend/finances/tests/test_household_indexes.py`:

```python
"""E03's indexes, re-created with household as the leading column.

The user-leading originals stay until phase 4: phase 3 converts one surface
at a time, and until a surface is converted its queries still filter by user.
Dropping the old indexes now would deoptimise the app mid-refactor.
"""

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

HOUSEHOLD_LEADING = {
    "finances_entry": ["entry_hh_billing_type_idx", "entry_hh_date_recent_idx"],
    "finances_income": ["income_hh_month_idx"],
    "assistant_chatmessage": ["chat_hh_recent_idx"],
    "assistant_receiptdraft": ["draft_hh_status_recent_idx"],
    "assistant_assistantusageevent": ["usage_hh_kind_recent_idx"],
}

USER_LEADING_STILL_PRESENT = [
    "entry_user_billing_type_idx",
    "entry_user_date_recent_idx",
    "income_user_month_idx",
    "chat_user_recent_idx",
    "draft_user_status_recent_idx",
    "usage_user_kind_recent_idx",
]


def _index_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        return {row[0] for row in cursor.fetchall()}


def test_every_household_leading_index_exists():
    existing = _index_names()
    expected = [name for names in HOUSEHOLD_LEADING.values() for name in names]

    assert set(expected) <= existing, sorted(set(expected) - existing)


def test_the_user_leading_indexes_are_still_there():
    """Phase 4 drops these with the column. Removing one earlier would slow
    every not-yet-converted query path in phase 3."""
    existing = _index_names()

    assert set(USER_LEADING_STILL_PRESENT) <= existing


def test_household_index_leads_with_household():
    """Leading column decides whether a household-only filter can use it."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", ["entry_hh_billing_type_idx"])
        definition = cursor.fetchone()[0]

    columns = definition.split("(", 1)[1].rstrip(")")
    assert columns.split(",")[0].strip().startswith("household_id")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_indexes.py -q`
Expected: FAIL — `test_every_household_leading_index_exists` lists all six as missing.

- [ ] **Step 3: Add the household-leading indexes**

`src/backend/finances/models/entry.py`, append to `Meta.indexes`:

```python
            # The household twins of the two indexes above. Phase 3 converts
            # the dashboard's queries onto them one surface at a time; the
            # user-leading pair stays until phase 4 drops the column.
            models.Index(
                fields=["household", "billing_month", "entry_type"],
                name="entry_hh_billing_type_idx",
            ),
            models.Index(
                fields=["household", "-date", "-created_at"],
                name="entry_hh_date_recent_idx",
            ),
```

`src/backend/finances/models/income.py`, append to `Meta.indexes`:

```python
            models.Index(fields=["household", "month"], name="income_hh_month_idx"),
```

`src/backend/assistant/models.py` — `ChatMessage.Meta.indexes`:

```python
            models.Index(fields=["household", "-created_at"], name="chat_hh_recent_idx"),
```

`ReceiptDraft.Meta.indexes`:

```python
            models.Index(
                fields=["household", "status", "-created_at"],
                name="draft_hh_status_recent_idx",
            ),
```

`AssistantUsageEvent.Meta.indexes`:

```python
            models.Index(
                fields=["household", "kind", "-created_at"],
                name="usage_hh_kind_recent_idx",
            ),
```

Leave every existing index in place. Leave `db_index=False` on `Entry.user`, `Income.user`, `ChatMessage.user`, and `ReceiptDraft.user` — the reasoning in those comments still holds while the user indexes exist. Do **not** add `db_index=False` to `household`: the base class does not set it, and the FK's own index is what serves a bare `for_household()` lookup until the composites are in play. Phase 4 revisits this with fresh `EXPLAIN` numbers, exactly as E03 did.

- [ ] **Step 4: Regenerate the migrations**

Task 6's `0015` and `0012` hold constraints only. Delete and regenerate so each app ships one migration carrying both constraints and indexes:

```bash
rm src/backend/finances/migrations/0015_household_constraints_and_indexes.py
rm src/backend/assistant/migrations/0012_household_constraints_and_indexes.py
uv run python src/backend/manage.py makemigrations finances --name household_constraints_and_indexes
uv run python src/backend/manage.py makemigrations assistant --name household_constraints_and_indexes
uv run python src/backend/manage.py migrate
```

Expected: `finances/0015` with 3 `AddConstraint` + 3 `AddIndex`; `assistant/0012` with 1 `AddConstraint` + 3 `AddIndex`.

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_household_indexes.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

Expected: all 3 index tests PASS; full suite at baseline + new tests, 0 failed.

- [ ] **Step 6: Confirm the planner will actually use one**

The real `EXPLAIN ANALYZE` evidence belongs to phase 3, when the app's queries filter by household. What is checkable now is that the index is usable at all:

```bash
uv run python src/backend/manage.py dbshell -c "
  EXPLAIN (ANALYZE, BUFFERS)
  SELECT * FROM finances_entry
   WHERE household_id = (SELECT id FROM accounts_household LIMIT 1)
     AND billing_month = '2026-08-01';"
```

Expected: an `Index Scan using entry_hh_billing_type_idx`. On a dev database with few rows the planner may prefer a `Seq Scan` — that is not a failure. If it does, force the comparison and record it:

```bash
uv run python src/backend/manage.py dbshell -c "
  SET enable_seqscan = off;
  EXPLAIN SELECT * FROM finances_entry
   WHERE household_id = (SELECT id FROM accounts_household LIMIT 1)
     AND billing_month = '2026-08-01';"
```

Expected: the index scan appears, proving the index is applicable to the predicate. Paste both outputs into the commit body.

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances src/backend/assistant
git commit -m "perf(finances): E03's indexes, re-cut with household leading"
```

---

### Task 8: Rehearse the migration against a copy of production data

The epic's Definition of Done is explicit and this project has a documented history of balance reconciliation issues: **compare balances, not row counts.**

The lever that makes this cheap: phase 2 does not touch a single read path. `build_projection(user, ...)` in `finances/services/projection.py` still scopes by `user` and computes `acumulado` exactly as it did yesterday. So running it before and after the migration must produce **byte-identical** output. Any difference is data corruption, and the comparison needs no new arithmetic to trust.

**Files:**
- Create: `scripts/rehearse-e04-migration.sh`
- Create: `src/backend/finances/management/commands/dump_ledger_totals.py`
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: `finances.services.projection.build_projection(user, start_month, num_months)` — returns a list of dicts including `acumulado`, `total`, `income`.
- Produces: `manage.py dump_ledger_totals --json` — a stable, sorted JSON document of every figure that must survive the migration.

- [ ] **Step 1: Write the failing test**

`src/backend/finances/tests/test_dump_ledger_totals.py`:

```python
"""The before/after fingerprint used to prove the E04 migration is lossless."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

pytestmark = pytest.mark.django_db


def test_dump_reports_per_user_totals_and_acumulado(user):
    category = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 10),
        amount=Decimal("50.00"),
        description="Feira",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 3, 1),
    )
    baker.make("finances.Income", user=user, amount=Decimal("100.00"), month=date(2026, 3, 1))

    out = StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out)
    report = json.loads(out.getvalue())

    ledger = report["vagner"]
    assert ledger["entry_count"] == 1
    assert ledger["entry_sum"] == "50.00"
    assert ledger["income_sum"] == "100.00"
    assert any(month["acumulado"] == "50.00" for month in ledger["months"])


def test_dump_is_deterministic(user):
    out_a, out_b = StringIO(), StringIO()
    call_command("dump_ledger_totals", "--json", stdout=out_a)
    call_command("dump_ledger_totals", "--json", stdout=out_b)

    assert out_a.getvalue() == out_b.getvalue()
```

The `acumulado` assertion checks the sign convention this project actually uses — if the first run shows `-50.00`, take that as the answer and fix the test to match, since the point is stability across the migration rather than a claim about the sign.

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_dump_ledger_totals.py -q`
Expected: FAIL — `CommandError: Unknown command: 'dump_ledger_totals'`

- [ ] **Step 3: Write the command**

`src/backend/finances/management/commands/dump_ledger_totals.py`:

```python
"""Fingerprint the ledger's money, for before/after comparison across a migration.

Row counts do not prove a migration was lossless — this project has a
documented history of reconciliation issues where the counts matched and the
balances did not. This dumps the numbers that actually matter: per-user entry
and income sums, and the running acumulado per month straight out of the
projection service.

Scoped by user on purpose. E04 phase 2 changes no read path, so running this
before and after the migration must produce identical output; a diff is
corruption. Phase 4 re-points it at household.
"""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Count, Min, Sum

from finances.models import Entry, Income
from finances.services.projection import build_projection, projection_origin


class Command(BaseCommand):
    help = "Dump per-user ledger totals and the monthly acumulado as JSON."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")
        parser.add_argument(
            "--months", type=int, default=36, help="How many months of acumulado to include."
        )

    def handle(self, *args, **options):
        report = {}
        for user in get_user_model().objects.order_by("username"):
            entries = Entry.objects.filter(user=user).aggregate(
                n=Count("id"), total=Sum("amount"), first=Min("billing_month")
            )
            incomes = Income.objects.filter(user=user).aggregate(total=Sum("amount"))
            start = entries["first"] or projection_origin()
            start = max(start.replace(day=1), projection_origin())
            months = build_projection(
                user, start, options["months"], today=date(2026, 8, 12)
            )
            report[user.get_username()] = {
                "entry_count": entries["n"],
                "entry_sum": f"{entries['total'] or 0:.2f}",
                "income_sum": f"{incomes['total'] or 0:.2f}",
                "months": [
                    {
                        "month": m["month"].isoformat(),
                        "total": f"{m['total']:.2f}",
                        "income": f"{m['income']:.2f}",
                        "acumulado": f"{m['acumulado']:.2f}",
                    }
                    for m in months
                ],
            }

        payload = json.dumps(report, indent=2, sort_keys=True)
        self.stdout.write(payload if options["json"] else payload)
```

`today` is pinned to a literal date so two runs days apart still compare — the past/future split in `build_projection` depends on it, and a drifting `today` would produce a spurious diff. Update the literal if the rehearsal happens after 2026-08-12.

- [ ] **Step 4: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_dump_ledger_totals.py -q`
Expected: both PASS.

- [ ] **Step 5: Write the rehearsal script**

`scripts/rehearse-e04-migration.sh`:

```bash
#!/usr/bin/env bash
# Rehearse E04 phase 2 against a COPY of production Supabase data.
#
# The epic's Definition of Done: "entry counts, balances, and the monthly
# acumulado match before and after". Phase 2 changes no read path, so the
# fingerprint must be byte-identical — any diff is corruption.
#
# Credentials come from libpq/Django env vars, never a URL: the production
# password contains a space (docs/runbook.md, "Common failure #2").
#
# Required env: PGHOST PGPORT PGUSER PGPASSWORD PGSSLMODE
# Usage: scripts/rehearse-e04-migration.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPY="${COPY:-ledger_rehearsal}"
DUMP="${DUMP:-/tmp/ledger-prod.dump}"
: "${PGHOST:?set PGHOST}" "${PGUSER:?set PGUSER}" "${PGPASSWORD:?set PGPASSWORD}"
export PGPORT="${PGPORT:-5432}" PGSSLMODE="${PGSSLMODE:-require}"

pg17() {
  docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGSSLMODE \
    -e PGDATABASE -v /tmp:/tmp postgres:17 "$@"
}
on_copy() {  # run manage.py against the rehearsal copy
  POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" \
  POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$COPY" \
    uv run python "$ROOT/src/backend/manage.py" "$@"
}

echo "==> dumping production (treat $DUMP as production data)"
PGDATABASE=postgres pg17 pg_dump --no-owner --no-acl -Fc -f "$DUMP"

echo "==> (re)creating $COPY"
PGDATABASE=postgres pg17 psql -q -c "DROP DATABASE IF EXISTS $COPY WITH (FORCE);"
PGDATABASE=postgres pg17 psql -q -c "CREATE DATABASE $COPY;"
PGDATABASE="$COPY" pg17 psql -q -c "CREATE EXTENSION IF NOT EXISTS vector;"
PGDATABASE="$COPY" pg17 pg_restore -d "$COPY" --no-owner "$DUMP" || \
  echo "   (pg_restore errors on Supabase's vault schema are expected — checking data instead)"

echo "==> BEFORE fingerprint"
on_copy dump_ledger_totals --json > /tmp/e04-before.json
python3 -c "import json;d=json.load(open('/tmp/e04-before.json'));print('  users:',len(d));[print(f\"  {u}: {v['entry_count']} entries, sum {v['entry_sum']}\") for u,v in d.items()]"

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER fingerprint"
on_copy dump_ledger_totals --json > /tmp/e04-after.json

echo "==> diff"
if diff -u /tmp/e04-before.json /tmp/e04-after.json; then
  echo "OK — counts, sums and acumulado identical across the migration."
else
  echo "!! FINGERPRINT CHANGED. Do not apply this migration to production." >&2
  exit 1
fi

echo "==> no row left tenant-less"
on_copy shell -c "
from accounts.models import household_owned_models
bad = {m._meta.label: m.objects.filter(household__isnull=True).count() for m in household_owned_models()}
bad = {k: v for k, v in bad.items() if v}
print('unfilled rows:', bad or 'none')
assert not bad, bad
print('OK')
"

echo "==> household-leading indexes present"
PGDATABASE="$COPY" pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE indexname IN ('entry_hh_billing_type_idx','entry_hh_date_recent_idx',
                       'income_hh_month_idx','chat_hh_recent_idx',
                       'draft_hh_status_recent_idx','usage_hh_kind_recent_idx')
   ORDER BY indexname;"
echo "   (expect six rows)"

echo "==> cleaning up"
PGDATABASE=postgres pg17 psql -q -c "DROP DATABASE IF EXISTS $COPY WITH (FORCE);"
rm -f "$DUMP" /tmp/e04-before.json /tmp/e04-after.json
echo "Rehearsal complete."
```

```bash
chmod +x scripts/rehearse-e04-migration.sh
```

- [ ] **Step 6: Run the rehearsal for real**

This is the DoD item that cannot be skipped or simulated. Export the Supabase credentials as libpq variables (never a URL — the password has a space) and run:

```bash
scripts/rehearse-e04-migration.sh
```

Expected: `OK — counts, sums and acumulado identical across the migration.`, `unfilled rows: none`, six index rows, then `Rehearsal complete.`

If the diff is non-empty, **stop**. Do not adjust the fingerprint to make it pass. Read the diff: a changed `acumulado` with unchanged `entry_sum` means rows moved between billing months; a changed `entry_count` means the migration deleted or duplicated. Either way the back-fill is wrong and Task 4 needs revisiting.

If `unfilled rows` is non-empty, some production user has no owner `Membership` — phase 1's seed did not cover them. Fix by re-running `accounts.0003` on the copy, then re-run the whole rehearsal.

- [ ] **Step 7: Document it in the runbook**

Add to `docs/runbook.md`, immediately after the "Applying a migration to Supabase" section, a subsection `### Rehearsing the E04 tenancy migration` containing: the required env vars, the one command, the three expected outputs, and the sentence *"A non-empty diff means the back-fill is wrong. Never apply to production on a non-empty diff."* Also add a one-line pointer from the README quickstart and from `AGENTS.md` if it exists, per the project's runbook convention.

- [ ] **Step 8: Commit**

```bash
git add scripts/rehearse-e04-migration.sh src/backend/finances docs/runbook.md README.md
git commit -m "test(finances): fingerprint the ledger's money across the migration"
```

---

### Task 9: Phase gate

No files created. This is the checkpoint before phase 3 touches a read path.

- [ ] **Step 1: Full suite under the real clock**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: the baseline recorded before Task 1, plus roughly 45 new tests, 0 failed.

- [ ] **Step 2: Full suite under a shifted clock**

Run: `POSTGRES_PORT=5433 TEST_CLOCK_SHIFT=+1y uv run pytest src/backend/ -q -m "not current_date"`
Expected: same counts. Run **serially** after Step 1 — concurrent runs collide on the test database.

- [ ] **Step 3: Gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run python src/backend/manage.py check
```

Expected: coverage ≥ 80, lint clean, `No changes detected`, system check clean.

- [ ] **Step 4: The ratchet has not moved**

Phase 2 converts no read path, so the baseline in `accounts/tests/test_scoping_ratchet.py` must be **unchanged** — same 22 files, nothing struck, nothing added.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
git diff main --stat -- src/backend/accounts/tests/test_scoping_ratchet.py
```

Expected: both tests PASS and the diff is **empty**. A struck entry means a read path was converted — that is phase 3 work and does not belong in this branch. An added entry means a new leak.

- [ ] **Step 5: Confirm the invariants phase 3 depends on**

```bash
uv run python src/backend/manage.py shell -c "
from accounts.models import household_owned_models
models = household_owned_models()
print('re-tenanted models:', len(models))
assert len(models) == 13, [m._meta.label for m in models]
unfilled = {m._meta.label: m.objects.filter(household__isnull=True).count() for m in models}
unfilled = {k: v for k, v in unfilled.items() if v}
print('rows without a household:', unfilled or 'none')
assert not unfilled, unfilled
print('OK')
"
```

Expected: `13`, `none`, `OK`.

- [ ] **Step 6: Confirm no read path was touched**

```bash
git diff main --stat -- src/backend/finances/views src/backend/finances/api \
  src/backend/finances/services src/backend/assistant/agents src/backend/assistant/views.py
```

Expected: **empty**. If anything appears here, phase 3 leaked into phase 2 — move it to its own branch.

- [ ] **Step 7: Commit and open for review**

```bash
git commit --allow-empty -m "chore(accounts): E04 phase 2 gate — 13 models re-tenanted, ledger totals unchanged"
```

Then request review per `superpowers:requesting-code-review`, and run `/security-review` — this branch changes the tenancy schema, and the epic makes that review mandatory.

**Do not start phase 3 in the same session.** Phase 3 converts ~200 call sites across six view modules, a DRF API, the services layer, and ~45 agent tools; it deserves a fresh reviewer on this foundation and a plan of its own.

---

## Follow-on plans — NOT part of this plan

Do not execute these from this document. Each gets its own plan file, written after the preceding phase has landed and been reviewed.

| Phase | Epic stories | Deliverable | Why it waits |
|---|---|---|---|
| **3 · Re-scope reads and writes** | S04-4, S04-5 | DRF API, six HTMX view modules, `finances/services/`, then the agent — `deps_type` becomes a structure carrying household **and** acting user, and ~45 tools in `assistant/agents/tools.py` scope by household. One surface per commit; a ratchet baseline entry struck as each lands. The two `PaymentMethod.objects.filter(pk=...)` unions at `views/cockpit.py:233` and `:469` are **not** leaks — read the epic's note before "fixing" them, and add the cheap test it asks for. | Cannot start until models carry `household`, which is what this plan delivers. The agent goes last: its scope must come from `ctx.deps` and never from an LLM-supplied argument, so it wants the quietest possible diff. |
| **4 · Prove the boundary** | S04-6 | The 12 isolation test modules convert from cross-user to cross-household; a parameterized test over `household_owned_models()` asserts every one rejects cross-household access, reaching `PaymentMethodClosingDay` through its parent; a test asserts two users in one household see identical data; `household` becomes NOT NULL; `user` is dropped from 12 of the 13 models (**not** from `AssistantUsageEvent`, where it is the actor); the user-leading constraints and indexes are dropped; `accounts/bridge.py` and `accounts/tests/test_bridge.py` are deleted; the ratchet's baseline is emptied and its test becomes the absolute assertion S04-2 asked for. | The epic's own risk note: "a missed call site is a cross-tenant data leak, not a bug." Write the parameterized test **early in phase 4**, not last. |

---

## Self-Review

**Spec coverage.** This plan covers S04-3 completely, clause by clause:

| S04-3 clause | Task |
|---|---|
| each model carries `household = FK(Household)` | 1, 2, 3 |
| `created_by = FK(User, null=True, on_delete=SET_NULL)` where provenance matters | 1 (the base), with the 11-of-13 split justified in the base-class table |
| every listed unique constraint re-scoped from user to household | 6 (all four: `Budget`, `Category`, `PaymentMethod`, `MemoryRule`) |
| data migration back-fills `household` from `user` via the Membership from S04-1 | 4 |
| `created_by` back-filled from the previous `user`, preserving history | 4 |
| E03's indexes re-created with `household` leading | 7 (all six user-leading indexes; the HNSW one needs no change) |

DoD items this plan discharges: *"`created_by` is populated for all back-filled rows"* (Task 4 Step 7, Task 9 Step 5); *"the data migration has been run against a copy of the real Supabase data, and entry counts, balances, and the monthly acumulado match"* (Task 8, which compares `acumulado` and not just counts); *"E03's indexes are re-created with `household` leading"* (Task 7). The remaining DoD items — the parameterized cross-household test, two users seeing identical data, the agent argument-injection test, `/security-review` clean — belong to phases 3 and 4 and are listed in the follow-on table.

**Two deliberate deviations from the epic's letter, both stated where an executor will meet them:** 13 models rather than "10" (the epic's own table lists 11; `ImportBatch` and `AssistantUsageEvent` were added by decision on 2026-08-12), and `user` columns, constraints, and indexes are *kept* rather than replaced, so there is no window in which the data is less protected than today.

**Placeholder scan.** No TBDs. Every code step carries real code. The three places where reality might differ from the plan name the check and the fix rather than hand-waving: the `acumulado` sign convention (Task 8 Step 1), a `Seq Scan` on a small dev database (Task 7 Step 6), and query-count tests that create data inside the assertion (Task 5 Step 7).

**Type consistency.** `HouseholdOwnedModel` / `AuthoredHouseholdModel` / `household_owned_models()` are named identically in Task 1 (definition), Tasks 2–3 (call sites), Task 5 (`bridge.connect`), Task 8's rehearsal script, and Task 9's invariant check. `household_for_writer(user)` is defined in Task 5 Step 3 and imported by Task 5 Step 5's `seed_perf_data` change. `backfill_household_columns(Membership, models_by_label, apps)` has the same three-argument signature in Task 4 Steps 3, 5 and 6. `seed_household_for_user(Household, Membership, user)` matches phase 1's existing helper exactly. The six new index names are spelled identically in Task 7 Step 3, Task 7 Step 1's test, and Task 8's script, and all six are under Django's 30-character limit.

**One known seam, stated rather than hidden.** `accounts/backfill.py` and `accounts/bridge.py` both run bare `filter(user=...)` queries. Both are correct — a back-fill *from* `user` and the resolution of *which* household a writer belongs to are the two queries that cannot themselves be household-scoped — and both live in `accounts`, which the phase 1 ratchet excludes by construction. This is the same seam phase 1 documented for `resolve_active_household`.
