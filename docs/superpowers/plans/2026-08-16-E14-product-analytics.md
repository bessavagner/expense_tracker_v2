# E14 · Product analytics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The four metrics that decide whether this product works — exposure, activation rate, time-to-value, and D7 retention — are measured on real beta users, so the GA decision is made on evidence rather than optimism.

**Architecture:** E11 already shipped the foundation this epic was written before:
`core.models.ProductEvent` (household-scoped, PII-free, with a partial unique index
making "once per household" a database fact), `core.events.emit` / `emit_once`, a
six-name funnel, and `activation_report`. E14 therefore **extends** rather than
builds — three new event names, one derived-metrics command, one staff-only
dashboard, and one feedback model. Everything is computed from Postgres; no
analytics vendor, because that would be another sub-processor on E13's inventory
for numbers this database already holds.

**Tech Stack:** Django 6, DRF, django-allauth signals, pytest + `time-machine`,
Django templates + HTMX (the operator dashboard is not a React island).

**Spec:** [`docs/backlog/E14-product-analytics.md`](../../backlog/E14-product-analytics.md)

**Reads:** [`docs/architecture/activation-event.md`](../../architecture/activation-event.md) — the activation definition E11 decided and this epic must not redefine.

## Global Constraints

- **`ProductEvent.metadata` never carries user content.** No descriptions, no
  store names, no chat text. Counts, ids and enum values only. This table is read
  by operators and exported by E13. Same discipline as `core.observability.scrub_event`.
- **Event name values are stable strings.** They live in rows that outlive any
  refactor; renaming one is a data migration, not an edit.
- **Every event carries a household.** `emit(household=None)` is a deliberate
  no-op, because every scoped queryset in this codebase fails closed rather than
  raising, and an event writer must not be the one thing that raises instead.
- **Do not redefine activation.** It is decided in
  `docs/architecture/activation-event.md` and emitted from `commit_receipt`.
- **User-facing copy is pt-BR.** Tests in English; Portuguese only inside
  assertions about user-facing strings.
- **A test may not read the wall clock by accident** — inject the date, or freeze
  with the `time_machine` fixture at **midday UTC**. Every metric here is a
  function of elapsed days, so this constraint is load-bearing. See
  `docs/testing-conventions.md`.
- **No third-party analytics vendor.** Explicitly out of scope in the spec.
- **Definition of Done, run from the repo root:**
  ```bash
  POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
  uv run ruff check src/backend/ && uv run ruff format --check src/backend/
  ```

## Decisions taken before this plan

The spec's open questions, answered here so no task has to guess. Task 1 records
them in the repo; this table is why they say what they say.

| Question | Decision | Reasoning |
|---|---|---|
| Open question 1 — database or vendor? | **Database-derived.** | The spec recommends it, "no vendor" is in Out of scope, and `ProductEvent` already exists. Definitions can be recomputed from history when they change, which a vendor's pipeline cannot do. |
| Open question 2 — GA thresholds | **Activation ≥ 25%, D7 retention ≥ 15%, cost per household ≤ R$ 5,00/month** against a ~R$ 10/month intended price. Stop condition: **AI-captured : manual ratio below 1:1 after 30 days of beta.** | Learning-mode, chosen deliberately: this beta's purpose is to find out whether the wedge lands, not to prove a number. The stop condition carries the real weight — it is the one result that would mean rethinking rather than launching. |
| Open question 3 — how is exposure measured with no marketing site? | **Defined now, measured when E17 ships a landing page.** Until then exposure is measured at the edge — Cloud Run request counts on the signup URL — and is explicitly *not* a `ProductEvent`. | `ProductEvent.household` is non-null, and a visitor who has not signed up has no household. Modelling pre-signup steps would mean nullable-household events, which breaks the scoping base class every other read depends on. Not worth it for a number that is zero until there is traffic. |
| Open question 4 — does instrumentation need LGPD consent? | **First-party, server-side, no user content: proceeds under legitimate interest, and is added to E13's inventory as a processing activity.** Task 1 records it; E13 owns the privacy notice. | Consistent with the PII rule already enforced on `metadata`. |
| S14-1 edge case — does an invited member count as a separate activation? | **No.** A household auto-created for an invited user who works from someone else's household is excluded from both numerator and denominator. | `activation-event.md` documents that every signup mints a household even when the user then joins another. Counting those as failed signups understates activation for invited users — the doc says to answer this against the fact rather than guess. |
| S14-1 edge case — does a user who returns on day 9 count for D7? | **Yes.** Retention is **rolling**: DN-retained means active on day N *or later*. | Exact-day retention is noise at beta sample sizes — one household's Tuesday decides the number. Rolling retention answers the question the operator actually has ("did they come back and stay?") and is a named, standard definition rather than an invention. |
| S14-5 scope | Feedback lands **last**, as Task 6, so it can ship separately if the epic is stopped early. | Chosen by the operator. E14's DoD spans both, so the epic does not close until it is done. |

## What already exists (do not rebuild)

| Thing | Where | Status |
|---|---|---|
| `ProductEvent` model, PII rule, partial unique index | `core/models.py:133` | Shipped in E11 |
| `emit` / `emit_once` / `EventName` / `ONCE_PER_HOUSEHOLD` | `core/events.py` | Shipped |
| Read-only `ProductEventAdmin` | `core/admin.py` | Shipped |
| `signup`, `household_seeded` | `accounts/signals.py:45`, `accounts/starter_data.py:105` | Shipped |
| `onboarding_step`, `onboarding_done` | `accounts/onboarding.py:60` and `:67` | Shipped |
| `activated`, `first_ai_entry` | `assistant/agents/tools.py:674` and `:680` | Shipped |
| Activation rate + time-to-activation | `core/management/commands/activation_report.py` | Shipped |
| The activation definition | `docs/architecture/activation-event.md` | Shipped |
| Cost per household | `assistant/management/commands/usage_report.py`, `UsageRecord.cost_usd` | Shipped in E07 |

## File Structure

