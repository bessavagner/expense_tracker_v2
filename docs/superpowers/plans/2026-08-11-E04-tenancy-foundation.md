# E04 Phase 1 — Tenancy Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `accounts` app — `Household`, `Membership`, one auditable scoping path, and `request.household` — so that every later phase has exactly one way to scope a query, without touching a single domain model yet.

**Architecture:** A new `accounts` Django app owns tenancy. `Household` is the tenant; `Membership(user, household, role)` joins them, so a user may belong to several households while the UI keeps one active at a time (resolved per request from the session by middleware). All scoping goes through `HouseholdScopedQuerySet.for_household()` / `.for_request()` — one class, one place to review, one place to test. A data migration gives every existing user their own household so no row is ever orphaned. Domain models are **untouched** in this phase; they still carry `FK(user)` and the suite stays green throughout.

**Tech Stack:** Django 5, PostgreSQL (pgvector image on `:5433` locally), pytest + pytest-django + model_bakery, ruff, uv.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7 and the E04 epic. Every task's requirements implicitly include this section.

- **TDD.** Test first, always. Red → green → refactor. Project convention, not a preference.
- **Worktrees.** This work happens in an isolated worktree, not on `main`.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing (currently 90%).
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean.
- **Migrations are reversible**, or the task states explicitly why not.
- **pt-BR in the product UI, English in code, comments, and docs.** `verbose_name` is UI-facing → pt-BR.
- **No time-bomb tests.** Any date-sensitive test freezes the clock (`time_machine`). The suite runs under `TEST_CLOCK_SHIFT=+1y` in CI and must stay green.
- **No new secret in git.**
- **UUID primary keys** on new domain-ish models, matching `finances/models/category.py`.
- **The money boundary holds.** Not exercised in this phase — no arithmetic changes.

### Decisions already made — do not re-litigate

From `docs/backlog/E04-household-tenancy.md` § "Open questions — DECIDED 2026-08-11":

1. Multi-household **yes in the schema**, one active at a time in the UI.
2. Roles are **`owner` and `member`, nothing else.** No viewer, no permission framework.
3. Last owner deleting their account → **promote the longest-standing remaining member.** Implemented in E13; this phase only needs `Membership.created_at` to exist and be indexed so the promotion is expressible.
4. `PaymentMethodClosingDay` stays **transitively scoped** via `PaymentMethod`. No household column.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# The accounts app alone, while iterating
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q

# Gates
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

**Do not run two pytest invocations concurrently** — they share the `test_expense_tracker` database and the second fails with `database ... is being accessed by other users`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/accounts/__init__.py` | app package |
| `src/backend/accounts/apps.py` | `AccountsConfig` |
| `src/backend/accounts/models.py` | `Household`, `Membership`, `Role` — both models, one file: they change together and neither is large |
| `src/backend/accounts/scoping.py` | `HouseholdScopedQuerySet`, `HouseholdScopedManager` — the single auditable scoping path |
| `src/backend/accounts/middleware.py` | `active_household_middleware`, `resolve_active_household` — sets `request.household` |
| `src/backend/accounts/mixins.py` | `HouseholdScopedMixin` for Django CBVs and DRF generics |
| `src/backend/accounts/migrations/0001_initial.py` | schema |
| `src/backend/accounts/migrations/0002_household_per_existing_user.py` | data migration, reversible |
| `src/backend/accounts/tests/test_models.py` | `Household`/`Membership` behaviour and constraints |
| `src/backend/accounts/tests/test_scoping.py` | the manager, exercised against `Membership` itself |
| `src/backend/accounts/tests/test_middleware.py` | active-household resolution |
| `src/backend/accounts/tests/test_mixins.py` | the CBV mixin |
| `src/backend/accounts/tests/test_migration_seed.py` | the data migration's effect |
| `src/backend/accounts/tests/test_scoping_ratchet.py` | the ratchet: no *new* bare `user=` scoping may appear |
| `src/backend/config/settings.py` | register app + middleware |

Domain models under `finances/` and `assistant/` are **not modified in this phase.**

---

### Task 1: The `accounts` app and the `Household` model

**Files:**
- Create: `src/backend/accounts/__init__.py`, `src/backend/accounts/apps.py`, `src/backend/accounts/models.py`, `src/backend/accounts/tests/__init__.py`
- Create: `src/backend/accounts/tests/test_models.py`
- Modify: `src/backend/config/settings.py` — `INSTALLED_APPS`

**Interfaces:**
- Consumes: nothing.
- Produces: `accounts.models.Household` with fields `id: UUID (pk)`, `name: str`, `created_at: datetime`, `updated_at: datetime`.

- [ ] **Step 1: Create the app package and register it**

```bash
mkdir -p src/backend/accounts/migrations src/backend/accounts/tests
touch src/backend/accounts/__init__.py src/backend/accounts/migrations/__init__.py src/backend/accounts/tests/__init__.py
```

`src/backend/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
```

In `src/backend/config/settings.py`, add `"accounts",` to `INSTALLED_APPS` immediately after `"core",`:

```python
    # Local apps
    "core",
    "accounts",
    "finances",
    "assistant",
