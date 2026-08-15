# E11 · Onboarding & activation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger who signs up reaches the activation moment — a photographed receipt confirmed into their ledger — unaided, and that moment is emitted as a measurable server-side event.

**Architecture:** A new `core.ProductEvent` table is the single, database-derived event log (E14 extends it; no third-party vendor). Signup seeds a starter catalogue so a brand-new household can record something immediately. A three-step HTMX guided setup, resumable from `accounts.OnboardingState`, ends by opening the chat with the camera rather than by dropping the user on an empty dashboard. Empty states across every surface point at the wedge.

**Tech Stack:** Django 5 + HTMX + Alpine (server-rendered flows), React 18 islands (dashboard cards, chat widget), DaisyUI/Tailwind, PostgreSQL, pytest + model_bakery + time-machine.

**Spec:** [`docs/backlog/E11-onboarding-and-activation.md`](../../backlog/E11-onboarding-and-activation.md)

## Decisions taken before this plan (the epic's Open questions)

Recorded here so no task re-litigates them.

1. **What is the activation event?** → **The household's first confirmed receipt.**
   Emitted as `activated` from `assistant.agents.tools.commit_receipt`, the one
   place where a photograph becomes real `Entry` rows. A second, lighter
   once-per-household event `first_ai_entry` is emitted from *any* assistant
   write path (chat capture as well as a receipt), so E14 can measure
   wedge adoption without reopening these files.
2. **What is the default category set?** → **A trimmed 12 + the 2 system
   categories**, taken from the production-derived list in
   `finances/management/commands/seed_data.py` rather than invented. The full
   26-category list stays where it is — it is one household's real catalogue,
   not a stranger's starting point. Budget ceilings seed at `0`: a ceiling
   copied from the operator's household is a made-up number in someone else's
   ledger.
3. **Is email verification required before onboarding starts?** → **Yes,
   already decided in E05 open question 3** (`ACCOUNT_EMAIL_VERIFICATION =
   "mandatory"`, `config/settings.py:278`). Onboarding begins after
   verification; nothing in this epic changes that.
4. **How is the closing day explained?** → **One sentence plus a worked
   example rendered live from the number the user typed** (Task 6), not a
   paragraph.

Additionally: `PROJECTION_ORIGIN_MONTH` becomes **per household** (Task 10). A
global "nothing before Nov 2025 counts" is migration noise from one household
and is nonsense in a stranger's projection.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7. Every task's requirements implicitly include these.

1. **TDD.** Test first, always.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number**. No arithmetic moves into a prompt.
4. **Tenant scoping is centralized.** No `filter(user=...)` on a domain model. Use the household-scoped manager (`Model.objects.for_household(...)` / `.for_request(request)`).
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
8. **pt-BR in the product UI, English in code, comments, and docs.**
9. **Migrations are reversible** or the task states explicitly why not.
10. **No time-bomb tests.** Any date-sensitive test freezes the clock — see `docs/testing-conventions.md`.

Plus, for this epic specifically:

11. **No user content in `ProductEvent.metadata`.** Same PII discipline as E06's Sentry scrubber (`core/observability.py`): counts, ids, enum values. Never a description, a store name, or a chat message.
12. **Local test DB is the pgvector container on port 5433.** Every pytest invocation below is prefixed `POSTGRES_PORT=5433`.

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/core/models.py` (modify) | `ProductEvent` — the one product-event row shape |
| `src/backend/core/events.py` (create) | `EventName`, `emit`, `emit_once` — the only way anything writes a `ProductEvent` |
| `src/backend/core/management/commands/activation_report.py` (create) | Operator report: activation count, time-to-activation percentiles, funnel drop-off |
| `src/backend/assistant/starter_rules.py` (create) | `DEFAULT_RULES` — moved out of the management command so both seeders share one list |
| `src/backend/accounts/starter_data.py` (create) | `STARTER_CATEGORIES`, `STARTER_PAYMENT_METHODS`, `seed_starter_data()` |
| `src/backend/accounts/management/commands/seed_starter_data.py` (create) | Operator entry point for the same seeding |
| `src/backend/accounts/models.py` (modify) | `OnboardingStep`, `OnboardingState`, `Household.projection_origin_month` |
| `src/backend/accounts/onboarding.py` (create) | The three guided-setup views + skip |
| `src/backend/accounts/middleware.py` (modify) | `onboarding_redirect_middleware` |
| `src/backend/templates/onboarding/*.html` (create) | The guided-setup screens |
| `src/backend/frontend/src/chat.ts` (create) | `openChat()` — the one way any surface opens the chat widget |
| `src/backend/frontend/src/components/EmptyState.tsx` (modify) | Gains an `onAction` button alongside `actionHref` |
| `src/backend/frontend/src/cards/ChatWidget.tsx` (modify) | First-run invitation + `open-chat` listener |
| `src/backend/finances/services/projection.py` (modify) | `projection_origin(household)` |
| `docs/architecture/activation-event.md` (create) | The activation event's written definition — E14 reads this |
| `docs/runbook.md` (modify) | "Onboarding & activation" operator section |

---

## Task 1: The product-event log

**Files:**
- Create: `src/backend/core/events.py`
- Modify: `src/backend/core/models.py` (append after `TaskRun`)
- Create: `src/backend/core/migrations/0007_productevent.py` (generated)
- Test: `src/backend/core/tests/test_product_events.py`

**Interfaces:**
- Consumes: `accounts.models.HouseholdOwnedModel` (existing abstract base, gives the `household` FK and `HouseholdScopedManager`).
- Produces:
  - `core.models.ProductEvent` — fields `id: UUID`, `household: FK`, `name: str`, `user: FK|None`, `once: bool`, `metadata: dict`, `created_at: datetime`
  - `core.events.EventName` — `TextChoices` with `SIGNUP`, `HOUSEHOLD_SEEDED`, `ONBOARDING_STEP`, `ONBOARDING_DONE`, `FIRST_AI_ENTRY`, `ACTIVATED`
  - `core.events.emit(name: str, *, household, user=None, metadata: dict | None = None) -> ProductEvent | None`
  - `core.events.emit_once(name: str, *, household, user=None, metadata: dict | None = None) -> ProductEvent | None` — returns the row **only when it was newly created**, `None` when the household already had one (or when `household is None`)

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_product_events.py`:

```python
"""The product-event log: one row shape, one writer, and 'first' as a database fact."""

import pytest
from django.db import IntegrityError

from core.events import EventName, emit, emit_once
from core.models import ProductEvent


@pytest.mark.django_db
class TestEmit:
    def test_emit_writes_a_row_scoped_to_the_household(self, household, user):
        event = emit(EventName.ONBOARDING_STEP, household=household, user=user,
                     metadata={"step": "income", "action": "done"})

        assert event.household == household
        assert event.user == user
        assert event.name == EventName.ONBOARDING_STEP
        assert event.metadata == {"step": "income", "action": "done"}
        assert event.once is False

    def test_emit_is_repeatable(self, household, user):
        emit(EventName.ONBOARDING_STEP, household=household, user=user)
        emit(EventName.ONBOARDING_STEP, household=household, user=user)

        assert ProductEvent.objects.for_household(household).count() == 2

    def test_emit_without_a_household_is_a_no_op(self, user):
        """Fail closed like every scoped queryset: no tenant, no row, no crash."""
        assert emit(EventName.ACTIVATED, household=None, user=user) is None
        assert ProductEvent.objects.count() == 0


@pytest.mark.django_db
class TestEmitOnce:
    def test_first_call_returns_the_new_row(self, household, user):
        event = emit_once(EventName.ACTIVATED, household=household, user=user)

        assert event is not None
        assert event.once is True

    def test_second_call_returns_none_and_writes_nothing(self, household, user):
        emit_once(EventName.ACTIVATED, household=household, user=user)

        assert emit_once(EventName.ACTIVATED, household=household, user=user) is None
        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.ACTIVATED
        ).count() == 1

    def test_each_household_activates_independently(self, household, other_household, user):
        assert emit_once(EventName.ACTIVATED, household=household, user=user) is not None
        assert emit_once(EventName.ACTIVATED, household=other_household, user=user) is not None

    def test_the_database_refuses_a_duplicate_once_event(self, household, user):
        """Not merely a convention: two concurrent commits must not both 'activate'."""
        emit_once(EventName.ACTIVATED, household=household, user=user)

        with pytest.raises(IntegrityError):
            ProductEvent.objects.create(
                household=household, name=EventName.ACTIVATED, once=True
            )


@pytest.mark.django_db
class TestIsolation:
    def test_one_household_cannot_see_another_households_events(
        self, household, other_household, user
    ):
        emit(EventName.ACTIVATED, household=other_household, user=user)

        assert ProductEvent.objects.for_household(household).count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_product_events.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.events'`

- [ ] **Step 3: Add the model**

Append to `src/backend/core/models.py` (and add `from accounts.models import HouseholdOwnedModel` to its imports — `accounts.models` imports only `core.tiers`, never `core.models`, so there is no cycle):

```python
class ProductEvent(HouseholdOwnedModel):
    """One thing a person did that the product wants to count.

    Database-derived rather than shipped to an analytics vendor (E14 open
    question 1): it is cheaper, the numbers can be recomputed from history when
    a definition changes, and it keeps one more sub-processor off E13's
    inventory.

    ``metadata`` never carries user content — no descriptions, no store names,
    no chat text. Counts, ids and enum values only. Same discipline as
    ``core.observability.scrub_event``, and for the same reason: this table is
    read by operators and exported by E13.

    ``once`` marks the events that may happen at most once per household —
    activation above all. The partial unique constraint makes "the first
    receipt" a database fact rather than a convention, so two concurrent
    commits cannot both claim it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    once = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de produto"
        verbose_name_plural = "eventos de produto"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"],
                condition=models.Q(once=True),
                name="one_once_event_per_household",
            )
        ]
        indexes = [
            models.Index(fields=["name", "-created_at"], name="event_name_recent_idx"),
            models.Index(fields=["household", "-created_at"], name="event_hh_recent_idx"),
        ]

    def __str__(self):
        return f"{self.name} @ {self.household} ({self.created_at:%Y-%m-%d %H:%M})"
```

- [ ] **Step 4: Add the emitter**

Create `src/backend/core/events.py`:

```python
"""The only way a ``ProductEvent`` gets written.

A function rather than direct ``objects.create`` calls so that the PII rule
(constraint 11: no user content in ``metadata``) has one place to be enforced
and reviewed, and so E14 can change what an event carries without visiting
every call site.
"""

from django.db import models

from core.models import ProductEvent


class EventName(models.TextChoices):
    """The funnel, from arrival to the moment the wedge lands.

    E14 (S14-2) extends this list. The values are stable strings because they
    are stored in rows that outlive any refactor — renaming one is a data
    migration, not an edit.
    """

    SIGNUP = "signup", "Cadastro"
    HOUSEHOLD_SEEDED = "household_seeded", "Casa preparada"
    ONBOARDING_STEP = "onboarding_step", "Passo do início"
    ONBOARDING_DONE = "onboarding_done", "Início concluído"
    FIRST_AI_ENTRY = "first_ai_entry", "Primeiro lançamento por IA"
    ACTIVATED = "activated", "Ativado"


#: Events that may happen at most once per household. Anything here is written
#: with ``once=True`` and is therefore covered by the partial unique index.
ONCE_PER_HOUSEHOLD = frozenset(
    {
        EventName.SIGNUP,
        EventName.HOUSEHOLD_SEEDED,
        EventName.ONBOARDING_DONE,
        EventName.FIRST_AI_ENTRY,
        EventName.ACTIVATED,
    }
)


def emit(name, *, household, user=None, metadata=None):
    """Record that ``name`` happened. Returns the row, or ``None`` if it could not.

    ``household is None`` is a no-op rather than an error: every scoped
    queryset in this codebase fails closed to ``none()`` for a household-less
    request, and an event writer must not be the one thing that raises instead.
    """
    if household is None:
        return None
    return ProductEvent.objects.create(
        household=household,
        name=str(name),
        user=user,
        once=name in ONCE_PER_HOUSEHOLD,
        metadata=metadata or {},
    )


def emit_once(name, *, household, user=None, metadata=None):
    """Record ``name`` only if this household has never had it.

    Returns the newly created row, or ``None`` when the household already had
    one. The return value is the "was this the first time?" answer — callers
    use it to decide whether to also emit a downstream event, so it must never
    be a truthy row on the second call.
    """
    if household is None:
        return None
    event, created = ProductEvent.objects.get_or_create(
        household=household,
        name=str(name),
        defaults={"user": user, "once": True, "metadata": metadata or {}},
    )
    return event if created else None
```

- [ ] **Step 5: Generate the migration**

Run: `POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations core --name productevent`
Expected: `core/migrations/0007_productevent.py` created. Open it and confirm it contains `CreateModel` plus `AddConstraint` — nothing else. It is reversible by construction (a plain `CreateModel`).

- [ ] **Step 6: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_product_events.py -q`
Expected: PASS (8 tests)

- [ ] **Step 7: Register it in admin, read-only**

Append to `src/backend/core/admin.py`:

```python
@admin.register(ProductEvent)
class ProductEventAdmin(admin.ModelAdmin):
    """Read-only: these rows are measurements. An editable measurement is a lie."""

    list_display = ("name", "household", "user", "created_at")
    list_filter = ("name", "once")
    date_hierarchy = "created_at"
    readonly_fields = ("household", "name", "user", "once", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

Add `ProductEvent` to the existing `from core.models import ...` line at the top of that file.

- [ ] **Step 8: Verify the whole gate**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations --check --dry-run
```
Expected: all pass; `makemigrations --check` reports no changes.

- [ ] **Step 9: Commit**

```bash
git add src/backend/core/events.py src/backend/core/models.py \
        src/backend/core/admin.py src/backend/core/migrations/0007_productevent.py \
        src/backend/core/tests/test_product_events.py
git commit -m "feat(events): the product-event log, with 'first' as a database fact"
```

---

## Task 2: Emit signup, activation, and the first AI entry

**Files:**
- Modify: `src/backend/accounts/signals.py` (the `create_household_for_new_user` receiver)
- Modify: `src/backend/assistant/agents/tools.py` (`create_entry` ~line 108-175, `commit_receipt` ~line 617-664)
- Test: `src/backend/assistant/tests/test_activation_event.py`
- Test: `src/backend/accounts/tests/test_signup_emits_event.py`

**Interfaces:**
- Consumes: `core.events.EventName`, `core.events.emit_once` (Task 1).
- Produces: nothing new for later tasks to import. After this task, a household that has confirmed a receipt has exactly one `ProductEvent(name="activated", once=True)` row.

**Why here, and not in a view:** `commit_receipt` is the *only* code path that
turns a photograph into `Entry` rows. A view-level hook would miss the eval
harness and any future entry point; a signal on `Entry` could not tell a
receipt from a manual typing.

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_activation_event.py`:

```python
"""Activation is the first confirmed receipt — see docs/architecture/activation-event.md."""

from decimal import Decimal

import pytest
from model_bakery import baker

from assistant.agents.scope import AgentScope
from assistant.agents.tools import commit_receipt, create_entry
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from core.events import EventName
from core.models import ProductEvent


@pytest.fixture
def scope(household, user):
    return AgentScope(household=household, user=user)


@pytest.fixture
def category(household, user):
    return baker.make("finances.Category", household=household, name="Alimentação",
                      created_by=user)


@pytest.fixture
def payment_method(household, user):
    return baker.make("finances.PaymentMethod", household=household, name="Pix",
                      type="pix", created_by=user)


def _pending_draft(household, user, category, payment_method):
    """A draft whose plan is already resolved, so commit_receipt can be called alone."""
    return baker.make(
        "assistant.ReceiptDraft",
        household=household,
        created_by=user,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Mercadinho",
            "plan": {
                "date": "2026-08-15",
                "store": "Mercadinho",
                "payment_method_id": str(payment_method.id),
                "payment_method_name": payment_method.name,
                "table": "-",
                "lines": [
                    {
                        "category_id": str(category.id),
                        "category_name": category.name,
                        "description": "compras",
                        "amount": "42.00",
                    }
                ],
            },
        },
    )


@pytest.mark.django_db
class TestActivation:
    def test_the_first_confirmed_receipt_activates_the_household(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)

        commit_receipt(scope)

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.ACTIVATED
        ).count() == 1

    def test_a_second_receipt_does_not_activate_again(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)
        commit_receipt(scope)
        _pending_draft(household, user, category, payment_method)
        commit_receipt(scope)

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.ACTIVATED
        ).count() == 1

    def test_a_receipt_with_no_plan_does_not_activate(self, scope, household, user):
        baker.make("assistant.ReceiptDraft", household=household, created_by=user,
                   status=ReceiptDraftStatus.PENDING, payload={"store": "X"})

        commit_receipt(scope)

        assert not ProductEvent.objects.for_household(household).filter(
            name=EventName.ACTIVATED
        ).exists()

    def test_confirming_a_receipt_also_counts_as_the_first_ai_entry(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)

        commit_receipt(scope)

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.FIRST_AI_ENTRY
        ).count() == 1


@pytest.mark.django_db
class TestFirstAiEntry:
    def test_a_chat_captured_entry_emits_first_ai_entry(
        self, scope, household, category, payment_method
    ):
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.FIRST_AI_ENTRY
        ).count() == 1

    def test_a_chat_captured_entry_does_not_activate(
        self, scope, household, category, payment_method
    ):
        """Activation is the wedge, not any entry. E11 S11-1 is explicit about this."""
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")

        assert not ProductEvent.objects.for_household(household).filter(
            name=EventName.ACTIVATED
        ).exists()

    def test_a_rejected_entry_emits_nothing(self, scope, household, payment_method):
        result = create_entry(scope, "2026-08-15", "45.00", "x", "Inexistente", "Pix")

        assert result.startswith("Erro:")
        assert ProductEvent.objects.for_household(household).count() == 0

    def test_the_second_ai_entry_does_not_re_emit(
        self, scope, household, category, payment_method
    ):
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")
        create_entry(scope, "2026-08-16", "12.00", "pão", "Alimentação", "Pix")

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.FIRST_AI_ENTRY
        ).count() == 1

    def test_the_event_carries_no_user_content(
        self, scope, household, category, payment_method
    ):
        """Constraint 11: metadata holds counts and enum values, never descriptions."""
        create_entry(scope, "2026-08-15", "45.00", "farmácia do bairro",
                     "Alimentação", "Pix")

        event = ProductEvent.objects.for_household(household).get(
            name=EventName.FIRST_AI_ENTRY
        )
        assert "farmácia" not in str(event.metadata)
        assert event.metadata == {"source": "chat"}
```

Create `src/backend/accounts/tests/test_signup_emits_event.py`:

```python
"""Signup is the funnel's anchor: time-to-activation is measured from it."""

import pytest
from django.urls import reverse

from core.events import EventName
from core.models import ProductEvent


@pytest.mark.django_db
def test_signing_up_emits_a_signup_event(client):
    client.post(
        reverse("account_signup"),
        {
            "email": "novo@example.com",
            "email2": "novo@example.com",
            "password1": "uma-senha-bem-comprida",
            "password2": "uma-senha-bem-comprida",
        },
    )

    event = ProductEvent.objects.get(name=EventName.SIGNUP)
    assert event.user.email == "novo@example.com"
    assert event.household == event.user.memberships.get().household
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_activation_event.py \
  src/backend/accounts/tests/test_signup_emits_event.py -q
```
Expected: FAIL — `ProductEvent.DoesNotExist` / assertion errors on counts of 0.

- [ ] **Step 3: Emit from the signup signal**

In `src/backend/accounts/signals.py`, replace the body of `create_household_for_new_user`:

```python
@receiver(user_signed_up)
def create_household_for_new_user(request, user, **kwargs):
    """Give the new account its own household, as owner. Idempotent."""
    if Membership.objects.filter(user=user).exists():
        return
    with transaction.atomic():
        household = Household.objects.create(name=household_name_for(user))
        Membership.objects.create(user=user, household=household, role=Role.OWNER)
        # The funnel's T0. Time-to-activation is measured from this row rather
        # than from `date_joined` so that one query answers it and E14 does not
        # have to join the auth table to compute a product metric.
        emit_once(EventName.SIGNUP, household=household, user=user)
```

and add to the imports at the top of that file:

```python
from core.events import EventName, emit_once
```

- [ ] **Step 4: Emit from `create_entry`**

In `src/backend/assistant/agents/tools.py`, in `create_entry`, immediately after
the `entry = Entry.objects.create(...)` block and before the `return`:

```python
    # Wedge adoption (E11 S11-1): the household has now captured something
    # through the assistant rather than by typing into a form. Once per
    # household — E14 turns this into the AI-versus-manual ratio.
    emit_once(
        EventName.FIRST_AI_ENTRY,
        household=scope.household,
        user=scope.user,
        metadata={"source": "chat"},
    )
```

Place it **after** the `Entry.objects.create(...)` call, so a rejected category
or an unparseable amount — both of which return early above — emits nothing.

- [ ] **Step 5: Emit from `commit_receipt`**

In the same file, in `commit_receipt`, immediately after the `with transaction.atomic():`
block closes (after the orphan-draft cleanup, before `total = sum(...)`):

```python
    # Activation. This is the product's defining moment — a photograph became
    # money in the ledger, correctly split, in the right billing month — and it
    # is the single event E14's activation rate is computed from. See
    # docs/architecture/activation-event.md.
    emit_once(
        EventName.ACTIVATED,
        household=scope.household,
        user=scope.user,
        metadata={"lines": len(created)},
    )
    emit_once(
        EventName.FIRST_AI_ENTRY,
        household=scope.household,
        user=scope.user,
        metadata={"source": "receipt"},
    )
```

Add to the imports at the top of `tools.py`:

```python
from core.events import EventName, emit_once
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_activation_event.py \
  src/backend/accounts/tests/test_signup_emits_event.py -q
```
Expected: PASS (11 tests)

- [ ] **Step 7: Run the neighbours that touch these functions**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ src/backend/accounts/ -q`
Expected: PASS. If the eval behaviour runner (`assistant/eval/behaviour_runner.py`) fails,
it is because it builds drafts directly — emitting is additive and must not change
any assertion; read the failure before changing anything.

- [ ] **Step 8: Commit**

```bash
git add src/backend/accounts/signals.py src/backend/assistant/agents/tools.py \
        src/backend/assistant/tests/test_activation_event.py \
        src/backend/accounts/tests/test_signup_emits_event.py
git commit -m "feat(events): emit signup, first AI entry, and activation at the receipt commit"
```

---

## Task 3: A new household is usable in under a minute

**Files:**
- Create: `src/backend/assistant/starter_rules.py`
- Modify: `src/backend/assistant/management/commands/seed_category_rules.py` (import `DEFAULT_RULES` instead of defining it)
- Create: `src/backend/accounts/starter_data.py`
- Create: `src/backend/accounts/management/commands/seed_starter_data.py`
- Modify: `src/backend/accounts/signals.py` (call the seeder)
- Test: `src/backend/accounts/tests/test_starter_data.py`

**Interfaces:**
- Consumes: `core.events.EventName`, `core.events.emit_once` (Task 1).
- Produces:
  - `accounts.starter_data.STARTER_CATEGORIES: list[tuple[str, bool]]` — `(name, is_system)`
  - `accounts.starter_data.STARTER_PAYMENT_METHODS: list[tuple[str, str]]` — `(name, type)`
  - `accounts.starter_data.seed_starter_data(household, user=None) -> dict` with keys `categories`, `payment_methods`, `rules` (ints — how many were *created*)
  - `assistant.starter_rules.DEFAULT_RULES: list[tuple[str, str]]` — `(nf_token, category_name)`

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_starter_data.py`:

```python
"""A brand-new household must be able to record something without setup.

`Entry.category` and `Entry.payment_method` are required, so a household with
neither cannot write its first row — that is the wall S11-2 removes.
"""

import pytest
from django.urls import reverse

from accounts.starter_data import (
    STARTER_CATEGORIES,
    STARTER_PAYMENT_METHODS,
    seed_starter_data,
)
from assistant.models import MemoryRule
from assistant.starter_rules import DEFAULT_RULES
from core.events import EventName
from core.models import ProductEvent
from finances.models import Category, PaymentMethod


@pytest.mark.django_db
class TestSeeding:
    def test_it_creates_the_starter_catalogue(self, household, user):
        counts = seed_starter_data(household, user)

        assert counts["categories"] == len(STARTER_CATEGORIES)
        assert counts["payment_methods"] == len(STARTER_PAYMENT_METHODS)
        assert Category.objects.for_household(household).count() == len(STARTER_CATEGORIES)
        assert PaymentMethod.objects.for_household(household).count() == len(
            STARTER_PAYMENT_METHODS
        )

    def test_it_is_idempotent(self, household, user):
        seed_starter_data(household, user)
        second = seed_starter_data(household, user)

        assert second == {"categories": 0, "payment_methods": 0, "rules": 0}
        assert Category.objects.for_household(household).count() == len(STARTER_CATEGORIES)

    def test_it_never_touches_another_household(self, household, other_household, user):
        seed_starter_data(household, user)

        assert Category.objects.for_household(other_household).count() == 0

    def test_seeded_rows_are_attributed_to_the_seeding_user(self, household, user):
        seed_starter_data(household, user)

        assert Category.objects.for_household(household).exclude(created_by=user).count() == 0

    def test_it_emits_household_seeded_once(self, household, user):
        seed_starter_data(household, user)
        seed_starter_data(household, user)

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.HOUSEHOLD_SEEDED
        ).count() == 1


@pytest.mark.django_db
class TestTheAssistantWorksImmediately:
    def test_every_starter_memory_rule_targets_a_starter_category(self):
        """S11-2: the AI works on day one rather than after manual setup.

        A pure-data assertion, so it fails at review time rather than the first
        time a real receipt is photographed by a real stranger.
        """
        starter_names = {name for name, _is_system in STARTER_CATEGORIES}
        missing = {
            category for _trigger, category in DEFAULT_RULES
            if category not in starter_names
        }

        assert missing == set()

    def test_seeding_installs_the_memory_rules(self, household, user):
        counts = seed_starter_data(household, user)

        assert counts["rules"] == len(DEFAULT_RULES)
        assert MemoryRule.objects.for_household(household).count() == len(DEFAULT_RULES)


@pytest.mark.django_db
class TestDefaultsAreAStartingPointNotACage:
    def test_non_system_starter_categories_can_be_deleted(self, household, user):
        seed_starter_data(household, user)
        category = Category.objects.for_household(household).get(name="Lanche")

        category.delete()

        assert not Category.objects.for_household(household).filter(name="Lanche").exists()

    def test_starter_categories_seed_with_no_invented_budget(self, household, user):
        """A ceiling copied from someone else's household is a made-up number."""
        seed_starter_data(household, user)

        assert Category.objects.for_household(household).exclude(budget_ceiling=0).count() == 0


@pytest.mark.django_db
class TestSignupSeeds:
    def test_a_brand_new_signup_can_record_an_entry_with_zero_setup(self, client):
        client.post(
            reverse("account_signup"),
            {
                "email": "estranho@example.com",
                "email2": "estranho@example.com",
                "password1": "uma-senha-bem-comprida",
                "password2": "uma-senha-bem-comprida",
            },
        )
        household = ProductEvent.objects.get(name=EventName.SIGNUP).household

        assert Category.objects.for_household(household).exists()
        assert PaymentMethod.objects.for_household(household).filter(is_active=True).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_starter_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.starter_data'`

- [ ] **Step 3: Move the memory rules to a shared module**

Create `src/backend/assistant/starter_rules.py`:

```python
"""The starter NF-token → category rules, in one place.

Receipt item names on fiscal coupons are abbreviated (``ENERG MONSTER``,
``REFRIG LARANJA SJ 350ML``), so a trigger must be a token that literally
appears in the NF name — not the colloquial word ("energético"), which would
never substring-match.

Lifted out of ``assistant/management/commands/seed_category_rules.py`` because
E11 seeds the same rules from ``accounts.starter_data`` on signup, and two
copies of this list would drift the day someone edits one. The command still
exists for an existing household that predates the automatic seeding.
"""

#: (NF-token trigger, category name). Triggers are lowercased by
#: ``create_memory_rule`` and matched case-insensitively as substrings of the
#: item description. Every category named here MUST be in
#: ``accounts.starter_data.STARTER_CATEGORIES`` — a test asserts it.
DEFAULT_RULES = [
    ("energ", "Lanche"),  # ENERG MONSTER, ENERGY MONSTER
    ("refrig", "Lanche"),  # REFRIG LARANJA ...
    ("monster", "Lanche"),  # energético (marca) — reforça "energ"
]
```

In `src/backend/assistant/management/commands/seed_category_rules.py`, delete the
`DEFAULT_RULES = [...]` block (lines 22-28) and its preceding comment, and add
to the imports:

```python
from assistant.starter_rules import DEFAULT_RULES
```

- [ ] **Step 4: Write the seeder**

Create `src/backend/accounts/starter_data.py`:

```python
"""What a brand-new household starts with.

`Entry.category` is `PROTECT` and required, and so is `payment_method` — so a
household with an empty catalogue cannot record anything at all. That is the
first wall a stranger hits, and it is invisible: the form simply has no options.

The list is a trimmed subset of the production-derived catalogue in
`finances/management/commands/seed_data.py`, not an invention. The full
26-category version stays there: it is one real household's catalogue, built up
over months, and handing all of it to a stranger on day one is 26 decisions
before the first receipt. Twelve plus the two system categories covers the bulk
of Brazilian household spending, and everything here is editable and deletable.

Budget ceilings are deliberately absent. `seed_data.py` carries real ceilings
because they are the operator's real ceilings; copying them into a stranger's
ledger would put a made-up number on their dashboard on day one.
"""

from django.db import transaction

from core.events import EventName, emit_once
from finances.models import Category, PaymentMethod
from finances.models.payment_method import PaymentType

#: (name, is_system). The two system categories back `SystemicExpense` posting
#: and cannot be deleted — see `Category.delete`.
STARTER_CATEGORIES = [
    ("Alimentação", False),
    ("Lanche", False),
    ("Transporte", False),
    ("Combustível", False),
    ("Farmácia", False),
    ("Saúde", False),
    ("Casa", False),
    ("Lazer", False),
    ("Higiene", False),
    ("Limpeza", False),
    ("Serviços", False),
    ("Outros", False),
    ("Custeio", True),
    ("Financiamentos", True),
]

#: (name, type). No credit card: a card needs a closing day to put a purchase in
#: the right billing month, and guessing one silently misfiles every credit
#: purchase. The onboarding's card step asks for it and explains why (Task 6).
STARTER_PAYMENT_METHODS = [
    ("Dinheiro", PaymentType.CASH),
    ("Pix", PaymentType.PIX),
]


def seed_starter_data(household, user=None) -> dict:
    """Give ``household`` a usable catalogue. Idempotent.

    Returns how many rows were *created* — zero on every call after the first,
    which is what makes it safe to call from a signal that may fire twice.
    """
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import create_memory_rule
    from assistant.starter_rules import DEFAULT_RULES

    created = {"categories": 0, "payment_methods": 0, "rules": 0}

    with transaction.atomic():
        for name, is_system in STARTER_CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                household=household,
                name=name,
                defaults={"is_system": is_system, "created_by": user},
            )
            created["categories"] += int(was_created)

        for name, pm_type in STARTER_PAYMENT_METHODS:
            _, was_created = PaymentMethod.objects.get_or_create(
                household=household,
                name=name,
                defaults={"type": pm_type, "closing_day": None, "created_by": user},
            )
            created["payment_methods"] += int(was_created)

        # Imported inside the function, not at module scope: `assistant.models`
        # already imports `accounts.models`, so an import the other way at
        # module level would be circular. Same reason `core/tiers.py` exists.
        scope = AgentScope(household=household, user=user)
        existing_triggers = set(
            _memory_rule_triggers(household)
        )
        for trigger, category_name in DEFAULT_RULES:
            if trigger.lower() in existing_triggers:
                continue
            create_memory_rule(scope, trigger, "category", category_name)
            created["rules"] += 1

    emit_once(EventName.HOUSEHOLD_SEEDED, household=household, user=user,
              metadata=created)
    return created


def _memory_rule_triggers(household):
    """Triggers this household already has, so re-seeding creates nothing.

    `create_memory_rule` is an `update_or_create`, so calling it twice would not
    duplicate a row — but it *would* re-enqueue an embedding task and report a
    non-zero created count, and "idempotent" has to mean both.
    """
    from assistant.models import MemoryRule

    return MemoryRule.objects.for_household(household).values_list("trigger", flat=True)
```

- [ ] **Step 5: Call it on signup**

In `src/backend/accounts/signals.py`, inside `create_household_for_new_user`,
after the `emit_once(EventName.SIGNUP, ...)` line and still inside the
`transaction.atomic()` block:

```python
        seed_starter_data(household, user)
```

and add to the imports:

```python
from accounts.starter_data import seed_starter_data
```

- [ ] **Step 6: Add the operator command**

Create `src/backend/accounts/management/commands/seed_starter_data.py`:

```python
"""Seed the starter catalogue into a household that predates automatic seeding.

Signup does this by itself (`accounts/signals.py`). This command exists for the
accounts that already existed when E11 shipped, and for a household minted by
`createsuperuser`, which never fires `user_signed_up`.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Household, Membership, Role
from accounts.starter_data import seed_starter_data


class Command(BaseCommand):
    help = "Seed the starter categories, payment methods and memory rules for a household."

    def add_arguments(self, parser):
        parser.add_argument("--household", required=True, help="Household UUID")

    def handle(self, *args, **options):
        household = Household.objects.filter(pk=options["household"]).first()
        if household is None:
            raise CommandError(f"Casa '{options['household']}' não encontrada.")

        owner = (
            Membership.objects.filter(household=household, role=Role.OWNER)
            .select_related("user")
            .first()
        )
        created = seed_starter_data(household, owner.user if owner else None)
        self.stdout.write(
            self.style.SUCCESS(
                f"{household.name}: {created['categories']} categoria(s), "
                f"{created['payment_methods']} forma(s) de pagamento, "
                f"{created['rules']} regra(s)."
            )
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_starter_data.py -q`
Expected: PASS (11 tests)

- [ ] **Step 8: Run the suites that could be disturbed by a seeded household**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ src/backend/assistant/ -q`
Expected: PASS. Signup tests that previously asserted an empty catalogue now see
one — that is the change; update the assertion, do not weaken the seeding.

- [ ] **Step 9: Commit**

```bash
git add src/backend/assistant/starter_rules.py \
        src/backend/assistant/management/commands/seed_category_rules.py \
        src/backend/accounts/starter_data.py src/backend/accounts/signals.py \
        src/backend/accounts/management/commands/seed_starter_data.py \
        src/backend/accounts/tests/test_starter_data.py
git commit -m "feat(onboarding): seed a usable catalogue the moment a household exists"
```

---

## Task 4: Onboarding state that survives an interruption

**Files:**
- Modify: `src/backend/accounts/models.py` (append `OnboardingStep`, `OnboardingState`)
- Create: `src/backend/accounts/migrations/0008_onboardingstate.py` (generated; `0007_beta_credit_grant_from_real_usage` is the current head)
- Test: `src/backend/accounts/tests/test_onboarding_state.py`

**Interfaces:**
- Consumes: `accounts.models.Household` (existing).
- Produces:
  - `accounts.models.OnboardingStep` — `TextChoices` with `INCOME = "income"`, `CARDS = "cards"`, `CAPTURE = "capture"`, in that order
  - `accounts.models.OnboardingState` — `household: OneToOne`, `steps_done: list[str]`, `completed_at: datetime|None`
  - `OnboardingState.for_household(household) -> OnboardingState` (classmethod, get-or-create)
  - `OnboardingState.mark(step) -> None`
  - `OnboardingState.next_step() -> str | None` — the first step not in `steps_done`, or `None`
  - `OnboardingState.is_complete -> bool` (property)

Three steps, deliberately under the five-step ceiling S11-3 names.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_onboarding_state.py`:

```python
"""Guided setup must be resumable: a phone loses a session mid-signup constantly."""

import pytest

from accounts.models import OnboardingState, OnboardingStep


@pytest.mark.django_db
class TestOnboardingState:
    def test_a_fresh_household_starts_at_the_first_step(self, household):
        state = OnboardingState.for_household(household)

        assert state.next_step() == OnboardingStep.INCOME
        assert state.is_complete is False

    def test_for_household_is_idempotent(self, household):
        first = OnboardingState.for_household(household)
        second = OnboardingState.for_household(household)

        assert first.pk == second.pk
        assert OnboardingState.objects.filter(household=household).count() == 1

    def test_marking_a_step_advances_to_the_next(self, household):
        state = OnboardingState.for_household(household)

        state.mark(OnboardingStep.INCOME)

        assert state.next_step() == OnboardingStep.CARDS

    def test_marking_the_same_step_twice_does_not_skip_one(self, household):
        state = OnboardingState.for_household(household)

        state.mark(OnboardingStep.INCOME)
        state.mark(OnboardingStep.INCOME)

        assert state.next_step() == OnboardingStep.CARDS
        assert state.steps_done == [OnboardingStep.INCOME]

    def test_progress_survives_a_reload(self, household):
        OnboardingState.for_household(household).mark(OnboardingStep.INCOME)

        assert OnboardingState.for_household(household).next_step() == OnboardingStep.CARDS

    def test_marking_every_step_completes_it(self, household):
        state = OnboardingState.for_household(household)

        for step in OnboardingStep:
            state.mark(step)

        assert state.next_step() is None
        assert state.is_complete is True
        assert state.completed_at is not None

    def test_completion_timestamp_is_not_overwritten(self, household):
        state = OnboardingState.for_household(household)
        for step in OnboardingStep:
            state.mark(step)
        first_completion = state.completed_at

        state.mark(OnboardingStep.CAPTURE)

        assert state.completed_at == first_completion

    def test_the_flow_is_at_most_five_steps(self):
        """S11-3 and the industry standard it cites. A guard, not a formality."""
        assert len(OnboardingStep) <= 5

    def test_each_household_has_its_own_progress(self, household, other_household):
        OnboardingState.for_household(household).mark(OnboardingStep.INCOME)

        assert OnboardingState.for_household(other_household).next_step() == (
            OnboardingStep.INCOME
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_state.py -q`
Expected: FAIL — `ImportError: cannot import name 'OnboardingState' from 'accounts.models'`

- [ ] **Step 3: Add the model**

Append to `src/backend/accounts/models.py`:

```python
class OnboardingStep(models.TextChoices):
    """The guided setup, in order.

    Three, against S11-3's ceiling of five. Each one removes a wall a stranger
    would otherwise hit silently: no income means an empty projection, no card
    means every credit purchase lands in the wrong billing month, and no photo
    means they never see what this product is for.
    """

    INCOME = "income", "Renda"
    CARDS = "cards", "Cartões"
    CAPTURE = "capture", "Primeira foto"


class OnboardingState(models.Model):
    """How far through the guided setup a household is.

    On the household rather than the user: a second person joining a household
    that is already set up must not be walked through setting it up again.

    A step is "done" whether the user filled it in or skipped it. That is
    deliberate — S11-3 requires every step to be skippable and skipping not to
    break anything, so the flow only needs to know it has *asked*.
    """

    household = models.OneToOneField(
        Household,
        on_delete=models.CASCADE,
        related_name="onboarding",
        primary_key=True,
    )
    steps_done = models.JSONField(default=list, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "início de uso"
        verbose_name_plural = "inícios de uso"

    def __str__(self):
        return f"{self.household}: {len(self.steps_done)}/{len(OnboardingStep)}"

    @classmethod
    def for_household(cls, household):
        """This household's progress, creating the row on first sight."""
        state, _ = cls.objects.get_or_create(household=household)
        return state

    def next_step(self):
        """The first step not yet asked, or ``None`` when the flow is over."""
        done = set(self.steps_done or [])
        for step in OnboardingStep:
            if step.value not in done:
                return step.value
        return None

    @property
    def is_complete(self) -> bool:
        return self.next_step() is None

    def mark(self, step) -> None:
        """Record that ``step`` has been asked. Idempotent."""
        from django.utils import timezone

        value = str(step)
        steps = list(self.steps_done or [])
        if value not in steps:
            steps.append(value)
            self.steps_done = steps
        # Stamped once. A user who walks back through a finished flow has not
        # re-onboarded, and moving this timestamp would move E14's cohort.
        if self.completed_at is None and self.next_step() is None:
            self.completed_at = timezone.now()
        self.save(update_fields=["steps_done", "completed_at", "updated_at"])
```

- [ ] **Step 4: Generate the migration**

Run: `POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations accounts --name onboardingstate`
Expected: a migration containing one `CreateModel`. Reversible by construction.

- [ ] **Step 5: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_state.py -q`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add src/backend/accounts/models.py src/backend/accounts/migrations/ \
        src/backend/accounts/tests/test_onboarding_state.py
git commit -m "feat(onboarding): resumable per-household setup progress"
```

---

## Task 5: Route a new household into the guided setup

**Files:**
- Modify: `src/backend/accounts/middleware.py` (append `onboarding_redirect_middleware`)
- Modify: `src/backend/config/settings.py` (`MIDDLEWARE`, after `active_household_middleware`)
- Test: `src/backend/accounts/tests/test_onboarding_redirect.py`

**Interfaces:**
- Consumes: `accounts.models.OnboardingState` (Task 4); the URL name `onboarding` (declared in Task 6 — this task adds a placeholder view so the name resolves, and Task 6 replaces it).
- Produces: `accounts.middleware.onboarding_redirect_middleware(get_response)` — a standard Django middleware factory.

**Sequencing note:** this task lands the *routing* and a minimal `/casa/comecar/`
page; Task 6 lands the three real screens behind it. Split because a reviewer
can reject "you redirect the wrong requests" independently of "the card step
explains the closing day badly", and the redirect is the piece with the blast
radius — get it wrong and every request loops.

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_onboarding_redirect.py`:

```python
"""A new household lands in the guided setup; everything else is left alone.

The redirect is the one piece of this epic that can take the whole product
down — an over-broad rule loops, and a rule that catches the API breaks the
chat widget with no visible error. Hence the exemption tests.
"""

import pytest
from django.urls import reverse

from accounts.models import OnboardingState, OnboardingStep


@pytest.mark.django_db
class TestRedirect:
    def test_an_unonboarded_household_is_sent_to_the_guided_setup(self, logged_client):
        response = logged_client.get("/")

        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")

    def test_a_completed_household_is_left_alone(self, logged_client, household):
        state = OnboardingState.for_household(household)
        for step in OnboardingStep:
            state.mark(step)

        assert logged_client.get("/").status_code == 200

    def test_an_anonymous_visitor_is_not_redirected(self, client):
        """They get the login redirect, which is a different destination."""
        response = client.get("/")

        assert reverse("onboarding") not in response.get("Location", "")


@pytest.mark.django_db
class TestExemptions:
    @pytest.mark.parametrize(
        "path",
        [
            "/casa/comecar/",
            "/api/assistant/history/",
            "/api/dashboard/summary/",
            "/healthz/",
            "/manifest.webmanifest",
            "/sw.js",
            "/accounts/logout/",
        ],
    )
    def test_these_paths_are_never_redirected(self, logged_client, path):
        response = logged_client.get(path)

        assert response.get("Location", "") != reverse("onboarding")

    def test_an_htmx_request_is_not_redirected(self, logged_client):
        """HTMX swaps a redirect's body into a fragment slot, which would paint
        the whole setup page inside a table cell."""
        response = logged_client.get("/", HTTP_HX_REQUEST="true")

        assert response.get("Location", "") != reverse("onboarding")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_redirect.py -q`
Expected: FAIL — `NoReverseMatch: Reverse for 'onboarding' not found`

- [ ] **Step 3: Add a minimal view and URL so the name resolves**

Create `src/backend/accounts/onboarding.py`:

```python
"""The guided setup — three steps, every one skippable, progress resumable.

Server-rendered with HTMX rather than a React island, matching every other
form surface in this product (`templates/settings/`, `templates/account/`).
The one React island a new user meets is the chat, which is where this flow
deliberately hands them off.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from accounts.models import OnboardingState


class OnboardingView(LoginRequiredMixin, TemplateView):
    """Whichever step this household has not been asked yet."""

    template_name = "onboarding/onboarding_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = OnboardingState.for_household(self.request.household)
        context["state"] = state
        context["step"] = state.next_step()
        return context
```

Add to `src/backend/accounts/urls.py` — import `OnboardingView` from
`accounts.onboarding` and add the path:

```python
    path("comecar/", OnboardingView.as_view(), name="onboarding"),
```

Create a minimal `src/backend/templates/onboarding/onboarding_page.html`:

```html
{% extends "base.html" %}
{% block title %}Vamos começar — Expense Tracker{% endblock %}
{% block content %}
<h2 class="text-2xl font-bold">Vamos começar</h2>
<p class="opacity-70">Passo: {{ step }}</p>
{% endblock %}
```

- [ ] **Step 4: Write the middleware**

Append to `src/backend/accounts/middleware.py`:

```python
#: Prefixes the redirect never touches. Everything here either has no user
#: interface to redirect (the API, the health check, the task dispatcher), or
#: redirecting it would break something worse than an unonboarded dashboard
#: (the setup flow itself would loop; logout would become unreachable).
_ONBOARDING_EXEMPT_PREFIXES = (
    "/casa/comecar/",
    "/api/",
    "/accounts/",
    "/tasks/",
    "/healthz",
    "/static/",
    "/sw.js",
    "/offline/",
    "/manifest.webmanifest",
    "/.well-known/",
)


def onboarding_redirect_middleware(get_response):
    """Send a household that has not been through setup to the setup.

    Runs after `active_household_middleware`, because it needs
    `request.household`. Deliberately narrow:

    * only GET — a POST redirected loses its body, and a 302 on a form
      submission is indistinguishable from the form having worked;
    * never HTMX — HTMX swaps a redirect's *body* into whatever target the
      fragment named, which would paint the whole setup page inside a table
      cell rather than navigating;
    * never the exempt prefixes above.

    One query per request, and only for a household that has not finished. A
    finished household short-circuits on the `completed_at` column.
    """
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    from accounts.models import OnboardingState

    def middleware(request):
        if (
            request.method == "GET"
            and getattr(request, "household", None) is not None
            and not request.headers.get("HX-Request")
            and not request.path.startswith(_ONBOARDING_EXEMPT_PREFIXES)
        ):
            state = OnboardingState.for_household(request.household)
            if not state.is_complete:
                return HttpResponseRedirect(reverse("onboarding"))
        return get_response(request)

    return middleware
```

- [ ] **Step 5: Register the middleware**

In `src/backend/config/settings.py`, add to `MIDDLEWARE` immediately after
`"accounts.middleware.active_household_middleware"`:

```python
    # After the household is resolved, because it reads request.household. E11.
    "accounts.middleware.onboarding_redirect_middleware",
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_redirect.py -q`
Expected: PASS (11 tests)

- [ ] **Step 7: Run the whole suite — this middleware touches every request**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: a batch of existing view tests now get a 302. Those tests must mark
their household's onboarding complete. Add this to `src/backend/conftest.py`:

```python
@pytest.fixture
def onboarded_household(household):
    """A household past the guided setup, so view tests are not redirected.

    Separate from `household` on purpose: a test that asserts something about a
    *new* household must not silently get an onboarded one.
    """
    from accounts.models import OnboardingState, OnboardingStep

    state = OnboardingState.for_household(household)
    for step in OnboardingStep:
        state.mark(step)
    return household
```

and change the existing `logged_client` fixture to depend on `onboarded_household`
instead of `household`:

```python
@pytest.fixture
def logged_client(user, onboarded_household):
    """A logged-in client whose user resolves to an onboarded household.

    `onboarded_household` is requested for its side effects, and both matter:
    the middleware reads `request.household` from a Membership, and from E11 a
    household that has not finished the guided setup is redirected out of every
    page — which would turn "the neighbour's row is absent" into a test that
    passes because *every* page is a 302.
    """
    from django.test import Client

    client = Client()
    client.force_login(user)
    return client
```

Then re-run `POSTGRES_PORT=5433 uv run pytest src/backend/ -q` and fix any
remaining module-local client fixtures the same way.

- [ ] **Step 8: Commit**

```bash
git add src/backend/accounts/middleware.py src/backend/accounts/onboarding.py \
        src/backend/accounts/urls.py src/backend/config/settings.py \
        src/backend/conftest.py src/backend/templates/onboarding/ \
        src/backend/accounts/tests/test_onboarding_redirect.py
git commit -m "feat(onboarding): route an unonboarded household into the guided setup"
```

---

## Task 6: The three guided-setup screens

**Files:**
- Modify: `src/backend/accounts/onboarding.py` (the step views)
- Modify: `src/backend/accounts/urls.py`
- Create: `src/backend/templates/onboarding/onboarding_page.html` (replaces the placeholder)
- Create: `src/backend/templates/onboarding/_step_income.html`
- Create: `src/backend/templates/onboarding/_step_cards.html`
- Create: `src/backend/templates/onboarding/_step_capture.html`
- Test: `src/backend/accounts/tests/test_onboarding_flow.py`

**Interfaces:**
- Consumes: `accounts.models.OnboardingState`, `OnboardingStep` (Task 4); `core.events.emit`, `emit_once`, `EventName` (Task 1); `finances.models.Income`, `finances.models.PaymentMethod`.
- Produces: URL names `onboarding` (existing), `onboarding_step` (POST, one per step), `onboarding_skip` (POST).

**Design constraints from the spec:**
- Every step skippable, and skipping breaks nothing (S11-3).
- The closing day explained in one plain sentence (S11-3, open question 4).
- The flow ends by handing the user to the activation moment, not an empty dashboard (S11-3).
- The CSV importer is discoverable *during* setup and presented as optional (S11-6).

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_onboarding_flow.py`:

```python
"""The guided setup end to end: three steps, all skippable, ending at the wedge."""

import pytest
from django.urls import reverse

from accounts.models import OnboardingState, OnboardingStep
from core.events import EventName
from core.models import ProductEvent
from finances.models import Income, PaymentMethod


@pytest.mark.django_db
class TestTheFlow:
    def test_it_opens_on_the_income_step(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.get(reverse("onboarding"))

        assert response.status_code == 200
        assertion = response.content.decode()
        assert "Quanto entra por mês" in assertion

    def test_submitting_income_records_it_and_advances(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.post(
            reverse("onboarding_step", args=[OnboardingStep.INCOME]),
            {"name": "Salário", "amount": "4500.00"},
        )

        assert response.status_code == 302
        assert Income.objects.for_household(household).get().amount == 4500
        assert OnboardingState.for_household(household).next_step() == OnboardingStep.CARDS

    def test_submitting_a_card_records_its_closing_day(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        logged_client.post(
            reverse("onboarding_step", args=[OnboardingStep.CARDS]),
            {"name": "Nubank", "closing_day": "25"},
        )

        card = PaymentMethod.objects.for_household(household).get(name="Nubank")
        assert card.type == "credit_card"
        assert card.closing_day == 25

    def test_the_last_step_hands_the_user_to_the_chat_not_the_dashboard(
        self, logged_client, household
    ):
        OnboardingState.objects.filter(household=household).delete()
        state = OnboardingState.for_household(household)
        state.mark(OnboardingStep.INCOME)
        state.mark(OnboardingStep.CARDS)

        response = logged_client.post(
            reverse("onboarding_step", args=[OnboardingStep.CAPTURE])
        )

        assert response["Location"] == "/?comecar=foto"


@pytest.mark.django_db
class TestSkipping:
    @pytest.mark.parametrize("step", list(OnboardingStep))
    def test_every_step_can_be_skipped(self, logged_client, household, step):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.post(reverse("onboarding_skip", args=[step]))

        assert response.status_code == 302
        assert step.value in OnboardingState.for_household(household).steps_done

    def test_skipping_everything_leaves_a_working_product(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        for step in OnboardingStep:
            logged_client.post(reverse("onboarding_skip", args=[step]))

        assert logged_client.get("/").status_code == 200
        assert Income.objects.for_household(household).count() == 0


@pytest.mark.django_db
class TestResumability:
    def test_an_interrupted_setup_resumes_where_it_stopped(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        logged_client.post(reverse("onboarding_skip", args=[OnboardingStep.INCOME]))

        response = logged_client.get(reverse("onboarding"))

        assert "fecha a fatura" in response.content.decode()


@pytest.mark.django_db
class TestCopy:
    def test_the_closing_day_is_explained_in_one_sentence(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        OnboardingState.for_household(household).mark(OnboardingStep.INCOME)

        body = logged_client.get(reverse("onboarding")).content.decode()

        assert "fecha a fatura" in body
        assert "mês seguinte" in body

    def test_the_importer_is_offered_during_setup_and_marked_optional(
        self, logged_client, household
    ):
        OnboardingState.objects.filter(household=household).delete()

        body = logged_client.get(reverse("onboarding")).content.decode()

        assert reverse("finances:import_upload") in body
        assert "opcional" in body.lower()


@pytest.mark.django_db
class TestInstrumentation:
    def test_each_step_emits_an_event_with_its_outcome(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        logged_client.post(reverse("onboarding_skip", args=[OnboardingStep.INCOME]))

        event = ProductEvent.objects.for_household(household).get(
            name=EventName.ONBOARDING_STEP
        )
        assert event.metadata == {"step": "income", "action": "skipped"}

    def test_finishing_emits_onboarding_done_once(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        for step in OnboardingStep:
            logged_client.post(reverse("onboarding_skip", args=[step]))

        assert ProductEvent.objects.for_household(household).filter(
            name=EventName.ONBOARDING_DONE
        ).count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_flow.py -q`
Expected: FAIL — `NoReverseMatch: Reverse for 'onboarding_step' not found`

- [ ] **Step 3: Write the step views**

Replace the contents of `src/backend/accounts/onboarding.py`:

```python
"""The guided setup — three steps, every one skippable, progress resumable.

Server-rendered with HTMX rather than a React island, matching every other form
surface in this product (`templates/settings/`, `templates/account/`). The one
React island a new user meets is the chat, which is where this flow
deliberately hands them off: S11-3's last requirement is that setup ends at the
activation moment, not at an empty dashboard.

Every step writes through the ordinary models, so nothing here is a parallel
write path that could drift from what the settings screens do.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from accounts.models import OnboardingState, OnboardingStep
from core.events import EventName, emit, emit_once
from finances.models import Income, PaymentMethod
from finances.models.payment_method import PaymentType

#: Where the flow lets go of the user. The query string is what makes the
#: dashboard open the chat with the camera ready (Task 8) instead of showing
#: the empty cards S11-3 explicitly refuses to end on.
ACTIVATION_HANDOFF_URL = "/?comecar=foto"


class OnboardingView(LoginRequiredMixin, TemplateView):
    """Whichever step this household has not been asked yet."""

    template_name = "onboarding/onboarding_page.html"

    def get(self, request, *args, **kwargs):
        state = OnboardingState.for_household(request.household)
        if state.is_complete:
            return HttpResponseRedirect("/")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = OnboardingState.for_household(self.request.household)
        context["state"] = state
        context["step"] = state.next_step()
        context["step_number"] = len(state.steps_done or []) + 1
        context["step_total"] = len(OnboardingStep)
        return context


class _StepView(LoginRequiredMixin, View):
    """Shared plumbing: mark the step, emit, and go wherever the flow goes next."""

    def _advance(self, request, step, action):
        state = OnboardingState.for_household(request.household)
        state.mark(step)
        emit(
            EventName.ONBOARDING_STEP,
            household=request.household,
            user=request.user,
            metadata={"step": str(step), "action": action},
        )
        if state.is_complete:
            emit_once(
                EventName.ONBOARDING_DONE,
                household=request.household,
                user=request.user,
            )
            return HttpResponseRedirect(ACTIVATION_HANDOFF_URL)
        return HttpResponseRedirect(reverse("onboarding"))


class OnboardingStepView(_StepView):
    """The user filled a step in."""

    def post(self, request, step, *args, **kwargs):
        if step == OnboardingStep.INCOME:
            self._save_income(request)
        elif step == OnboardingStep.CARDS:
            self._save_card(request)
        # CAPTURE has nothing to save: its "submit" is the handoff itself.
        return self._advance(request, step, "done")

    def _save_income(self, request):
        name = (request.POST.get("name") or "").strip() or "Renda"
        try:
            amount = Decimal(request.POST.get("amount") or "")
        except InvalidOperation:
            return
        if amount <= 0:
            return
        Income.objects.create(
            household=request.household,
            created_by=request.user,
            name=name,
            amount=amount,
            month=date.today().replace(day=1),
            is_recurring=True,
            recurrence_start=date.today().replace(day=1),
        )

    def _save_card(self, request):
        name = (request.POST.get("name") or "").strip()
        if not name:
            return
        try:
            closing_day = int(request.POST.get("closing_day") or "")
        except ValueError:
            return
        if not 1 <= closing_day <= 31:
            return
        PaymentMethod.objects.get_or_create(
            household=request.household,
            name=name,
            defaults={
                "type": PaymentType.CREDIT_CARD,
                "closing_day": closing_day,
                "created_by": request.user,
            },
        )


class OnboardingSkipView(_StepView):
    """The user chose not to answer. Nothing is written; the flow moves on.

    S11-3 requires skipping not to break the product, and it does not: the
    starter catalogue from Task 3 already makes the household usable, so every
    step here is an improvement rather than a prerequisite.
    """

    def post(self, request, step, *args, **kwargs):
        return self._advance(request, step, "skipped")
```

- [ ] **Step 4: Wire the URLs**

In `src/backend/accounts/urls.py`, import `OnboardingSkipView`, `OnboardingStepView`,
`OnboardingView` from `accounts.onboarding` and register:

```python
    path("comecar/", OnboardingView.as_view(), name="onboarding"),
    path("comecar/<str:step>/", OnboardingStepView.as_view(), name="onboarding_step"),
    path("comecar/<str:step>/pular/", OnboardingSkipView.as_view(), name="onboarding_skip"),
```

- [ ] **Step 5: Write the shell template**

Replace `src/backend/templates/onboarding/onboarding_page.html`:

```html
{% extends "base.html" %}

{% block title %}Vamos começar — Expense Tracker{% endblock %}

{% block content %}
<div class="max-w-lg mx-auto">
    <div class="flex items-center justify-between mb-2">
        <p class="text-xs uppercase tracking-wide opacity-60">
            Passo {{ step_number }} de {{ step_total }}
        </p>
        <a href="{% url 'finances:import_upload' %}" class="link link-hover text-xs opacity-70">
            Já uso planilha (opcional)
        </a>
    </div>
    <progress class="progress progress-accent w-full mb-6"
              value="{{ step_number }}" max="{{ step_total }}"></progress>

    <div class="card bg-base-100 shadow-sm">
        <div class="card-body">
            {% if step == "income" %}{% include "onboarding/_step_income.html" %}
            {% elif step == "cards" %}{% include "onboarding/_step_cards.html" %}
            {% else %}{% include "onboarding/_step_capture.html" %}{% endif %}
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Write the income step**

Create `src/backend/templates/onboarding/_step_income.html`:

```html
<h2 class="card-title">Quanto entra por mês?</h2>
<p class="text-sm opacity-70">
    É com esse número que o app calcula quanto sobra. Dá para mudar depois.
</p>

<form method="post" action="{% url 'onboarding_step' 'income' %}" class="mt-4">
    {% csrf_token %}
    <fieldset class="fieldset">
        <label class="label" for="income-name">De onde vem</label>
        <input type="text" name="name" id="income-name" class="input w-full"
               value="Salário" autocomplete="off">

        <label class="label" for="income-amount">Valor por mês</label>
        <label class="input w-full">
            <span class="opacity-60">R$</span>
            <input type="number" name="amount" id="income-amount" step="0.01" min="0"
                   inputmode="decimal" placeholder="0,00" autofocus>
        </label>
    </fieldset>
    <button type="submit" class="btn btn-accent w-full mt-4" data-pending="Salvando…">
        Continuar
    </button>
</form>

<form method="post" action="{% url 'onboarding_skip' 'income' %}">
    {% csrf_token %}
    <button type="submit" class="btn btn-ghost btn-sm w-full mt-2">Agora não</button>
</form>
```

- [ ] **Step 7: Write the cards step — the closing day, in one sentence**

Create `src/backend/templates/onboarding/_step_cards.html`. The explanation is
one sentence plus a worked example that updates live from the number typed, so
the concept is *shown* rather than described (open question 4):

```html
<h2 class="card-title">Qual cartão de crédito você usa?</h2>
<p class="text-sm opacity-70">
    O dia de fechamento é o dia em que o cartão fecha a fatura — o que você
    compra depois dele cai na fatura do mês seguinte.
</p>

<form method="post" action="{% url 'onboarding_step' 'cards' %}" class="mt-4"
      x-data="{ day: 25 }">
    {% csrf_token %}
    <fieldset class="fieldset">
        <label class="label" for="card-name">Nome do cartão</label>
        <input type="text" name="name" id="card-name" class="input w-full"
               placeholder="Nubank" autocomplete="off" autofocus>

        <label class="label" for="card-closing-day">Dia de fechamento</label>
        <input type="number" name="closing_day" id="card-closing-day"
               class="input w-full" min="1" max="31" inputmode="numeric"
               x-model.number="day" value="25">
    </fieldset>

    <div class="alert alert-info mt-3 text-sm">
        <span>
            Uma compra no dia <span class="font-semibold" x-text="day"></span>
            entra na fatura deste mês; no dia
            <span class="font-semibold" x-text="day + 1"></span>, na do mês seguinte.
        </span>
    </div>

    <button type="submit" class="btn btn-accent w-full mt-4" data-pending="Salvando…">
        Continuar
    </button>
</form>

<form method="post" action="{% url 'onboarding_skip' 'cards' %}">
    {% csrf_token %}
    <button type="submit" class="btn btn-ghost btn-sm w-full mt-2">
        Não uso cartão de crédito
    </button>
</form>
```

- [ ] **Step 8: Write the capture step — the handoff**

Create `src/backend/templates/onboarding/_step_capture.html`:

```html
<h2 class="card-title">Agora o que este app faz de diferente</h2>
<p class="text-sm opacity-70">
    Fotografe um cupom fiscal. O app lê item por item, separa por categoria e
    lança tudo na fatura certa — você só confirma.
</p>

<form method="post" action="{% url 'onboarding_step' 'capture' %}" class="mt-4">
    {% csrf_token %}
    <button type="submit" class="btn btn-accent btn-lg w-full" data-pending="Abrindo…">
        📷 Fotografar um cupom
    </button>
</form>

<form method="post" action="{% url 'onboarding_skip' 'capture' %}">
    {% csrf_token %}
    <button type="submit" class="btn btn-ghost btn-sm w-full mt-2">Depois</button>
</form>
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_onboarding_flow.py -q`
Expected: PASS (13 tests)

- [ ] **Step 10: Verify the whole backend gate**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/backend/accounts/onboarding.py src/backend/accounts/urls.py \
        src/backend/templates/onboarding/ \
        src/backend/accounts/tests/test_onboarding_flow.py
git commit -m "feat(onboarding): three guided steps, all skippable, ending at the camera"
```

---

## Task 7: Empty states that teach, and point at the wedge

**Files:**
- Create: `src/backend/frontend/src/chat.ts`
- Modify: `src/backend/frontend/src/components/EmptyState.tsx`
- Modify: `src/backend/frontend/src/cards/RecentEntriesCard.tsx`
- Modify: `src/backend/frontend/src/cards/TopCategoriesCard.tsx`
- Modify: `src/backend/frontend/src/cards/EvolutionCard.tsx`
- Modify: `src/backend/frontend/src/cards/DailyTrendCard.tsx`
- Modify: `src/backend/frontend/src/cards/ProjectionCard.tsx`
- Modify: `src/backend/templates/entries/_entries_table.html`
- Modify: `src/backend/templates/consolidated/_consolidated_table.html`
- Modify: `src/backend/templates/settings/_categories_tab.html`
- Modify: `src/backend/templates/settings/_payment_methods_tab.html`
- Modify: `src/backend/templates/settings/_income_tab.html`
- Modify: `src/backend/templates/projection/_projection_table.html`
- Modify: `src/backend/finances/views/projection.py` (`build_projection_context`, ~line 129)
- Modify: `src/backend/templates/cockpit/_income_section.html`
- Modify: `src/backend/templates/cockpit/_systemic_section.html`
- Modify: `src/backend/templates/cockpit/_parcelamentos_section.html`
- Modify: `src/backend/templates/cockpit/_vencimentos_section.html`
- Test: `src/backend/finances/tests/test_empty_states.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `frontend/src/chat.ts` exporting `openChat(prompt?: string): void` — dispatches `new CustomEvent("open-chat", { detail: { prompt } })` on `window`. Task 8 makes `ChatWidget` listen for it.

**Rule for every empty state in this task:** say what will appear there, and
offer exactly one action. On the dashboard that action is the wedge — the
camera — not "add an entry manually". S11-4 is explicit.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_empty_states.py`:

```python
"""Every day-one surface renders against no data and must teach, not just shrug.

Server-rendered surfaces only. The React cards are covered by `pnpm build`
plus the visual-verdict pass, since this repo has no frontend test runner.
"""

from datetime import date

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestEmptySurfacesTeach:
    def test_the_entries_table_offers_the_camera(self, logged_client):
        body = logged_client.get(reverse("finances:entries_month", args=[2026, 8])).content.decode()

        assert "Nenhuma entrada neste mês" in body
        assert "cupom" in body

    def test_the_consolidated_view_explains_what_will_appear(self, logged_client):
        body = logged_client.get(reverse("finances:consolidated")).content.decode()

        assert "categoria" in body.lower()

    def test_the_categories_tab_says_what_a_category_is_for(self, logged_client):
        body = logged_client.get(reverse("finances:settings_categories")).content.decode()

        assert "como o app agrupa seus gastos" in body

    def test_the_payment_methods_tab_explains_the_closing_day(self, logged_client):
        body = logged_client.get(reverse("finances:settings_payment_methods")).content.decode()

        assert "fecha a fatura" in body

    def test_the_income_tab_says_why_income_matters(self, logged_client):
        body = logged_client.get(reverse("finances:settings_income")).content.decode()

        assert "quanto sobra" in body

    def test_the_projection_explains_itself_before_there_is_data(self, logged_client):
        """Keyed on the household having no data, NOT on `rows` being empty.

        `_default_start` returns last month, which is after the projection
        origin in every realistic case, so `build_projection` returns a full
        window of zero rows and the `{% if not rows %}` branch never fires for
        a new household. It stays as the pre-origin fallback it already was.
        """
        body = logged_client.get(reverse("finances:projection")).content.decode()

        assert "Nada para projetar ainda" in body
        assert "estimar os próximos meses" in body

    def test_the_projection_stops_teaching_once_there_is_data(self, logged_client, household, user):
        from model_bakery import baker

        baker.make("finances.Income", household=household, created_by=user,
                   month=date(2026, 8, 1), amount=1000)

        body = logged_client.get(reverse("finances:projection")).content.decode()

        assert "Nada para projetar ainda" not in body


@pytest.mark.django_db
class TestTheCockpitSectionsTeach:
    """The cockpit is four HTMX fragments, each of which a new household hits empty."""

    def test_the_income_section_says_where_income_comes_from(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_income", args=[2026, 8])
        ).content.decode()

        assert "quanto sobra" in body

    def test_the_systemic_section_explains_what_a_systemic_expense_is(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_systemic", args=[2026, 8])
        ).content.decode()

        assert "todo mês" in body

    def test_the_parcelamentos_section_explains_itself(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_parcelamentos", args=[2026, 8])
        ).content.decode()

        assert "parcelada" in body

    def test_the_vencimentos_section_points_at_the_card_setup(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_vencimentos", args=[2026, 8])
        ).content.decode()

        assert reverse("finances:settings_payment_methods") in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_empty_states.py -q`
Expected: FAIL — `assert 'cupom' in body` and the closing-day / "quanto sobra" assertions.

- [ ] **Step 3: Add the chat opener**

Create `src/backend/frontend/src/chat.ts`:

```ts
/**
 * The one way any surface asks the chat widget to open.
 *
 * A window event rather than a shared store: the chat is mounted as its own
 * React root by `mount.tsx`, so a card in a different root has no other way to
 * reach it, and a global is worse than an event because it would have to exist
 * before either root mounts.
 */