| File | Responsibility |
|---|---|
| `docs/architecture/product-metrics.md` **(new)** | The four definitions, the edge cases, and the LGPD note. The document S14-1 requires; every other task's numbers mean what this file says. |
| `docs/architecture/ga-criteria.md` **(new)** | S14-6's thresholds and stop condition, written before the data. |
| `src/backend/core/events.py` **(modify)** | Three new names: `ENTRY_CREATED`, `EMAIL_VERIFIED`, `RECEIPT_PHOTO`. |
| `src/backend/core/metrics.py` **(new)** | Every metric as a pure, testable function over querysets — cohorts, rolling retention, the wedge ratio, funnel drop-off. The command and the dashboard both call these, so a number cannot mean two things. |
| `src/backend/core/management/commands/retention_report.py` **(new)** | S14-3's repeatable command. |
| `src/backend/core/views_metrics.py` **(new)** | S14-4's staff-only dashboard view. |
| `src/backend/core/templates/core/metrics.html` **(new)** | Its template. |
| `src/backend/core/models.py` **(modify)** | The `Feedback` model — user content lives here, deliberately, and never in `ProductEvent.metadata`. |
| `src/backend/core/feedback.py` **(new)** | The feedback form and view. |
| `docs/runbook.md` **(modify)** | Operator procedures for both commands and the dashboard. |

---

### Task 1: Write the definitions down before measuring anything (S14-1)

The spec is blunt about why this comes first: *vague metric definitions produce
numbers nobody trusts*, and *the definitions are agreed before the code, so the
numbers mean one thing*. The test is not decorative — it fails if the funnel grows
an event the document never explains, which is exactly how a metrics doc rots.

**Files:**
- Create: `docs/architecture/product-metrics.md`
- Test: `src/backend/core/tests/test_metrics_doc.py`

**Interfaces:**
- Consumes: `core.events.EventName`
- Produces: the document every later task cites. No code.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_metrics_doc.py`:

```python
"""The metrics document must explain every event the funnel emits.

Not decoration: a funnel that grows an event nobody documented is how "activation
rate" quietly starts meaning something else. This test is the only thing that
makes the document a contract rather than a snapshot.
"""

from pathlib import Path

from core.events import EventName

DOC = Path(__file__).resolve().parents[3].parent / "docs" / "architecture" / "product-metrics.md"


def test_the_document_exists():
    assert DOC.is_file(), f"expected the metrics definitions at {DOC}"


def test_every_event_name_is_documented():
    text = DOC.read_text(encoding="utf-8")
    missing = [event.value for event in EventName if event.value not in text]
    assert not missing, f"undocumented events: {missing}"


def test_the_four_metrics_are_all_defined():
    text = DOC.read_text(encoding="utf-8").lower()
    for metric in ("exposição", "ativação", "time-to-value", "retenção"):
        assert metric in text, f"the document never defines {metric}"
```

Check the `parents[...]` depth against the real layout before running — the file
sits at `src/backend/core/tests/`, so the repo root is four levels up from
`__file__`. Adjust the index until `DOC` resolves, then keep it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics_doc.py -q`
Expected: FAIL — `AssertionError: expected the metrics definitions at .../product-metrics.md`

- [ ] **Step 3: Write the document**

Create `docs/architecture/product-metrics.md` containing, in this order:

1. **Header** — `**Decided:** 2026-08-16, in E14.` and `**Reads:** docs/architecture/activation-event.md`. State that changing a definition here changes what every reported number means, so it is a decision, not an edit.
2. **Exposure** — distinct visitors who reach the signup form. **Not a `ProductEvent`**: a visitor has no household, and `ProductEvent.household` is non-null. Measured at the edge from Cloud Run request counts on the signup URL until E17 ships a landing page. Record that this is deliberately unmeasured today and why (open question 3).
3. **Activation** — quote the one-sentence definition from `activation-event.md` and link to it. Do not restate the table; a second copy will drift.
4. **Time-to-value** — minutes from the household's `signup` event to its `activated` event. T0 is the event, not `User.date_joined`. Reported as p50 and p90 by `activation_report`. A household that never activates contributes to the rate, not to the time.
5. **Retention** — **rolling**: a household is DN-retained if it was *active* on day N after signup **or any later day**. Define *active* as any of: a `ProductEvent` row, a `ChatMessage`, or an `Entry` created by that household. State the day-9 answer explicitly: it counts for D7. Explain why rolling and not exact-day, in one sentence — exact-day retention is noise at beta sample sizes.
6. **Engagement and the wedge ratio** — assistant turns per active household per week; receipts confirmed per week; and the **AI-captured : manually-entered ratio**, computed from `entry_created` events with `metadata.source` in `{receipt, chat}` against `{form}`. State that `source="import"` is excluded because a CSV backfill is migration, not capture behaviour, and would swamp the ratio.
7. **Edge cases** — the invited-member rule and the day-9 rule, each with the reasoning from *Decisions taken before this plan*.
8. **Every event name** — a table of the funnel: `signup`, `household_seeded`, `onboarding_step`, `onboarding_done`, `first_ai_entry`, `activated`, plus the three this epic adds: `entry_created`, `email_verified`, `receipt_photo`. One line each: when it fires, whether it is once-per-household, and what `metadata` carries.
9. **LGPD** — first-party, server-side, no user content in `metadata`; proceeds under legitimate interest; belongs on E13's processing inventory. Note that `Feedback` (Task 6) *does* hold user content and is inventoried separately.

Write the three names Task 2 and Task 3 will add now, in step 8 — the test asserts
on `EventName`, so the document may lead the code but must never lag it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics_doc.py -q`
Expected: PASS — 3 passed. (`test_every_event_name_is_documented` passes trivially
today and starts doing real work in Task 2.)

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/product-metrics.md src/backend/core/tests/test_metrics_doc.py
git commit -m "docs(E14): the four metric definitions, decided before the code"
```

---

### Task 2: `entry_created`, and the ratio that is the point of the product

S14-3 calls the AI-versus-manual ratio *the most important number in the product*.
Nothing today can compute it: `Entry` has no source column, and `first_ai_entry`
fires once per household, so it cannot count anything. A non-once event at each
write path answers it with no migration and no new column.