```

- [ ] **Step 2: Write the failing test**

`src/backend/accounts/tests/test_models.py`:

```python
import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


def test_household_has_uuid_pk_and_str():
    household = baker.make(Household, name="Casa Bessa")
    assert str(household) == "Casa Bessa"
    # UUID pk, matching the convention in finances/models/category.py
    assert len(str(household.id)) == 36
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.models'`

- [ ] **Step 4: Write the model**

`src/backend/accounts/models.py`:

```python
import uuid

from django.db import models


class Household(models.Model):
    """The tenant. A ledger belongs to a household, not to a person."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "casa"
        verbose_name_plural = "casas"
        ordering = ["name"]

    def __str__(self):
        return self.name
```

- [ ] **Step 5: Generate the migration and run the test**

```bash
uv run python src/backend/manage.py makemigrations accounts
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_models.py -q
```

Expected: migration `0001_initial.py` created; test PASSES.

- [ ] **Step 6: Commit**

```bash
git add src/backend/accounts src/backend/config/settings.py
git commit -m "feat(accounts): Household model — the tenant a ledger belongs to"
```

---

### Task 2: `Membership` — who belongs to which household, in what role

**Files:**
- Modify: `src/backend/accounts/models.py`
- Modify: `src/backend/accounts/tests/test_models.py`

**Interfaces:**
- Consumes: `accounts.models.Household` (Task 1).
- Produces:
  - `accounts.models.Role` — `TextChoices` with `OWNER = "owner"` and `MEMBER = "member"`.
  - `accounts.models.Membership` with fields `id: UUID (pk)`, `user: FK(AUTH_USER_MODEL, related_name="memberships")`, `household: FK(Household, related_name="memberships")`, `role: str`, `created_at: datetime`.
  - `Membership.objects` is a plain manager in this task; Task 4 replaces it with the scoped one.

- [ ] **Step 1: Write the failing tests**

Append to `src/backend/accounts/tests/test_models.py`:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from accounts.models import Membership, Role


def test_user_can_belong_to_two_households():
    """Decision 1: multi-household in the schema, one active in the UI."""
    user = baker.make(get_user_model())
    first = baker.make(Household, name="Casa A")
    second = baker.make(Household, name="Casa B")

    baker.make(Membership, user=user, household=first, role=Role.OWNER)
    baker.make(Membership, user=user, household=second, role=Role.MEMBER)

    assert user.memberships.count() == 2


def test_same_user_cannot_join_one_household_twice():
    user = baker.make(get_user_model())
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, household=household, role=Role.MEMBER)


def test_roles_are_exactly_owner_and_member():
    """Decision 2: resist any third role. A viewer role is a new epic."""
    assert [choice[0] for choice in Role.choices] == ["owner", "member"]


def test_memberships_order_oldest_first_for_owner_promotion():
    """Decision 3: the last owner's departure promotes the longest-standing
    member, so creation order must be both recorded and the default ordering."""
    household = baker.make(Household)
    older = baker.make(Membership, household=household, role=Role.MEMBER)
    newer = baker.make(Membership, household=household, role=Role.MEMBER)

    assert list(household.memberships.all()) == [older, newer]
    assert older.created_at <= newer.created_at
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'Membership' from 'accounts.models'`

- [ ] **Step 3: Write the model**

Append to `src/backend/accounts/models.py`:

```python
from django.conf import settings


class Role(models.TextChoices):
    OWNER = "owner", "Dono"
    MEMBER = "member", "Membro"