export function openChat(prompt?: string): void {
  window.dispatchEvent(new CustomEvent("open-chat", { detail: { prompt } }));
}
```

- [ ] **Step 4: Let `EmptyState` carry a button, not only a link**

Replace `src/backend/frontend/src/components/EmptyState.tsx`:

```tsx
interface EmptyStateProps {
  emoji: string;
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
  /** An in-page action — opening the chat, mostly. Wins over `actionHref`. */
  onAction?: () => void;
}

export default function EmptyState({
  emoji,
  title,
  description,
  actionHref,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <span className="text-4xl mb-3">{emoji}</span>
      <p className="font-semibold text-sm text-base-content">{title}</p>
      <p className="text-xs text-base-content/60 mt-1">{description}</p>
      {actionLabel && onAction && (
        <button type="button" className="btn btn-xs btn-accent mt-3" onClick={onAction}>
          {actionLabel}
        </button>
      )}
      {actionLabel && !onAction && actionHref && (
        <a href={actionHref} className="btn btn-xs btn-accent mt-3">{actionLabel}</a>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Point the dashboard cards at the wedge**

In each card, import the opener and replace the empty state's props.

`RecentEntriesCard.tsx` — replace the existing `<EmptyState .../>` with:

```tsx
          <EmptyState
            emoji="📷"
            title="Nada lançado ainda"
            description="Fotografe um cupom fiscal — o app lê os itens, separa por categoria e lança tudo aqui."
            actionLabel="Fotografar um cupom"
            onAction={() => openChat()}
          />
```

`TopCategoriesCard.tsx`:

```tsx
          <EmptyState
            emoji="🥗"
            title="Sem gastos por categoria"
            description="Assim que houver lançamentos, aqui aparece para onde o dinheiro está indo."
            actionLabel="Fotografar um cupom"
            onAction={() => openChat()}
          />
```

`EvolutionCard.tsx`:

```tsx
          <EmptyState
            emoji="📈"
            title="Sem movimentação"
            description="A partir do segundo mês com lançamentos, esta curva mostra se você está gastando mais ou menos."
            actionLabel="Fotografar um cupom"
            onAction={() => openChat()}
          />
```

`DailyTrendCard.tsx`:

```tsx
          <EmptyState
            emoji="📅"
            title="Sem gastos neste mês"
            description="Aqui aparece o gasto de cada dia, para você ver em que semana o mês aperta."
            actionLabel="Fotografar um cupom"
            onAction={() => openChat()}
          />
```

`ProjectionCard.tsx`:

```tsx
          <EmptyState
            emoji="🔮"
            title="Ainda não dá para projetar"
            description="Informe sua renda em Configurações e lance alguns gastos — aí o app estima quanto sobra nos próximos meses."
            actionHref="/settings/income/"
            actionLabel="Informar renda"
          />
```

Add `import { openChat } from "../chat";` to the four cards that use it.

- [ ] **Step 6: Rewrite the server-rendered empty states**

`templates/entries/_entries_table.html` — replace lines 32-33:

```html
                    <p class="font-semibold text-sm">Nenhuma entrada neste mês</p>
                    <p class="text-xs text-base-content/60 mt-1">
                        Fotografe um cupom pelo chat e o app lança tudo aqui — ou use o botão “+” para digitar.
                    </p>
```

`templates/consolidated/_consolidated_table.html` — replace lines 45-46:

```html
    <p class="font-semibold mt-2">Nenhum gasto neste mês</p>
    <p class="text-sm">
        Esta tela soma o mês inteiro por categoria. Lance um gasto e ele aparece aqui.
    </p>
```

`templates/settings/_categories_tab.html` — replace line 67:

```html
                <p class="text-xs text-base-content/60 mt-1">
                    Nenhuma categoria. Elas são como o app agrupa seus gastos — crie a primeira no formulário acima.
                </p>
```

`templates/settings/_payment_methods_tab.html` — replace line 35:

```html
                <p class="text-xs text-base-content/60 mt-1">
                    Nenhuma forma de pagamento. Para cartão de crédito informe o dia em que ele fecha a fatura — o que você compra depois cai na fatura do mês seguinte.
                </p>
```

`templates/settings/_income_tab.html` — replace line 68:

```html
                <p class="text-xs text-base-content/60 mt-1">
                    Nenhuma renda cadastrada. É com ela que o app calcula quanto sobra no mês.
                </p>
```

**The projection needs a view change, not only a template one.**
`_default_start` returns *last month*, which is after the projection origin in
every realistic case — so `build_projection` hands back a full window of
zero-filled rows and the existing `{% if not rows %}` branch never fires for a
new household. Keying the teaching state off `rows` would ship dead code.

In `finances/views/projection.py`, in the dict `build_projection_context`
returns (~line 129), add one key:

```python
        # A new household gets a full window of zero rows, not an empty list —
        # so "is there anything to project?" has to ask the data, not the rows.
        "has_any_data": any(
            r["total"] or r["income"] for r in rows
        ),
```

`templates/projection/_projection_table.html` — leave the existing
`{% if not rows %}` block (it is the pre-origin fallback and still correct) and
add, immediately after it:

```html
{% if rows and not has_any_data %}
<div class="text-center py-10 text-base-content/60">
    <span class="text-3xl">🔮</span>
    <p class="font-semibold mt-2">Nada para projetar ainda</p>
    <p class="text-sm">
        A projeção usa sua renda e seus lançamentos para estimar os próximos meses.
    </p>
</div>
{% endif %}
```

- [ ] **Step 6b: Rewrite the four cockpit sections**

`templates/cockpit/_income_section.html` — replace line 25:

```html
        <tr><td colspan="3" class="text-center opacity-60 py-6">
            Nenhuma renda neste mês. É com ela que o app calcula quanto sobra.
        </td></tr>
```

`templates/cockpit/_systemic_section.html` — replace line 43:

```html
        <tr><td colspan="3" class="text-center opacity-60 py-6">
            Nenhum gasto sistemático ativo. São as contas que chegam todo mês — aluguel, luz, internet.
        </td></tr>
```

`templates/cockpit/_parcelamentos_section.html` — replace line 23:

```html
        <tr><td colspan="4" class="text-center opacity-60 py-6">
            Nenhum parcelamento neste mês. Uma compra parcelada aparece aqui, parcela por parcela.
        </td></tr>
```

`templates/cockpit/_vencimentos_section.html` — replace line 23:

```html
        <tr><td colspan="2" class="text-center opacity-60 py-6">
            Nenhum cartão de crédito ativo.
            <a href="{% url 'finances:settings_payment_methods' %}" class="link">Cadastrar um cartão</a>
        </td></tr>
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_empty_states.py -q`
Expected: PASS (11 tests)

- [ ] **Step 8: Build the frontend**

Run: `cd src/backend/frontend && pnpm build`
Expected: `tsc` clean, Vite build succeeds.

- [ ] **Step 9: Commit the build artifacts too**

`mount.js` and `tailwind.css` are git-tracked in this repo, and a Tailwind
rebuild is required because new class names appeared.

```bash
cd src/backend/frontend && pnpm build && cd -
uv run python src/backend/manage.py tailwind build --force
git add src/backend/frontend/src src/backend/static/frontend/mount.js \
        src/backend/static/css/tailwind.css \
        src/backend/templates/entries/_entries_table.html \
        src/backend/templates/consolidated/_consolidated_table.html \
        src/backend/templates/settings/_categories_tab.html \
        src/backend/templates/settings/_payment_methods_tab.html \
        src/backend/templates/settings/_income_tab.html \
        src/backend/templates/projection/_projection_table.html \
        src/backend/templates/cockpit/ src/backend/finances/views/projection.py \
        src/backend/finances/tests/test_empty_states.py
git commit -m "feat(onboarding): empty states that teach and point at the camera"
```

---

## Task 8: First-run assistant behaviour

**Files:**
- Modify: `src/backend/frontend/src/cards/ChatWidget.tsx`
- Test: `src/backend/core/tests/test_first_run_handoff.py`

**Interfaces:**
- Consumes: the `open-chat` window event (Task 7).
- Produces: nothing later tasks import.

**What this adds:**
1. `ChatWidget` listens for `open-chat` and opens itself.
2. When the loaded history is empty, it renders a concrete pt-BR invitation
   with tappable examples instead of a blank panel.
3. `/?comecar=foto` — the handoff URL Task 6 redirects to — opens the chat on
   arrival, so the flow ends inside the wedge.

Suggestion chips deliberately name **no** category or payment method: S11-5
requires the first interaction not to assume the user has learned the
catalogue, and the assistant's accent- and case-lenient `_resolve_by_name`
(fixed in D02) is what makes that safe.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_first_run_handoff.py`:

```python
"""The last onboarding step lands on a page that opens the chat by itself."""

import pytest


@pytest.mark.django_db
def test_the_handoff_url_renders_the_dashboard_with_the_chat_flag(logged_client):
    response = logged_client.get("/?comecar=foto")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-react-component="ChatWidget"' in body
    assert 'data-autostart="foto"' in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_first_run_handoff.py -q`
Expected: FAIL — `assert 'data-autostart="foto"' in body`

- [ ] **Step 3: Pass the flag through the template and the mount**

In `src/backend/templates/base.html`, replace the chat island line (line 57):

```html
    <!-- Floating chat island (React) -->
    <div data-react-component="ChatWidget" data-api-url="/api/assistant/"
         data-autostart="{{ request.GET.comecar|default:'' }}"></div>
```

In `src/backend/frontend/src/mount.tsx`, read and forward the attribute — replace
the body of `mountAll`:

```tsx
function mountAll() {
  const elements = document.querySelectorAll("[data-react-component]");
  elements.forEach((el) => {
    const name = el.getAttribute("data-react-component");
    const apiUrl = el.getAttribute("data-api-url") || "";
    const sparkUrl = el.getAttribute("data-spark-url") ?? undefined;
    const autostart = el.getAttribute("data-autostart") || undefined;
    if (name && COMPONENTS[name]) {
      const Component = COMPONENTS[name];
      const root = createRoot(el);
      root.render(<Component apiUrl={apiUrl} sparkUrl={sparkUrl} autostart={autostart} />);
    }
  });
}
```

- [ ] **Step 4: Make `ChatWidget` open on demand and greet a first-time user**

In `src/backend/frontend/src/cards/ChatWidget.tsx`:

**(a)** Add `autostart` to the component's props interface (alongside `apiUrl`):

```tsx
  autostart?: string;
```

**(b)** Track whether history came back empty. Beside the existing `messages`
state (line ~209), add:

```tsx
  const [historyLoaded, setHistoryLoaded] = useState(false);
```

**(c)** Replace the history effect (lines 245-253) so it records the load:

```tsx
  // Load history on first open
  useEffect(() => {
    if (isOpen && messages.length === 0 && !historyLoaded) {
      fetch(`${apiUrl}history/`, { credentials: "same-origin" })
        .then((r) => r.json())
        .then((data: Message[]) => setMessages(data))
        .catch(() => {})
        .finally(() => setHistoryLoaded(true));
    }
  }, [isOpen, apiUrl, historyLoaded, messages.length]);
```

**(d)** Open on the `open-chat` event, and on the onboarding handoff. Add a new
effect next to the other mount-time effects:

```tsx
  // Any surface can ask for the chat (see frontend/src/chat.ts); the last
  // onboarding step asks by loading `/?comecar=foto`, which is the whole point
  // of S11-3's "ends by handing the user to the activation moment".
  useEffect(() => {
    const onOpenChat = () => setIsOpen(true);
    window.addEventListener("open-chat", onOpenChat);
    if (autostart === "foto") setIsOpen(true);
    return () => window.removeEventListener("open-chat", onOpenChat);
  }, [autostart]);
```

**(e)** Render the first-run invitation. In the messages area, immediately
before the existing message list rendering, add:

```tsx
          {historyLoaded && messages.length === 0 && (
            <div className="p-4 text-sm">
              <p className="font-semibold">Oi! Eu lanço seus gastos para você.</p>
              <p className="opacity-70 mt-1">
                Não precisa saber o nome das categorias — eu descubro. Tente
                assim:
              </p>
              <div className="flex flex-col gap-2 mt-3">
                <button
                  type="button"
                  className="btn btn-sm btn-outline justify-start"
                  onClick={() => setInput("me manda uma foto do cupom")}
                >
                  📷 Me manda uma foto do cupom
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-outline justify-start"
                  onClick={() => setInput("gastei 45 no mercado no crédito")}
                >
                  💬 “gastei 45 no mercado no crédito”
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-outline justify-start"
                  onClick={() => setInput("quanto gastei este mês?")}
                >
                  📊 “quanto gastei este mês?”
                </button>
              </div>
            </div>
          )}
```

The photo chip fills the input rather than firing a request: the user still has
to attach the picture, and pretending otherwise would send a turn the assistant
cannot answer.

- [ ] **Step 5: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_first_run_handoff.py -q`
Expected: PASS

- [ ] **Step 6: Build and check types**

Run: `cd src/backend/frontend && pnpm build`
Expected: `tsc` clean. If `tsc` complains that `sparkUrl`/`autostart` are not on
some card's props, add them as optional to the shared props type rather than
casting.

- [ ] **Step 7: Commit**

```bash
cd src/backend/frontend && pnpm build && cd -
uv run python src/backend/manage.py tailwind build --force
git add src/backend/frontend/src src/backend/static/frontend/mount.js \
        src/backend/static/css/tailwind.css src/backend/templates/base.html \
        src/backend/core/tests/test_first_run_handoff.py
git commit -m "feat(assistant): a first-run invitation, and one way for any surface to open the chat"
```

---

## Task 9: A projection origin that means something to a new household

**Files:**
- Modify: `src/backend/accounts/models.py` (`Household.projection_origin_month`)
- Create: `src/backend/accounts/migrations/0009_household_projection_origin_month.py` (generated, plus a data step)
- Modify: `src/backend/finances/services/projection.py` (`_projection_origin`, `projection_origin`, `build_projection`)
- Modify: `src/backend/finances/views/entries.py:66,78`
- Modify: `src/backend/finances/management/commands/dump_ledger_totals.py:63,64`
- Test: `src/backend/finances/tests/test_projection_origin.py`

**Interfaces:**
- Consumes: `accounts.models.Household`.
- Produces: `finances.services.projection.projection_origin(household) -> date` — **the signature changes from no arguments to one required argument.** Every call site is listed above; there are five.

**The rule:**

```
origin = household.projection_origin_month           if set
       = first month with any Income or Entry        if the household has data
       = the household's creation month              otherwise
```

The existing production household keeps `2025-11` because the migration writes
`settings.PROJECTION_ORIGIN_MONTH` into `projection_origin_month` for every
household that exists at migration time. New households get `NULL` and derive
their own — which is also what makes a CSV import of three years of history
work, where a global floor would have silently discarded the lot.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_projection_origin.py`:

```python
"""The projection's origin is per household, because 'nothing before Nov 2025
counts' is one household's migration history, not a fact about money."""

from datetime import date

import pytest
from model_bakery import baker

from finances.services.projection import projection_origin


@pytest.mark.django_db
class TestOrigin:
    def test_an_explicit_origin_wins(self, household):
        household.projection_origin_month = date(2025, 11, 1)
        household.save(update_fields=["projection_origin_month"])

        assert projection_origin(household) == date(2025, 11, 1)

    def test_without_one_it_is_the_first_month_with_data(self, household, user):
        baker.make("finances.Income", household=household, created_by=user,
                   month=date(2026, 3, 1), amount=1000)

        assert projection_origin(household) == date(2026, 3, 1)

    def test_an_entry_counts_as_data_too(self, household, user):
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make("finances.PaymentMethod", household=household,
                             created_by=user, type="pix")
        baker.make("finances.Entry", household=household, created_by=user,
                   category=category, payment_method=payment,
                   date=date(2026, 2, 10), amount=10)

        assert projection_origin(household) == date(2026, 2, 1)

    def test_the_earliest_of_the_two_wins(self, household, user):
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make("finances.PaymentMethod", household=household,
                             created_by=user, type="pix")
        baker.make("finances.Entry", household=household, created_by=user,
                   category=category, payment_method=payment,
                   date=date(2026, 2, 10), amount=10)
        baker.make("finances.Income", household=household, created_by=user,
                   month=date(2026, 1, 1), amount=1000)

        assert projection_origin(household) == date(2026, 1, 1)

    def test_an_empty_household_falls_back_to_its_creation_month(self, household):
        expected = household.created_at.date().replace(day=1)

        assert projection_origin(household) == expected

    def test_no_household_at_all_does_not_raise(self):
        """Fail closed like every other household-less path in this codebase."""
        assert projection_origin(None) is not None


@pytest.mark.django_db
class TestImportedHistory:
    def test_history_older_than_the_old_global_floor_is_kept(self, household, user):
        """A CSV import of 2024 must not be silently discarded, which is exactly
        what a global 2025-11 floor did."""
        category = baker.make("finances.Category", household=household, created_by=user)
        payment = baker.make("finances.PaymentMethod", household=household,
                             created_by=user, type="pix")
        baker.make("finances.Entry", household=household, created_by=user,
                   category=category, payment_method=payment,
                   date=date(2024, 5, 3), amount=10)

        assert projection_origin(household) == date(2024, 5, 1)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_projection_origin.py -q`
Expected: FAIL — `TypeError: projection_origin() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: Add the field**

In `src/backend/accounts/models.py`, add to `Household` after `preferred_tier`:

```python
    # The first month this household's projection counts. NULL means "derive it
    # from the household's own data", which is right for everyone who signs up.
    # It is set explicitly only for the households that predate E11, whose early
    # months are migration and seed noise — see the data migration that fills it.
    projection_origin_month = models.DateField(null=True, blank=True)
```

- [ ] **Step 4: Generate the migration and add the backfill**

Run: `POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations accounts --name household_projection_origin_month`

Then edit the generated file to append a data operation after the `AddField`:

```python
from datetime import date

from django.conf import settings as django_settings
from django.db import migrations, models


def _configured_origin():
    """The old global floor, parsed exactly as `_projection_origin` used to."""
    raw = getattr(django_settings, "PROJECTION_ORIGIN_MONTH", None)
    if isinstance(raw, date):
        return raw.replace(day=1)
    if isinstance(raw, str) and raw.strip():
        try:
            year, month = (int(p) for p in raw.split("-")[:2])
            return date(year, month, 1)
        except (ValueError, TypeError):
            pass
    return date(2025, 11, 1)


def freeze_existing_origins(apps, schema_editor):
    """Every household that exists right now keeps the floor it has been using.

    Without this, deploying E11 would move the operator's own `acumulado`,
    because their ledger contains pre-origin seed rows the global floor was
    put there to exclude.
    """
    Household = apps.get_model("accounts", "Household")
    Household.objects.filter(projection_origin_month__isnull=True).update(
        projection_origin_month=_configured_origin()
    )


def unfreeze(apps, schema_editor):
    """Reverse: clear what the forward step wrote. The column goes away with the
    AddField's own reverse, so this only has to be non-destructive."""
    Household = apps.get_model("accounts", "Household")
    Household.objects.update(projection_origin_month=None)
```

and add to the migration's `operations` list, after the `AddField`:

```python
        migrations.RunPython(freeze_existing_origins, unfreeze),
```

- [ ] **Step 5: Rewrite the origin resolver**

In `src/backend/finances/services/projection.py`, replace `_projection_origin`
and `projection_origin` (lines 31-54) with:

```python
def projection_origin(household) -> date:
    """First month that counts for ``household``. Nothing earlier enters at all.

    Per household rather than global (E11). The old
    ``settings.PROJECTION_ORIGIN_MONTH`` recorded one fact about one ledger —
    that everything before Nov 2025 was migration and seed noise — and applying
    it to a stranger produced a projection anchored two years before they had
    heard of the product. Worse, it silently discarded imported history: a CSV
    of 2024 landed below the floor and vanished from the ``acumulado``.

    Resolution order:

    1. ``household.projection_origin_month`` when set. The data migration set
       it for every household that existed when E11 shipped, so their numbers
       did not move.
    2. The earliest month with any income or entry.
    3. The household's own creation month, for a household with no data yet.
    """
    if household is None:
        return DEFAULT_PROJECTION_ORIGIN

    explicit = getattr(household, "projection_origin_month", None)
    if explicit:
        return explicit.replace(day=1)

    inc_min = Income.objects.for_household(household).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.for_household(household).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    if candidates:
        return min(candidates).replace(day=1)

    created = getattr(household, "created_at", None)
    if created is not None:
        return created.date().replace(day=1)
    return DEFAULT_PROJECTION_ORIGIN
```

- [ ] **Step 6: Update the five call sites**

`finances/services/projection.py:95` (inside `build_projection`):

```python
    origin = projection_origin(household)
```

`finances/views/entries.py:66` and `:78` — both dict literals are inside the
same module-level helper, which already binds `household` (it is the argument
`Income.objects.for_household(household)` uses at line 45). Both become:

```python
            "origin_month": projection_origin(household),
```

`finances/management/commands/dump_ledger_totals.py:63-64` — inside
`for household in Household.objects.order_by("name"):`, so `household` is the
loop variable:

```python
            start = entries["first"] or projection_origin(household)
            start = max(start.replace(day=1), projection_origin(household))
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_projection_origin.py -q`
Expected: PASS (7 tests)

- [ ] **Step 8: Run the projection and entries suites — this changed a shared signature**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/ -q`
Expected: PASS. Any test that patched `settings.PROJECTION_ORIGIN_MONTH` to move
the origin must now set `household.projection_origin_month` instead — the
setting is only the migration's source from here.

- [ ] **Step 9: Verify the migration is reversible**

Run:
```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate accounts
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate accounts <previous_number>
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate accounts
```
Expected: all three succeed with no error.

- [ ] **Step 10: Commit**

```bash
git add src/backend/accounts/models.py src/backend/accounts/migrations/ \
        src/backend/finances/services/projection.py \
        src/backend/finances/views/entries.py \
        src/backend/finances/management/commands/dump_ledger_totals.py \
        src/backend/finances/tests/test_projection_origin.py
git commit -m "feat(projection): a per-household origin month, derived rather than global"
```

---

## Task 10: The activation report, and writing the definition down

**Files:**
- Create: `src/backend/core/management/commands/activation_report.py`
- Create: `docs/architecture/activation-event.md`
- Modify: `docs/runbook.md` (new section)
- Modify: `README.md` (one pointer line in the quickstart)
- Test: `src/backend/core/tests/test_activation_report.py`

**Interfaces:**
- Consumes: `core.models.ProductEvent`, `core.events.EventName` (Task 1).
- Produces: `python manage.py activation_report [--days N]`, printing signup count, activation count, activation rate, and time-to-activation p50/p90.

E14 owns the *analysis*; this command is the minimum E11's DoD requires —
"time from signup to activation is measurable" — and it is what the unaided
walkthrough in Task 11 is checked against.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_activation_report.py`:

```python
"""`activation_report` is E11's evidence that time-to-activation is measurable."""

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command

from core.events import EventName
from core.models import ProductEvent


def _event(household, name, at, user=None):
    event = ProductEvent.objects.create(
        household=household, name=name, user=user, once=True
    )
    ProductEvent.objects.filter(pk=event.pk).update(created_at=at)
    return event


@pytest.mark.django_db
class TestActivationReport:
    NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    def test_it_reports_zero_without_crashing(self):
        out = StringIO()

        call_command("activation_report", stdout=out)

        assert "Cadastros: 0" in out.getvalue()

    def test_it_counts_signups_and_activations(self, household, other_household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=2), user)
        _event(household, EventName.ACTIVATED, self.NOW - timedelta(days=2) + timedelta(hours=1), user)
        _event(other_household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        out = StringIO()

        call_command("activation_report", stdout=out)

        body = out.getvalue()
        assert "Cadastros: 2" in body
        assert "Ativados: 1" in body
        assert "50.0%" in body

    def test_it_reports_time_to_activation(self, household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        _event(household, EventName.ACTIVATED, self.NOW - timedelta(days=1) + timedelta(minutes=30), user)
        out = StringIO()

        call_command("activation_report", stdout=out)

        assert "p50" in out.getvalue()
        assert "30" in out.getvalue()

    def test_days_narrows_the_window(self, household, other_household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=40), user)
        _event(other_household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        out = StringIO()

        call_command("activation_report", "--days", "7", stdout=out)

        assert "Cadastros: 1" in out.getvalue()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_activation_report.py -q`
Expected: FAIL — `CommandError: Unknown command: 'activation_report'`

- [ ] **Step 3: Write the command**

Create `src/backend/core/management/commands/activation_report.py`:

```python
"""How many people got to the moment this product exists for, and how long it took.

E11's Definition of Done requires time-to-activation to be measurable. E14 owns
the dashboard and the rest of the funnel; this is the command that proves the
number exists, and the one the unaided walkthrough is checked against.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.events import EventName
from core.models import ProductEvent


def _percentile(sorted_values, fraction):
    """Nearest-rank, so a single sample reports itself rather than an average."""
    if not sorted_values:
        return None
    index = min(int(round(fraction * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return sorted_values[index]


class Command(BaseCommand):
    help = "Signups, activations, activation rate and time-to-activation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Only count signups from the last N days (default 90).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])

        signups = {
            row.household_id: row.created_at
            for row in ProductEvent.objects.filter(
                name=EventName.SIGNUP, created_at__gte=cutoff
            )
        }
        activations = {
            row.household_id: row.created_at
            for row in ProductEvent.objects.filter(name=EventName.ACTIVATED)
        }

        activated = [hh for hh in signups if hh in activations]
        deltas = sorted(
            (activations[hh] - signups[hh]).total_seconds() / 60 for hh in activated
        )

        rate = (len(activated) / len(signups) * 100) if signups else 0.0
        self.stdout.write(f"Janela: últimos {options['days']} dia(s)")
        self.stdout.write(f"Cadastros: {len(signups)}")
        self.stdout.write(f"Ativados: {len(activated)}")
        self.stdout.write(f"Taxa de ativação: {rate:.1f}%")

        p50 = _percentile(deltas, 0.5)
        p90 = _percentile(deltas, 0.9)
        if p50 is None:
            self.stdout.write("Tempo até ativação: sem amostras ainda.")
            return
        self.stdout.write(
            f"Tempo até ativação (min): p50 {p50:.0f} · p90 {p90:.0f} "
            f"(n={len(deltas)})"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_activation_report.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the activation-event definition**

Create `docs/architecture/activation-event.md`:

```markdown
# The activation event

**Decided:** 2026-08-15, in E11 (`docs/backlog/E11-onboarding-and-activation.md`, S11-1).
**Read by:** E14 (product analytics), E15 (the beta → GA decision).

## The event

> **A household is activated the first time it confirms a photographed receipt
> into its ledger.**

Emitted as `ProductEvent(name="activated", once=True)` from
`assistant.agents.tools.commit_receipt` — the single code path where an
extracted receipt becomes real `Entry` rows.

## Why this and not something easier to count

*Signed up* measures a form submission. *Created an entry* measures a
spreadsheet with extra steps. Neither is the moment the user learns why this
product is not the thing they already have.

Confirming a receipt is the wedge (PD-1), it is the thing incumbents with bank
feeds structurally cannot do, and it can only happen after the user has a
category, a payment method and a working chat — so it certifies setup as a side
effect rather than measuring it separately.

## Precise definition, for E14

| Question | Answer |
|---|---|
| Unit | The **household**, not the user. A second member joining an activated household does not activate it again. |
| Cardinality | At most one per household, enforced by a partial unique index (`one_once_event_per_household`). |
| T0 for time-to-activation | The household's `signup` event, not `User.date_joined`. |
| Does a manually typed entry count? | No. |
| Does a chat-captured entry count? | No — it emits `first_ai_entry` instead. |
| Does a CSV import count? | No. |
| What if the receipt is later deleted? | The event stands. It records that the moment happened. |

## The companion event

`first_ai_entry` (also once per household) is emitted by **any** assistant write
path — `create_entry` from chat, and `commit_receipt`. Its `metadata.source` is
`"chat"` or `"receipt"`. E14 uses it for the AI-versus-manual ratio, which S14-3
calls the most important number in the product.

## Where the numbers come from

    uv run python src/backend/manage.py activation_report --days 30

See `docs/runbook.md`, "Onboarding & activation".
```

- [ ] **Step 6: Add the runbook section**

Append to `docs/runbook.md`:

````markdown
## Onboarding & activation

### The activation report

    uv run python src/backend/manage.py activation_report --days 30

Prints:

    Janela: últimos 30 dia(s)
    Cadastros: 12
    Ativados: 7
    Taxa de ativação: 58.3%
    Tempo até ativação (min): p50 9 · p90 214 (n=7)

`Cadastros` counts `signup` events inside the window; `Ativados` counts how many
of *those* households have ever activated, so the rate cannot exceed 100% when a
household signs up in one window and activates in the next.

**Common failure:** `Tempo até ativação: sem amostras ainda.` means signups exist
but no household has confirmed a receipt. That is a real product result, not a
broken command — check it against the funnel before assuming instrumentation is
missing.

The event's definition lives in `docs/architecture/activation-event.md`. Do not
redefine it in a query.

### Seeding a household that predates automatic seeding

Signup seeds the starter catalogue by itself. For an account created before E11,
or by `createsuperuser` (which never fires `user_signed_up`):

    uv run python src/backend/manage.py seed_starter_data --household <uuid>

Prints `Casa de fulano: 14 categoria(s), 2 forma(s) de pagamento, 3 regra(s).`
Idempotent — a second run prints zeros.

**Common failure:** `Casa '<uuid>' não encontrada.` — the argument is the
`Household` UUID, not the user's.

### Replaying the guided setup

To walk a household through setup again (for a walkthrough rehearsal):

    uv run python src/backend/manage.py shell -c "
    from accounts.models import OnboardingState
    OnboardingState.objects.filter(household_id='<uuid>').delete()"

The next page load redirects that household back to `/casa/comecar/`.
````

- [ ] **Step 7: Point at the runbook from the README**

In `README.md`, in the quickstart section, add one line:

```markdown
Operator procedures — activation report, seeding, deploys, recovery — live in [`docs/runbook.md`](docs/runbook.md).
```

- [ ] **Step 8: Commit**

```bash
git add src/backend/core/management/commands/activation_report.py \
        src/backend/core/tests/test_activation_report.py \
        docs/architecture/activation-event.md docs/runbook.md README.md
git commit -m "feat(activation): the activation report, and the definition it computes"
```

---

## Task 11: The unaided walkthrough

**Files:**
- Create: `docs/superpowers/evidence/e11-walkthrough/README.md`
- Modify: `docs/backlog/E11-onboarding-and-activation.md` (tick the DoD boxes, set frontmatter `status: review`)
- Modify: `docs/backlog/INDEX.md` (§4 table row for E11)

**This task has no code.** It is the epic's stated evidence: *"an unaided
walkthrough has been done by a real person who has not seen the product"*, on a
phone. A passing suite is explicitly not sufficient for E11.

**Interfaces:** none.

- [ ] **Step 1: Run the full Definition of Done first**

Run:
```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
cd src/backend/frontend && pnpm build && cd -
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations --check --dry-run
```
Expected: all four pass. Paste the output into the walkthrough record in Step 3.

- [ ] **Step 2: Verify the flow renders on a phone viewport**

Use `oh-my-claudecode:visual-verdict` (or Playwright directly) at **390 × 844**
against a locally running server, for these four screens:

1. `/casa/comecar/` — income step
2. `/casa/comecar/` after skipping income — the card step, with the closing-day
   example visible without scrolling
3. `/casa/comecar/` after skipping cards — the capture step
4. `/?comecar=foto` — the dashboard with the chat open and the first-run
   invitation showing

Record what you saw. A screen where the primary button is below the fold on a
390px viewport is a failure, not a note.

- [ ] **Step 3: Create the walkthrough record**

Create `docs/superpowers/evidence/e11-walkthrough/README.md`:

```markdown
# E11 · Unaided walkthrough

**Date:**
**Participant:** (someone who has not seen this product — not the operator)
**Device:** (make, model, browser; the PWA or the TWA)
**Build:** (git SHA, and the deployed revision if not local)

## Protocol

Hand them a phone at the signup screen and say exactly this, then say nothing else:

> "Este app registra os gastos da casa. Faça o que achar que deve fazer."

Do not explain. Do not answer questions with answers — answer with
"o que você faria?". Note the timestamp when they start, and the timestamp when
a receipt is confirmed into the ledger.

Have a real supermarket receipt ready to photograph.

## What to record

| Moment | Timestamp | Notes |
|---|---|---|
| Signup submitted | | |
| Verification email opened | | |
| Guided setup opened | | |
| Income step | | filled / skipped, and why |
| Cards step | | did the closing-day sentence land? |
| Capture step | | |
| Photo taken | | |
| Receipt confirmed — **ACTIVATION** | | |

**Time to activation:** ______ minutes.

Cross-check against the command:

    uv run python src/backend/manage.py activation_report --days 1

## Friction points

One line each. Verbatim quotes where you have them — a paraphrase loses the
thing that made it friction.

1.
2.
3.

## What was NOT understood

Specifically: did they understand the closing day? Did they know the chat could
read a photo before being told?

## Verdict

- [ ] Reached activation unaided
- [ ] Needed one hint (record which)
- [ ] Did not reach activation

## DoD command output

(paste the four commands from Task 11 Step 1)
```

- [ ] **Step 4: Run the walkthrough and fill the record in**

Do not fill this in from imagination. An unfilled record is honest; an invented
one poisons every decision E14 makes on top of it.

- [ ] **Step 5: Update the epic and the index**

In `docs/backlog/E11-onboarding-and-activation.md`:
- set frontmatter `status: review`
- tick each Observable assertion that is genuinely true, and **leave unticked
  any that is not**, with a one-line footnote saying why — the convention every
  other closed epic in this backlog follows (see E07's ², E08's ³, E09's ⁴).

In `docs/backlog/INDEX.md` §4, update E11's Status cell.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/e11-walkthrough/ \
        docs/backlog/E11-onboarding-and-activation.md docs/backlog/INDEX.md
git commit -m "docs(E11): the unaided walkthrough record and the epic's status"
```

---

## Definition of Done (from the epic)

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
cd src/backend/frontend && pnpm build
```

| Assertion | Task |
|---|---|
| The activation event is documented in this repo and emitted as a measurable event | 1, 2, 10 |
| A brand-new household can record an entry with zero manual setup | 3 |
| Seeded categories align with the assistant's category rules, verified by test | 3 |
| Guided setup is at most five steps, every one skippable, progress resumable | 4, 5, 6 |
| Every listed surface has a purposeful empty state | 7 |
| An unaided walkthrough has been done by a real person who has not seen the product | 11 |
| The walkthrough was performed on a phone | 11 |
| Time from signup to activation is measurable | 1, 2, 10 |

## Out of scope (do not drag these in)

- Measuring activation rate and retention **over time**, the funnel's remaining
  steps, the operator dashboard, and the feedback channel → **E14**. This epic
  emits the activation event and one report; E14 analyses.
- Paywall and trial mechanics → **E15**.
- Marketing landing page → **E17**.
- In-app tours or a tooltip system beyond the setup flow — YAGNI.
- Redesigning the dashboard.