**Files:**
- Modify: `src/backend/core/events.py`
- Modify: `src/backend/assistant/agents/tools.py` — `commit_receipt` (~line 674) and `create_entry` (~line 109)
- Modify: `src/backend/finances/views/entries.py` — `EntryCreateView` (line 149)
- Modify: `src/backend/finances/management/commands/import_csv.py` — `handle`
- Test: `src/backend/core/tests/test_entry_source_events.py`

**Interfaces:**
- Consumes: `emit` from `core.events`
- Produces: `EventName.ENTRY_CREATED = "entry_created"` — **not** in `ONCE_PER_HOUSEHOLD`; `metadata` is `{"source": "receipt" | "chat" | "form" | "import"}`, plus `{"count": int}` for `import` only.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_entry_source_events.py`:

```python
"""Every entry records how it was captured, so the wedge ratio is computable.

The ratio S14-3 calls the most important number: AI-captured against
manually-typed. If users are typing entries rather than photographing receipts,
the wedge is not landing.
"""

import pytest
from model_bakery import baker

from accounts.models import Household
from core.events import ONCE_PER_HOUSEHOLD, EventName
from core.models import ProductEvent

pytestmark = pytest.mark.django_db


def test_entry_created_is_not_a_once_event():
    """Once-per-household events cannot count anything. This one has to count."""
    assert EventName.ENTRY_CREATED not in ONCE_PER_HOUSEHOLD


def test_the_event_survives_many_writes_in_one_household():
    """The partial unique index must not apply here — two entries, two rows."""
    from core.events import emit

    household = baker.make(Household, name="Casa de teste")

    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})

    assert ProductEvent.objects.filter(name=EventName.ENTRY_CREATED).count() == 2


def test_the_metadata_carries_a_source_and_nothing_else():
    """Constraint 11: counts and enum values, never user content. A description
    leaking into metadata is a PII incident, not a bug."""
    from core.events import emit

    household = baker.make(Household, name="Casa de teste")

    row = emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "chat"})

    assert set(row.metadata) == {"source"}