class Membership(models.Model):
    """Links a user to a household. Two roles, deliberately — an owner may
    invite and remove people, a member may only edit the ledger. Anything
    finer-grained is a separate epic (see the epic's decision 2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    # Indexed and ordered on: E13 promotes the longest-standing member when the
    # last owner deletes their account, and the active-household fallback picks
    # the oldest membership so it is deterministic across requests.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vínculo"
        verbose_name_plural = "vínculos"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "household"], name="unique_membership_per_household"
            )
        ]
        indexes = [
            models.Index(fields=["household", "created_at"], name="membership_household_age_idx"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"
```

Move the `from django.conf import settings` import to the top of the file with the other imports; ruff will flag it otherwise.

- [ ] **Step 4: Generate the migration and run the tests**

```bash
uv run python src/backend/manage.py makemigrations accounts
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_models.py -q
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/accounts
git commit -m "feat(accounts): Membership with owner/member roles and age ordering"
```

---

### Task 3: Data migration — one household per existing user

**Files:**
- Create: `src/backend/accounts/migrations/0002_household_per_existing_user.py`
- Create: `src/backend/accounts/tests/test_migration_seed.py`

**Interfaces:**
- Consumes: `Household`, `Membership`, `Role` (Tasks 1–2).
- Produces: the invariant every later phase depends on — **every `CustomUser` has at least one `Membership`, and exactly one where `role="owner"`.**

- [ ] **Step 1: Write the failing test**

`src/backend/accounts/tests/test_migration_seed.py`:

```python
"""The seed migration's *rule*, tested against the live models.

Testing a historical migration by replaying it (django-test-migrations) is
heavier than this project needs. What matters is the invariant the rest of
E04 leans on, so assert the invariant and keep the helper the migration
calls in one place.
"""

import pytest
from django.contrib.auth import get_user_model
from model_bakery import baker

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


def test_seed_creates_one_household_and_an_owner_membership():
    user = baker.make(get_user_model(), username="bessavagner")

    seed_household_for_user(Household, Membership, user)

    membership = Membership.objects.get(user=user)
    assert membership.role == Role.OWNER
    assert membership.household.name == "Casa de bessavagner"


def test_seed_is_idempotent():
    """Re-running must not create a second household — migrations get replayed
    on a rebuilt database more often than anyone expects."""
    user = baker.make(get_user_model(), username="bessavagner")

    seed_household_for_user(Household, Membership, user)
    seed_household_for_user(Household, Membership, user)

    assert Membership.objects.filter(user=user).count() == 1
    assert Household.objects.count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_migration_seed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.migrations_helpers'`

- [ ] **Step 3: Write the helper**

`src/backend/accounts/migrations_helpers.py`:

```python
"""Helpers shared by data migrations and their tests.

Migrations receive *historical* model classes from ``apps.get_model``, so
these take the model classes as arguments rather than importing them.
"""


def seed_household_for_user(Household, Membership, user):
    """Give ``user`` their own household, as its owner. Idempotent."""
    if Membership.objects.filter(user=user).exists():
        return Membership.objects.filter(user=user).first().household

    household = Household.objects.create(name=f"Casa de {user.get_username()}")
    Membership.objects.create(user=user, household=household, role="owner")
    return household
```

`user.get_username()` is unavailable on historical model instances in some Django versions; if the migration errors, use `user.username` there and keep `get_username()` in the test. Verify at Step 5.

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_migration_seed.py -q`
Expected: both tests PASS.

- [ ] **Step 5: Write the migration**

`src/backend/accounts/migrations/0002_household_per_existing_user.py`:

```python
"""Give every existing user their own household, as its owner.

