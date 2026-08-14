# E05 · Identity, invitations & admin isolation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger can sign up with an email, verify it, log in, reset a forgotten password, and invite a partner into their household — while `/admin/` stops being reachable by anyone who is not staff with a second factor.

**Architecture:** `django-allauth` owns every credential flow (signup, verification, password reset, TOTP). The existing E01 lockout stays where it is — in an authentication backend — but is rebased onto allauth's backend so it keeps covering both doors. Invitations are a household-scoped model in the `accounts` app carrying a hashed, single-use, expiring token; redemption creates a `Membership`, which is all E04 needs for the invitee to see the ledger. Django admin moves to a secret path behind a staff-only middleware that 404s everyone else and logs every staff request.

**Tech Stack:** Django 6.0, django-allauth (with `[mfa]` extra), PostgreSQL, pytest + pytest-django + model-bakery, HTMX, Tailwind v4 + daisyUI, Resend SMTP, Cloud Run.

**Spec:** `docs/backlog/E05-identity-invitations-admin-isolation.md`

---

## Decisions taken before this plan (they close the spec's Open Questions)

| Spec question | Decision |
|---|---|
| OQ1 · Email provider | **Resend** over SMTP. No SDK dependency — `EMAIL_HOST=smtp.resend.com`, API key in Secret Manager. |
| OQ2 · How `/admin/` is restricted | **Middleware staff-gate + secret URL path + TOTP.** Cloud Run stays `--allow-unauthenticated` because the product needs it. Rejected: IP allowlist (dynamic home IP), second IAM-gated service (doubles deploy surface). |
| OQ3 · Verification mandatory? | **Mandatory.** `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`. One code path, no half-trusted user state for E11 to reason about. |
| OQ4 · Last owner leaves | **Out of scope here.** Task 12 refuses to remove the last owner; the full semantics stay with E13. |
| *Not in the spec, forced by the code* | **Login identifier becomes email.** `CustomUser.email` gains `unique=True`; `username` stays on the model, is auto-derived by allauth, and is never shown. |

## The spec's evidence table is stale — read this instead

E01 already did part of S05-4. On `origin/main` today:

- `LOGIN_URL` is `/login/`, **not** `/admin/login/` (`config/settings.py`).
- `core.views.AppLoginView` exists and renders `templates/registration/login.html` — a styled pt-BR daisyUI page.
- `core.auth_backends.LockoutModelBackend` exists and was written *in anticipation of this epic*; its docstring says so.
- `logout` already returns to `/login/`, not to admin.

So S05-4 reduces to: point the door at allauth, keep `/login/` working for the TWA, and **prove the lockout survives the move**. It does not survive for free — allauth's own `login_failed` rate limit explicitly does not cover Django admin, and allauth authenticates through its own backend, which `LockoutModelBackend` does not subclass. Task 4 is the whole point.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python ≥ 3.12, Django ≥ 6.0.** `requires-python = ">=3.12"`, `django>=6.0`.
- **Ruff, line-length 100.** `uv run ruff check src/backend/ && uv run ruff format --check src/backend/` must pass before every commit.
- **Copy is pt-BR.** Every user-facing string — templates, form labels, error messages, email subjects and bodies, `verbose_name`. Test code and test names are English; only assertions *about* user-facing copy contain pt-BR. (`docs/testing-conventions.md`.)
- **Tests run against the pgvector container on port 5433**, never system Postgres: `POSTGRES_PORT=5433 uv run pytest src/backend/`.
- **No test may read the wall clock by accident.** Inject `now=`/`today=` where the code takes it; otherwise freeze with the `time_machine` fixture at **midday UTC** and say in the docstring *which requirement* the frozen date makes true. See `docs/testing-conventions.md`.
- **E04 global constraint 4 stands: no `filter(user=...)` on a domain model.** Scope through `HouseholdScopedManager` / `HouseholdScopedMixin`. `accounts/tests/test_scoping_ratchet.py` enforces this and will see the new `Invitation` model automatically.
- **`household` is NOT NULL on domain models.** Any new household-owned model names its household explicitly at every write site.
- **Never commit secrets.** The Resend API key lives in Secret Manager and in the local `.env` only. `ADMIN_URL_PATH` is likewise an env var, never a literal in a committed file outside its dev default.
- **daisyUI work goes through the Blueprint MCP chain** (Setup Expert → Rules Enforcer → Component Syntax Expert → code → Quality Inspector), one `workflowId` per cohesive design. **Do not call `daisyui_creative_director` or `daisyui_page_architect`** — this repo has a settled design direction (`docs/superpowers/specs/*-design.md`, `base_public.html`, the `ledger`/`ledger-dark` themes); Blueprint is authoritative on daisyUI *syntax* only.
- **No AI attribution in commit messages.** No `Co-Authored-By`, no "Generated with".
- **Coverage floor is 80%**, asserted at the end by the Definition of Done command.