```

Then add a receipt-path test to
`src/backend/assistant/tests/test_receipt_billing_month.py` **if D05 has landed**,
or a new `src/backend/assistant/tests/test_entry_source.py` otherwise:

```python
def test_committing_a_receipt_records_the_source(scope, household):
    """`first_ai_entry` fires once per household and cannot count the second
    receipt. `entry_created` is what the ratio is built on."""
    from core.events import EventName
    from core.models import ProductEvent

    # ... build and commit a pending draft as the surrounding module does ...

    events = ProductEvent.objects.filter(household=household, name=EventName.ENTRY_CREATED)
    assert [e.metadata["source"] for e in events] == ["receipt"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_entry_source_events.py -q`
Expected: FAIL — `AttributeError: type object 'EventName' has no attribute 'ENTRY_CREATED'`

- [ ] **Step 3: Add the event name**

In `src/backend/core/events.py`, add to `EventName`, after `FIRST_AI_ENTRY`:

```python
    ENTRY_CREATED = "entry_created", "Lançamento criado"
```

Leave `ONCE_PER_HOUSEHOLD` untouched — this event must repeat, and adding it there
would make the partial unique index reject every entry after the first.

Extend the class docstring to say so:

```python
    """The funnel, from arrival to the moment the wedge lands.

    The values are stable strings because they are stored in rows that outlive
    any refactor — renaming one is a data migration, not an edit.

    ``ENTRY_CREATED`` is deliberately NOT once-per-household: it is the only
    event that counts, and the AI-versus-manual ratio (E14 S14-3) is a GROUP BY
    over its ``metadata.source``.
    """
```

- [ ] **Step 4: Emit at all four write paths**

In `src/backend/assistant/agents/tools.py`, inside `commit_receipt`, immediately
after the two existing `emit_once` calls:

```python
    emit(
        EventName.ENTRY_CREATED,
        household=scope.household,
        user=scope.user,
        metadata={"source": "receipt"},
    )
```

Add `emit` to the existing `from core.events import ...` line in that module.

In the same file, at the end of `create_entry`'s successful path — after the
`Entry` is created and before it returns its confirmation string:

```python
    emit(
        EventName.ENTRY_CREATED,
        household=scope.household,
        user=scope.user,
        metadata={"source": "chat"},
    )
```

In `src/backend/finances/views/entries.py`, in `EntryCreateView`, after the form
saves successfully and before the response is returned:

```python
    emit(
        EventName.ENTRY_CREATED,
        household=request.household,
        user=request.user,
        metadata={"source": "form"},
    )
```

with `from core.events import EventName, emit` at the top of the module. Read the
view before editing — if it creates several entries in one submission (an
installment plan), emit **once per submission**, not once per generated row: the
ratio is about how a person captured a purchase, and a twelve-instalment plan is
one capture.

In `src/backend/finances/management/commands/import_csv.py`, at the very end of
`handle`, one run-level event:

```python
        emit(
            EventName.ENTRY_CREATED,
            household=self.household,
            user=self.user,
            metadata={"source": "import", "count": Entry.objects.for_household(self.household).count()},
        )
```

One event per run, not per row: a CSV backfill of two thousand rows would
otherwise swamp both the event table and the ratio. `product-metrics.md` already
records that `import` is excluded from the ratio for exactly this reason.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_entry_source_events.py src/backend/assistant -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/backend/core/events.py src/backend/assistant/agents/tools.py \
        src/backend/finances/views/entries.py \
        src/backend/finances/management/commands/import_csv.py \
        src/backend/core/tests/test_entry_source_events.py
git commit -m "feat(analytics): record how every entry was captured"
```

---

### Task 3: Close the two remaining funnel gaps (S14-2)

S14-2 wants drop-off derivable at each step. Between `signup` and
`onboarding_step` sits email verification, where a real funnel loses people; and
between `onboarding_done` and `activated` sits the photograph itself — the
difference between "never tried" and "tried and the extraction failed", which are
opposite problems with opposite fixes.

**Files:**
- Modify: `src/backend/core/events.py`
- Modify: `src/backend/accounts/signals.py`
- Modify: `src/backend/assistant/views.py` — `_dispatch_extraction` (line 431)
- Test: `src/backend/core/tests/test_funnel_events.py`

**Interfaces:**
- Consumes: `allauth.account.signals.email_confirmed`, `accounts.resolution.household_for_user`, `emit_once`, `emit`
- Produces: `EventName.EMAIL_VERIFIED = "email_verified"` (once per household), `EventName.RECEIPT_PHOTO = "receipt_photo"` (**not** once — the gap between photos taken and receipts committed is the extraction failure rate).

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_funnel_events.py`:

```python
"""The two funnel steps E11 left unmeasured.

Drop-off is only derivable if every step between signup and activation emits.
Email verification is where a real funnel loses people; the photograph is what
separates "never tried the wedge" from "tried it and extraction failed".
"""

import pytest
from model_bakery import baker

from accounts.models import Household
from core.events import ONCE_PER_HOUSEHOLD, EventName

pytestmark = pytest.mark.django_db


def test_email_verified_happens_at_most_once_per_household():
    assert EventName.EMAIL_VERIFIED in ONCE_PER_HOUSEHOLD


def test_receipt_photo_is_countable():
    """Photos taken against receipts committed IS the extraction failure rate.
    A once-per-household event could not express it."""
    assert EventName.RECEIPT_PHOTO not in ONCE_PER_HOUSEHOLD


def test_confirming_an_email_emits_once(django_user_model):
    """Driven through the allauth signal rather than by calling emit directly —
    the wiring is the thing that can break."""
    from allauth.account.models import EmailAddress
    from allauth.account.signals import email_confirmed

    from core.models import ProductEvent

    user = baker.make(django_user_model, username="stranger", email="s@example.com")
    household = baker.make(Household, name="Casa de stranger")
    baker.make("accounts.Membership", household=household, user=user, role="owner")
    address = baker.make(EmailAddress, user=user, email=user.email, verified=True)

    email_confirmed.send(sender=EmailAddress, request=None, email_address=address)
    email_confirmed.send(sender=EmailAddress, request=None, email_address=address)

    assert (
        ProductEvent.objects.filter(
            household=household, name=EventName.EMAIL_VERIFIED
        ).count()
        == 1
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_funnel_events.py -q`
Expected: FAIL — `AttributeError: type object 'EventName' has no attribute 'EMAIL_VERIFIED'`

- [ ] **Step 3: Add both names**

In `src/backend/core/events.py`, add to `EventName` after `SIGNUP`:

```python
    EMAIL_VERIFIED = "email_verified", "E-mail verificado"
```

and after `ONBOARDING_DONE`:

```python
    RECEIPT_PHOTO = "receipt_photo", "Foto de cupom enviada"
```

Add **only** `EMAIL_VERIFIED` to `ONCE_PER_HOUSEHOLD`:

```python
ONCE_PER_HOUSEHOLD = frozenset(
    {
        EventName.SIGNUP,
        EventName.EMAIL_VERIFIED,
        EventName.HOUSEHOLD_SEEDED,
        EventName.ONBOARDING_DONE,
        EventName.FIRST_AI_ENTRY,
        EventName.ACTIVATED,
    }
)
```

- [ ] **Step 4: Wire the email signal**

In `src/backend/accounts/signals.py`, add the receiver alongside the existing ones:

```python
@receiver(email_confirmed)
def record_email_verified(request, email_address, **kwargs):
    """The funnel step between signing up and being able to do anything.

    `emit_once` rather than `emit`: allauth can fire this again if a user
    re-confirms an address, and a second row would make the funnel report more
    verifications than signups.
    """
    household = household_for_user(email_address.user)
    emit_once(
        EventName.EMAIL_VERIFIED,
        household=household,
        user=email_address.user,
    )
```

with `from allauth.account.signals import email_confirmed` added to the imports,
and `household_for_user` already imported in that module via
`accounts.resolution` — check, and add it if not.

- [ ] **Step 5: Emit the photograph**

In `src/backend/assistant/views.py`, inside `_dispatch_extraction`, immediately
after the `await ReceiptDraft.objects.acreate(...)` call:

```python
    # Counted, not once-per-household: photos taken against receipts committed is
    # the extraction failure rate, and it is the difference between "nobody tried
    # the wedge" and "the wedge did not work" — opposite problems.
    await sync_to_async(emit)(
        EventName.RECEIPT_PHOTO,
        household=scope.household,
        user=scope.user,
        metadata={"needs_review": bool(receipt_needs_review(extraction, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE))},
    )
```

Place it after `needs_review` is computed, and reuse that variable rather than
calling `receipt_needs_review` twice. `sync_to_async` is the established pattern
in this module (`views.py:446`), because `emit` does a synchronous ORM write and
this view is async.

Add `from core.events import EventName, emit` to the module's imports.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/ src/backend/accounts/ src/backend/assistant/ -q`
Expected: PASS. `test_metrics_doc.py::test_every_event_name_is_documented` now
does real work — if it fails, the document is missing one of the three new names,
and the fix is the document.

- [ ] **Step 7: Commit**

```bash
git add src/backend/core/events.py src/backend/accounts/signals.py \
        src/backend/assistant/views.py src/backend/core/tests/test_funnel_events.py
git commit -m "feat(analytics): instrument email verification and receipt photos"
```

---

### Task 4: The metrics themselves, as functions, then as a command (S14-3)

Every number gets one implementation. The command and the dashboard both call
these functions, so "D7 retention" cannot mean one thing on a terminal and
another in a browser.

**Files:**
- Create: `src/backend/core/metrics.py`
- Create: `src/backend/core/management/commands/retention_report.py`
- Test: `src/backend/core/tests/test_metrics.py`

**Interfaces:**
- Consumes: `ProductEvent`, `EventName`, `assistant.models.ChatMessage`, `finances.models.Entry`, `assistant.models.UsageRecord`
- Produces, all in `core/metrics.py`:
  - `signup_cohorts(since=None) -> dict[date, list[UUID]]` — households by ISO-week of signup, keyed by the Monday
  - `last_activity(household_ids) -> dict[UUID, datetime]` — most recent qualifying activity per household
  - `rolling_retention(cohort_ids, signups, activity, day) -> float` — fraction retained at day N or later
  - `wedge_ratio(since=None) -> tuple[int, int]` — `(ai_captured, manually_typed)`
  - `funnel_counts(since=None) -> list[tuple[str, int]]` — one row per funnel step, in order
  - `cost_per_household(since=None) -> dict[UUID, Decimal]`
  - `excluded_shadow_households() -> set[UUID]` — auto-created households whose owner works from another household

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_metrics.py`:

```python
"""Every metric, against a ledger whose answer is known by construction.

Frozen at 2026-08-16 midday UTC: every number here is a function of elapsed days,
so a test that reads the real clock would drift into passing for the wrong reason.
"""

from datetime import UTC, datetime, timedelta

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from core.events import EventName, emit, emit_once
from core.metrics import (
    excluded_shadow_households,
    funnel_counts,
    rolling_retention,
    signup_cohorts,
    wedge_ratio,
)

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


def _household(name):
    return baker.make(Household, name=name)


def _signed_up(household, days_ago):
    row = emit_once(EventName.SIGNUP, household=household)
    when = FROZEN_NOW - timedelta(days=days_ago)
    type(row).objects.filter(pk=row.pk).update(created_at=when)
    return household


def test_cohorts_are_keyed_by_the_monday_of_the_signup_week():
    _signed_up(_household("A"), days_ago=10)

    cohorts = signup_cohorts()

    (monday,) = cohorts.keys()
    assert monday.weekday() == 0


def test_a_household_active_on_day_nine_is_d7_retained():
    """The spec's exact edge case. Rolling retention: day 7 OR LATER counts."""
    household = _signed_up(_household("A"), days_ago=30)
    activity = emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})
    type(activity).objects.filter(pk=activity.pk).update(
        created_at=FROZEN_NOW - timedelta(days=21)  # 9 days after signup
    )

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) == 1.0