Forward: one Household + one owner Membership per user that has none.
Reverse: delete every Membership and Household. That is safe *only* while no
domain model points at a household — which is true in this migration's phase
and stops being true in E04 phase 2. Phase 2's migration must therefore not
be reversed past this one without restoring from a dump.
"""

from django.db import migrations

from accounts.migrations_helpers import seed_household_for_user


def create_households(apps, schema_editor):
    User = apps.get_model("core", "CustomUser")
    Household = apps.get_model("accounts", "Household")
    Membership = apps.get_model("accounts", "Membership")

    for user in User.objects.all().iterator():
        seed_household_for_user(Household, Membership, user)


def delete_households(apps, schema_editor):
    Household = apps.get_model("accounts", "Household")
    Membership = apps.get_model("accounts", "Membership")
    Membership.objects.all().delete()
    Household.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("core", "0002_login_attempt"),
    ]

    operations = [
        migrations.RunPython(create_households, delete_households),
    ]
```

If `user.get_username()` raises on the historical model, change the helper to `getattr(user, "get_username", lambda: user.username)()`.

- [ ] **Step 6: Verify the migration runs forwards and backwards**

```bash
uv run python src/backend/manage.py migrate accounts
uv run python src/backend/manage.py migrate accounts 0001
uv run python src/backend/manage.py migrate accounts
uv run python src/backend/manage.py shell -c "
from accounts.models import Household, Membership
from django.contrib.auth import get_user_model
print('users', get_user_model().objects.count(), 'households', Household.objects.count(), 'memberships', Membership.objects.count())
"
```

Expected: the three counts are equal, and the down-migration leaves 0 households.

- [ ] **Step 7: Commit**

```bash
git add src/backend/accounts
git commit -m "feat(accounts): seed one household per existing user, reversibly"
```

---

### Task 4: `HouseholdScopedQuerySet` — the single auditable scoping path

**Files:**
- Create: `src/backend/accounts/scoping.py`
- Create: `src/backend/accounts/tests/test_scoping.py`
- Modify: `src/backend/accounts/models.py` — attach the manager to `Membership`

**Interfaces:**
- Consumes: `Household`, `Membership`.
- Produces:
  - `accounts.scoping.HouseholdScopedQuerySet` with `.for_household(household)` and `.for_request(request)`.
  - `accounts.scoping.HouseholdScopedManager` = `models.Manager.from_queryset(HouseholdScopedQuerySet)`.
  - Both are what every phase-3 call site will use. `.for_household(None)` returns **none()**, never everything.

> This is the heart of the epic. Scoping repeated at ~200 call sites is 200 chances to leak; scoping in one class is one thing to review. `Membership` itself carries a `household` FK, so the manager can be tested against a real model in this phase — before any domain model has been re-tenanted.

- [ ] **Step 1: Write the failing tests**

`src/backend/accounts/tests/test_scoping.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from model_bakery import baker

from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_households():
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make(Membership, household=ours, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)
    return ours, theirs


def test_for_household_returns_only_that_households_rows(two_households):
    ours, _theirs = two_households
    assert list(Membership.objects.for_household(ours)) == list(ours.memberships.all())


def test_for_household_of_none_returns_nothing_not_everything(two_households):
    """The failure mode that matters: an unresolved household must never
    degrade into an unscoped queryset."""
    assert Membership.objects.for_household(None).count() == 0


def test_for_request_uses_the_requests_household(rf, two_households):
    ours, theirs = two_households
    request = rf.get("/")
    request.household = ours

    scoped = Membership.objects.for_request(request)

    assert scoped.count() == 1
    assert scoped.first().household == ours


def test_for_request_without_a_household_attribute_returns_nothing(rf, two_households):
    request = rf.get("/")  # no .household — e.g. middleware not installed

    assert Membership.objects.for_request(request).count() == 0


def test_scoping_survives_further_filtering(two_households):
    ours, _theirs = two_households
    user = baker.make(get_user_model())
    baker.make(Membership, household=ours, user=user, role=Role.MEMBER)

    scoped = Membership.objects.for_household(ours).filter(role=Role.MEMBER)

    assert scoped.count() == 1
    assert scoped.first().user == user
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping.py -q`
Expected: FAIL — `AttributeError: 'Manager' object has no attribute 'for_household'`

- [ ] **Step 3: Write the scoping module**

`src/backend/accounts/scoping.py`:

```python
"""The one supported way to scope a query to a household.