## Definition of Done (from the spec — run at Task 16)

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com ADMIN_URL_PATH=gestao-test/ uv run python src/backend/manage.py check --deploy
```

---

## File Structure

**New files**

| Path | Responsibility |
|---|---|
| `src/backend/accounts/invitations.py` | Invitation lifecycle as pure functions: mint, look up by raw token, redeem, revoke. No HTTP. Clock injected. |
| `src/backend/accounts/permissions.py` | `is_owner(user, household)` and `OwnerRequiredMixin`. One definition of "may invite / may remove". |
| `src/backend/accounts/signals.py` | `user_signed_up` receiver: new account gets a `Household` + owner `Membership`. |
| `src/backend/accounts/views.py` | Invitation accept page, members page, invite/revoke/remove HTMX endpoints. |
| `src/backend/accounts/urls.py` | `/casa/` URL namespace for the above. |
| `src/backend/accounts/adapters.py` | `AppAccountAdapter` — auto-verifies an email address proven by an invitation token. |
| `src/backend/core/admin_gate.py` | `admin_staff_only_middleware` + the `AdminAccessLog` write. |
| `src/backend/templates/account/*.html` | Overridden allauth pages, pt-BR + daisyUI. |
| `src/backend/templates/account/email/*.txt` | Overridden allauth email bodies and subjects, pt-BR. |
| `src/backend/templates/accounts/*.html` | Invitation and members pages. |

**Modified files**

| Path | Change |
|---|---|
| `pyproject.toml` | `django-allauth[mfa]` dependency. |
| `src/backend/config/settings.py` | allauth apps/middleware/backend/settings, email settings, `ADMIN_URL_PATH`. |
| `src/backend/config/urls.py` | allauth mount, `/login/` redirect, `/casa/` include, admin moves to the secret path. |
| `src/backend/core/models.py` | `CustomUser.email` unique; new `AdminAccessLog`. |
| `src/backend/core/auth_backends.py` | `LockoutModelBackend` rebased onto allauth's backend. |
| `src/backend/core/views.py` | `AppLoginView` rebased onto allauth's `LoginView`. |
| `src/backend/core/admin.py` | `AdminAccessLog` registered read-only. |
| `src/backend/assistant/admin.py` | `ChatMessage` unregistered. |
| `src/backend/accounts/models.py` | `Invitation` model. |
| `src/backend/accounts/apps.py` | `ready()` wires the signal. |
| `src/backend/conftest.py` | Fixtures set explicit unique emails. |
| `src/backend/templates/sw.js` | The service-worker admin bypass follows the secret path. |
| `docs/runbook.md` | Resend/SPF/DKIM, the admin path, TOTP enrolment, invitation troubleshooting. |

---

## Phasing

The tasks are ordered by dependency, not by convenience. Two natural checkpoints:

- **Tasks 1–8** — identity. Ends with signup → verify → login → reset working end to end against a console email backend.
- **Tasks 9–13** — invitations. Ends with owner invites → invitee joins → both see one ledger.
- **Tasks 14–16** — admin isolation + ship. Independent of the invitation work; could land first if you needed it to.

---

## Task 0: Sync, worktree, and a green baseline

Local `main` is 21 commits behind `origin/main` (E04 landed remotely and is deployed). Every file reference in this plan is to `origin/main`. Starting work on the stale tree will produce conflicts and a plan that does not match the code.

**Files:**
- No source changes. This task produces a workspace, not a diff.

**Interfaces:**
- Consumes: nothing.
- Produces: an isolated worktree on branch `e05-identity` whose `HEAD` is `origin/main`, with a green test suite.

- [ ] **Step 1: Confirm the sync is a fast-forward, then take it**

```bash
git fetch origin
git merge-base --is-ancestor HEAD origin/main && echo "FAST-FORWARD OK"
git pull --ff-only origin main
```

Expected: `FAST-FORWARD OK`, then the pull reports `Fast-forward`. If it does not, stop and ask — do not merge or rebase your way out of it.

- [ ] **Step 2: Create the worktree**

Use the `superpowers:using-git-worktrees` skill. The repo convention is `.claude/worktrees/<branch>`:

```bash
git worktree add .claude/worktrees/e05-identity -b e05-identity origin/main
cd .claude/worktrees/e05-identity
```

- [ ] **Step 3: Install dependencies and confirm the DB container is up**

```bash
uv sync
docker ps --filter "publish=5433" --format "{{.Names}}\t{{.Status}}"
```

Expected: a running container publishing 5433. If nothing is listed, start the pgvector container — tests and dev need it, **not** system Postgres.

- [ ] **Step 4: Record the baseline**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
```

Expected: all pass. Write the exact pass count into the commit message below — every later task compares against it, and "the suite was already red" must not be discoverable only at the end.

- [ ] **Step 5: Commit the gate**

```bash
git commit --allow-empty -m "chore(accounts): E05 gate — baseline is <N> passed on origin/main"
```

---

## Task 1: Land allauth without changing a single existing behaviour

allauth arrives inert: installed, mounted, configured, but the product still logs in exactly as it did. Separating "allauth is present" from "allauth is the door" means that when something breaks in Task 6, you know which of the two caused it.

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/backend/config/settings.py`
- Modify: `src/backend/config/urls.py`
- Test: `src/backend/core/tests/test_allauth_wiring.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `allauth`, `allauth.account`, `allauth.mfa` in `INSTALLED_APPS`; `allauth.account.middleware.AccountMiddleware` in `MIDDLEWARE`; allauth's URLs mounted under `/accounts/`; settings constants `ACCOUNT_LOGIN_METHODS`, `ACCOUNT_SIGNUP_FIELDS`, `ACCOUNT_EMAIL_VERIFICATION`, `ACCOUNT_ADAPTER` (pointing at the default for now — Task 11 replaces it).

- [ ] **Step 1: Add the dependency**

```bash
uv add "django-allauth[mfa]"
```

- [ ] **Step 2: Confirm the backend's import path for the installed version**

The rest of this plan hardcodes `allauth.account.auth_backends.AuthenticationBackend`. Verify it rather than trusting the plan:

```bash
uv run python -c "from allauth.account.auth_backends import AuthenticationBackend; print(AuthenticationBackend)"
uv run python -c "import allauth; print(allauth.VERSION)"
```

Expected: the class prints, and the version is 65.4 or newer (the release that introduced `ACCOUNT_LOGIN_METHODS`). If the import fails, find the real path with `uv run python -c "import allauth.account.auth_backends as m; print(dir(m))"` and use that everywhere this plan says `AuthenticationBackend`.

- [ ] **Step 3: Write the failing wiring test**

Create `src/backend/core/tests/test_allauth_wiring.py`:

```python
"""allauth is installed and mounted, and it is configured for email-only login.

Deliberately asserts settings rather than behaviour: this task installs the
library without handing it the door, so there is no behaviour to assert yet.
The behavioural tests arrive with Task 6.
"""

from django.conf import settings
from django.test import Client
from django.urls import reverse


class TestAllauthIsInstalled:
    def test_apps_are_installed(self):
        for app in ("allauth", "allauth.account", "allauth.mfa"):
            assert app in settings.INSTALLED_APPS

    def test_account_middleware_is_installed(self):
        assert "allauth.account.middleware.AccountMiddleware" in settings.MIDDLEWARE

    def test_login_is_by_email_only(self):
        assert settings.ACCOUNT_LOGIN_METHODS == {"email"}

    def test_username_is_not_a_signup_field(self):
        """The user model keeps `username`, but nobody is ever asked for one."""
        assert "username" not in settings.ACCOUNT_SIGNUP_FIELDS
        assert "username*" not in settings.ACCOUNT_SIGNUP_FIELDS
        assert "email*" in settings.ACCOUNT_SIGNUP_FIELDS

    def test_verification_is_mandatory(self):
        assert settings.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


class TestAllauthIsMounted:
    def test_signup_page_is_reachable(self, db):
        response = Client().get(reverse("account_signup"))
        assert response.status_code == 200

    def test_password_reset_page_is_reachable(self, db):
        response = Client().get(reverse("account_reset_password"))
        assert response.status_code == 200
```

- [ ] **Step 4: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_allauth_wiring.py -v
```

Expected: FAIL — `AssertionError` on the app list, and `NoReverseMatch: 'account_signup' is not a valid view function or pattern name`.

- [ ] **Step 5: Add the apps and the middleware**

In `src/backend/config/settings.py`, in `INSTALLED_APPS`, after the existing `# Third-party` block entries:

```python
    "django_tailwind_cli",
    "django_htmx",
    "rest_framework",
    # Identity (E05, ADR-007). `allauth.mfa` is the second factor Task 15
    # requires of staff before admin will answer them.
    "allauth",
    "allauth.account",
    "allauth.mfa",
```

In `MIDDLEWARE`, immediately after `django.contrib.auth.middleware.AuthenticationMiddleware` and **before** `accounts.middleware.active_household_middleware`:

```python
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must sit after AuthenticationMiddleware: it reads request.user. Must sit
    # before the household resolver, because a request allauth rejects should
    # never have cost us a membership query.
    "allauth.account.middleware.AccountMiddleware",
    "accounts.middleware.active_household_middleware",
```

- [ ] **Step 6: Add the allauth settings block**

In `src/backend/config/settings.py`, immediately below the existing `AUTHENTICATION_BACKENDS` / `LOGIN_FAILURE_*` block:

```python
# --- Identity (E05 / ADR-007) -------------------------------------------
# Email is the login identifier. `username` stays on CustomUser because ten
# models and every historical migration reference it, but allauth derives it
# from the email at signup and no screen ever shows it.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "email2*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
# Mandatory rather than optional: a half-verified account is a state every
# downstream feature would have to reason about, and E11's activation funnel
# would inherit the ambiguity. Decided with E11, per the epic's question 3.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Do not confirm or deny that an address has an account — applies to signup
# and to password reset alike.
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_ADAPTER = "allauth.account.adapter.DefaultAccountAdapter"

# The second factor Task 15 demands of staff. Recovery codes are on by
# default and stay on: losing a phone must not lock the only operator out of
# their own admin.
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
```

- [ ] **Step 7: Mount the URLs**

In `src/backend/config/urls.py`, add the import and one entry. The old `/login/` is untouched by this task:

```python
from django.urls import include, path

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("manifest.webmanifest", ManifestView.as_view(), name="manifest"),
    path(".well-known/assetlinks.json", AssetLinksView.as_view(), name="assetlinks"),
    path("login/", AppLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(next_page="/login/"), name="logout"),
    # E05: allauth owns signup, verification, password reset and TOTP. Task 6
    # hands it the login page too; until then this coexists with /login/.
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
    ...
]
```

- [ ] **Step 8: Migrate and run the wiring test**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_allauth_wiring.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 9: Prove nothing else moved**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
```

Expected: the same pass count as the Task 0 baseline, plus 7. If anything regressed, it is almost certainly `AccountMiddleware` ordering — it must sit after `AuthenticationMiddleware`.

- [ ] **Step 10: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add pyproject.toml uv.lock src/backend/config/settings.py src/backend/config/urls.py \
        src/backend/core/tests/test_allauth_wiring.py
git commit -m "feat(auth): install django-allauth, mounted but not yet the front door"
```

---

## Task 2: Email becomes the unique, required identity on CustomUser

`AbstractUser.email` is `blank=True` and not unique. Email-only login is impossible until that changes, and the change has to survive a production table that already holds rows — including at least one account whose email may be blank.

**Files:**
- Modify: `src/backend/core/models.py`
- Create: `src/backend/core/migrations/0003_customuser_email_unique.py`
- Modify: `src/backend/conftest.py`
- Test: `src/backend/core/tests/test_email_identity.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `CustomUser.email` is `EmailField(unique=True, blank=False)`. The `user` and `other_user` conftest fixtures now carry explicit, distinct emails (`vagner@example.com`, `amanda@example.com`).

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_email_identity.py`:

```python
"""Email is the identity. Two accounts may not share one.

Email-only login is only coherent if the address resolves to exactly one
account — otherwise `authenticate()` has to pick, and picking is a
vulnerability, not a feature.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

User = get_user_model()


@pytest.mark.django_db
class TestEmailUniqueness:
    def test_two_accounts_cannot_share_an_email(self):
        User.objects.create_user(
            username="primeiro", email="casa@example.com", password="senha-longa-o-bastante"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="segundo", email="casa@example.com", password="senha-longa-o-bastante"
            )

    def test_email_is_required(self):
        field = User._meta.get_field("email")
        assert field.unique is True
        assert field.blank is False


@pytest.mark.django_db
class TestExistingAccountsSurviveTheMigration:
    def test_fixtures_have_distinct_emails(self, user, other_user):
        """The suite's two tenants must not collide under the new constraint."""
        assert user.email
        assert other_user.email
        assert user.email != other_user.email
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_email_identity.py -v
```

Expected: FAIL — `test_two_accounts_cannot_share_an_email` fails with `DID NOT RAISE IntegrityError`; `test_email_is_required` fails on `field.unique is True`.

- [ ] **Step 3: Change the field**

In `src/backend/core/models.py`, add the override to `CustomUser`:

```python
from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    # AbstractUser leaves this blank-able and non-unique. E05 makes the address
    # the login identifier, so it has to be exactly one account's. `username`
    # stays — ten models and every historical migration reference it — but
    # allauth derives it from the email and no screen shows it.
    email = models.EmailField("endereço de e-mail", unique=True)

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.username
```

- [ ] **Step 4: Generate the migration, then hand-write the backfill into it**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations core --name customuser_email_unique
```

Open the generated file and put a data migration **before** the `AlterField`. Without it, `ALTER TABLE ... ADD CONSTRAINT UNIQUE` dies on production the moment two rows share `''`:

```python
from django.db import migrations, models


def fill_blank_emails(apps, schema_editor):
    """Give every address-less account a reserved, non-deliverable placeholder.

    `.invalid` is reserved by RFC 2606 and can never resolve, so a placeholder
    can neither collide with a real address nor accidentally receive mail. The
    operator repairs these by hand — see docs/runbook.md — and until they do,
    the account simply cannot log in, which is the correct failure.
    """
    User = apps.get_model("core", "CustomUser")
    for user in User.objects.filter(models.Q(email="") | models.Q(email__isnull=True)):
        User.objects.filter(pk=user.pk).update(email=f"{user.username}@sem-email.invalid")


def unfill(apps, schema_editor):
    User = apps.get_model("core", "CustomUser")
    User.objects.filter(email__endswith="@sem-email.invalid").update(email="")


class Migration(migrations.Migration):
    dependencies = [("core", "0002_login_attempt")]

    operations = [
        migrations.RunPython(fill_blank_emails, unfill),
        migrations.AlterField(
            model_name="customuser",
            name="email",
            field=models.EmailField(max_length=254, unique=True, verbose_name="endereço de e-mail"),
        ),
    ]
```

- [ ] **Step 5: Give the fixtures explicit emails**

model-bakery fills a non-blank `EmailField` with a random address, which is *usually* unique — "usually" is how a suite becomes flaky. Pin the two tenants. In `src/backend/conftest.py`:

```python
@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner", email="vagner@example.com")


@pytest.fixture
def other_user(db):
    """A second tenant, for asserting that a query stays scoped to one owner."""
    return baker.make("core.CustomUser", username="amanda", email="amanda@example.com")
```

- [ ] **Step 6: Run the new test, then the whole suite**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_email_identity.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -20
```

Expected: the new file PASSES. The full suite may now fail in modules that build two users with `baker.make(CustomUser)` and no email — read each failure and give that test's users explicit distinct emails. Do not weaken the constraint to make a test pass.

- [ ] **Step 7: Rehearse the migration against a copy of production data**

This migration adds a UNIQUE constraint to a live table. `docs/runbook.md` has a rehearsal procedure from E04 (`### Rehearsing the E04 tenancy migration`) — follow the same shape:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core 0003 --plan
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core
```

Then confirm on the restored production copy that no two accounts share an address:

```sql
SELECT email, COUNT(*) FROM core_customuser GROUP BY email HAVING COUNT(*) > 1;
```

Expected: zero rows. If it returns anything, stop — the duplicates must be resolved by hand before this ships, and that is an operator decision, not a code one.

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/core/models.py src/backend/core/migrations/0003_customuser_email_unique.py \
        src/backend/conftest.py src/backend/core/tests/test_email_identity.py
git commit -m "feat(core): email is unique and required — the login identifier from here on"
```

---

## Task 3: Signup creates a household and makes the signer its owner

S05-1's last bullet. `accounts.middleware.resolve_active_household` already back-stops a membership-less user by minting them a household — but it names it `Casa de <username>`, and from Task 6 the username is an allauth-generated slug. A new account must get a household with a human name, at signup, deliberately.

**Files:**
- Create: `src/backend/accounts/signals.py`
- Modify: `src/backend/accounts/apps.py`
- Test: `src/backend/accounts/tests/test_signup_creates_household.py` (create)

**Interfaces:**
- Consumes: `accounts.models.Household`, `accounts.models.Membership`, `accounts.models.Role` (all exist).
- Produces: `accounts.signals.create_household_for_new_user(request, user, **kwargs)`, connected to `allauth.account.signals.user_signed_up`. Also `accounts.signals.household_name_for(user) -> str`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_signup_creates_household.py`:

```python
"""A brand-new account owns a household from its first request.

The middleware would eventually mint one anyway, but it names the household
after the username — and from E05 the username is a generated slug nobody
chose. Doing it at signup is what makes the name readable, and what makes the
role `owner` rather than incidental.
"""

import pytest
from allauth.account.signals import user_signed_up
from model_bakery import baker

from accounts.models import Membership, Role
from accounts.signals import household_name_for


@pytest.mark.django_db
class TestSignupCreatesHousehold:
    def test_signing_up_creates_one_household_owned_by_the_signer(self):
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)

        memberships = Membership.objects.filter(user=user)
        assert memberships.count() == 1
        assert memberships.first().role == Role.OWNER

    def test_the_household_is_named_after_the_email_not_the_slug_username(self):
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)

        household = Membership.objects.get(user=user).household
        assert household.name == "Casa de rita"
        assert "a1b2c3" not in household.name

    def test_it_is_idempotent(self):
        """A resent signal must not hand one person two households."""
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)
        user_signed_up.send(sender=type(user), request=None, user=user)

        assert Membership.objects.filter(user=user).count() == 1


class TestHouseholdName:
    def test_it_clips_to_the_column_width(self):
        """Household.name is varchar(120); a long local part must not overflow."""
        user = type("U", (), {"email": "x" * 200 + "@example.com", "username": "u"})()
        assert len(household_name_for(user)) <= 120

    def test_it_falls_back_to_the_username_when_there_is_no_email(self):
        user = type("U", (), {"email": "", "username": "operador"})()
        assert household_name_for(user) == "Casa de operador"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_creates_household.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.signals'`.

- [ ] **Step 3: Write the receiver**

Create `src/backend/accounts/signals.py`:

```python
"""What happens the moment an account comes into existence.

`accounts.middleware.resolve_active_household` also mints a household for a
membership-less user, and deliberately keeps doing so — it is the fail-closed
answer for accounts created by `createsuperuser`, which never fires this
signal. The difference is the name: this path knows the email, so it can call
the household something its owner recognises.
"""

from allauth.account.signals import user_signed_up
from django.db import transaction
from django.dispatch import receiver

from accounts.models import Household, Membership, Role

_NAME_PREFIX = "Casa de "
_NAME_MAX_LENGTH = 120


def household_name_for(user) -> str:
    """``Casa de <email local part>``, clipped to fit ``Household.name``.

    Clipped rather than rejected: the name is a label, not an identifier, and
    a 200-character address must not be the thing that fails a signup.
    """
    email = getattr(user, "email", "") or ""
    label = email.split("@")[0] if "@" in email else (email or user.username)
    return f"{_NAME_PREFIX}{label}"[:_NAME_MAX_LENGTH]


@receiver(user_signed_up)
def create_household_for_new_user(request, user, **kwargs):
    """Give the new account its own household, as owner. Idempotent."""
    if Membership.objects.filter(user=user).exists():
        return
    with transaction.atomic():
        household = Household.objects.create(name=household_name_for(user))
        Membership.objects.create(user=user, household=household, role=Role.OWNER)
```

- [ ] **Step 4: Connect it**

Replace `src/backend/accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # Imported for the @receiver side effect. Not re-exported: nothing
        # should import from here.
        from accounts import signals  # noqa: F401
```

- [ ] **Step 5: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_creates_household.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/signals.py src/backend/accounts/apps.py \
        src/backend/accounts/tests/test_signup_creates_household.py
git commit -m "feat(accounts): a new signup owns a household named after its email"
```

---

## Task 4: The E01 lockout survives the move to allauth

This is S05-4's real content and the one thing in this epic that fails silently. `LockoutModelBackend` extends `ModelBackend`, which looks users up by `username`. allauth authenticates through its own backend, which resolves an email to a user first. Swap the door without swapping the backend's base class and the lockout stops applying to the login page — while every existing lockout test keeps passing, because they call `authenticate()` directly.

**Files:**
- Modify: `src/backend/core/auth_backends.py`
- Modify: `src/backend/config/settings.py:AUTHENTICATION_BACKENDS`
- Test: `src/backend/core/tests/test_lockout_at_allauth_login.py` (create)

**Interfaces:**
- Consumes: `core.security.is_locked`, `core.security.client_ip` (both exist, unchanged).
- Produces: `core.auth_backends.LockoutAuthenticationBackend`, subclassing allauth's `AuthenticationBackend`. `LockoutModelBackend` is retired in the same commit — leaving two backends registered would mean a locked credential could still be checked by the other one.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_lockout_at_allauth_login.py`:

```python
"""The E01 lockout has to follow the credential check to its new URL.

E01 put the lockout in an authentication backend precisely so it would not be
tied to a view. That only holds if the backend the *new* login form uses is
the one carrying the lockout — allauth ships its own, and inheriting from
Django's ModelBackend is not enough once email is the identifier.

allauth's own `login_failed` rate limit is not a substitute: its documentation
states it protects the allauth login view and not Django's admin login, and
this product needs both doors covered.
"""

import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from core.models import LoginAttempt

PASSWORD = "senha-correta-longa-o-suficiente"


@pytest.fixture
def account(db):
    user = baker.make("core.CustomUser", username="alvo", email="alvo@example.com")
    user.set_password(PASSWORD)
    user.save()
    return user


def _fail_n_times(username, ip, count):
    for _ in range(count):
        LoginAttempt.objects.create(username=username, ip=ip)


@pytest.mark.django_db
class TestLockoutAppliesToEmailLogin:
    def test_a_locked_email_is_refused_even_with_the_right_password(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail_n_times("alvo@example.com", "203.0.113.9", 3)

        result = authenticate(
            request=None, username="alvo@example.com", password=PASSWORD
        )
        assert result is None

    def test_an_unlocked_email_still_authenticates(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        result = authenticate(request=None, username="alvo@example.com", password=PASSWORD)
        assert result == account


@pytest.mark.django_db
class TestLockoutAppliesAtTheLoginView:
    def test_repeated_failures_at_the_login_page_lock_the_account(self, account, settings):
        """Drive the real form, because the point is that the *view* is covered."""
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        url = reverse("account_login")

        for _ in range(3):
            client.post(url, {"login": "alvo@example.com", "password": "errada"})

        response = client.post(url, {"login": "alvo@example.com", "password": PASSWORD})
        assert response.status_code == 200  # re-rendered form, not a redirect
        assert "_auth_user_id" not in client.session

    def test_a_failed_attempt_at_the_login_page_is_recorded(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 10
        Client().post(
            reverse("account_login"), {"login": "alvo@example.com", "password": "errada"}
        )
        assert LoginAttempt.objects.filter(username="alvo@example.com").exists()


@pytest.mark.django_db
class TestOnlyOneBackendIsRegistered:
    def test_no_unlocked_backend_remains(self, settings):
        """A second, lockout-free backend would quietly undo the whole thing."""
        assert settings.AUTHENTICATION_BACKENDS == [
            "core.auth_backends.LockoutAuthenticationBackend"
        ]
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_lockout_at_allauth_login.py -v
```

Expected: FAIL. `TestOnlyOneBackendIsRegistered` fails on the backend list; the email-login tests fail because `ModelBackend` looks up `username="alvo@example.com"` and finds nobody, so the assertion that the *right* password succeeds fails first.

- [ ] **Step 3: Rebase the backend onto allauth's**

Replace `src/backend/core/auth_backends.py`:

```python
"""Authentication backend that refuses locked-out credentials.

Subclasses allauth's backend, not Django's `ModelBackend`. That is the whole
substance of it: from E05 the identifier is an email address, and resolving an
address to a user is allauth's job. Inheriting from `ModelBackend` would leave
the lockout attached to a lookup nothing performs any more — and every
existing lockout test would keep passing, because they call `authenticate()`
with a username directly.

Enforcing here rather than in a view means the lockout follows
`authenticate()` wherever it is called from: the allauth login form, the
Django admin login form, a management command. allauth's own `login_failed`
rate limit does not cover the admin form; this does.
"""

from allauth.account.auth_backends import AuthenticationBackend

from core.security import client_ip, is_locked


class LockoutAuthenticationBackend(AuthenticationBackend):
    """allauth's backend, but it will not check a locked credential's password.

    Returns ``None`` rather than raising, so the caller stays on the ordinary
    "invalid credentials" path and a locked-out attacker learns nothing about
    whether the password was right.
    """

    def authenticate(self, request, **credentials):
        identifier = (
            credentials.get("email")
            or credentials.get("username")
            or credentials.get("login")
        )
        if is_locked(identifier, client_ip(request)):
            return None
        return super().authenticate(request, **credentials)
```

- [ ] **Step 4: Point settings at it**

In `src/backend/config/settings.py`, replace the `AUTHENTICATION_BACKENDS` line:

```python
# Brute-force protection lives in the authentication backend, not a view, so it
# applies to every door: the allauth login page and the admin's own form.
# Exactly one backend is registered on purpose — a second, lockout-free backend
# would silently answer the credential the first one refused.
AUTHENTICATION_BACKENDS = ["core.auth_backends.LockoutAuthenticationBackend"]
```

- [ ] **Step 5: Check the failure recorder still fires**

`is_locked` counts `LoginAttempt` rows, and something has to write them. Find the writer and confirm it keys on the same identifier the backend now checks:

```bash
grep -rn "LoginAttempt.objects.create\|LoginAttempt(" src/backend/ --include=*.py | grep -v tests
```

If the writer is a `user_login_failed` receiver, it already receives `credentials` and needs no change beyond reading `credentials.get("login")` as well as `"username"`. If it lives in the old `LockoutModelBackend`, move it into `LockoutAuthenticationBackend` — the test `test_a_failed_attempt_at_the_login_page_is_recorded` is what tells you which.

- [ ] **Step 6: Run the new test, then the whole suite**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_lockout_at_allauth_login.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_login_lockout.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
```

Expected: all PASS. `test_login_lockout.py` is E01's suite and must stay green — if it fails, the lockout primitives changed behaviour, which this task must not do.

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/core/auth_backends.py src/backend/config/settings.py \
        src/backend/core/tests/test_lockout_at_allauth_login.py
git commit -m "fix(auth): the E01 lockout follows the credential check onto allauth's backend"
```

---

## Task 5: Transactional email — Resend over SMTP, console locally

S05-2. Verification and invitation emails are worthless if they do not arrive, and every task after this one sends mail.

**Files:**
- Modify: `src/backend/config/settings.py`
- Modify: `docs/runbook.md`
- Test: `src/backend/core/tests/test_email_config.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: settings `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`. Env vars `EMAIL_HOST`, `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_email_config.py`:

```python
"""Email configuration, asserted rather than assumed.

The failure mode this guards against is silent: with no EMAIL_HOST set, Django
falls back to an SMTP backend pointed at localhost:25, where mail is accepted
by nothing and lost without an exception. A developer would see "verification
email sent" and no email.
"""

import importlib

from django.conf import settings


def _settings_with(monkeypatch, **env):
    """Re-import config.settings under a patched environment."""
    import config.settings as module

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(module)


class TestLocalDevelopmentSendsNothing:
    def test_no_email_host_means_the_console_backend(self, monkeypatch):
        monkeypatch.delenv("EMAIL_HOST", raising=False)
        reloaded = _settings_with(monkeypatch)
        assert reloaded.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


class TestProductionUsesSmtp:
    def test_an_email_host_switches_to_smtp(self, monkeypatch):
        reloaded = _settings_with(monkeypatch, EMAIL_HOST="smtp.resend.com")
        assert reloaded.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        assert reloaded.EMAIL_PORT == 587
        assert reloaded.EMAIL_USE_TLS is True


class TestFromAddress:
    def test_there_is_a_default_from_address(self):
        assert settings.DEFAULT_FROM_EMAIL
        assert "@" in settings.DEFAULT_FROM_EMAIL
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_email_config.py -v
```

Expected: FAIL — `AttributeError` / the default `DEFAULT_FROM_EMAIL` is `webmaster@localhost`, and `EMAIL_BACKEND` is the SMTP default.

- [ ] **Step 3: Add the settings block**

In `src/backend/config/settings.py`, immediately after the identity block from Task 1:

```python
# --- Transactional email (E05 S05-2) ------------------------------------
# Resend over plain SMTP, deliberately: an API-key-in-a-header SDK would be a
# dependency and a code path, and Django already speaks SMTP. Switching
# provider is then an environment change, not a deploy.
#
# The absent-EMAIL_HOST branch is the important one. Django's default is an
# SMTP backend pointed at localhost:25 — mail vanishes with no exception, so a
# developer sees "e-mail enviado" and an empty inbox. Console backend instead.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
# Resend's SMTP username is the literal string "resend"; the password is the
# API key, which lives in Secret Manager and never in this repo.
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "resend")
EMAIL_HOST_PASSWORD = os.environ.get("RESEND_API_KEY", "")
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "Ledger <nao-responda@localhost>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL
```

- [ ] **Step 4: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_email_config.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Write the runbook section**

Operator procedures go in `docs/runbook.md`, not the README — this is a standing rule for this repo. Add a `## Transactional email` section after `## Signing in, and clearing a lockout`, covering:

1. **Creating the Resend account and verifying the sending domain.** The exact DNS records Resend issues: an SPF `TXT` record, and the DKIM `CNAME`/`TXT` records. State that unverified financial-app email lands in Gmail's spam folder — this is why the step is not optional.
2. **Storing the key.** The full command, with realistic values:
   ```bash
   printf '%s' 're_xxxxxxxxxxxxxxxxxxxxx' | gcloud secrets create resend-api-key \
     --project=expense-tracker-482807 --data-file=-
   gcloud run services update expense-tracker --region=<region> \
     --project=expense-tracker-482807 \
     --set-env-vars=EMAIL_HOST=smtp.resend.com,DEFAULT_FROM_EMAIL='Ledger <nao-responda@SEU-DOMINIO>' \
     --set-secrets=RESEND_API_KEY=resend-api-key:latest
   ```
3. **What it prints**, and the common failure: a `535 Authentication failed` means the key was pasted with a trailing newline — `printf` rather than `echo` is why the command above uses it.
4. **Sending a test message** from a deployed revision:
   ```bash
   gcloud run services proxy expense-tracker --region=<region> &
   # then, in a Django shell on the revision:
   # from django.core.mail import send_mail
   # send_mail("Teste", "corpo", None, ["seu-endereco@gmail.com"])
   ```
5. **The deliverability check itself** — S05-2's last bullet — recorded as a checklist: send to a Gmail address, confirm it lands in the inbox and not Promotions or Spam, and paste the resulting `Authentication-Results` header (it must show `spf=pass` and `dkim=pass`) into the runbook as evidence.

- [ ] **Step 6: Add the pointer**

The runbook is only documentation if it can be found. Add one line to the README quickstart and to `AGENTS.md` if it exists:

```markdown
Operational procedures — deploys, secrets, email, admin access — live in [docs/runbook.md](docs/runbook.md).
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/config/settings.py src/backend/core/tests/test_email_config.py \
        docs/runbook.md README.md
git commit -m "feat(email): Resend over SMTP in production, console backend locally"
```

**Note for the executor:** the *account* setup and DNS records in Step 5 are work you cannot do — they need the domain registrar. Write the runbook section fully, then flag to the user that steps 1 and 5 of that section are theirs to execute before Task 16's manual verification can pass.

---

## Task 6: Hand allauth the front door, keeping `/login/` alive for the TWA

S05-4. `AppLoginView` already carries the lockout explanation and a styled template; it moves rather than dies. `/login/` must keep answering — the installed Android TWA and any PWA shortcut point at it.

**Files:**
- Modify: `src/backend/core/views.py:AppLoginView`
- Modify: `src/backend/config/urls.py`
- Modify: `src/backend/config/settings.py` (`LOGIN_URL`)
- Modify: `src/backend/templates/sw.js`
- Test: `src/backend/core/tests/test_front_door.py` (create)

**Interfaces:**
- Consumes: `core.security.is_locked`, `core.security.client_ip`; the URL name `account_login` from Task 1.
- Produces: `AppLoginView` now subclasses `allauth.account.views.LoginView` and is mounted **as** `account_login`, keeping `locked_out` and `lockout_minutes` in the template context. `/login/` and `/logout/` are permanent redirects to allauth's equivalents.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_front_door.py`:

```python
"""Where the product's front door is, and what still answers at the old one.

`/login/` is not merely a legacy path: it is compiled into the installed
Android TWA and into the PWA manifest. Breaking it logs out every phone that
has the app, with no way to push a fix to them.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from model_bakery import baker


class TestLoginUrlPointsAtAllauth:
    def test_login_url_setting(self):
        assert settings.LOGIN_URL == "/accounts/login/"

    def test_account_login_resolves_to_the_app_view(self):
        from core.views import AppLoginView

        assert reverse("account_login") == "/accounts/login/"
        assert AppLoginView.__name__ == "AppLoginView"


@pytest.mark.django_db
class TestOldPathsStillAnswer:
    def test_slash_login_redirects_to_allauth(self):
        response = Client().get("/login/")
        assert response.status_code == 301
        assert response["Location"] == "/accounts/login/"

    def test_slash_login_preserves_the_next_parameter(self):
        response = Client().get("/login/?next=/entries/")
        assert response.status_code == 301
        assert "next=/entries/" in response["Location"]

    def test_logout_still_works_and_lands_somewhere_public(self):
        user = baker.make("core.CustomUser", email="sai@example.com")
        client = Client()
        client.force_login(user)
        response = client.post("/logout/")
        assert response.status_code == 302
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
class TestProtectedPagesBounceToTheNewDoor:
    def test_an_anonymous_request_is_sent_to_allauth_login(self):
        response = Client().get("/entries/")
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
class TestTheLockoutExplanationSurvived:
    def test_the_login_page_still_knows_the_lockout_window(self):
        response = Client().get(reverse("account_login"))
        assert response.context["lockout_minutes"] == settings.LOGIN_FAILURE_WINDOW_MINUTES
        assert response.context["locked_out"] is False
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_front_door.py -v
```

Expected: FAIL — `LOGIN_URL` is `/login/`, `reverse("account_login")` resolves to allauth's stock view (so `lockout_minutes` is absent from the context), and `/login/` returns 200 rather than 301.

- [ ] **Step 3: Rebase `AppLoginView` onto allauth's login view**

In `src/backend/core/views.py`, replace the `AppLoginView` class and its import:

```python
from allauth.account.views import LoginView
```

```python
class AppLoginView(LoginView):
    """The family's front door.

    Subclasses allauth's login view rather than Django's: from E05 the
    identifier is an email address, and allauth owns that resolution along
    with signup, verification and reset. What this class adds is the one thing
    allauth does not know about — E01's lockout, which lives in
    `core.auth_backends` and refuses a locked credential without checking it.

    Naming the lockout leaks nothing: a failed attempt is recorded for any
    identifier, existing or not, so the message cannot tell an attacker that an
    account exists.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lockout_minutes"] = settings.LOGIN_FAILURE_WINDOW_MINUTES
        context.setdefault("locked_out", False)
        return context

    def form_invalid(self, form):
        """Say *why* it failed when the reason is the lockout, not the password.

        The backend refuses a locked-out credential without checking it, so the
        form comes back with the ordinary "invalid credentials" error and the
        user has no way to tell a lockout from a typo — which is exactly the
        situation that makes someone keep trying.
        """
        response = super().form_invalid(form)
        identifier = form.data.get("login", "")
        if is_locked(identifier, client_ip(self.request)):
            response.context_data["locked_out"] = True
        return response
```

Note `form.data.get("login")` — allauth's login form field is named `login`, not `username`.

- [ ] **Step 4: Rewire the URLs**

In `src/backend/config/urls.py`:

```python
from django.views.generic import RedirectView

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("manifest.webmanifest", ManifestView.as_view(), name="manifest"),
    path(".well-known/assetlinks.json", AssetLinksView.as_view(), name="assetlinks"),
    # The installed Android TWA and the PWA shortcut both point at these two
    # paths. They are permanent redirects rather than deletions because there
    # is no way to push a URL change to a phone that already has the app.
    path("login/", RedirectView.as_view(url="/accounts/login/", permanent=True, query_string=True)),
    path("logout/", RedirectView.as_view(url="/accounts/logout/", permanent=True)),
    # Declared *before* allauth's include so this one wins the `account_login`
    # name — allauth's own view never gets a chance to resolve.
    path("accounts/login/", AppLoginView.as_view(), name="account_login"),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
    ...
]
```

Remove the now-unused `LogoutView` import.

- [ ] **Step 5: Point `LOGIN_URL` at the new door**

In `src/backend/config/settings.py`:

```python
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"
```

- [ ] **Step 6: Move the login template to where allauth looks for it**

```bash
git mv src/backend/templates/registration/login.html src/backend/templates/account/login.html
```

Then edit the moved file for allauth's form: the field is `form.login` (label **E-mail**), not `form.username`; the action is `{% url 'account_login' %}`; `autocomplete` becomes `email` and the input `type="email"`. Add a "Esqueceu a senha?" link to `{% url 'account_reset_password' %}` and a "Criar conta" link to `{% url 'account_signup' %}` — a login page with no way to sign up is the front door problem restated. Task 7 does the full daisyUI pass over every auth page; this step only makes the page functional.

- [ ] **Step 7: Follow the admin bypass in the service worker**

`templates/sw.js` skips `/admin/` so admin pages never hit the cache. Leave that line alone for now — Task 14 moves the admin path and updates it there — but confirm the new `/accounts/` paths are handled: they are navigations, so `networkFirstNav` applies, which is correct. No change needed. Add nothing; this step is a check, not an edit.

- [ ] **Step 8: Run the test, then the whole suite**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_front_door.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -20
```

Expected: the new file PASSES. Existing failures will cluster in `test_navbar_auth.py` and `test_login_view.py`, which assert `/login/` and the old form — update them to the new paths. `test_navbar_auth.py::test_navbar_has_theme_toggle_and_logout` asserts `/logout/` appears in the navbar; that path still works via the redirect, so decide deliberately whether to point the navbar at `/accounts/logout/` (preferred) and update the assertion.

- [ ] **Step 9: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add -A
git commit -m "feat(auth): allauth is the front door; /login/ redirects for the installed TWA"
```

---

## Task 7: Style every auth page — pt-BR, daisyUI, matching the product

S05-1's third and fourth bullets. allauth's stock templates are unstyled English forms; shipping them is the spec's explicit failure condition. This is the first thing a stranger sees.

**Files:**
- Create: `src/backend/templates/account/base.html`
- Modify: `src/backend/templates/account/login.html`
- Create: `src/backend/templates/account/signup.html`
- Create: `src/backend/templates/account/verification_sent.html`
- Create: `src/backend/templates/account/email_confirm.html`
- Create: `src/backend/templates/account/password_reset.html`
- Create: `src/backend/templates/account/password_reset_done.html`
- Create: `src/backend/templates/account/password_reset_from_key.html`
- Create: `src/backend/templates/account/password_reset_from_key_done.html`
- Create: `src/backend/templates/account/email/*.txt` (four files)
- Test: `src/backend/core/tests/test_auth_pages.py` (create)

**Interfaces:**
- Consumes: `base_public.html` (exists — the shell built for pre-login pages, sharing the head, theme bootstrap and fonts with the app).
- Produces: `templates/account/base.html`, which every auth page extends. Nothing else depends on these.

- [ ] **Step 1: Discover the installed version's template inheritance chain**

Do not guess this. allauth restructured its templates around version 65 (`allauth/layouts/entrance.html`), and the names differ between versions:

```bash
ALLAUTH=$(uv run python -c "import allauth, os; print(os.path.dirname(allauth.__file__))")
ls "$ALLAUTH/templates/allauth/layouts/" 2>/dev/null
head -3 "$ALLAUTH/templates/account/login.html"
head -3 "$ALLAUTH/templates/account/signup.html"
grep -rn "extends" "$ALLAUTH/templates/account/base_entrance.html" 2>/dev/null
```

Record what each stock page extends. Every page this task overrides is written in full, so the chain only matters for the pages **not** overridden — the MFA screens from Task 15. Whatever those extend, provide a styled version of it in Step 2.

- [ ] **Step 2: Create the shared auth shell**

Create `src/backend/templates/account/base.html`:

```html
{% extends "base_public.html" %}
{% comment %}
The shell every allauth page hangs off.

base_public.html already carries the head the app uses — theme bootstrap
before paint, the same fonts, the same stylesheet, the PWA tags — so an auth
page looks like the product rather than like a gate in front of it. That is
deliberate: these pages are the first thing a stranger sees.

allauth's stock pages extend a chain of its own; overriding this file at the
top of the chain means the pages this repo does NOT override (the MFA screens)
inherit the product's look for free.
{% endcomment %}

{% block content %}
<div class="card bg-base-100 shadow-sm w-full max-w-sm">
    <div class="card-body">
        <h1 class="card-title text-2xl justify-center mb-1">{% block heading %}Expense Tracker{% endblock %}</h1>
        <p class="text-sm opacity-70 text-center mb-4">{% block subheading %}{% endblock %}</p>

        {% if messages %}
        <div class="mb-4 space-y-2">
            {% for message in messages %}
            <div class="alert alert-info"><span>{{ message }}</span></div>
            {% endfor %}
        </div>
        {% endif %}

        {% block inner %}{% endblock %}
    </div>
</div>
{% endblock %}
```

If Step 1 showed the stock pages extending something other than `account/base.html`, create that file instead (or as well) with the same body.

- [ ] **Step 3: Run the daisyUI Blueprint chain before writing any markup**

This is a MUST for this repo, and it runs **before** the templates, not after. With one `workflowId` for the whole cohesive auth design, e.g. `e05auth`:

1. Inspect the build setup first: Tailwind v4 via `django-tailwind-cli`, entry CSS at `src/backend/static/css/input.css`, `TAILWIND_CLI_USE_DAISY_UI = True`, output committed at `static/css/tailwind.css`.
2. `daisyui_setup_expert` — `workflowId: "e05auth"`, absolute `projectRoot`, `install: false` (daisyUI is already configured).
3. `daisyui_rules_enforcer` — same `workflowId`.
4. **Skip `daisyui_creative_director` and `daisyui_page_architect`.** This repo has a settled design direction; a competing aesthetic here is a defect, not an improvement.
5. `daisyui_component_syntax_expert` — submit every component these pages use: `card`, `form-control`, `label`, `input`, `btn`, `alert`, `link`, `divider`, `loading`. Repeat with the same `workflowId` until the final batch advances the workflow.

- [ ] **Step 4: Write the failing test**

Create `src/backend/core/tests/test_auth_pages.py`:

```python
"""Every auth page renders, in pt-BR, in the product's shell.

allauth's stock templates are unstyled English. Shipping them is the spec's
named failure condition — these pages are a stranger's first impression of a
financial product, and an unstyled form reads as a phishing page.
"""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from model_bakery import baker

PAGES = [
    ("account_login", "Entrar"),
    ("account_signup", "Criar conta"),
    ("account_reset_password", "Recuperar senha"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,expected_copy", PAGES)
def test_page_renders_in_ptbr(url_name, expected_copy):
    response = Client().get(reverse(url_name))
    assert response.status_code == 200
    body = response.content.decode()
    assert expected_copy in body


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,_copy", PAGES)
def test_page_uses_the_product_shell(url_name, _copy):
    """The theme bootstrap lives in base_public.html; its absence means the
    page fell back to allauth's own unstyled base."""
    body = Client().get(reverse(url_name)).content.decode()
    assert 'lang="pt-BR"' in body
    assert "css/tailwind.css" in body


@pytest.mark.django_db
class TestNoEnglishLeaksThrough:
    def test_signup_page_has_no_stock_english(self):
        body = Client().get(reverse("account_signup")).content.decode()
        for stock in ("Sign Up", "Sign In", "Already have an account", "Forgot Password"):
            assert stock not in body


@pytest.mark.django_db
class TestEmailsAreInPortuguese:
    def test_the_verification_email_is_ptbr(self):
        Client().post(
            reverse("account_signup"),
            {
                "email": "nova@example.com",
                "email2": "nova@example.com",
                "password1": "uma-senha-bem-longa-9",
                "password2": "uma-senha-bem-longa-9",
            },
        )
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert "Confirme" in message.subject
        assert "http" in message.body
        for stock in ("Hello from", "Please confirm", "You're receiving"):
            assert stock not in message.body

    def test_the_password_reset_email_is_ptbr(self):
        baker.make("core.CustomUser", email="volta@example.com")
        Client().post(reverse("account_reset_password"), {"email": "volta@example.com"})
        assert len(mail.outbox) == 1
        assert "senha" in mail.outbox[0].subject.lower()
```

- [ ] **Step 5: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_auth_pages.py -v
```

Expected: FAIL — the signup and reset pages render allauth's English stock templates, so the pt-BR assertions and the `TestNoEnglishLeaksThrough` assertions fail.

- [ ] **Step 6: Write the page templates**

Each extends `account/base.html` and fills `heading`, `subheading` and `inner`. `signup.html`:

```html
{% extends "account/base.html" %}

{% block title %}Criar conta — Expense Tracker{% endblock %}
{% block heading %}Criar conta{% endblock %}
{% block subheading %}Comece a acompanhar as contas da casa.{% endblock %}

{% block inner %}
{% if form.non_field_errors %}
<div class="alert alert-error mb-4"><span>{{ form.non_field_errors|first }}</span></div>
{% endif %}

<form method="post" action="{% url 'account_signup' %}" class="space-y-3">
    {% csrf_token %}
    <div class="form-control">
        <label class="label" for="{{ form.email.id_for_label }}">
            <span class="label-text">E-mail</span>
        </label>
        <input type="email" name="{{ form.email.html_name }}" id="{{ form.email.id_for_label }}"
               class="input input-bordered w-full{% if form.email.errors %} input-error{% endif %}"
               autocomplete="email" autocapitalize="none" inputmode="email"
               value="{{ form.email.value|default:'' }}" required autofocus>
        {% if form.email.errors %}
        <span class="label-text-alt text-error mt-1">{{ form.email.errors|first }}</span>
        {% endif %}
    </div>
    <div class="form-control">
        <label class="label" for="{{ form.email2.id_for_label }}">
            <span class="label-text">Confirme o e-mail</span>
        </label>
        <input type="email" name="{{ form.email2.html_name }}" id="{{ form.email2.id_for_label }}"
               class="input input-bordered w-full{% if form.email2.errors %} input-error{% endif %}"
               autocomplete="email" autocapitalize="none" inputmode="email" required>
        {% if form.email2.errors %}
        <span class="label-text-alt text-error mt-1">{{ form.email2.errors|first }}</span>
        {% endif %}
    </div>
    <div class="form-control">
        <label class="label" for="{{ form.password1.id_for_label }}">
            <span class="label-text">Senha</span>
        </label>
        <input type="password" name="{{ form.password1.html_name }}" id="{{ form.password1.id_for_label }}"
               class="input input-bordered w-full{% if form.password1.errors %} input-error{% endif %}"
               autocomplete="new-password" required>
        {% if form.password1.errors %}
        <span class="label-text-alt text-error mt-1">{{ form.password1.errors|first }}</span>
        {% endif %}
    </div>
    <div class="form-control">
        <label class="label" for="{{ form.password2.id_for_label }}">
            <span class="label-text">Repita a senha</span>
        </label>
        <input type="password" name="{{ form.password2.html_name }}" id="{{ form.password2.id_for_label }}"
               class="input input-bordered w-full{% if form.password2.errors %} input-error{% endif %}"
               autocomplete="new-password" required>
        {% if form.password2.errors %}
        <span class="label-text-alt text-error mt-1">{{ form.password2.errors|first }}</span>
        {% endif %}
    </div>
    {% if redirect_field_value %}
    <input type="hidden" name="{{ redirect_field_name }}" value="{{ redirect_field_value }}">
    {% endif %}
    <button type="submit" class="btn btn-accent w-full" data-pending="Criando…">Criar conta</button>
</form>

<div class="divider text-xs opacity-60">ou</div>
<a href="{% url 'account_login' %}" class="btn btn-ghost btn-sm w-full">Já tenho conta</a>
{% endblock %}
```

Write the remaining pages the same way. Their copy:

| Template | Heading | Body |
|---|---|---|
| `verification_sent.html` | `Confirme seu e-mail` | "Enviamos um link de confirmação para o seu e-mail. Abra a mensagem e clique no link para ativar a conta." Plus a note that the link expires in 3 days. |
| `email_confirm.html` | `Confirmar e-mail` | A `POST` form to `{{ action_url }}` with a single **Confirmar** button. If `confirmation` is absent, say the link expired and link to `account_signup`. |
| `password_reset.html` | `Recuperar senha` | One email field, button **Enviar link**, and a link back to `account_login`. |
| `password_reset_done.html` | `Verifique seu e-mail` | "Se existe uma conta com esse endereço, enviamos um link para redefinir a senha." — phrased that way because `ACCOUNT_PREVENT_ENUMERATION` is on and the page must not contradict it. |
| `password_reset_from_key.html` | `Nova senha` | Two password fields (`form.password1`, `form.password2`), button **Salvar senha**. When `token_fail` is true, say the link is invalid or expired and link to `account_reset_password`. |
| `password_reset_from_key_done.html` | `Senha alterada` | Confirmation plus a button to `account_login`. |

- [ ] **Step 7: Write the four email templates**

allauth reads subject and body from separate files. Create under `src/backend/templates/account/email/`:

`email_confirmation_subject.txt` — one line, no trailing newline issues (allauth strips it):
```
Confirme seu e-mail no Expense Tracker
```

`email_confirmation_message.txt`:
```
{% autoescape off %}Olá,

Alguém — esperamos que você — criou uma conta no Expense Tracker com este endereço.

Confirme clicando no link abaixo:

{{ activate_url }}

O link vale por {{ expiration_days }} dias. Se não foi você, ignore esta mensagem: sem a confirmação, a conta não é ativada.

— Expense Tracker
{% endautoescape %}
```

`password_reset_key_subject.txt`:
```
Redefinir sua senha do Expense Tracker
```

`password_reset_key_message.txt`:
```
{% autoescape off %}Olá,

Recebemos um pedido para redefinir a senha da sua conta no Expense Tracker.

Escolha uma nova senha aqui:

{{ password_reset_url }}

Se não foi você, ignore esta mensagem — sua senha continua a mesma.

— Expense Tracker
{% endautoescape %}
```

- [ ] **Step 8: Rebuild the stylesheet**

New daisyUI class names in new templates mean the committed CSS is stale — this repo has been bitten by exactly that. `--force` is not optional:

```bash
uv run python src/backend/manage.py tailwind build --force
```

- [ ] **Step 9: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_auth_pages.py -v
```

Expected: PASS, 11 tests.

- [ ] **Step 10: Audit the markup**

`daisyui_quality_inspector` with `auditIntent: "fix_changes"`, `workflowId: "e05auth"`, paths **relative to `projectRoot`**, line ranges from `git diff --unified=0`. Follow the single returned action, fix, rerun until it finalizes.

Two standing exceptions for this repo: do not apply a fix that breaks an accessible name, focus behaviour, or a semantic token; and its "static Tailwind arbitrary utilities, never authored selectors" rule targets decorative effects, not structural or accessibility CSS. If a finding collides with one of those, leave the code, say so in the commit body, and note the deviation.

- [ ] **Step 11: Look at the pages**

If a browser tool is available, open `/accounts/login/`, `/accounts/signup/` and `/accounts/password/reset/` at ~390px and ~1440px, in both `ledger` and `ledger-dark`. Check that the card does not overflow at 390px and that the inputs are tall enough to tap. Do not skip this on the grounds that the tests pass — the tests assert copy, not layout.

- [ ] **Step 12: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/templates/account/ src/backend/static/css/tailwind.css \
        src/backend/core/tests/test_auth_pages.py
git commit -m "feat(auth): pt-BR daisyUI templates for every allauth page and email"
```

---

## Task 8: The account lifecycle, end to end

The spec's first observable assertion: sign up → verify → log in → reset password → log in with the new password. Everything up to here was built in pieces; this proves the pieces are one road.

**Files:**
- Test: `src/backend/core/tests/test_account_lifecycle.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1–7. Adds no production code — if this task needs a source change, that change belongs to whichever earlier task got it wrong.

- [ ] **Step 1: Write the end-to-end test**

Create `src/backend/core/tests/test_account_lifecycle.py`:

```python
"""Sign up, verify, log in, forget the password, reset it, log in again.

The epic's first observable assertion, written as one road rather than six
unit tests, because the failure this catches is always at a seam: a signal
that fires too late, a redirect that drops `next`, a verification that lets an
unverified account through.

Reads links out of `mail.outbox` rather than constructing them, so a change to
allauth's URL shapes fails here loudly instead of passing against a URL the
product never sends.
"""

import re

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import Membership, Role

EMAIL = "estranho@example.com"
FIRST_PASSWORD = "primeira-senha-longa-7"
SECOND_PASSWORD = "segunda-senha-longa-42"


def _link_from(message, fragment):
    """The first URL in the message body containing `fragment`."""
    urls = re.findall(r"https?://\S+", message.body)
    matches = [u for u in urls if fragment in u]
    assert matches, f"no {fragment!r} link in:\n{message.body}"
    return matches[0]


@pytest.mark.django_db
class TestAccountLifecycle:
    def test_a_stranger_can_sign_up_verify_log_in_and_reset(self):
        client = Client()

        # --- sign up ---------------------------------------------------
        response = client.post(
            reverse("account_signup"),
            {
                "email": EMAIL,
                "email2": EMAIL,
                "password1": FIRST_PASSWORD,
                "password2": FIRST_PASSWORD,
            },
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1

        # --- verification is mandatory ---------------------------------
        fresh = Client()
        fresh.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" not in fresh.session, "unverified account logged in"

        # --- verify ----------------------------------------------------
        confirm_url = _link_from(mail.outbox[0], "confirm")
        path = confirm_url.split("testserver")[-1]
        assert fresh.post(path).status_code in (302, 200)

        # --- log in ----------------------------------------------------
        fresh.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" in fresh.session

        # --- the signup owns a household -------------------------------
        membership = Membership.objects.get(user_id=fresh.session["_auth_user_id"])
        assert membership.role == Role.OWNER

        # --- forget the password ---------------------------------------
        mail.outbox.clear()
        anonymous = Client()
        anonymous.post(reverse("account_reset_password"), {"email": EMAIL})
        assert len(mail.outbox) == 1

        reset_url = _link_from(mail.outbox[0], "password/reset")
        reset_path = reset_url.split("testserver")[-1]

        # allauth redirects the key URL to a `set-password` URL before showing
        # the form; follow it, then post to wherever it landed.
        landed = anonymous.get(reset_path, follow=True)
        assert landed.status_code == 200
        form_path = landed.request["PATH_INFO"]
        anonymous.post(
            form_path, {"password1": SECOND_PASSWORD, "password2": SECOND_PASSWORD}
        )

        # --- the old password is dead, the new one works ---------------
        stale = Client()
        stale.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" not in stale.session

        final = Client()
        final.post(reverse("account_login"), {"login": EMAIL, "password": SECOND_PASSWORD})
        assert "_auth_user_id" in final.session


@pytest.mark.django_db
class TestPasswordValidatorsStillApply:
    """settings.AUTH_PASSWORD_VALIDATORS must survive the move to allauth."""

    def test_a_short_password_is_rejected_at_signup(self):
        response = Client().post(
            reverse("account_signup"),
            {"email": "curta@example.com", "email2": "curta@example.com",
             "password1": "abc", "password2": "abc"},
        )
        assert response.status_code == 200  # re-rendered with errors
        assert not mail.outbox

    def test_a_common_password_is_rejected_at_signup(self):
        response = Client().post(
            reverse("account_signup"),
            {"email": "comum@example.com", "email2": "comum@example.com",
             "password1": "password123", "password2": "password123"},
        )
        assert response.status_code == 200
        assert not mail.outbox
```

- [ ] **Step 2: Run it**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_account_lifecycle.py -v
```

Expected: PASS. If it fails, fix the *earlier task's* code, not this test — this test is the specification. The two likeliest failures: the confirmation link's path shape (print `mail.outbox[0].body` and read it), and the reset flow's intermediate redirect (allauth swaps the key for a session-held one, which is why the test follows redirects rather than posting to the emailed URL directly).

- [ ] **Step 3: Commit**

```bash
git add src/backend/core/tests/test_account_lifecycle.py
git commit -m "test(auth): the account lifecycle, signup through password reset, end to end"
```

---

## Task 9: The `Invitation` model

S05-3's storage. A token that is not guessable, is single-use, and expires — and a row that E04's isolation ratchet recognises as household-owned without being told.

**Files:**
- Modify: `src/backend/accounts/models.py`
- Create: `src/backend/accounts/migrations/0004_invitation.py`
- Test: `src/backend/accounts/tests/test_invitation_model.py` (create)

**Interfaces:**
- Consumes: `accounts.models.AuthoredHouseholdModel` (gives `household` NOT NULL + `created_by` SET_NULL), `accounts.models.Role`.
- Produces: `accounts.models.Invitation` with fields `id` (UUID pk), `email`, `role`, `token_hash` (unique, 64 chars), `expires_at`, `accepted_at` (nullable), `revoked_at` (nullable), `created_at`; and properties `is_pending`, `is_expired(now=None)`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_invitation_model.py`:

```python
"""What an invitation is, before anything sends or redeems one.

Inherits AuthoredHouseholdModel deliberately: that is what makes `household`
NOT NULL, gives `created_by` SET_NULL semantics (an owner who deletes their
account must not delete the household's invitation history), and puts the row
inside E04's isolation ratchet without anyone maintaining a list.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from model_bakery import baker

from accounts.models import AuthoredHouseholdModel, Invitation, Role, household_owned_models

# Frozen so `is_expired` is compared against a fixed instant rather than the
# real clock: the assertions below are about an hour either side of an expiry,
# and a suite that reads `now()` twice can straddle it.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.mark.django_db
class TestInvitationIsHouseholdOwned:
    def test_it_inherits_the_tenancy_base(self):
        assert issubclass(Invitation, AuthoredHouseholdModel)

    def test_the_ratchet_discovers_it(self):
        """E04's isolation test enumerates by base class, not by a list."""
        assert Invitation in household_owned_models()

    def test_household_is_not_nullable(self):
        assert Invitation._meta.get_field("household").null is False


@pytest.mark.django_db
class TestTokenHashIsUnique:
    def test_two_invitations_cannot_share_a_token_hash(self, household):
        baker.make(Invitation, household=household, token_hash="a" * 64)
        with pytest.raises(IntegrityError), transaction.atomic():
            baker.make(Invitation, household=household, token_hash="a" * 64)


@pytest.mark.django_db
class TestPendingAndExpired:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)

    def _invite(self, household, **kwargs):
        defaults = {
            "household": household,
            "email": "convidada@example.com",
            "role": Role.MEMBER,
            "token_hash": "b" * 64,
            "expires_at": timezone.now() + timedelta(days=7),
        }
        defaults.update(kwargs)
        return Invitation.objects.create(**defaults)

    def test_a_fresh_invitation_is_pending(self, household):
        assert self._invite(household).is_pending is True

    def test_an_accepted_invitation_is_not_pending(self, household):
        invite = self._invite(household, accepted_at=timezone.now())
        assert invite.is_pending is False

    def test_a_revoked_invitation_is_not_pending(self, household):
        invite = self._invite(household, revoked_at=timezone.now())
        assert invite.is_pending is False

    def test_an_expired_invitation_is_not_pending(self, household):
        invite = self._invite(household, expires_at=timezone.now() - timedelta(seconds=1))
        assert invite.is_expired() is True
        assert invite.is_pending is False

    def test_expiry_accepts_an_injected_clock(self, household):
        invite = self._invite(household, expires_at=FROZEN_NOW + timedelta(days=7))
        assert invite.is_expired(now=FROZEN_NOW + timedelta(days=6)) is False
        assert invite.is_expired(now=FROZEN_NOW + timedelta(days=8)) is True
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invitation_model.py -v
```

Expected: FAIL — `ImportError: cannot import name 'Invitation' from 'accounts.models'`.

- [ ] **Step 3: Add the model**

Append to `src/backend/accounts/models.py`:

```python
class Invitation(AuthoredHouseholdModel):
    """A pending offer to join a household.

    Inherits ``AuthoredHouseholdModel`` rather than ``models.Model`` so the
    tenant column is the same one every other domain row carries: E04's
    ratchet test enumerates by base class, so this model is covered by the
    cross-household isolation suite the moment it exists, without anyone
    adding it to a list.

    ``created_by`` is the inviter. SET_NULL, like everywhere else — an owner
    who deletes their account must not take the household's invitation history
    with them.

    The raw token is never stored. ``token_hash`` holds its SHA-256, so a
    database read — a leaked backup, an over-broad admin query — yields
    nothing redeemable. See ``accounts.invitations``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("e-mail convidado")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "convite"
        verbose_name_plural = "convites"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["household", "-created_at"], name="invite_household_recent_idx"),
        ]

    def __str__(self):
        return f"{self.email} → {self.household}"

    def is_expired(self, now=None) -> bool:
        """Clock injected: `docs/testing-conventions.md` — a boundary test must
        not have to straddle two reads of `timezone.now()`."""
        from django.utils import timezone

        return self.expires_at <= (now or timezone.now())

    @property
    def is_pending(self) -> bool:
        """Redeemable right now: not accepted, not revoked, not expired."""
        return self.accepted_at is None and self.revoked_at is None and not self.is_expired()
```

- [ ] **Step 4: Generate and apply the migration**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations accounts --name invitation
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate accounts
```

- [ ] **Step 5: Run the new test, then E04's ratchet**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invitation_model.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/ -v
```

Expected: all PASS. `test_scoping_ratchet.py` and `test_cross_household_isolation.py` now cover `Invitation` automatically — if either fails, the model is missing something the ratchet requires, and the ratchet is right.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/models.py src/backend/accounts/migrations/0004_invitation.py \
        src/backend/accounts/tests/test_invitation_model.py
git commit -m "feat(accounts): an Invitation is a household row with a hashed, expiring token"
```

---

## Task 10: The invitation lifecycle as pure functions

Minting, looking up, redeeming and revoking — with no HTTP anywhere near them, so the security properties can be tested exhaustively without a client.

**Files:**
- Create: `src/backend/accounts/invitations.py`
- Test: `src/backend/accounts/tests/test_invitations.py` (create)

**Interfaces:**
- Consumes: `accounts.models.Invitation`, `Membership`, `Role`.
- Produces:
  - `create_invitation(*, household, invited_by, email, role=Role.MEMBER, now=None, ttl_days=7) -> tuple[Invitation, str]` — returns the row and the **raw** token, which is the only moment the raw token exists.
  - `invitation_for_token(raw_token) -> Invitation | None`
  - `redeem_invitation(raw_token, user, *, now=None) -> Membership` — raises `InvitationUnusable`.
  - `revoke_invitation(invitation, *, now=None) -> None`
  - `InvitationUnusable(Exception)` with subclasses `InvitationNotFound`, `InvitationExpired`, `InvitationAlreadyUsed`, `InvitationRevoked`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_invitations.py`:

```python
"""The invitation lifecycle, with no HTTP in sight.

Kept as pure functions so the security properties — unguessable, single-use,
expiring, never stored in the clear — are tested against the functions
themselves rather than through a view that might be the thing enforcing them.
A property enforced in a view is a property one new view can lose.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from model_bakery import baker

from accounts.invitations import (
    InvitationAlreadyUsed,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    create_invitation,
    invitation_for_token,
    redeem_invitation,
    revoke_invitation,
)
from accounts.models import Invitation, Membership, Role

# 2026-06-15 is arbitrary; what matters is that the TTL boundary tests below
# compare against one fixed instant rather than two reads of the real clock.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def invitee(db):
    return baker.make("core.CustomUser", username="convidada", email="convidada@example.com")


@pytest.mark.django_db
class TestCreateInvitation:
    def test_it_returns_the_row_and_a_raw_token(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="nova@example.com"
        )
        assert isinstance(invitation, Invitation)
        assert isinstance(raw, str)

    def test_the_raw_token_is_not_stored(self, household, user):
        _, raw = create_invitation(household=household, invited_by=user, email="n@example.com")
        assert not Invitation.objects.filter(token_hash=raw).exists()

    def test_the_stored_value_is_the_sha256_of_the_raw_token(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.token_hash == hashlib.sha256(raw.encode()).hexdigest()

    def test_the_token_has_enough_entropy_to_be_unguessable(self, household, user):
        """S05-3: 'invitation tokens are not guessable'. 32 bytes urlsafe-encoded
        is >= 43 characters; anything shorter is a brute-force target."""
        _, raw = create_invitation(household=household, invited_by=user, email="n@example.com")
        assert len(raw) >= 43

    def test_two_invitations_never_share_a_token(self, household, user):
        _, first = create_invitation(household=household, invited_by=user, email="a@example.com")
        _, second = create_invitation(household=household, invited_by=user, email="b@example.com")
        assert first != second

    def test_it_records_the_inviter_and_the_household(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.household == household
        assert invitation.created_by == user

    def test_the_default_role_is_member(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.role == Role.MEMBER

    def test_the_ttl_is_seven_days_from_the_injected_clock(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com", now=FROZEN_NOW
        )
        assert invitation.expires_at == FROZEN_NOW + timedelta(days=7)


@pytest.mark.django_db
class TestLookup:
    def test_a_valid_raw_token_finds_its_invitation(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation_for_token(raw) == invitation

    def test_an_unknown_token_finds_nothing(self):
        assert invitation_for_token("nao-existe") is None

    def test_an_empty_token_finds_nothing(self):
        assert invitation_for_token("") is None


@pytest.mark.django_db
class TestRedeem:
    def test_redeeming_creates_a_membership_in_that_household(self, household, user, invitee):
        _, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        membership = redeem_invitation(raw, invitee)
        assert membership.household == household
        assert membership.user == invitee
        assert membership.role == Role.MEMBER

    def test_redeeming_marks_the_invitation_accepted(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        redeem_invitation(raw, invitee)
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None

    def test_a_token_is_single_use(self, household, user, invitee):
        """S05-3: 'invitation tokens are ... invalidated on use'."""
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        redeem_invitation(raw, invitee)

        other = baker.make("core.CustomUser", email="outra@example.com")
        with pytest.raises(InvitationAlreadyUsed):
            redeem_invitation(raw, other)

    def test_an_expired_token_is_refused(self, household, user, invitee):
        _, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email, now=FROZEN_NOW
        )
        with pytest.raises(InvitationExpired):
            redeem_invitation(raw, invitee, now=FROZEN_NOW + timedelta(days=8))

    def test_a_revoked_token_is_refused(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        revoke_invitation(invitation)
        with pytest.raises(InvitationRevoked):
            redeem_invitation(raw, invitee)

    def test_an_unknown_token_is_refused(self, invitee):
        with pytest.raises(InvitationNotFound):
            redeem_invitation("nao-existe", invitee)

    def test_redeeming_twice_by_the_same_user_does_not_duplicate_a_membership(
        self, household, user, invitee
    ):
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        redeem_invitation(raw, invitee)
        assert Membership.objects.filter(user=invitee, household=household).count() == 1

    def test_redeeming_is_atomic(self, household, user, invitee):
        """A failure after the membership insert must not leave the token spent
        with nobody in the household — nor the reverse."""
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        membership = redeem_invitation(raw, invitee)
        invitation = Invitation.objects.get(pk=membership.household.accounts_invitation.first().pk)
        assert invitation.accepted_at is not None
        assert Membership.objects.filter(user=invitee, household=household).exists()


@pytest.mark.django_db
class TestRevoke:
    def test_revoking_stamps_the_row(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        revoke_invitation(invitation, now=FROZEN_NOW)
        invitation.refresh_from_db()
        assert invitation.revoked_at == FROZEN_NOW

    def test_revoking_an_accepted_invitation_changes_nothing(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        redeem_invitation(raw, invitee)
        revoke_invitation(invitation)
        invitation.refresh_from_db()
        assert invitation.revoked_at is None
        assert Membership.objects.filter(user=invitee, household=household).exists()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invitations.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.invitations'`.

- [ ] **Step 3: Write the module**

Create `src/backend/accounts/invitations.py`:

```python
"""The invitation lifecycle. No HTTP, no templates, no request.

Kept pure so the four security properties S05-3 asks for — unguessable,
single-use, expiring, invalidated on use — are properties of *these
functions*, testable without a client. A property enforced in a view is a
property that one new view can quietly lose.

The raw token exists exactly once, as `create_invitation`'s second return
value, on its way into an email. Only its SHA-256 is stored, so a leaked
database backup contains nothing redeemable. SHA-256 without a salt or a work
factor is right here and would be wrong for a password: the input is 32 bytes
of `secrets` output, so there is no dictionary to attack and no low-entropy
guess to slow down.
"""

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Invitation, Membership, Role

#: 32 bytes -> 43 urlsafe characters. Well beyond guessing, still short enough
#: to survive an email client's line wrapping without being broken in half.
TOKEN_BYTES = 32
DEFAULT_TTL_DAYS = 7


class InvitationUnusable(Exception):
    """Base for every reason a token will not redeem."""


class InvitationNotFound(InvitationUnusable):
    pass


class InvitationExpired(InvitationUnusable):
    pass


class InvitationAlreadyUsed(InvitationUnusable):
    pass


class InvitationRevoked(InvitationUnusable):
    pass


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_invitation(
    *, household, invited_by, email, role=Role.MEMBER, now=None, ttl_days=DEFAULT_TTL_DAYS
) -> tuple[Invitation, str]:
    """Mint an invitation and return it alongside its raw token.

    The raw token is returned rather than stored: this call is the only moment
    it exists in the process, and the caller's only job with it is to put it in
    a link and forget it.
    """
    now = now or timezone.now()
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation.objects.create(
        household=household,
        created_by=invited_by,
        email=email,
        role=role,
        token_hash=_hash(raw_token),
        expires_at=now + timedelta(days=ttl_days),
    )
    return invitation, raw_token


def invitation_for_token(raw_token: str) -> Invitation | None:
    """The invitation a raw token refers to, valid or not, or ``None``.

    Deliberately unscoped: the redeemer is by definition not yet a member of
    the household, so a household-scoped read would return nothing. The token
    itself is the authorisation.
    """
    if not raw_token:
        return None
    return Invitation.objects.select_related("household").filter(
        token_hash=_hash(raw_token)
    ).first()


def redeem_invitation(raw_token: str, user, *, now=None) -> Membership:
    """Turn a token into a membership. Raises ``InvitationUnusable``.

    Atomic, and the row is locked for the duration: two taps on the same link
    from a flaky mobile connection must produce one membership and one spent
    token, not two of either.
    """
    now = now or timezone.now()
    with transaction.atomic():
        invitation = (
            Invitation.objects.select_for_update()
            .select_related("household")
            .filter(token_hash=_hash(raw_token))
            .first()
        )
        if invitation is None:
            raise InvitationNotFound
        if invitation.revoked_at is not None:
            raise InvitationRevoked
        if invitation.accepted_at is not None:
            raise InvitationAlreadyUsed
        if invitation.is_expired(now=now):
            raise InvitationExpired

        membership, _ = Membership.objects.get_or_create(
            user=user,
            household=invitation.household,
            defaults={"role": invitation.role},
        )
        invitation.accepted_at = now
        invitation.save(update_fields=["accepted_at"])
        return membership


def revoke_invitation(invitation: Invitation, *, now=None) -> None:
    """Withdraw a pending invitation. Accepted ones are left alone.

    Revoking an already-accepted invitation is a no-op rather than an error:
    the membership it produced is what matters now, and removing that person is
    a different operation with different consequences.
    """
    if invitation.accepted_at is not None:
        return
    invitation.revoked_at = now or timezone.now()
    invitation.save(update_fields=["revoked_at"])
```

- [ ] **Step 4: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invitations.py -v
```

Expected: PASS, 22 tests. `test_redeeming_is_atomic` uses the reverse accessor `household.accounts_invitation` — the name comes from `HouseholdOwnedModel`'s `related_name="%(app_label)s_%(class)s"`. If it does not resolve, print `[f.name for f in household._meta.related_objects]` and use the real name.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/invitations.py src/backend/accounts/tests/test_invitations.py
git commit -m "feat(accounts): invitation lifecycle — unguessable, single-use, expiring"
```

---

## Task 11: Who may invite, and who may remove

One definition of "owner", used by every view in Task 12 and Task 13. Without it the rule gets restated per view, and the fourth restatement is the one that gets it wrong.

**Files:**
- Create: `src/backend/accounts/permissions.py`
- Test: `src/backend/accounts/tests/test_permissions.py` (create)

**Interfaces:**
- Consumes: `accounts.models.Membership`, `Role`.
- Produces: `is_owner(user, household) -> bool`; `OwnerRequiredMixin` — a CBV mixin that 403s a non-owner, reading `request.household`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_permissions.py`:

```python
"""Two roles, one place that decides what each may do.

E04 chose exactly two roles on purpose: an owner may invite and remove, a
member may only edit the ledger. Anything finer-grained is a separate epic.
The value of this module is that the rule is written once — the fourth
restatement of it inside a view is the one that gets it wrong.
"""

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.views.generic import View
from model_bakery import baker

from accounts.models import Membership, Role
from accounts.permissions import OwnerRequiredMixin, is_owner


@pytest.mark.django_db
class TestIsOwner:
    def test_the_founder_of_a_household_is_its_owner(self, user, household):
        assert is_owner(user, household) is True

    def test_a_plain_member_is_not_an_owner(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        assert is_owner(member, household) is False

    def test_a_stranger_is_not_an_owner(self, household):
        stranger = baker.make("core.CustomUser", email="estranha@example.com")
        assert is_owner(stranger, household) is False

    def test_an_owner_of_another_household_is_not_an_owner_of_this_one(
        self, other_user, household
    ):
        assert is_owner(other_user, household) is False

    def test_none_is_never_an_owner(self, household):
        assert is_owner(None, household) is False

    def test_nobody_owns_a_missing_household(self, user):
        assert is_owner(user, None) is False


@pytest.mark.django_db
class TestOwnerRequiredMixin:
    class _View(OwnerRequiredMixin, View):
        def get(self, request, *args, **kwargs):
            from django.http import HttpResponse

            return HttpResponse("ok")

    def _request(self, user, household):
        request = RequestFactory().get("/")
        request.user = user
        request.household = household
        return request

    def test_an_owner_gets_through(self, user, household):
        response = self._View.as_view()(self._request(user, household))
        assert response.status_code == 200

    def test_a_member_is_refused(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        with pytest.raises(PermissionDenied):
            self._View.as_view()(self._request(member, household))

    def test_a_request_with_no_household_is_refused(self, user):
        with pytest.raises(PermissionDenied):
            self._View.as_view()(self._request(user, None))
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_permissions.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.permissions'`.

- [ ] **Step 3: Write the module**

Create `src/backend/accounts/permissions.py`:

```python
"""Which member may do what.

E04 settled on two roles deliberately: an owner may invite and remove people,
a member may only edit the ledger. That rule is written here once so the views
ask rather than restate it.
"""

from django.core.exceptions import PermissionDenied

from accounts.models import Membership, Role


def is_owner(user, household) -> bool:
    """True when ``user`` owns ``household``.

    Fails closed on every missing input: an unauthenticated user, an
    unresolved household, or a membership in some *other* household are all
    "no", and none of them raise. A permission check that raises on absent
    input becomes a 500 on the exact request that should have been a 403.
    """
    if user is None or household is None or not getattr(user, "is_authenticated", False):
        return False
    return Membership.objects.filter(
        user=user, household=household, role=Role.OWNER
    ).exists()


class OwnerRequiredMixin:
    """Refuse the request unless it comes from an owner of its own household.

    Reads ``request.household``, which ``accounts.middleware`` has already
    resolved and validated against the user's memberships — so this never has
    to re-derive the tenant, and cannot disagree with the rest of the request.

    Raises ``PermissionDenied`` rather than redirecting: the caller is signed
    in and simply may not do this, and bouncing them to a login page they are
    already past is the confusing answer.
    """

    def dispatch(self, request, *args, **kwargs):
        if not is_owner(getattr(request, "user", None), getattr(request, "household", None)):
            raise PermissionDenied("Somente o dono da casa pode fazer isso.")
        return super().dispatch(request, *args, **kwargs)
```

- [ ] **Step 4: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_permissions.py -v
```

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/permissions.py src/backend/accounts/tests/test_permissions.py
git commit -m "feat(accounts): one definition of who may invite and who may remove"
```

---

## Task 12: Sending and accepting an invitation

S05-3's first three bullets, including the invitee who has no account yet.

**Files:**
- Create: `src/backend/accounts/views.py`
- Create: `src/backend/accounts/urls.py`
- Create: `src/backend/accounts/emails.py`
- Modify: `src/backend/config/urls.py`
- Create: `src/backend/templates/accounts/invite_landing.html`
- Create: `src/backend/templates/accounts/invite_invalid.html`
- Create: `src/backend/templates/accounts/email/invitation_subject.txt`
- Create: `src/backend/templates/accounts/email/invitation_message.txt`
- Test: `src/backend/accounts/tests/test_invite_flow.py` (create)

**Interfaces:**
- Consumes: `accounts.invitations.*` (Task 10), `accounts.permissions.OwnerRequiredMixin` (Task 11).
- Produces: URL names `invite_accept` (`/casa/convite/<token>/`), `invite_create` (`/casa/convites/`), and `accounts.emails.send_invitation(invitation, raw_token, request)`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_invite_flow.py`:

```python
"""Owner invites, invitee joins, both see one ledger.

The epic's second observable assertion. The interesting case is the invitee
with no account: they arrive at a link, have to sign up, have to verify, and
must still land inside the right household afterwards — a round trip through
three redirects and an email client, which is exactly where a session-only
design loses the token.
"""

import re

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.invitations import create_invitation
from accounts.models import Membership, Role

PASSWORD = "senha-da-convidada-99"


def _link_from(message, fragment):
    urls = re.findall(r"https?://\S+", message.body)
    matches = [u for u in urls if fragment in u]
    assert matches, f"no {fragment!r} link in:\n{message.body}"
    return matches[0].split("testserver")[-1]


@pytest.mark.django_db
class TestOwnerSendsAnInvitation:
    def test_an_owner_can_invite_by_email(self, logged_client, household):
        response = logged_client.post(
            reverse("invite_create"), {"email": "parceira@example.com"}
        )
        assert response.status_code in (200, 302)
        assert household.accounts_invitation.filter(email="parceira@example.com").exists()

    def test_the_invitation_email_carries_a_link(self, logged_client):
        logged_client.post(reverse("invite_create"), {"email": "parceira@example.com"})
        assert len(mail.outbox) == 1
        assert "/casa/convite/" in mail.outbox[0].body

    def test_the_email_does_not_contain_the_stored_hash(self, logged_client, household):
        logged_client.post(reverse("invite_create"), {"email": "parceira@example.com"})
        invitation = household.accounts_invitation.get()
        assert invitation.token_hash not in mail.outbox[0].body

    def test_a_plain_member_may_not_invite(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        client = Client()
        client.force_login(member)
        response = client.post(reverse("invite_create"), {"email": "x@example.com"})
        assert response.status_code == 403


@pytest.mark.django_db
class TestAcceptingWithAnExistingAccount:
    def test_an_authenticated_invitee_joins_the_household(self, household, user):
        invitee = baker.make("core.CustomUser", email="ja-tem@example.com")
        _, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        client = Client()
        client.force_login(invitee)
        response = client.post(reverse("invite_accept", args=[raw]))
        assert response.status_code == 302
        assert Membership.objects.filter(user=invitee, household=household).exists()

    def test_an_anonymous_visitor_sees_the_household_name_and_a_way_in(
        self, household, user
    ):
        _, raw = create_invitation(
            household=household, invited_by=user, email="quem@example.com"
        )
        response = Client().get(reverse("invite_accept", args=[raw]))
        assert response.status_code == 200
        body = response.content.decode()
        assert household.name in body
        assert "/accounts/signup/" in body
        assert "/accounts/login/" in body

    def test_a_bad_token_says_so_without_a_traceback(self):
        response = Client().get(reverse("invite_accept", args=["nao-existe"]))
        assert response.status_code == 404

    def test_a_spent_token_is_refused_on_the_second_use(self, household, user):
        first = baker.make("core.CustomUser", email="primeira@example.com")
        second = baker.make("core.CustomUser", email="segunda@example.com")
        _, raw = create_invitation(household=household, invited_by=user, email=first.email)

        one = Client()
        one.force_login(first)
        one.post(reverse("invite_accept", args=[raw]))

        two = Client()
        two.force_login(second)
        two.post(reverse("invite_accept", args=[raw]))
        assert not Membership.objects.filter(user=second, household=household).exists()


@pytest.mark.django_db
class TestAcceptingWithoutAnAccount:
    def test_an_invitee_signs_up_then_lands_in_the_household(self, household, user):
        _, raw = create_invitation(
            household=household, invited_by=user, email="nova@example.com"
        )
        accept_path = reverse("invite_accept", args=[raw])

        client = Client()
        # 1. Lands on the invitation, is anonymous, follows "criar conta".
        assert client.get(accept_path).status_code == 200

        # 2. Signs up with the invited address. `next` carries the way back.
        mail.outbox.clear()
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {
                "email": "nova@example.com",
                "email2": "nova@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        # 3. Verifies. (Task 13 removes this step for invited addresses; until
        #    then the round trip has to work the long way.)
        if mail.outbox:
            client.post(_link_from(mail.outbox[0], "confirm"))

        client.post(reverse("account_login"), {"login": "nova@example.com", "password": PASSWORD})

        # 4. Back to the invitation, now signed in.
        client.post(accept_path)

        invitee = Membership.objects.filter(household=household).exclude(user=user).first()
        assert invitee is not None
        assert invitee.user.email == "nova@example.com"


@pytest.mark.django_db
class TestBothSeeOneLedger:
    def test_the_invitee_reads_the_inviters_entries(self, household, user):
        """The whole point of an invitation: E04's scoping does the rest."""
        baker.make(
            "finances.Entry", household=household, created_by=user, description="Feira"
        )
        invitee = baker.make("core.CustomUser", email="socia@example.com")
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)

        client = Client()
        client.force_login(invitee)
        client.post(reverse("invite_accept", args=[raw]))

        body = client.get("/entries/").content.decode()
        assert "Feira" in body
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invite_flow.py -v
```

Expected: FAIL — `NoReverseMatch: 'invite_create' is not a valid view function or pattern name`.

- [ ] **Step 3: Write the email sender**

Create `src/backend/accounts/emails.py`:

```python
"""Outbound mail for invitations.

Separate from `accounts.invitations` on purpose: that module is pure, and
keeping it that way is what lets the security properties be tested without a
mail backend. This module is the only place that knows a raw token becomes a
URL.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def send_invitation(invitation, raw_token: str, request=None) -> None:
    """Email the invitee their link.

    Takes the raw token as an argument rather than reading it off the row,
    because the row does not have it — only its hash is stored. This is the
    last point in the process where the raw token exists.
    """
    path = reverse("invite_accept", args=[raw_token])
    url = request.build_absolute_uri(path) if request is not None else path
    context = {
        "url": url,
        "household": invitation.household,
        "inviter": invitation.created_by,
        "expires_at": invitation.expires_at,
    }
    subject = render_to_string("accounts/email/invitation_subject.txt", context).strip()
    body = render_to_string("accounts/email/invitation_message.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [invitation.email])
```

- [ ] **Step 4: Write the email templates**

`src/backend/templates/accounts/email/invitation_subject.txt`:
```
Você foi convidado para a {{ household.name }} no Expense Tracker
```

`src/backend/templates/accounts/email/invitation_message.txt`:
```
{% autoescape off %}Olá,

{% if inviter %}{{ inviter.email }}{% else %}Alguém{% endif %} convidou você para acompanhar as contas da {{ household.name }} no Expense Tracker.

Aceite o convite aqui:

{{ url }}

O convite vale até {{ expires_at|date:"d/m/Y" }} e só pode ser usado uma vez. Se você não esperava este convite, ignore esta mensagem.

— Expense Tracker
{% endautoescape %}
```

- [ ] **Step 5: Write the views**

Create `src/backend/accounts/views.py`:

```python
"""Invitation and membership screens.

The accept view is deliberately reachable by an anonymous visitor: the invitee
may not have an account yet, and bouncing them to a login page loses the token
in the round trip through their email client. Instead the token stays in the
URL, and `?next=` carries it back through signup and verification.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from accounts.emails import send_invitation
from accounts.invitations import (
    InvitationUnusable,
    create_invitation,
    invitation_for_token,
    redeem_invitation,
)
from accounts.permissions import OwnerRequiredMixin


class InvitationCreateView(OwnerRequiredMixin, View):
    """An owner invites someone by email."""

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip()
        if not email:
            messages.error(request, "Informe um e-mail.")
            return HttpResponseRedirect(reverse("members"))

        invitation, raw_token = create_invitation(
            household=request.household, invited_by=request.user, email=email
        )
        send_invitation(invitation, raw_token, request)
        messages.success(request, f"Convite enviado para {email}.")
        return HttpResponseRedirect(reverse("members"))


class InvitationAcceptView(View):
    """The page an invitation link opens.

    GET is safe and idempotent — it only describes the invitation — because an
    email client or a link scanner will fetch it before a human sees it, and a
    scanner must not be able to spend the token. Redemption is the POST.
    """

    def get(self, request, token, *args, **kwargs):
        invitation = invitation_for_token(token)
        if invitation is None or not invitation.is_pending:
            return render(request, "accounts/invite_invalid.html", status=404)
        return render(
            request,
            "accounts/invite_landing.html",
            {"invitation": invitation, "token": token, "next": request.path},
        )

    def post(self, request, token, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied
        try:
            membership = redeem_invitation(token, request.user)
        except InvitationUnusable:
            return render(request, "accounts/invite_invalid.html", status=404)

        # Make the household they just joined the one they are looking at —
        # otherwise the middleware's oldest-membership fallback would leave
        # them staring at their own empty ledger and wondering what happened.
        from accounts.middleware import ACTIVE_HOUSEHOLD_SESSION_KEY

        request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] = str(membership.household.id)
        messages.success(request, f"Você agora faz parte da {membership.household.name}.")
        return HttpResponseRedirect("/")
```

Note: `Http404` is imported for Task 13's use and may be unused here — drop the import if ruff flags it.

- [ ] **Step 6: Wire the URLs**

Create `src/backend/accounts/urls.py`:

```python
from django.urls import path

from accounts.views import InvitationAcceptView, InvitationCreateView

urlpatterns = [
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
```

In `src/backend/config/urls.py`, before the catch-all `finances.urls` include:

```python
    path("casa/", include("accounts.urls")),
    path("", include("finances.urls")),
```

- [ ] **Step 7: Write the two templates**

`src/backend/templates/accounts/invite_landing.html` extends `base_public.html` when anonymous and shows: the household name in a heading, who invited them, and — if `user.is_authenticated` — a POST form to `{% url 'invite_accept' token %}` with an **Aceitar convite** button; if anonymous, two buttons, `Criar conta` linking to `{% url 'account_signup' %}?next={{ next|urlencode }}` and `Já tenho conta` linking to `{% url 'account_login' %}?next={{ next|urlencode }}`.

`src/backend/templates/accounts/invite_invalid.html` extends `base_public.html`: "Este convite não vale mais. Ele pode ter expirado, já ter sido usado ou ter sido cancelado. Peça um novo para quem convidou você." plus a link to `{% url 'account_login' %}`.

Run the daisyUI Blueprint chain for these two (new `workflowId`, e.g. `e05invite`, since this is a different cohesive surface): Setup Expert → Rules Enforcer → Component Syntax Expert (`card`, `btn`, `alert`, `divider`) → write → Quality Inspector with `auditIntent: "fix_changes"`.

- [ ] **Step 8: Rebuild the stylesheet and run the test**

```bash
uv run python src/backend/manage.py tailwind build --force
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invite_flow.py -v
```

Expected: PASS. `test_an_owner_can_invite_by_email` and friends reverse `members`, which Task 13 creates — until then, point the redirects at `/` and change them in Task 13, or write Task 13 first. Prefer writing Task 13's URL stub now so the redirects are honest.

- [ ] **Step 9: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/views.py src/backend/accounts/urls.py src/backend/accounts/emails.py \
        src/backend/config/urls.py src/backend/templates/accounts/ \
        src/backend/static/css/tailwind.css src/backend/accounts/tests/test_invite_flow.py
git commit -m "feat(accounts): send and accept household invitations"
```

---

## Task 13: An invited address is already proven — skip the verification round trip

Small, and it removes the ugliest part of Task 12's flow: an invitee who clicked a link sent *to their address* should not then be asked to prove they own that address.

**Files:**
- Create: `src/backend/accounts/adapters.py`
- Modify: `src/backend/config/settings.py` (`ACCOUNT_ADAPTER`)
- Modify: `src/backend/accounts/views.py` (stash the token on GET)
- Test: `src/backend/accounts/tests/test_invited_signup.py` (create)

**Interfaces:**
- Consumes: `accounts.invitations.invitation_for_token`.
- Produces: `accounts.adapters.AppAccountAdapter`, set as `ACCOUNT_ADAPTER`. Session key `accounts.views.PENDING_INVITE_SESSION_KEY = "pending_invitation_token"`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_invited_signup.py`:

```python
"""Clicking a link sent to an address proves you control that address.

Asking an invitee to then verify the same address is a round trip through an
email client for no security gain — and it is where the invite flow loses
people. The proof is narrow on purpose: only the address the invitation was
sent to, and only while the invitation is still pending.
"""

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.invitations import create_invitation
from accounts.models import Membership

PASSWORD = "senha-da-convidada-99"


@pytest.mark.django_db
class TestInvitedSignupSkipsVerification:
    def _signup_via_invitation(self, household, user, email, invited_email=None):
        _, raw = create_invitation(
            household=household, invited_by=user, email=invited_email or email
        )
        accept_path = reverse("invite_accept", args=[raw])
        client = Client()
        client.get(accept_path)  # stashes the token in the session
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {"email": email, "email2": email, "password1": PASSWORD, "password2": PASSWORD},
        )
        return client, accept_path

    def test_the_invited_address_is_verified_without_an_email(self, household, user):
        mail.outbox.clear()
        client, _ = self._signup_via_invitation(household, user, "nova@example.com")

        address = EmailAddress.objects.get(email="nova@example.com")
        assert address.verified is True
        assert "_auth_user_id" in client.session, "invited signup did not log in"

    def test_no_verification_email_is_sent_to_an_invited_address(self, household, user):
        mail.outbox.clear()
        self._signup_via_invitation(household, user, "nova@example.com")
        subjects = [m.subject for m in mail.outbox]
        assert not any("Confirme" in s for s in subjects), subjects

    def test_signing_up_with_a_different_address_still_verifies_normally(
        self, household, user
    ):
        """The proof covers the invited address only. Anything else is a
        stranger typing a stranger's address and must not be trusted."""
        mail.outbox.clear()
        client, _ = self._signup_via_invitation(
            household, user, email="outra@example.com", invited_email="convidada@example.com"
        )
        address = EmailAddress.objects.get(email="outra@example.com")
        assert address.verified is False
        assert "_auth_user_id" not in client.session

    def test_an_ordinary_signup_is_untouched(self):
        mail.outbox.clear()
        client = Client()
        client.post(
            reverse("account_signup"),
            {"email": "sozinha@example.com", "email2": "sozinha@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        assert EmailAddress.objects.get(email="sozinha@example.com").verified is False
        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestTheInviteeLandsInTheHousehold:
    def test_signup_then_accept_produces_the_membership(self, household, user):
        _, raw = create_invitation(
            household=household, invited_by=user, email="nova@example.com"
        )
        accept_path = reverse("invite_accept", args=[raw])
        client = Client()
        client.get(accept_path)
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {"email": "nova@example.com", "email2": "nova@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        client.post(accept_path)

        joined = Membership.objects.filter(household=household).exclude(user=user)
        assert joined.count() == 1
        assert joined.first().user.email == "nova@example.com"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invited_signup.py -v
```

Expected: FAIL — the address is unverified and no session is created, because `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` applies uniformly.

- [ ] **Step 3: Stash the token when the landing page is fetched**

In `src/backend/accounts/views.py`, add the constant and one line in `InvitationAcceptView.get`:

```python
#: Where the landing page leaves the token so signup can find it. The URL is
#: the primary carrier (`?next=`); this is the backup for the case that URL
#: cannot survive — a verification link opened later, a redirect chain that
#: drops the query string.
PENDING_INVITE_SESSION_KEY = "pending_invitation_token"
```

```python
    def get(self, request, token, *args, **kwargs):
        invitation = invitation_for_token(token)
        if invitation is None or not invitation.is_pending:
            return render(request, "accounts/invite_invalid.html", status=404)
        request.session[PENDING_INVITE_SESSION_KEY] = token
        return render(
            request,
            "accounts/invite_landing.html",
            {"invitation": invitation, "token": token, "next": request.path},
        )
```

- [ ] **Step 4: Write the adapter**

Create `src/backend/accounts/adapters.py`:

```python
"""Account adapter: the one place signup deviates from allauth's defaults.

Clicking a link that was emailed to an address is proof of control over that
address — the same proof allauth's own verification email establishes. So an
invitee who signs up with the invited address has already verified it, and
asking them to do it again is a round trip through an email client for no
security gain.

The exemption is narrow on purpose. It applies only to the address the
invitation was sent to, only while that invitation is still pending, and only
for the session that actually opened the invitation link. A signup with any
other address verifies the ordinary way.
"""

from allauth.account.adapter import DefaultAccountAdapter

from accounts.invitations import invitation_for_token


class AppAccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=commit)
        self._verify_if_invited(request, user)
        return user

    def _verify_if_invited(self, request, user):
        from allauth.account.models import EmailAddress

        from accounts.views import PENDING_INVITE_SESSION_KEY

        token = (request.session or {}).get(PENDING_INVITE_SESSION_KEY)
        if not token:
            return
        invitation = invitation_for_token(token)
        if invitation is None or not invitation.is_pending:
            return
        if invitation.email.lower() != (user.email or "").lower():
            return
        EmailAddress.objects.filter(user=user, email__iexact=user.email).update(verified=True)
```

- [ ] **Step 5: Point settings at it**

In `src/backend/config/settings.py`, replace the placeholder from Task 1:

```python
ACCOUNT_ADAPTER = "accounts.adapters.AppAccountAdapter"
```

- [ ] **Step 6: Run the test**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_invited_signup.py -v
```

Expected: PASS, 5 tests. If the verification email is still sent, `save_user` runs before allauth decides to send — in that case override `send_confirmation_mail` instead and return early under the same condition. Run both files together to be sure Task 12's flow still passes:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/ -v
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/adapters.py src/backend/accounts/views.py \
        src/backend/config/settings.py src/backend/accounts/tests/test_invited_signup.py
git commit -m "feat(accounts): an invited address is already proven — no second verification"
```

---

## Task 14: Revoking, removing, and the members page

S05-3's last two bullets, including the one the spec insists on asserting: **a removed member immediately loses access to that household's data.**

**Files:**
- Modify: `src/backend/accounts/views.py`
- Modify: `src/backend/accounts/urls.py`
- Create: `src/backend/templates/accounts/members.html`
- Create: `src/backend/templates/accounts/partials/_members_list.html`
- Test: `src/backend/accounts/tests/test_membership_removal.py` (create)

**Interfaces:**
- Consumes: `OwnerRequiredMixin`, `revoke_invitation`, `HouseholdScopedMixin`.
- Produces: URL names `members` (`/casa/membros/`), `invite_revoke` (`/casa/convites/<uuid:pk>/cancelar/`), `member_remove` (`/casa/membros/<uuid:pk>/remover/`).

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_membership_removal.py`:

```python
"""Revoking a pending invitation, and removing someone who already joined.

The second one is the assertion the epic singles out: removal has to take
effect on the *next request*, not at the next login. E04 put the scoping in
the middleware and the managers precisely so that deleting one row is enough —
this test is what proves that claim rather than assuming it.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.invitations import create_invitation
from accounts.models import Membership, Role


@pytest.fixture
def joined_member(household, user, db):
    """Someone who accepted an invitation and is looking at the ledger."""
    member = baker.make("core.CustomUser", email="socia@example.com")
    Membership.objects.create(user=member, household=household, role=Role.MEMBER)
    client = Client()
    client.force_login(member)
    return member, client


@pytest.mark.django_db
class TestRevokingAPendingInvitation:
    def test_an_owner_can_revoke(self, logged_client, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="desistiu@example.com"
        )
        response = logged_client.post(reverse("invite_revoke", args=[invitation.pk]))
        assert response.status_code in (200, 302)
        invitation.refresh_from_db()
        assert invitation.revoked_at is not None

    def test_a_revoked_token_no_longer_redeems(self, logged_client, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="desistiu@example.com"
        )
        logged_client.post(reverse("invite_revoke", args=[invitation.pk]))

        latecomer = baker.make("core.CustomUser", email="desistiu@example.com")
        client = Client()
        client.force_login(latecomer)
        client.post(reverse("invite_accept", args=[raw]))
        assert not Membership.objects.filter(user=latecomer, household=household).exists()

    def test_an_owner_of_another_household_cannot_revoke_this_ones_invitation(
        self, household, user, other_user, other_household
    ):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="alvo@example.com"
        )
        intruder = Client()
        intruder.force_login(other_user)
        response = intruder.post(reverse("invite_revoke", args=[invitation.pk]))
        assert response.status_code == 404
        invitation.refresh_from_db()
        assert invitation.revoked_at is None


@pytest.mark.django_db
class TestRemovingAMember:
    def test_an_owner_can_remove_a_member(self, logged_client, household, joined_member):
        member, _ = joined_member
        membership = Membership.objects.get(user=member, household=household)
        logged_client.post(reverse("member_remove", args=[membership.pk]))
        assert not Membership.objects.filter(pk=membership.pk).exists()

    def test_a_removed_member_loses_data_access_on_the_very_next_request(
        self, logged_client, household, user, joined_member
    ):
        """The epic's third observable assertion, stated as bluntly as it reads."""
        member, member_client = joined_member
        baker.make(
            "finances.Entry", household=household, created_by=user, description="Feira"
        )

        before = member_client.get("/entries/").content.decode()
        assert "Feira" in before, "the fixture never had access, so removal proves nothing"

        membership = Membership.objects.get(user=member, household=household)
        logged_client.post(reverse("member_remove", args=[membership.pk]))

        after = member_client.get("/entries/").content.decode()
        assert "Feira" not in after

    def test_a_member_may_not_remove_anyone(self, household, joined_member, user):
        member, member_client = joined_member
        owners = Membership.objects.get(user=user, household=household)
        response = member_client.post(reverse("member_remove", args=[owners.pk]))
        assert response.status_code == 403
        assert Membership.objects.filter(pk=owners.pk).exists()

    def test_the_last_owner_cannot_be_removed(self, logged_client, household, user):
        """E04's open question 3 and E13 own what *should* happen when the last
        owner leaves. Until they do, refusing is the answer that cannot corrupt
        a household."""
        membership = Membership.objects.get(user=user, household=household)
        response = logged_client.post(reverse("member_remove", args=[membership.pk]))
        assert response.status_code == 400
        assert Membership.objects.filter(pk=membership.pk).exists()

    def test_a_membership_in_another_household_is_invisible(
        self, logged_client, other_user, other_household
    ):
        foreign = Membership.objects.get(user=other_user, household=other_household)
        response = logged_client.post(reverse("member_remove", args=[foreign.pk]))
        assert response.status_code == 404
        assert Membership.objects.filter(pk=foreign.pk).exists()


@pytest.mark.django_db
class TestMembersPage:
    def test_it_lists_members_and_pending_invitations(
        self, logged_client, household, user, joined_member
    ):
        create_invitation(household=household, invited_by=user, email="pendente@example.com")
        body = logged_client.get(reverse("members")).content.decode()
        assert "socia@example.com" in body
        assert "pendente@example.com" in body

    def test_it_does_not_leak_another_households_members(
        self, logged_client, other_user, other_household
    ):
        body = logged_client.get(reverse("members")).content.decode()
        assert other_user.email not in body

    def test_a_member_sees_the_page_without_the_owner_controls(self, joined_member):
        _, member_client = joined_member
        body = member_client.get(reverse("members")).content.decode()
        assert "Convidar" not in body
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_membership_removal.py -v
```

Expected: FAIL — `NoReverseMatch` for `members`, `invite_revoke` and `member_remove`.

- [ ] **Step 3: Add the three views**

Append to `src/backend/accounts/views.py`:

```python
class MembersView(LoginRequiredMixin, TemplateView):
    """Who is in this household, and who has been invited.

    Visible to every member — knowing who can see the family's money is not a
    privilege. Only the owner gets the controls, and that is enforced in the
    views they post to, not by hiding the buttons.
    """

    template_name = "accounts/members.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        household = self.request.household
        context["household"] = household
        context["memberships"] = (
            Membership.objects.filter(household=household)
            .select_related("user")
            .order_by("created_at")
        )
        context["invitations"] = [
            invitation
            for invitation in Invitation.objects.for_request(self.request)
            if invitation.is_pending
        ]
        context["viewer_is_owner"] = is_owner(self.request.user, household)
        return context


class InvitationRevokeView(OwnerRequiredMixin, View):
    """Withdraw a pending invitation."""

    def post(self, request, pk, *args, **kwargs):
        # Scoped, not filtered by hand: an invitation belonging to another
        # household must be *invisible* (404), never merely refused (403) —
        # a 403 confirms the id exists.
        invitation = Invitation.objects.for_request(request).filter(pk=pk).first()
        if invitation is None:
            raise Http404
        revoke_invitation(invitation)
        messages.success(request, f"Convite para {invitation.email} cancelado.")
        return HttpResponseRedirect(reverse("members"))


class MemberRemoveView(OwnerRequiredMixin, View):
    """Remove someone from the household.

    Deleting the Membership is the entire mechanism. E04 resolves the active
    household from memberships on every request and every scoped queryset
    fails closed to `none()`, so access ends on the next request — no session
    to purge, no cache to bust.
    """

    def post(self, request, pk, *args, **kwargs):
        membership = (
            Membership.objects.filter(pk=pk, household=request.household)
            .select_related("user")
            .first()
        )
        if membership is None:
            raise Http404

        if membership.role == Role.OWNER:
            remaining_owners = (
                Membership.objects.filter(household=request.household, role=Role.OWNER)
                .exclude(pk=membership.pk)
                .count()
            )
            if remaining_owners == 0:
                # E04's open question 3 and E13 own the real semantics of a
                # household losing its last owner. Refusing is the only answer
                # here that cannot leave one orphaned.
                return HttpResponseBadRequest(
                    "A casa precisa de pelo menos um dono. Promova outra pessoa antes."
                )

        email = membership.user.email
        membership.delete()
        messages.success(request, f"{email} não faz mais parte da casa.")
        return HttpResponseRedirect(reverse("members"))
```

Add the imports this needs at the top of the file:

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
from django.views.generic import TemplateView

from accounts.invitations import revoke_invitation
from accounts.models import Invitation, Membership, Role
from accounts.permissions import OwnerRequiredMixin, is_owner
```

- [ ] **Step 4: Wire the URLs**

Replace `src/backend/accounts/urls.py`:

```python
from django.urls import path

from accounts.views import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationRevokeView,
    MemberRemoveView,
    MembersView,
)

urlpatterns = [
    path("membros/", MembersView.as_view(), name="members"),
    path("membros/<uuid:pk>/remover/", MemberRemoveView.as_view(), name="member_remove"),
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convites/<uuid:pk>/cancelar/", InvitationRevokeView.as_view(), name="invite_revoke"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
```

- [ ] **Step 5: Write the members page**

`templates/accounts/members.html` extends `base.html` (the logged-in shell, with the navbar). It shows:

- A heading `Quem vê as contas da {{ household.name }}`.
- A list of memberships: email, a `badge` reading `Dono` or `Membro`, and — when `viewer_is_owner` and the row is not the viewer — a **Remover** button posting to `{% url 'member_remove' membership.pk %}`.
- A pending-invitations list: email, expiry date, and a **Cancelar** button posting to `{% url 'invite_revoke' invitation.pk %}`.
- When `viewer_is_owner`, an invite form posting to `{% url 'invite_create' %}` with one email input and a **Convidar** button. The string `Convidar` must appear *only* inside this block — `test_a_member_sees_the_page_without_the_owner_controls` asserts on exactly that.

Every destructive button is a `<form method="post">`, never a link: a GET that removes someone is a link an email scanner can follow. Add a `daisyui` modal or an `onsubmit` confirm on **Remover** so it is not a single mis-tap.

Run the Blueprint chain with `workflowId: "e05members"` — Setup Expert → Rules Enforcer → Component Syntax Expert (`table`, `badge`, `btn`, `modal`, `form-control`, `input`, `alert`) → write → Quality Inspector `fix_changes`.

- [ ] **Step 6: Add a way to reach the page**

The members page nobody can find is not a feature. Add a link to `/casa/membros/` in the navbar or side drawer, next to the theme toggle and logout in `templates/base.html` (or the partial that holds them — `grep -rn "Alternar tema" src/backend/templates/` to find it). Label it `Membros da casa`.

- [ ] **Step 7: Rebuild the stylesheet and run the test**

```bash
uv run python src/backend/manage.py tailwind build --force
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_membership_removal.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
```

Expected: PASS. Watch `test_a_removed_member_loses_data_access_on_the_very_next_request` in particular — its first assertion (`"Feira" in before`) exists so that a fixture which never had access cannot make the test pass vacuously.

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/accounts/ src/backend/templates/ src/backend/static/css/tailwind.css
git commit -m "feat(accounts): revoke invitations, remove members, and a page that shows both"
```

---

## Task 15: Move admin off the open internet

S05-5's first, third and fifth bullets. `/admin/` currently answers on a public Cloud Run service with every model registered, including raw chat.

**Files:**
- Create: `src/backend/core/admin_gate.py`
- Modify: `src/backend/core/models.py` (`AdminAccessLog`)
- Create: `src/backend/core/migrations/0004_admin_access_log.py`
- Modify: `src/backend/config/settings.py`, `src/backend/config/urls.py`
- Modify: `src/backend/core/admin.py`, `src/backend/assistant/admin.py`
- Modify: `src/backend/templates/sw.js`
- Modify: `src/backend/core/tests/test_admin.py`
- Test: `src/backend/core/tests/test_admin_isolation.py` (create)

**Interfaces:**
- Consumes: `core.security.client_ip`.
- Produces: setting `ADMIN_URL_PATH`; `core.admin_gate.admin_staff_only_middleware`; `core.models.AdminAccessLog(actor, path, method, ip, created_at)`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_admin_isolation.py`:

```python
"""Admin holds every household's money and every user's raw chat.

Three properties, and the first one is why the other two matter: the service
is deployed --allow-unauthenticated because the product needs to be, so
"admin is on the internet" is not a deployment mistake to fix later, it is the
default this middleware exists to override.

404 rather than 403 throughout. A 403 confirms the path is admin; a 404 says
nothing, and an admin path nobody can confirm is one nobody can enumerate.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from core.models import AdminAccessLog


def _admin_url(suffix=""):
    return "/" + settings.ADMIN_URL_PATH.lstrip("/") + suffix


@pytest.fixture
def staff(db):
    return baker.make(
        "core.CustomUser", email="operador@example.com", is_staff=True, is_superuser=True
    )


@pytest.mark.django_db
class TestTheOldPathIsGone:
    def test_slash_admin_no_longer_routes(self):
        """The path every scanner tries first must not be the real one."""
        assert settings.ADMIN_URL_PATH != "admin/"
        assert Client().get("/admin/").status_code == 404

    def test_slash_admin_login_no_longer_routes(self):
        assert Client().get("/admin/login/").status_code == 404


@pytest.mark.django_db
class TestOnlyStaffReachAdmin:
    def test_an_anonymous_request_gets_404_not_a_login_page(self):
        """The epic's sixth observable assertion, anonymous half."""
        assert Client().get(_admin_url()).status_code == 404

    def test_an_authenticated_non_staff_user_gets_404(self, user):
        """The epic's sixth observable assertion, verbatim."""
        client = Client()
        client.force_login(user)
        assert client.get(_admin_url()).status_code == 404

    def test_a_non_staff_user_cannot_reach_a_model_page_either(self, user):
        client = Client()
        client.force_login(user)
        assert client.get(_admin_url("core/customuser/")).status_code == 404

    def test_staff_with_a_second_factor_get_in(self, staff):
        from allauth.mfa.models import Authenticator

        Authenticator.objects.create(
            user=staff, type=Authenticator.Type.TOTP, data={"secret": "x" * 32}
        )
        client = Client()
        client.force_login(staff)
        assert client.get(_admin_url()).status_code == 200


@pytest.mark.django_db
class TestStaffWithoutASecondFactor:
    def test_they_are_sent_to_enrol_rather_than_stonewalled(self, staff):
        """404ing the only operator out of their own admin, with no
        explanation, is how this feature gets reverted at 2am."""
        client = Client()
        client.force_login(staff)
        response = client.get(_admin_url())
        assert response.status_code == 302
        assert "2fa" in response["Location"] or "totp" in response["Location"]


@pytest.mark.django_db
class TestStaffAccessIsLogged:
    def test_a_staff_request_writes_a_row_with_actor_target_and_time(self, staff):
        from allauth.mfa.models import Authenticator

        Authenticator.objects.create(
            user=staff, type=Authenticator.Type.TOTP, data={"secret": "x" * 32}
        )
        client = Client()
        client.force_login(staff)
        client.get(_admin_url("core/customuser/"))

        entry = AdminAccessLog.objects.latest("created_at")
        assert entry.actor == staff
        assert "core/customuser" in entry.path
        assert entry.created_at is not None

    def test_a_refused_request_is_not_logged_as_access(self, user):
        client = Client()
        client.force_login(user)
        client.get(_admin_url())
        assert not AdminAccessLog.objects.filter(actor=user).exists()


@pytest.mark.django_db
class TestChatIsNotInAdmin:
    def test_chatmessage_is_not_registered(self):
        """S05-5: raw conversation content is not an admin list column."""
        from django.contrib import admin

        from assistant.models import ChatMessage

        assert ChatMessage not in admin.site._registry
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_admin_isolation.py -v
```

Expected: FAIL — `settings.ADMIN_URL_PATH` does not exist, `/admin/` returns 302 to a login page, and `ChatMessage` is registered.

- [ ] **Step 3: Add the setting**

In `src/backend/config/settings.py`, near the other security settings:

```python
# --- Staff isolation (E05 S05-5) ----------------------------------------
# Admin holds every household's financial records and every user's raw chat,
# on a service deployed --allow-unauthenticated because the product needs to
# be. Two independent controls: an unguessable path so it is not enumerable,
# and `core.admin_gate` so guessing it correctly still yields a 404 to anyone
# who is not staff with a second factor.
#
# The path is an env var, never a literal in a committed file. The dev default
# is deliberately not "admin/" so that a missing env var is loud in tests
# rather than silently restoring the old front door.
ADMIN_URL_PATH = os.environ.get("ADMIN_URL_PATH", "gestao-dev/").strip("/") + "/"
```

- [ ] **Step 4: Add the audit model**

Append to `src/backend/core/models.py`:

```python
class AdminAccessLog(models.Model):
    """One row per staff request that admin actually answered.

    S05-5: 'staff access to customer data is logged with actor, target, and
    timestamp'. Distinct from `LoginAttempt`, which is a lockout counter that
    gets deleted on success — these rows are kept.

    Refused requests are deliberately absent: a 404 for a non-staff user means
    nothing was disclosed, and logging those would drown the rows that record
    a human actually reading someone's money.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    path = models.CharField(max_length=500)
    method = models.CharField(max_length=10)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "acesso administrativo"
        verbose_name_plural = "acessos administrativos"
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="adminlog_actor_recent_idx"),
        ]

    def __str__(self):
        return f"{self.actor} {self.method} {self.path} @ {self.created_at:%Y-%m-%d %H:%M}"
```

Add `from django.conf import settings` to the imports at the top of the file.

- [ ] **Step 5: Write the gate**

Create `src/backend/core/admin_gate.py`:

```python
"""The only thing standing between the open internet and every household's money.

404 rather than 403, everywhere. A 403 tells an unauthenticated scanner that
the path it guessed is the admin; a 404 tells it nothing, which is the whole
value of moving the path in the first place. The two controls are independent
on purpose — guessing the path correctly still gets you nothing, and being
staff on the wrong path still gets you nothing.
"""

from django.conf import settings
from django.http import Http404, HttpResponseRedirect

from core.security import client_ip


def _admin_prefix() -> str:
    return "/" + settings.ADMIN_URL_PATH.lstrip("/")


def _has_second_factor(user) -> bool:
    from allauth.mfa.utils import is_mfa_enabled

    return is_mfa_enabled(user)


def admin_staff_only_middleware(get_response):
    """Refuse admin to everyone but staff carrying a second factor.

    Must run after `AuthenticationMiddleware` — it reads `request.user`.
    """

    def middleware(request):
        prefix = _admin_prefix()
        if not request.path.startswith(prefix):
            return get_response(request)

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_staff:
            # Anonymous and ordinary users are told the path does not exist,
            # which — as far as they are concerned — is true.
            raise Http404

        if not _has_second_factor(user):
            # Staff, but unarmed. 404ing here would lock the only operator out
            # of their own admin with no explanation, which is how this gets
            # reverted at 2am. Send them to enrol instead.
            from django.urls import reverse

            return HttpResponseRedirect(reverse("mfa_activate_totp"))

        from core.models import AdminAccessLog

        AdminAccessLog.objects.create(
            actor=user,
            path=request.path[:500],
            method=request.method,
            ip=client_ip(request),
        )
        return get_response(request)

    return middleware
```

Confirm the MFA URL name for the installed version before trusting `mfa_activate_totp`:

```bash
uv run python src/backend/manage.py show_urls 2>/dev/null | grep -i mfa || \
  uv run python -c "
from django.urls import get_resolver
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
print([k for k in get_resolver().reverse_dict.keys() if isinstance(k,str) and 'mfa' in k])"
```

- [ ] **Step 6: Register the middleware and move the URL**

In `src/backend/config/settings.py`, `MIDDLEWARE`, after `active_household_middleware`:

```python
    "accounts.middleware.active_household_middleware",
    # Reads request.user, so it must follow AuthenticationMiddleware.
    "core.admin_gate.admin_staff_only_middleware",
    "django.contrib.messages.middleware.MessageMiddleware",
```

In `src/backend/config/urls.py`, replace the admin line:

```python
from django.conf import settings

    # Not "admin/". The path is an environment variable and the middleware
    # above 404s anyone who is not staff with a second factor — two
    # independent controls, because this service is public by necessity.
    path(settings.ADMIN_URL_PATH, admin.site.urls),
```

- [ ] **Step 7: Take chat out of admin, put the log in**

Replace `src/backend/assistant/admin.py`'s `ChatMessageAdmin` block — delete the class and the `ChatMessage` import entirely, leaving `MemoryRuleAdmin`. Add a comment where it was:

```python
# ChatMessage is deliberately not registered (E05 S05-5). It holds every
# user's raw conversation with the assistant — receipts, salaries, arguments
# about money — and an admin list view of it is a standing invitation to read
# them. E17 owns the deliberate, consented, logged way to look at a customer's
# account.
```

In `src/backend/core/admin.py`, register the log read-only:

```python
@admin.register(AdminAccessLog)
class AdminAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "method", "path", "ip")
    list_filter = ("method", "created_at")
    search_fields = ("path", "actor__email")
    readonly_fields = ("actor", "path", "method", "ip", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        """An audit log a staff member can delete is not an audit log."""
        return False
```

- [ ] **Step 8: Follow the path in the service worker**

`templates/sw.js` hardcodes `/admin/` in its bypass list. Make it follow the setting:

```javascript
  if (p.startsWith('/api/') || p.startsWith('/{{ admin_url_path }}') || p === '/healthz/') return;
```

`ServiceWorkerView` is a `TemplateView`; add the value to its context in `core/views.py`:

```python
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admin_url_path"] = settings.ADMIN_URL_PATH
        return context
```

- [ ] **Step 9: Update the existing admin test**

`core/tests/test_admin.py` hardcodes `/admin/core/customuser/` and will now 404. Rewrite it to build the URL from `settings.ADMIN_URL_PATH` and to give its superuser a TOTP authenticator, matching `test_admin_isolation.py`'s `staff` fixture.

- [ ] **Step 10: Migrate and run**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations core --name admin_access_log
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_admin_isolation.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
```

Expected: PASS. `Authenticator.objects.create(...)` in the test may need a different `data` shape for your allauth version — if it raises, create one through `allauth.mfa.totp.internal.auth.TOTP.activate` or read `allauth/mfa/models.py` for the required keys.

- [ ] **Step 11: Write the runbook section**

Add `## Reaching the admin` to `docs/runbook.md`, covering: the `ADMIN_URL_PATH` env var and how to set it on Cloud Run; that `/admin/` is gone and this is deliberate; enrolling TOTP at `/accounts/2fa/totp/activate/` **before** the first admin visit; where recovery codes are and why they must be saved somewhere that is not the phone holding the TOTP; and the failure mode — a redirect loop to the MFA page means the authenticator was never activated, not that the gate is broken.

```bash
gcloud run services update expense-tracker --region=<region> \
  --project=expense-tracker-482807 \
  --set-env-vars=ADMIN_URL_PATH=gestao-4f9c2a/
```

- [ ] **Step 12: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add -A
git commit -m "feat(core): admin moves off /admin/, behind a staff+2FA gate that logs every visit"
```

---

## Task 16: Definition of Done

**Files:**
- Modify: `docs/backlog/E05-identity-invitations-admin-isolation.md` (tick the boxes)
- Modify: `docs/runbook.md` (final pass)

- [ ] **Step 1: Run the DoD commands exactly as the spec writes them**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com ADMIN_URL_PATH=gestao-test/ uv run python src/backend/manage.py check --deploy
```

Expected: all three clean. Paste the real output into the PR body — not a summary of it.

- [ ] **Step 2: Prove the suite is time-stable**

New code has expiry logic in it, which is exactly what `TEST_CLOCK_SHIFT` exists to catch:

```bash
TEST_CLOCK_SHIFT=+1m POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date" 2>&1 | tail -3
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date" 2>&1 | tail -3
```

Expected: the same result under both. A failure here is a real bug in the invitation TTL, not a flaky test.

- [ ] **Step 3: Run `/security-review`**

Mandatory per the spec's skill pipeline — authentication is where misconfigured flows leak. The spec's bar: **no authentication finding**. Fix what it finds, rerun, and record the clean run.

- [ ] **Step 4: The two manual verifications**

Neither can be automated, and neither may be marked done on the strength of a passing test:

1. **A real verification email arrives in a Gmail inbox, not spam.** Requires Task 5's DNS work to be finished. Check the `Authentication-Results` header shows `spf=pass` and `dkim=pass`, and paste it into the runbook.
2. **The Android TWA login flow works against the deployed revision.** The TWA points at `/login/`, which is now a 301 to `/accounts/login/`; confirm the redirect survives the TWA's navigation and that the session cookie is set (`SESSION_COOKIE_SAMESITE = "Lax"` and same-origin, so it should — confirm, do not assume).

- [ ] **Step 5: Tick the spec**

Update the Definition of Done checklist in `docs/backlog/E05-identity-invitations-admin-isolation.md`, ticking only what actually passed. If something did not, say so in the file rather than leaving the box ambiguous — this repo's E04 commits set that precedent (`docs(backlog): tick what E04 phase 3 discharged, and say what phase 4 still owes`).

Also record what this epic decided that the spec left open, so the next reader is not re-deciding: the four Open Questions, and the two follow-ons it deliberately did not solve — the last-owner-leaves semantics (E13) and support impersonation (E17).

- [ ] **Step 6: Request review, then finish the branch**

Use `superpowers:requesting-code-review`, then `superpowers:finishing-a-development-branch`. Do not force-push, and give a heads-up before applying the `core` migrations to production — `0003_customuser_email_unique` adds a UNIQUE constraint to a live table.

- [ ] **Step 7: Commit**

```bash
git add docs/backlog/E05-identity-invitations-admin-isolation.md docs/runbook.md
git commit -m "docs(backlog): E05 done — what shipped, what was decided, what E13 and E17 still owe"
```

---

## Self-review notes

**Spec coverage.** S05-1 → Tasks 1, 2, 3, 7, 8 (password validators asserted in Task 8). S05-2 → Task 5 + Task 16 Step 4. S05-3 → Tasks 9, 10, 11, 12, 13, 14. S05-4 → Tasks 4 and 6; note that E01 had already moved `LOGIN_URL`, so the surviving content is the lockout proof (Task 4) and the TWA-safe redirect (Task 6). S05-5 → Task 15. All nine of the spec's observable assertions have a named test: lifecycle (Task 8), invite-and-share-a-ledger (Task 12 `TestBothSeeOneLedger`), removal (Task 14), single-use/expiry (Task 10), throttling at the new URL (Task 4), non-staff cannot reach admin (Task 15), the two manual checks and `/security-review` (Task 16).

**Deliberately not built.** Social login, support impersonation (E17), post-login onboarding (E11), account deletion (E13), billing (E15) — all listed out of scope by the spec. Last-owner-leaves is refused rather than solved, and Task 14 says why in a comment and in the test name.

**Two things to watch during execution.** Task 4 is the one that fails silently if skipped or half-done — allauth authenticating through a lockout-free backend would leave every existing lockout test green. And Task 2's migration is the only irreversible-on-production step; it has its own rehearsal in Step 7.