def test_a_household_that_never_came_back_is_not_retained():
    household = _signed_up(_household("A"), days_ago=30)
    # Its only activity is the signup event itself, on day 0.

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) == 0.0


def test_a_cohort_too_young_to_judge_is_excluded_not_counted_as_lost():
    """A household that signed up yesterday cannot have failed D7 yet. Counting
    it as unretained is how a growing beta reports collapsing retention."""
    _signed_up(_household("A"), days_ago=2)

    cohorts = signup_cohorts()
    (ids,) = cohorts.values()

    assert rolling_retention(ids, day=7) is None


def test_the_wedge_ratio_counts_ai_against_manual():
    household = _household("A")
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "chat"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})

    assert wedge_ratio() == (2, 1)


def test_imports_are_excluded_from_the_ratio():
    """A CSV backfill is migration, not capture. Counting it would swamp the one
    number S14-3 calls the most important in the product."""
    household = _household("A")
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "import", "count": 2000})

    assert wedge_ratio() == (1, 0)


def test_the_funnel_is_reported_in_order():
    household = _signed_up(_household("A"), days_ago=5)
    emit_once(EventName.ONBOARDING_DONE, household=household)

    steps = [name for name, _ in funnel_counts()]

    assert steps.index("signup") < steps.index("onboarding_done") < steps.index("activated")


def test_an_invited_members_shadow_household_is_excluded(django_user_model):
    """Every signup mints a household even when the user then joins another one.
    Counting those as failed signups understates activation for invited users —
    see docs/architecture/activation-event.md."""
    invitee = baker.make(django_user_model, username="convidado")
    shadow = _signed_up(_household("Casa de convidado"), days_ago=10)
    baker.make(Membership, household=shadow, user=invitee, role=Role.OWNER)
    shared = _household("Casa compartilhada")
    baker.make(Membership, household=shared, user=invitee, role=Role.MEMBER)

    assert shadow.id in excluded_shadow_households()
    assert shared.id not in excluded_shadow_households()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.metrics'`

- [ ] **Step 3: Implement `core/metrics.py`**

Write each function to the signatures in **Interfaces** above. The decisions the
tests pin down, so they are not rediscovered while implementing:

- `rolling_retention` returns **`None`**, not `0.0`, for a cohort younger than
  `day` days. A cohort that has not had time to fail must not be reported as
  having failed.
- A household counts as *active* if it has a `ProductEvent`, `ChatMessage`, or
  `Entry` created after its signup. The signup event itself is day 0 and does not
  make a household retained.
- `wedge_ratio` groups `ENTRY_CREATED` by `metadata__source`, counting
  `{receipt, chat}` as AI and `{form}` as manual, and ignoring `import`.
- `funnel_counts` returns the steps in funnel order — `signup`, `email_verified`,
  `household_seeded`, `onboarding_step`, `onboarding_done`, `receipt_photo`,
  `activated` — so drop-off is the difference between adjacent rows.
- `excluded_shadow_households` returns households that (a) have exactly one
  membership, (b) whose sole member also holds a membership in a *different*
  household, and (c) have no `activated` event. All three conditions, or a
  legitimate solo household gets excluded from the denominator.