Global constraint 4 of the backlog: after E04, no epic may write
``filter(user=...)`` on a domain model. Everything goes through here, so
there is one class to review and one class to test exhaustively.
"""

from django.db import models


class HouseholdScopedQuerySet(models.QuerySet):
    """A queryset over a model carrying ``household``."""

    def for_household(self, household):
        """Rows belonging to ``household``.

        A falsy household yields ``none()`` — never the full table. An
        unresolved tenant must fail closed: the alternative is that one
        missing middleware turns every list view into a data leak.
        """
        if household is None:
            return self.none()
        return self.filter(household=household)

    def for_request(self, request):
        """Rows belonging to the request's active household.

        Uses ``getattr`` rather than ``request.household`` so that a request
        built without the middleware (a bare ``RequestFactory``, a management
        command) fails closed instead of raising.
        """
        return self.for_household(getattr(request, "household", None))


HouseholdScopedManager = models.Manager.from_queryset(HouseholdScopedQuerySet)
```

- [ ] **Step 4: Attach the manager to `Membership`**

In `src/backend/accounts/models.py`, import the manager and add it to `Membership`, directly above `class Meta`:

```python
from accounts.scoping import HouseholdScopedManager


class Membership(models.Model):
    ...
    created_at = models.DateTimeField(auto_now_add=True)

    objects = HouseholdScopedManager()

    class Meta:
        ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q`
Expected: all PASS. No new migration is generated — managers are not schema. Confirm with:

```bash
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: `No changes detected`.

- [ ] **Step 6: Commit**

```bash
git add src/backend/accounts
git commit -m "feat(accounts): HouseholdScopedQuerySet — fail-closed tenant scoping"
```

---

### Task 5: Middleware — resolve the active household onto `request.household`

**Files:**
- Create: `src/backend/accounts/middleware.py`
- Create: `src/backend/accounts/tests/test_middleware.py`
- Modify: `src/backend/config/settings.py` — `MIDDLEWARE`

**Interfaces:**
- Consumes: `Membership`, `Household`.
- Produces:
  - `accounts.middleware.resolve_active_household(request) -> Household | None`
  - `accounts.middleware.active_household_middleware(get_response)` — sets `request.household`
  - `accounts.middleware.ACTIVE_HOUSEHOLD_SESSION_KEY = "active_household_id"`

- [ ] **Step 1: Write the failing tests**

`src/backend/accounts/tests/test_middleware.py`:

```python
import pytest
from django.contrib.auth.models import AnonymousUser
from model_bakery import baker

from accounts.middleware import ACTIVE_HOUSEHOLD_SESSION_KEY, active_household_middleware
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


def _run_middleware(request):
    """Run the middleware over a request and hand back what it set."""
    active_household_middleware(lambda req: None)(request)
    return request.household


def test_anonymous_request_gets_no_household(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    request.session = {}

    assert _run_middleware(request) is None


def test_member_gets_their_only_household(rf, django_user_model):
    user = baker.make(django_user_model)
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {}

    assert _run_middleware(request) == household


def test_session_choice_wins_when_the_user_is_a_member(rf, django_user_model):
    user = baker.make(django_user_model)
    first = baker.make(Household, name="Primeira")
    second = baker.make(Household, name="Segunda")
    baker.make(Membership, user=user, household=first, role=Role.OWNER)
    baker.make(Membership, user=user, household=second, role=Role.MEMBER)

    request = rf.get("/")
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: str(second.id)}

    assert _run_middleware(request) == second


def test_session_pointing_at_a_foreign_household_is_ignored(rf, django_user_model):
    """The attack: paste someone else's household id into your session."""
    user = baker.make(django_user_model)
    mine = baker.make(Household, name="Minha")
    theirs = baker.make(Household, name="Alheia")
    baker.make(Membership, user=user, household=mine, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: str(theirs.id)}

    assert _run_middleware(request) == mine


def test_resolution_is_written_back_to_the_session(rf, django_user_model):
    user = baker.make(django_user_model)
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {}

    _run_middleware(request)

    assert request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == str(household.id)


def test_user_with_no_membership_gets_none(rf, django_user_model):
    """A user created before the seed migration, or by createsuperuser after
    it. Fails closed rather than borrowing somebody's ledger."""
    request = rf.get("/")
    request.user = baker.make(django_user_model)
    request.session = {}

    assert _run_middleware(request) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_middleware.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.middleware'`

- [ ] **Step 3: Write the middleware**

`src/backend/accounts/middleware.py`:

```python
"""Resolve the request's active household exactly once, before any view runs.

Decision 1 of the epic: a user may belong to several households, but works in
one at a time. The choice lives in the session; the *validation* of that
choice lives here, because a session value is user-controlled input.
"""

from accounts.models import Membership

ACTIVE_HOUSEHOLD_SESSION_KEY = "active_household_id"


def resolve_active_household(request):
    """The household this request operates in, or ``None``.

    Never trusts the session id on its own: it is only honoured when the
    user actually holds a membership in that household. Otherwise falls back
    to the oldest membership, which is deterministic because ``Membership``
    orders by ``created_at``.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    memberships = Membership.objects.filter(user=user).select_related("household")

    chosen_id = request.session.get(ACTIVE_HOUSEHOLD_SESSION_KEY)
    if chosen_id:
        chosen = memberships.filter(household_id=chosen_id).first()
        if chosen is not None:
            return chosen.household

    fallback = memberships.first()
    return fallback.household if fallback is not None else None


def active_household_middleware(get_response):
    def middleware(request):
        household = resolve_active_household(request)
        request.household = household
        if household is not None:
            request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] = str(household.id)
        return get_response(request)

    return middleware
```

> `Membership.objects.filter(user=user)` here is **correct and deliberate** — resolving *which* household a user belongs to is the one query that cannot itself be household-scoped. It lives in the `accounts` app, which is exactly why the ratchet in Task 7 excludes that app.

- [ ] **Step 4: Register the middleware**

In `src/backend/config/settings.py`, add it directly after `AuthenticationMiddleware` — it needs `request.user`, and every downstream view needs `request.household`:

```python
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.active_household_middleware",
    "django.contrib.messages.middleware.MessageMiddleware",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_middleware.py -q`
Expected: all 6 PASS.

- [ ] **Step 6: Run the whole suite — the middleware is now in every request's path**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: 967 passed, 2 skipped, plus the new accounts tests. If anything fails here, the middleware is raising on a request shape it did not anticipate — fix the middleware, not the failing test.

- [ ] **Step 7: Commit**

```bash
git add src/backend/accounts src/backend/config/settings.py
git commit -m "feat(accounts): resolve the active household onto request.household"
```

---

### Task 6: `HouseholdScopedMixin` for views

**Files:**
- Create: `src/backend/accounts/mixins.py`
- Create: `src/backend/accounts/tests/test_mixins.py`

**Interfaces:**
- Consumes: `HouseholdScopedQuerySet.for_request`.
- Produces: `accounts.mixins.HouseholdScopedMixin` — overrides `get_queryset()` to scope by `self.request.household`. Works for Django CBVs and DRF generics alike, since both call `get_queryset()`.

- [ ] **Step 1: Write the failing tests**

`src/backend/accounts/tests/test_mixins.py`:

```python
import pytest
from model_bakery import baker

from accounts.mixins import HouseholdScopedMixin
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


class _MembershipListView(HouseholdScopedMixin):
    """Minimal stand-in for a CBV: the mixin only needs get_queryset()."""

    model = Membership

    def __init__(self, request):
        self.request = request

    def get_queryset(self):
        return super().get_queryset()


def test_mixin_scopes_to_the_requests_household(rf):
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make(Membership, household=ours, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)

    request = rf.get("/")
    request.household = ours

    assert _MembershipListView(request).get_queryset().count() == 1


def test_mixin_without_a_household_yields_nothing(rf):
    baker.make(Membership, role=Role.OWNER)
    request = rf.get("/")
    request.household = None

    assert _MembershipListView(request).get_queryset().count() == 0


def test_mixin_raises_when_the_model_is_not_household_scoped(rf):
    """A model whose manager lacks for_request must fail loudly at the seam,
    not silently return an unscoped queryset."""
    from django.contrib.auth import get_user_model

    class _UserView(HouseholdScopedMixin):
        model = get_user_model()

        def __init__(self, request):
            self.request = request

    request = rf.get("/")
    request.household = baker.make(Household)

    with pytest.raises(TypeError, match="not household-scoped"):
        _UserView(request).get_queryset()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_mixins.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.mixins'`

- [ ] **Step 3: Write the mixin**

`src/backend/accounts/mixins.py`:

```python
"""View-layer entry point to household scoping.

Both Django's generic CBVs and DRF's generics funnel through
``get_queryset()``, so one mixin covers the HTMX views and the dashboard API.
"""

from accounts.scoping import HouseholdScopedQuerySet


class HouseholdScopedMixin:
    """Scope a view's queryset to ``request.household``.

    Raises rather than degrading: a view that mixes this in but points at a
    model without the scoped manager is a bug, and a silently unscoped
    queryset is the exact failure this epic exists to prevent.
    """

    def get_queryset(self):
        queryset = super().get_queryset() if hasattr(super(), "get_queryset") else self.model._default_manager.all()
        if not isinstance(queryset, HouseholdScopedQuerySet):
            raise TypeError(
                f"{queryset.model.__name__} is not household-scoped: give it "
                "HouseholdScopedManager before using HouseholdScopedMixin."
            )
        return queryset.for_request(self.request)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_mixins.py -q`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/accounts