- Every count is a query, not a Python loop over rows. `ProductEvent` has
  `event_name_recent_idx` on `(name, -created_at)`; use it by filtering on `name`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics.py -q`
Expected: PASS — 8 passed

- [ ] **Step 5: Write the command**

Create `src/backend/core/management/commands/retention_report.py`, modelled on
`activation_report.py` and `usage_report.py` — pt-BR output, a `--since`
`YYYY-MM-DD` argument, fixed-width columns. It prints, in this order:

1. **Cohorts** — one row per signup week: the Monday, the cohort size, and D1 / D7 / D30 rolling retention, printing `—` where `rolling_retention` returned `None`.
2. **Engagement** — assistant turns per active household per week, and receipts confirmed per week.
3. **The wedge ratio** — `IA 14 : 3 manual (82%)`, and the sentence from S14-3 when AI is below manual, in pt-BR: `⚠️ Mais lançamentos digitados que capturados por IA — a cunha não está pegando.`
4. **Excluded** — how many shadow households were left out of the cohorts, so the denominator is never silently smaller than the operator expects.

Print what was excluded. A report that silently narrows its own denominator reads
as authoritative and is not.

- [ ] **Step 6: Run it against the dev database**

Run: `POSTGRES_PORT=5433 uv run python src/backend/manage.py retention_report`
Expected: it runs and prints all four sections. With little dev data most numbers
will be `—` or zero; what is being verified is that it executes and that no
section raises on an empty queryset.

- [ ] **Step 7: Commit**

```bash
git add src/backend/core/metrics.py src/backend/core/management/commands/retention_report.py \
        src/backend/core/tests/test_metrics.py
git commit -m "feat(analytics): rolling retention, engagement and the wedge ratio"
```

---

### Task 5: The operator dashboard (S14-4)

S14-4's requirement is that these numbers are *looked at regularly, not computed
once*, and that **cost sits next to engagement** so unit economics and value are
visible together.

**Files:**
- Create: `src/backend/core/views_metrics.py`
- Create: `src/backend/core/templates/core/metrics.html`
- Modify: `src/backend/core/urls.py` (or `config/urls.py`, wherever core's routes live — check before editing)
- Modify: `docs/runbook.md`
- Test: `src/backend/core/tests/test_metrics_view.py`

**Interfaces:**
- Consumes: every function from `core/metrics.py` (Task 4)
- Produces: `GET /metricas/`, staff-only, route name `metrics_dashboard`

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_metrics_view.py`:

```python
"""The operator dashboard: staff only, and honest about empty data."""

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db

URL = "/metricas/"


def test_an_anonymous_visitor_is_turned_away(client):
    response = client.get(URL)
    assert response.status_code in (302, 403, 404)


def test_an_ordinary_user_cannot_see_it(client, django_user_model):
    """Household metrics across ALL households. A beta user seeing this would be
    seeing other families' behaviour."""
    user = baker.make(django_user_model, username="familia", is_staff=False)
    client.force_login(user)

    assert client.get(URL).status_code in (302, 403, 404)


def test_staff_can_see_it(client, django_user_model):
    staff = baker.make(django_user_model, username="operador", is_staff=True)
    client.force_login(staff)

    response = client.get(URL)

    assert response.status_code == 200


def test_it_renders_with_no_data_at_all(client, django_user_model):
    """The first time this is opened there will be nothing. An operator dashboard
    that 500s on an empty database is one nobody opens twice."""
    staff = baker.make(django_user_model, username="operador", is_staff=True)
    client.force_login(staff)

    response = client.get(URL)

    assert response.status_code == 200
    assert "Ativação" in response.content.decode()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics_view.py -q`
Expected: FAIL — 404 on every case, because the route does not exist.

- [ ] **Step 3: Write the view**

Create `src/backend/core/views_metrics.py`:

```python
"""The four metrics, the funnel, the wedge ratio and cost — on one screen.

Staff-only, and not under `settings.ADMIN_URL_PATH`: that path is a secret whose
404 must stay indistinguishable from a wrong guess (`core.admin_gate`), and this
page has no reason to live behind it. Staff are gated by identity here, the same
way `accounts.middleware.onboarding_redirect_middleware` exempts them.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from core import metrics


@method_decorator(staff_member_required, name="dispatch")
class MetricsDashboardView(TemplateView):
    template_name = "core/metrics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cohorts = metrics.signup_cohorts()
        context["cohorts"] = [
            {
                "week": week,
                "size": len(ids),
                "d1": metrics.rolling_retention(ids, day=1),
                "d7": metrics.rolling_retention(ids, day=7),
                "d30": metrics.rolling_retention(ids, day=30),
            }
            for week, ids in sorted(cohorts.items(), reverse=True)
        ]
        context["funnel"] = metrics.funnel_counts()
        ai, manual = metrics.wedge_ratio()
        context["wedge"] = {"ai": ai, "manual": manual, "landing": ai >= manual}
        context["costs"] = metrics.cost_per_household()
        context["excluded"] = len(metrics.excluded_shadow_households())
        return context
```

`staff_member_required` redirects to the admin login by default. If that leaks the
secret admin path, pass `login_url="/accounts/login/"` — check
`core/admin_gate.py` before deciding, and record whichever you chose in the
docstring.

- [ ] **Step 4: Write the template**

Create `src/backend/core/templates/core/metrics.html`, extending the project's
base template. Four sections, pt-BR headings:

- **Ativação** — signups, activations, rate, p50/p90 time-to-activation.
- **Funil** — one row per step with its count and the drop-off from the step above, so where users fall out is readable at a glance.
- **Cunha** — the AI : manual ratio, rendered green when AI ≥ manual and red otherwise. This is the number S14-3 says matters most; give it the most space, not the least.
- **Custo e engajamento, lado a lado** — cost per household from `UsageRecord` next to that household's assistant turns, which is S14-4's actual requirement.

Print `—` for any metric with no samples. Never render a bare `0%` for "we do not
know yet" — that is the same failure `usage_report` avoids by counting unpriced
calls separately instead of summing them as zero.

- [ ] **Step 5: Route it**

Add to the appropriate `urls.py`:

```python
    path("metricas/", MetricsDashboardView.as_view(), name="metrics_dashboard"),
```

Check `accounts/middleware.py::_ONBOARDING_EXEMPT_PREFIXES` — staff are already
exempt from the onboarding redirect by identity, so `/metricas/` needs no prefix
entry. Confirm rather than assume: a staff account with an unonboarded household
would otherwise be bounced to setup instead of the dashboard.

- [ ] **Step 6: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_metrics_view.py -q`
Expected: PASS — 4 passed

- [ ] **Step 7: Document it in the runbook**

Add a section to `docs/runbook.md` next to "Onboarding & activation", in that
file's established shape — the full invocation, what it prints, and the common
failure. Cover `retention_report` (Task 4) and `/metricas/`, and state that the
page is staff-only and shows every household, so it is not something to screen-share.

- [ ] **Step 8: Commit**

```bash
git add src/backend/core/views_metrics.py src/backend/core/templates/core/metrics.html \
        src/backend/core/urls.py src/backend/core/tests/test_metrics_view.py docs/runbook.md
git commit -m "feat(analytics): the operator dashboard, cost beside engagement"
```

---

### Task 6: A feedback channel (S14-5)

*Quantitative data tells you what happened and never why.* This is the only place
in the epic where user-authored text is stored on purpose — which is exactly why
it gets its own model rather than riding in `ProductEvent.metadata`, whose PII
rule forbids it.

**Files:**
- Modify: `src/backend/core/models.py` — add `Feedback`
- Create: `src/backend/core/migrations/00NN_feedback.py` (generated)
- Create: `src/backend/core/feedback.py` — form and view
- Modify: `src/backend/core/admin.py` — read-only admin
- Modify: a base template, for the entry point
- Test: `src/backend/core/tests/test_feedback.py`

**Interfaces:**
- Produces: `Feedback(household, user, message, context, created_at)`; `POST /feedback/` named `feedback_submit`; `FeedbackForm`

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_feedback.py`:

```python
"""Beta feedback: easy to send, scoped, and never silently dropped."""

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db

URL = "/feedback/"


@pytest.fixture
def member(client, django_user_model):
    user = baker.make(django_user_model, username="familia")
    household = baker.make(Household, name="Casa de teste")
    baker.make(Membership, household=household, user=user, role=Role.OWNER)
    client.force_login(user)
    return user, household


def test_a_user_can_send_feedback(client, member):
    from core.models import Feedback

    user, household = member

    response = client.post(URL, {"message": "A foto do cupom não leu o desconto."})

    assert response.status_code in (200, 204, 302)
    row = Feedback.objects.get()
    assert row.household == household
    assert row.user == user
    assert "desconto" in row.message


def test_empty_feedback_is_rejected_rather_than_stored(client, member):
    from core.models import Feedback

    response = client.post(URL, {"message": "   "})

    assert Feedback.objects.count() == 0
    assert response.status_code in (200, 400)


def test_feedback_is_capped_in_length(client, member):
    """A 2 MB paste is not feedback. The cap is a storage bound, not a judgement."""
    from core.models import Feedback

    client.post(URL, {"message": "x" * 10_000})

    row = Feedback.objects.get()
    assert len(row.message) <= 4000


def test_anonymous_visitors_cannot_post(client):
    from core.models import Feedback

    client.post(URL, {"message": "olá"})

    assert Feedback.objects.count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_feedback.py -q`
Expected: FAIL — `ImportError: cannot import name 'Feedback' from 'core.models'`

- [ ] **Step 3: Add the model**

In `src/backend/core/models.py`, after `ProductEvent`:

```python
class Feedback(HouseholdOwnedModel):
    """What a beta user said, in their own words.

    The one place in E14 that stores user-authored text on purpose. It does NOT
    go in `ProductEvent.metadata`, whose PII rule (constraint 11) forbids user
    content — which is the whole reason this is a separate table with its own
    entry on E13's processing inventory.

    `context` carries where they were when they wrote it (path, viewport) so a
    report is actionable, and never anything they typed elsewhere.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    message = models.TextField(max_length=4000)
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "feedback"
        verbose_name_plural = "feedbacks"
        ordering = ["-created_at"]
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations core --name feedback
```