git commit -m "feat(accounts): HouseholdScopedMixin that fails loudly, not open"
```

---

### Task 7: The scoping ratchet — no *new* bare `user=` scoping

**Files:**
- Create: `src/backend/accounts/tests/test_scoping_ratchet.py`

**Interfaces:**
- Consumes: nothing at runtime; it reads the source tree.
- Produces: the CI check story S04-2 asks for, in the only form that can exist today.

> S04-2 wants a check that "fails the build if a domain model is queried with a bare `filter(user=...)`". Twenty-two files do exactly that right now, so a plain check would fail on commit one. A **ratchet** works from day one: the current 22 files are recorded as a baseline, any *new* file joining them fails immediately, and a file that gets fixed must be struck from the baseline — so the list can only shrink. Phase 4 deletes the baseline entirely and the check becomes the absolute one.

- [ ] **Step 1: Write the test with the real baseline**

`src/backend/accounts/tests/test_scoping_ratchet.py`:

```python
"""Global constraint 4, enforced while E04 is still in flight.

After E04 lands, the baseline below is empty and this becomes a flat "no
domain query scopes by user" assertion. Until then it is a ratchet: the set
may shrink, never grow.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3].parent

# Every file that scoped by user at the start of E04 phase 1 (2026-08-11).
# Strike entries as phases 3 and 4 convert them. Never add one.
BASELINE = {
    "src/backend/assistant/agents/analytics.py",
    "src/backend/assistant/agents/memory.py",
    "src/backend/assistant/agents/tools.py",
    "src/backend/assistant/management/commands/seed_category_rules.py",
    "src/backend/assistant/views.py",
    "src/backend/finances/api/views.py",
    "src/backend/finances/forms.py",
    "src/backend/finances/management/commands/import_csv.py",
    "src/backend/finances/management/commands/seed_qa_data.py",
    "src/backend/finances/management/commands/transfer_entries.py",
    "src/backend/finances/services/budget_stats.py",
    "src/backend/finances/services/category_stats.py",
    "src/backend/finances/services/daily_trend.py",
    "src/backend/finances/services/income_recurrence.py",
    "src/backend/finances/services/projection.py",
    "src/backend/finances/services/systemic_month.py",
    "src/backend/finances/views/cockpit.py",
    "src/backend/finances/views/consolidated.py",
    "src/backend/finances/views/entries.py",
    "src/backend/finances/views/importer.py",
    "src/backend/finances/views/projection.py",
    "src/backend/finances/views/settings.py",
}

PATTERN = re.compile(r"\.(filter|get|exclude)\([^)]*user=")


def _files_scoping_by_user():
    found = set()
    for app in ("finances", "assistant"):
        for path in (REPO_ROOT / "src" / "backend" / app).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel or "/migrations/" in rel:
                continue
            if PATTERN.search(path.read_text(encoding="utf-8")):
                found.add(rel)
    return found


def test_no_new_file_scopes_a_domain_query_by_user():
    regressions = sorted(_files_scoping_by_user() - BASELINE)
    assert not regressions, (
        "These files scope a domain query by user=. Use the household-scoped "
        f"manager (accounts.scoping) instead: {regressions}"
    )


def test_baseline_has_no_stale_entries():
    """A file that has been converted must leave the baseline, or the ratchet
    stops ratcheting."""
    stale = sorted(BASELINE - _files_scoping_by_user())
    assert not stale, (
        f"These files no longer scope by user — remove them from BASELINE: {stale}"
    )
```

- [ ] **Step 2: Run the test — it must pass immediately**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q`
Expected: both PASS. This is the one task whose test is green on first run — it is a regression fence, not a feature.

If `test_baseline_has_no_stale_entries` fails, `REPO_ROOT` is resolving wrong. Verify with:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q -s --tb=long
```

- [ ] **Step 3: Prove the ratchet actually catches a regression**

Temporarily add a bare user-scoped query to a file outside the baseline and confirm the test fails:

```bash
printf '\n\ndef _leak(user):\n    from finances.models import Entry\n    return Entry.objects.filter(user=user)\n' >> src/backend/finances/services/billing.py
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
```

Expected: FAIL, naming `src/backend/finances/services/billing.py`. Then revert:

```bash
git checkout -- src/backend/finances/services/billing.py
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_scoping_ratchet.py -q
```

Expected: PASS. **A fence you never saw catch anything is not known to be a fence.**

- [ ] **Step 4: Commit**

```bash
git add src/backend/accounts/tests/test_scoping_ratchet.py
git commit -m "test(accounts): ratchet so user-scoped domain queries can only shrink"
```

---

### Task 8: Phase gate — full suite, gates, and the clock

**Files:** none created; this is the checkpoint before phase 2 touches a domain model.

- [ ] **Step 1: Full suite under the real clock**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: 967 pre-existing + the new accounts tests, 2 skipped, 0 failed.

- [ ] **Step 2: Full suite under a shifted clock**

Run: `POSTGRES_PORT=5433 TEST_CLOCK_SHIFT=+1y uv run pytest src/backend/ -q -m "not current_date"`
Expected: same counts. Run these two **serially** — concurrent runs collide on the test database.

- [ ] **Step 3: Gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: coverage ≥ 80 (it was 90 before this phase), lint clean, `No changes detected`.

- [ ] **Step 4: Confirm the invariant phase 2 depends on**

```bash
uv run python src/backend/manage.py shell -c "
from django.contrib.auth import get_user_model
from accounts.models import Membership
users = get_user_model().objects.count()
owned = Membership.objects.filter(role='owner').values('user').distinct().count()
print(f'users={users} users_with_an_owner_membership={owned}')
assert users == owned, 'phase 2 cannot back-fill household from user without this'
print('OK')
"
```

Expected: `users == users_with_an_owner_membership`, then `OK`.

- [ ] **Step 5: Commit and open for review**

```bash
git commit --allow-empty -m "chore(accounts): E04 phase 1 gate — suite, gates and tenancy invariant green"
```

Then request review per `superpowers:requesting-code-review`. **Do not start phase 2 in the same session** — phase 2 writes a data migration over real financial records, and it deserves a fresh reviewer on this foundation first.

---

## Follow-on plans — NOT part of this plan

These are **not tasks**; do not execute them from this document. Each gets its own plan file, written after the preceding phase has landed and been reviewed, because each one's task shape depends on the API the previous phase actually produced.

| Phase | Epic stories | Deliverable | Why it waits |
|---|---|---|---|
| **2 · Re-tenant the models** | S04-3 | `household` FK + `created_by` on all 10 domain models, back-fill migration from `user` via `Membership`, unique constraints re-scoped to household, E03's indexes re-created with `household` leading. `user` columns stay for now so the suite stays green. | Needs the seeded `Membership` rows from phase 1 to back-fill from. Must be rehearsed against a **copy of production Supabase data**, comparing balances and monthly acumulado — not row counts. This project has a documented history of balance reconciliation issues. |
| **3 · Re-scope reads and writes** | S04-4, S04-5 | DRF API, six HTMX view modules, `finances/services/`, then the agent (`deps_type` becomes a structure carrying household **and** acting user; ~45 tools in `assistant/agents/tools.py`). One surface per commit, baseline entries struck from the ratchet as each lands. | Cannot start until models carry `household`. The agent is deliberately last: its scope must come from `ctx.deps` and never from an LLM-supplied argument, so it wants the quietest possible diff. |
| **4 · Prove the boundary** | S04-6 | The 12 isolation test modules convert from cross-user to cross-household; a parameterized test asserts **every** domain model rejects cross-household access, so a model added later without scoping fails the suite; a test asserts two users in one household see identical data; `user` columns dropped; the ratchet's baseline emptied; `/security-review` run. | The epic's own risk note: "a missed call site is a cross-tenant data leak, not a bug". Write the parameterized test **early in phase 4**, not last. |

---

## Self-Review

**Spec coverage** — this plan covers E04 stories S04-1 (Tasks 1–3) and S04-2 (Tasks 4–7) completely. S04-3 through S04-6 are deliberately deferred to phases 2–4 above, per the epic's own instruction to split by surface. Within scope, every S04-1 clause is covered: `Household` (T1), `Membership(user, household, role)` (T2), multi-household with one active (T2 test + T5), minimal roles (T2), data migration with no orphans (T3), reversibility (T3 Step 6). Every S04-2 clause: the manager as the only supported path (T4), middleware onto `request.household` (T5), a view mixin for HTMX and DRF (T6), and a build-failing check for bare `filter(user=...)` (T7, as a ratchet — the only form that can exist while 22 files still violate it).

**Placeholder scan** — no TBDs. Every code step carries the actual code; the ratchet baseline is the real 22-file list measured at `cf0f462`, not a placeholder. Two conditional branches are called out explicitly with their fix rather than left vague: `get_username()` on historical models (T3 Step 3/5) and `REPO_ROOT` resolution (T7 Step 2).

**Type consistency** — `HouseholdScopedQuerySet.for_household(household)` and `.for_request(request)` are named identically in T4 (definition), T6 (mixin call site), and the phase-3 table. `HouseholdScopedManager` is the `from_queryset` product, attached in T4 Step 4 and required by T6's `isinstance` check. `Role.OWNER`/`Role.MEMBER` values `"owner"`/`"member"` are consistent between T2, T3's migration (which writes the literal `"owner"`, since historical models have no access to the `Role` class), and T8's verification query. `ACTIVE_HOUSEHOLD_SESSION_KEY` is defined in T5 and imported by its own tests only.

**One known seam, stated rather than hidden:** `Membership.objects.filter(user=user)` inside `resolve_active_household` is a bare user-scoped query by necessity — it is the query that *establishes* scope. It lives in `accounts`, which the ratchet excludes by construction (it only walks `finances` and `assistant`).