Read the generated file. It must be a single `CreateModel` — additive, nothing
else. Then apply it:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core
```

- [ ] **Step 5: Write the form and view**

Create `src/backend/core/feedback.py` with a `FeedbackForm` that strips whitespace
and rejects an empty message, and a `LoginRequiredMixin` view that truncates to
4000 characters, sets `household=request.household` and `user=request.user`, and
records `context={"path": request.META.get("HTTP_REFERER", "")[:500]}`. Return an
HTMX-friendly confirmation fragment in pt-BR — *"Obrigado. Isso vai ser lido."* —
because the spec is explicit that feedback nobody reads is worse than none, and a
promise made in the UI should be one the process keeps.

Route it as `path("feedback/", FeedbackView.as_view(), name="feedback_submit")`.

- [ ] **Step 6: Add the entry point**

Add a "Enviar feedback" item to the drawer navigation in the base template,
opening a small modal with the form. Follow the existing modal pattern in the
templates rather than inventing one; if a `.tsx` file changes, Task 5's rebuild
rules from the D05 plan apply — rebuild `mount.js` and `tailwind.css --force` and
commit both.

- [ ] **Step 7: Register the read-only admin**

In `src/backend/core/admin.py`, alongside `ProductEventAdmin`:

```python
@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    """Read-only, and ordered newest first: this is the reading queue."""

    list_display = ("created_at", "household", "user", "message")
    list_filter = ("created_at",)
    search_fields = ("message",)
    readonly_fields = ("household", "user", "message", "context", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

- [ ] **Step 8: Run the tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_feedback.py -q`
Expected: PASS — 4 passed

- [ ] **Step 9: Document the reading process**

Add to `docs/runbook.md`, under the metrics section: where feedback lands, that
the admin list is the queue, and the cadence for reading it (weekly, alongside
`retention_report`). One paragraph. The spec asks for a lightweight process, not a
system.

- [ ] **Step 10: Commit**

```bash
git add src/backend/core/models.py src/backend/core/migrations/ src/backend/core/feedback.py \
        src/backend/core/admin.py src/backend/core/tests/test_feedback.py docs/runbook.md
git commit -m "feat(analytics): a feedback channel, read weekly"
```

---

### Task 7: GA criteria, written before the data (S14-6)

*Writing thresholds after seeing the data is how every result becomes a good
result.* This task exists to make that impossible.

**Files:**
- Create: `docs/architecture/ga-criteria.md`
- Modify: `docs/backlog/E14-product-analytics.md`
- Modify: `docs/backlog/INDEX.md`

- [ ] **Step 1: Write the criteria document**

Create `docs/architecture/ga-criteria.md`:

- **Header** — `**Decided:** 2026-08-16, in E14 (S14-6), before any beta data existed.` State plainly that these are commitments rather than predictions, and that revising them *after* seeing data requires saying so in this file, with the old numbers left visible.
- **The thresholds** — activation rate **≥ 25%**, D7 rolling retention **≥ 15%**, cost per household **≤ R$ 5,00/month** against a ~R$ 10/month intended price. Record the USD→BRL rate used to compare against `UsageRecord.cost_usd` and that the comparison is re-run rather than re-derived when the rate moves.
- **Why these and not higher** — learning-mode, chosen deliberately: this beta exists to find out whether the wedge lands, not to prove a number. Note the risk the spec names — thresholds low enough that every result reads as a good result — and that the stop condition is what guards against it.
- **The stop condition** — *AI-captured : manually-typed below 1:1 after 30 days of beta means the wedge is not landing.* That is the result that means rethinking rather than launching. Point at `retention_report`'s ratio line as the number that decides it.
- **How each is measured** — one line each, naming the command: `activation_report` for the first two inputs, `retention_report` for retention and the ratio, `usage_report` for cost.

- [ ] **Step 2: Verify the criteria are computable today**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py activation_report --days 30
POSTGRES_PORT=5433 uv run python src/backend/manage.py retention_report
POSTGRES_PORT=5433 uv run python src/backend/manage.py usage_report
```

Expected: all three run. Every threshold in the document must map to a line one of
them prints. A criterion no command can evaluate is a wish.

- [ ] **Step 3: Run the Definition of Done in full**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: all pass.

- [ ] **Step 4: Prove the suite is still time-stable**

```bash
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
```

Expected: identical result to unshifted. Task 4's tests are the ones at risk —
every retention number is a function of elapsed days.

- [ ] **Step 5: Close the epic**

In `docs/backlog/E14-product-analytics.md`: set `status: done`, tick the Observable
assertions that hold, and answer all four Open questions with the decisions from
this plan rather than deleting them.

**Do not tick "Real numbers from actual beta users are visible, not just an empty
dashboard."** That assertion cannot be satisfied by writing code — it needs beta
users. Leave it unticked with a note naming what it waits on, and say so in the
INDEX footnote. The spec's own skill pipeline makes this point: *the evidence is
real beta numbers, not a working dashboard.*

In `docs/backlog/INDEX.md`, update E14's row and add a footnote in the established
style, stating what shipped, what is instrumented, and that the last assertion
waits on beta traffic.

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs(E14): GA criteria written before the data; close the epic"
```

---

## Self-review

**Spec coverage**

| Spec requirement | Where |
|---|---|
| S14-1 · four definitions written down, unambiguous | Task 1 |
| S14-1 · edge cases decided (invited member, day-9 D7) | Task 1 doc + Task 4 `excluded_shadow_households`, `rolling_retention` |
| S14-1 · agreed before the code | Task 1 is the first task, and its test fails until the document exists |
| S14-2 · funnel instrumented at each step | Already: signup, household_seeded, onboarding_step, onboarding_done, first_ai_entry, activated. Added: email_verified, receipt_photo (Task 3), entry_created (Task 2) |
| S14-2 · household, user, timestamp with E06's PII discipline | `ProductEvent` already carries all three; the metadata rule is a Global Constraint and is asserted in Task 2 |
| S14-2 · step-level drop-off derivable | Task 4 `funnel_counts`, rendered in Task 5 |
| S14-2 · server-side, not client | Every emitter is a signal, a view, or a tool. No client code emits. |
| S14-3 · D1/D7/D30 per signup cohort | Task 4 `signup_cohorts` + `rolling_retention` |
| S14-3 · engagement in wedge terms | Task 4 command, sections 2 and 3 |
| S14-3 · AI vs manual ratio | Task 2 (the data) + Task 4 `wedge_ratio` |
| S14-3 · a documented, repeatable command | Task 4 `retention_report`, documented in Task 5 step 7 |
| S14-4 · dashboard with four metrics, funnel, ratio | Task 5 |
| S14-4 · cost per household beside engagement | Task 5 context `costs`, template section 4 |
| S14-4 · documented in `docs/runbook.md` | Task 5 step 7 |
| S14-5 · feedback from inside the product | Task 6 |
| S14-5 · stored with context, respecting PII rules | Task 6 `Feedback.context`, and the reason it is not a `ProductEvent` |
| S14-5 · a process for reading it | Task 6 step 9 |
| S14-6 · thresholds written before the data | Task 7 |
| S14-6 · a stop condition | Task 7, the AI:manual ratio |
| Out of scope · no vendor, no attribution, no A/B, no session recording | No task adds any |

**Naming consistency:** `signup_cohorts`, `rolling_retention`, `wedge_ratio`,
`funnel_counts`, `cost_per_household`, `excluded_shadow_households` are declared in
Task 4's Interfaces and used under those exact names in Task 4's tests and Task 5's
view. `ENTRY_CREATED` / `EMAIL_VERIFIED` / `RECEIPT_PHOTO` are added in Tasks 2 and
3 and consumed in Task 4. `metadata.source` values `receipt` / `chat` / `form` /
`import` are fixed in Task 2 and matched in Task 4's `wedge_ratio`.

**Two places this plan is deliberately vaguer than the rest, and why.** Task 4
step 3 and Task 5 step 4 describe the metric bodies and the template as
requirements rather than as finished code. Each is a straightforward rendering of
signatures and decisions already pinned down by the tests above them, and writing
out a hundred lines of template markup here would go stale against the base
template faster than it would help. Every *decision* those steps depend on is
stated; only the typing is left. If an executor finds a decision missing, that is a
plan bug — stop and ask rather than inventing one.

**Known risk:** Task 3's allauth signal test constructs an `EmailAddress` and
sends `email_confirmed` by hand. If this project's allauth version passes a
different signal signature, fix the *test's* call to match the real signal — do not
change the receiver to fit the test.
