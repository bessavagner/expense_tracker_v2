# D05 · Backdated receipt visibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user who photographs a receipt always sees where it landed, so a successful first capture never looks like a failed one.

**Architecture:** Three surfaces, none of which changes where a row goes. (1) A new
`assistant/agents/receipt_billing.py` computes the billing month a plan *will*
produce, using exactly the call `Entry.save()` uses, so the number shown can never
disagree with the row written. (2) `propose_receipt` warns and asks when that month
is in the past; `commit_receipt` names the month and links to it whenever it is not
the current one. (3) A new dashboard API endpoint lets the empty state tell "you
have recorded nothing" apart from "nothing in *this* month", naming the nearest
month that has data.

**Tech Stack:** Django 6, DRF, pytest + `time-machine`, React 19 islands built by
Vite into a git-tracked `mount.js`, Tailwind v4 + daisyUI.

**Spec:** [`docs/backlog/D05-a-backdated-receipt-activates-into-an-invisible-month.md`](../../backlog/D05-a-backdated-receipt-activates-into-an-invisible-month.md)

**Walkthrough evidence:** `docs/superpowers/evidence/e11-walkthrough/README.md`

## Global Constraints

- **Do not change how `billing_month` is derived.** The spec's Out of scope is
  explicit: `commit_receipt` omits `billing_month_override` deliberately, and
  overriding it with today would re-break the historical frozen-billing-month
  defect. This plan changes what the user is *told*, never where the row goes.
- **User-facing copy is pt-BR.** Tests are written in English; only assertions
  about user-facing strings contain Portuguese.
- **A test may not read the wall clock by accident.** Inject the date where the
  code takes one; otherwise freeze with the `time_machine` fixture at **midday
  UTC** (`date.today()` reads the system timezone, not Django's). See
  `docs/testing-conventions.md`.
- **Every queryset is household-scoped** via `.for_household(...)` or
  `request.household`. Never `request.user`.
- **`mount.js` and `tailwind.css` are git-tracked build artifacts.** Any `.tsx`
  change requires rebuilding both and committing them, or production serves stale
  code. Tailwind needs `--force`.
- **Definition of Done, run from the repo root:**
  ```bash
  POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
  uv run ruff check src/backend/ && uv run ruff format --check src/backend/
  ```

## Decisions taken before this plan

| Question | Decision |
|---|---|
| D05 open question 1 — should an old receipt prompt rather than commit silently? | **Yes, prompt** — but at the confirmation turn that already exists. `propose_receipt` already returns a table ending in "Confirma?"; the warning enriches that turn rather than adding one. |
| When does the prompt fire? | Only when the prospective billing month is **earlier** than the current one. A credit-card purchase made today lands in M+1 or M+2 by design — warning about that would nag on every ordinary card purchase. |
| When does the commit confirmation name the month? | Whenever the billing month **is not the current month**, past or future. This is SD05-1's wording, and it is a statement rather than a question, so it costs nothing. |
| D05 open question 2 — confirmation or dashboard? | **Both**, because the spec has a story for each (SD05-1, SD05-2). They fail in different places: the confirmation is missed if the user looks away, and the dashboard is where they actually go looking. |

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/assistant/agents/receipt_billing.py` **(new)** | The only place that answers "which invoice will this plan land in, and how do we say that in pt-BR". Also owns the plan-date parsing that `commit_receipt` currently inlines, so the proposal and the commit can never disagree. |
| `src/backend/assistant/agents/tools.py` **(modify)** | `propose_receipt` gains the warning; `commit_receipt` gains the landing sentence and delegates date parsing. |
| `src/backend/finances/api/views.py` **(modify)** | `LedgerElsewhereView` — does this household have entries outside the month on screen, and which is nearest. |
| `src/backend/finances/api/urls.py` **(modify)** | Routes `ledger-elsewhere/`. |
| `src/backend/frontend/src/types.ts` **(modify)** | `LedgerElsewhere` response type. |
| `src/backend/frontend/src/cards/RecentEntriesCard.tsx` **(modify)** | Chooses between the E11 wedge empty state and the new other-month one. |
| `src/backend/assistant/tests/test_receipt_billing_month.py` **(new)** | Unit tests for the month helper, plus the walkthrough replay. |
| `src/backend/finances/tests/test_ledger_elsewhere.py` **(new)** | API tests for the endpoint, including household isolation. |

---

### Task 1: The prospective billing month, computed the way `Entry.save()` computes it

The proposal and the commit must both be able to say which invoice a plan lands
in. If either recomputes it a slightly different way, this fix invents a new lie.
So the derivation lives in one module, and it calls exactly what `Entry.save()`
calls: `compute_billing_month(date, payment_method.type, resolve_closing_day(payment_method, date))`.

**Files:**
- Create: `src/backend/assistant/agents/receipt_billing.py`
- Test: `src/backend/assistant/tests/test_receipt_billing_month.py`

**Interfaces:**
- Consumes: `finances.services.billing.compute_billing_month`, `finances.services.billing.resolve_closing_day`, `finances.models.PaymentMethod`
- Produces:
  - `plan_entry_date(plan: dict) -> datetime.date` — the plan's purchase date, falling back to today exactly as `commit_receipt` does now
  - `prospective_billing_month(household, plan: dict) -> datetime.date | None` — first day of the invoice month, or `None` when the plan's payment method cannot be resolved
  - `month_label(when: datetime.date) -> str` — `"junho/2023"`
  - `dashboard_url_for(when: datetime.date) -> str` — `"/?year=2023&month=6"`

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_receipt_billing_month.py`:

```python
"""The invoice month a receipt plan will land in, named before it is written.

Frozen to 2026-08-16 because every assertion here is about a month being in the
past relative to "now" — the walkthrough's receipt is dated 2023-06-04, and the
whole defect is that three years is invisible on a dashboard showing August.
"""

from datetime import UTC, date, datetime

import pytest
from model_bakery import baker

from accounts.models import Household
from assistant.agents.receipt_billing import (
    dashboard_url_for,
    month_label,
    plan_entry_date,
    prospective_billing_month,
)
from finances.models import PaymentMethod
from finances.models.payment_method import PaymentType

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


@pytest.fixture
def household():
    return baker.make(Household, name="Casa de teste")


def _plan(payment_method, when="2023-06-04"):
    return {
        "date": when,
        "payment_method_id": str(payment_method.id),
        "lines": [],
        "store": "HIPERMACIONAL",
        "payment_method_name": payment_method.name,
    }


def test_month_label_is_portuguese():
    assert month_label(date(2023, 6, 1)) == "junho/2023"


def test_dashboard_url_points_at_that_month():
    assert dashboard_url_for(date(2023, 6, 1)) == "/?year=2023&month=6"


def test_plan_entry_date_reads_the_plan():
    assert plan_entry_date({"date": "2023-06-04"}) == date(2023, 6, 4)


def test_plan_entry_date_falls_back_to_today_when_unusable():
    """Same fallback `commit_receipt` has always had — a plan with a broken date
    still writes rows, it just writes them today."""
    assert plan_entry_date({"date": "not-a-date"}) == date(2026, 8, 16)
    assert plan_entry_date({}) == date(2026, 8, 16)


def test_cash_lands_in_the_purchase_month(household):
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )

    assert prospective_billing_month(household, _plan(pix)) == date(2023, 6, 1)


def test_a_card_purchase_lands_on_the_invoice_that_pays_it(household):
    """Closing day 10, bought on the 4th: the invoice closes in June and is paid
    in July. This is the same arithmetic `Entry.save()` will do."""
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    assert prospective_billing_month(household, _plan(card)) == date(2023, 7, 1)


def test_a_card_purchase_after_closing_rolls_one_more_month(household):
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    plan = _plan(card, when="2023-06-20")

    assert prospective_billing_month(household, plan) == date(2023, 8, 1)


def test_an_unresolvable_payment_method_gives_no_answer(household):
    """Never guess. A caller that gets None says nothing rather than a wrong month."""
    plan = {"date": "2023-06-04", "payment_method_id": "00000000-0000-0000-0000-000000000000"}

    assert prospective_billing_month(household, plan) is None


def test_another_households_payment_method_is_not_visible(household):
    """The lookup is scoped. A plan naming someone else's card resolves to nothing,
    not to their closing day."""
    other = baker.make(Household, name="Casa alheia")
    card = baker.make(
        PaymentMethod,
        household=other,
        name="Crédito alheio",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )

    assert prospective_billing_month(household, _plan(card)) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.agents.receipt_billing'`

- [ ] **Step 3: Write the implementation**

Create `src/backend/assistant/agents/receipt_billing.py`:

```python
"""Which invoice a receipt plan lands in, and how to say that to a person.

D05: filing a receipt under its own date is correct and is not what this module
changes. What it provides is the ability to *say* where the row went, before and
after it is written, using exactly the derivation `Entry.save()` uses — see
`finances/models/entry.py::save`. Two code paths computing this two ways would
put a month on the screen that the database disagrees with, which is a worse
defect than the one D05 describes.
"""

from datetime import date

from django.utils import timezone

from finances.models import PaymentMethod
from finances.services.billing import compute_billing_month, resolve_closing_day

#: Month names in pt-BR, indexed by month number. Django's `date` filter would
#: need an active locale and a template; this is read by the assistant, which
#: renders strings, not templates.
_MONTHS_PT = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def month_label(when: date) -> str:
    """``junho/2023`` — how a Brazilian names an invoice."""
    return f"{_MONTHS_PT[when.month]}/{when.year}"


def dashboard_url_for(when: date) -> str:
    """The dashboard, showing that month.

    `finances/views/dashboard.py::DashboardView` reads `year` and `month` from
    the query string and falls back to today, so this is the whole contract.
    """
    return f"/?year={when.year}&month={when.month}"


def plan_entry_date(plan: dict) -> date:
    """The purchase date a plan will write, with the fallback commit has always had.

    Lifted out of `commit_receipt` so the proposal and the commit read the date
    the same way. A plan whose date is missing or malformed still writes rows —
    it writes them today — and the proposal must warn about the same day the
    commit will use.
    """
    try:
        return date.fromisoformat(plan["date"])
    except (ValueError, TypeError, KeyError):
        return timezone.localdate()


def prospective_billing_month(household, plan: dict) -> date | None:
    """First day of the invoice month this plan will land in, or ``None``.

    ``None`` when the plan's payment method cannot be resolved inside this
    household — a caller that cannot name the month must say nothing rather than
    guess, and a plan naming another household's card is exactly the case that
    must not silently borrow its closing day.
    """
    payment_method = (
        PaymentMethod.objects.for_household(household)
        .filter(pk=plan.get("payment_method_id"))
        .prefetch_related("monthly_closing_days")
        .first()
    )
    if payment_method is None:
        return None
    entry_date = plan_entry_date(plan)
    return compute_billing_month(
        entry_date,
        payment_method.type,
        resolve_closing_day(payment_method, entry_date),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q`
Expected: PASS — 9 passed

Note: `prospective_billing_month` filters on a UUID primary key. If the test for
an unresolvable id raises `ValidationError` rather than returning `None` on your
Django version, wrap the `.first()` in `try/except (ValidationError, ValueError)`
and return `None` — a malformed id is the same answer as a missing one.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/receipt_billing.py src/backend/assistant/tests/test_receipt_billing_month.py
git commit -m "feat(receipts): name the invoice month a plan will land in"
```

---

### Task 2: The proposal warns when the invoice is in the past, and asks

`propose_receipt` already ends with "Confirma?" — the user is already being asked.
The defect is that the question omits the one fact that turned out to matter. This
adds it to the existing turn rather than adding a turn.

**Files:**
- Modify: `src/backend/assistant/agents/tools.py` — `propose_receipt`, around line 625
- Test: `src/backend/assistant/tests/test_receipt_billing_month.py` (append)

**Interfaces:**
- Consumes: `prospective_billing_month`, `month_label` from Task 1
- Produces: no new callable. `propose_receipt`'s return value gains an optional
  paragraph between the table and `Confirma?`.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_receipt_billing_month.py`:

```python
from decimal import Decimal

from assistant.agents.tools import propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Category


class _Scope:
    """The two attributes the receipt tools read off a scope."""

    def __init__(self, household, user):
        self.household = household
        self.user = user


@pytest.fixture
def scope(household, django_user_model):
    user = baker.make(django_user_model, username="stranger")
    return _Scope(household, user)


def _pending_draft(household, payment_method, category, when="2023-06-04"):
    """A draft already carrying a saved plan, which is the state `propose_receipt`
    rewrites and `commit_receipt` reads."""
    return baker.make(
        ReceiptDraft,
        household=household,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "HIPERMACIONAL",
            "amount_paid": "376.70",
            "date": when,
            "items": [{"description": "ARROZ 5KG", "amount": "376.70"}],
            "plan": {
                "date": when,
                "payment_method_id": str(payment_method.id),
                "payment_method_name": payment_method.name,
                "store": "HIPERMACIONAL",
                "table": "| Categoria | Itens | Valor |",
                "lines": [
                    {
                        "category_id": str(category.id),
                        "category_name": category.name,
                        "description": "HIPERMACIONAL - arroz",
                        "amount": "376.70",
                    }
                ],
            },
        },
    )


def test_a_past_invoice_is_named_and_asked_about(scope, household):
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, pix, category)

    answer = propose_receipt(scope)

    assert "junho/2023" in answer
    assert "Registrar nessa fatura?" in answer
    assert answer.endswith("Confirma?")


def test_a_receipt_from_this_month_is_not_second_guessed(scope, household):
    """No warning for the ordinary case. A prompt on every receipt is noise, and
    noise is what makes a real warning invisible."""
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, pix, category, when="2026-08-16")

    answer = propose_receipt(scope)

    assert "fatura" not in answer.lower()


def test_a_card_purchase_landing_in_the_future_is_not_warned_about(scope, household):
    """Bought today on a card that closes on the 10th: this lands in October and
    that is the product working. Warning here would fire on every card purchase."""
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, card, category, when="2026-08-16")

    answer = propose_receipt(scope)

    assert "Registrar nessa fatura?" not in answer
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q -k past_invoice`
Expected: FAIL — `AssertionError: assert 'junho/2023' in '| Categoria | Itens | Valor |\n\nConfirma?'`

- [ ] **Step 3: Write the implementation**

In `src/backend/assistant/agents/tools.py`, add to the imports at the top of the file:

```python
from assistant.agents.receipt_billing import (
    dashboard_url_for,
    month_label,
    plan_entry_date,
    prospective_billing_month,
)
```

Then replace the final line of `propose_receipt` (currently
`return f"{plan['table']}\n\nConfirma?"`, around line 625) with:

```python
    return f"{plan['table']}{_past_invoice_warning(scope, plan)}\n\nConfirma?"
```

And add this helper immediately above `propose_receipt`:

```python
def _past_invoice_warning(scope, plan) -> str:
    """A sentence naming the invoice, when that invoice is already behind us.

    D05: the walkthrough participant photographed a 2023 coupon, everything
    worked, and they were then looking at an empty August dashboard. Only a
    *past* month earns this — a card purchase made today lands in M+1 or M+2 by
    design, and warning about that would fire on nearly every receipt.
    """
    billing_month = prospective_billing_month(scope.household, plan)
    if billing_month is None:
        return ""
    if billing_month >= timezone.localdate().replace(day=1):
        return ""
    entry_date = plan_entry_date(plan)
    return (
        f"\n\n⚠️ Este cupom é de {entry_date:%d/%m/%Y}, então entra na fatura de "
        f"{month_label(billing_month)} — não no mês atual. Registrar nessa fatura?"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q`
Expected: PASS — 12 passed

- [ ] **Step 5: Run the existing receipt suite, which asserts on these strings**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q`
Expected: PASS. If a test in `test_receipt_flow.py` or `test_receipt_date_and_dup.py`
asserts an exact equality against `propose_receipt`'s output and its fixture is
backdated, it will now see the extra paragraph. Fix the *assertion* to match the
new copy — do not weaken the warning to satisfy an old string.

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_billing_month.py
git commit -m "feat(receipts): the proposal names a past invoice and asks about it"
```

---

### Task 3: The confirmation says which invoice it landed in (SD05-1)

The warning in Task 2 is a question asked before writing. This is the statement
made after writing, and it fires for any non-current month — future included —
because by then it costs nothing and it is the last thing the user sees.

**Files:**
- Modify: `src/backend/assistant/agents/tools.py` — `commit_receipt`, lines 640–643 and 687–692
- Test: `src/backend/assistant/tests/test_receipt_billing_month.py` (append)

**Interfaces:**
- Consumes: `plan_entry_date`, `prospective_billing_month`, `month_label`, `dashboard_url_for` from Task 1
- Produces: no new callable. `commit_receipt`'s returned string gains a trailing sentence.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_receipt_billing_month.py`:

```python
from assistant.agents.tools import commit_receipt
from finances.models import Entry


def test_the_confirmation_names_the_invoice_and_links_to_it(scope, household):
    """The walkthrough, replayed. A stranger reading this reply knows where the
    money went and has one thing to tap — which is the whole defect."""
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, pix, category)

    answer = commit_receipt(scope)

    assert "junho/2023" in answer
    assert "/?year=2023&month=6" in answer
    # And the row really is where the reply claims it is.
    entry = Entry.objects.for_household(household).get()
    assert entry.billing_month == date(2023, 6, 1)


def test_a_receipt_in_the_current_month_says_nothing_extra(scope, household):
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, pix, category, when="2026-08-16")

    answer = commit_receipt(scope)

    assert "fatura" not in answer.lower()


def test_a_future_invoice_is_named_too(scope, household):
    """SD05-1 says "not the current month", not "in the past". A card purchase
    that lands two invoices out is just as invisible on today's dashboard."""
    card = baker.make(
        PaymentMethod,
        household=household,
        name="Crédito Santander",
        type=PaymentType.CREDIT_CARD,
        closing_day=10,
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, card, category, when="2026-08-16")

    answer = commit_receipt(scope)

    assert "outubro/2026" in answer
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q -k names_the_invoice`
Expected: FAIL — `AssertionError: assert 'junho/2023' in '✅ Registrado de HIPERMACIONAL em 04/06/2023 via Pix: ...'`

- [ ] **Step 3: Write the implementation**

In `commit_receipt`, replace the date-parsing block (lines 640–643):

```python
    try:
        entry_date = date.fromisoformat(plan["date"])
    except (ValueError, TypeError, KeyError):
        entry_date = timezone.localdate()
```

with the shared helper, so the proposal and the commit cannot drift apart:

```python
    entry_date = plan_entry_date(plan)
```

Then replace the return statement (lines 689–692) with:

```python
    landed = _landing_sentence(scope, plan)
    return (
        f"✅ Registrado de {plan['store']} em {entry_date:%d/%m/%Y} via "
        f"{plan['payment_method_name']}: {parts} (total R$ {total:.2f}){landed}"
    )
```

And add this helper immediately above `commit_receipt`:

```python
def _landing_sentence(scope, plan) -> str:
    """Where the rows went, when that is not the month the dashboard is showing.

    D05's root cause: the dashboard is silent about months it is not showing, so
    a correct receipt filed under its own date reads as a failed capture. Fires
    for any non-current month, past or future — both are equally invisible on
    today's screen.
    """
    billing_month = prospective_billing_month(scope.household, plan)
    if billing_month is None or billing_month == timezone.localdate().replace(day=1):
        return ""
    label = month_label(billing_month)
    return f"\n\n📅 Entrou na fatura de {label}. [Ver {label}]({dashboard_url_for(billing_month)})"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py -q`
Expected: PASS — 15 passed

- [ ] **Step 5: Run the whole assistant suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q`
Expected: PASS. Same rule as Task 2: fixtures asserting the old exact confirmation
string get updated to the new copy.

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_billing_month.py
git commit -m "fix(receipts): the confirmation says which invoice the receipt landed in"
```

---

### Task 4: The API answers "is the ledger empty, or just this month?"

**Files:**
- Modify: `src/backend/finances/api/views.py`
- Modify: `src/backend/finances/api/urls.py`
- Test: `src/backend/finances/tests/test_ledger_elsewhere.py` (new)

**Interfaces:**
- Consumes: `_get_month_params(request)` — already in `finances/api/views.py`, returns `(year, month, billing_month)`; `assistant.agents.receipt_billing.month_label`
- Produces: `GET /api/dashboard/ledger-elsewhere/?year=&month=` returning
  ```json
  {"has_any": true, "nearest": {"year": 2023, "month": 6, "label": "junho/2023"}}
  ```
  `nearest` is `null` when the household has no entries outside the month asked
  about. Route name: `api_ledger_elsewhere`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_ledger_elsewhere.py`:

```python
"""Does this household have a ledger at all, or just not in the month on screen?

Frozen because the endpoint defaults to the current month when the query string
omits it, and "the current month" is exactly what the walkthrough's user was
staring at.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from finances.models import Category, Entry, PaymentMethod
from finances.models.payment_method import PaymentType

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
URL = "/api/dashboard/ledger-elsewhere/"


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


@pytest.fixture
def household(django_user_model):
    house = baker.make(Household, name="Casa de teste")
    user = baker.make(django_user_model, username="stranger")
    baker.make(Membership, household=house, user=user, role=Role.OWNER)
    return house, user


def _entry(household, user, when):
    return baker.make(
        Entry,
        household=household,
        created_by=user,
        date=when,
        amount=Decimal("10.00"),
        description="compra",
        category=baker.make(Category, household=household, name="Alimentação"),
        payment_method=baker.make(
            PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
        ),
    )


def test_a_household_with_nothing_has_nothing_anywhere(client, household):
    house, user = household
    client.force_login(user)

    body = client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_entries_in_another_month_are_reported_with_that_month(client, household):
    """The walkthrough's exact shape: three entries in 06/2023, a dashboard on
    08/2026, and an empty state that currently claims the ledger is empty."""
    house, user = household
    _entry(house, user, date(2023, 6, 4))
    client.force_login(user)

    body = client.get(URL).json()

    assert body["has_any"] is True
    assert body["nearest"] == {"year": 2023, "month": 6, "label": "junho/2023"}


def test_entries_in_the_month_on_screen_do_not_count_as_elsewhere(client, household):
    house, user = household
    _entry(house, user, date(2026, 8, 2))
    client.force_login(user)

    body = client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_the_nearest_month_wins(client, household):
    """Two candidates, and the one closest to the month on screen is the one a
    user is most likely to have meant."""
    house, user = household
    _entry(house, user, date(2023, 6, 4))
    _entry(house, user, date(2026, 5, 4))
    client.force_login(user)

    body = client.get(URL).json()

    assert body["nearest"]["year"] == 2026
    assert body["nearest"]["month"] == 5


def test_a_tie_prefers_the_more_recent_month(client, household):
    """June and October are both two months from August. Recent data is the more
    useful answer, and a deterministic rule beats whichever row sorted first."""
    house, user = household
    _entry(house, user, date(2026, 6, 4))
    _entry(house, user, date(2026, 10, 4))
    client.force_login(user)

    body = client.get(URL).json()

    assert body["nearest"]["month"] == 10


def test_it_answers_about_the_month_asked_for(client, household):
    house, user = household
    _entry(house, user, date(2023, 6, 4))
    client.force_login(user)

    body = client.get(f"{URL}?year=2023&month=6").json()

    assert body == {"has_any": False, "nearest": None}


def test_another_households_entries_are_invisible(client, household):
    """The scoping test this codebase requires of every read."""
    house, user = household
    other = baker.make(Household, name="Casa alheia")
    other_user = baker.make(type(user), username="outro")
    _entry(other, other_user, date(2023, 6, 4))
    client.force_login(user)

    body = client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_it_requires_a_login(client):
    assert client.get(URL).status_code in (401, 403)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_ledger_elsewhere.py -q`
Expected: FAIL — every test 404s, because the route does not exist.

- [ ] **Step 3: Write the implementation**

Add to `src/backend/finances/api/views.py`, after `RecentEntriesView`:

```python
class LedgerElsewhereView(APIView):
    """Whether this household has entries outside the month on screen.

    D05: the dashboard shows one billing month and says nothing about the others,
    so a correctly-filed backdated receipt reads as a capture that did nothing.
    The empty state needs to tell "you have recorded nothing" apart from "nothing
    in *this* month", and to do that it needs one fact the month's own queryset
    cannot provide.

    Distinct months only — the row count is months-with-data, not entries, so
    doing the ranking in Python is both correct and cheap.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        months = (
            Entry.objects.for_household(request.household)
            .exclude(billing_month=billing_month)
            .values_list("billing_month", flat=True)
            .distinct()
        )
        months = [m for m in months if m is not None]
        if not months:
            return Response({"has_any": False, "nearest": None})

        def distance(candidate):
            # Ordered by absolute distance in months, then by recency so a tie —
            # two months equally far either side — resolves to the newer one
            # rather than to whatever the database happened to return first.
            gap = abs((candidate.year - year) * 12 + (candidate.month - month))
            return (gap, -candidate.toordinal())

        nearest = min(months, key=distance)
        return Response(
            {
                "has_any": True,
                "nearest": {
                    "year": nearest.year,
                    "month": nearest.month,
                    "label": month_label(nearest),
                },
            }
        )
```

Add the import at the top of `src/backend/finances/api/views.py`:

```python
from assistant.agents.receipt_billing import month_label
```

> If importing `assistant` from `finances` is unacceptable to the reviewer as a
> layering violation, move `month_label` and `dashboard_url_for` to
> `src/backend/finances/services/billing.py` and import them from there in both
> places. Do not duplicate the month names — two lists of Portuguese month names
> will drift.

Register the route in `src/backend/finances/api/urls.py` — add to the import
block and to `urlpatterns`:

```python
    path("ledger-elsewhere/", LedgerElsewhereView.as_view(), name="api_ledger_elsewhere"),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_ledger_elsewhere.py -q`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/api/views.py src/backend/finances/api/urls.py src/backend/finances/tests/test_ledger_elsewhere.py
git commit -m "feat(dashboard): an endpoint that knows the ledger is not empty elsewhere"
```

---

### Task 5: The empty state stops claiming the ledger is empty (SD05-2)

`RecentEntriesCard` currently renders one empty state for both cases. E11 wrote
that copy to point at the wedge, and it stays for the genuinely-empty household —
the spec is explicit about that. The other-month case gets its own.

**Files:**
- Modify: `src/backend/frontend/src/types.ts`
- Modify: `src/backend/frontend/src/cards/RecentEntriesCard.tsx`
- Rebuild: `src/backend/static/frontend/mount.js`, `src/backend/static/css/tailwind.css`

**Interfaces:**
- Consumes: `GET /api/dashboard/ledger-elsewhere/` from Task 4; `useApiData<T>(url)` from `../useApiData`; `EmptyState` from `../components/EmptyState`
- Produces: no new exports. `RecentEntriesCard` keeps its `{ apiUrl }` prop.

- [ ] **Step 1: Add the response type**

In `src/backend/frontend/src/types.ts`, add:

```ts
export interface LedgerElsewhere {
  has_any: boolean;
  nearest: { year: number; month: number; label: string } | null;
}
```

- [ ] **Step 2: Branch the empty state**

Replace the `data.length === 0` block in
`src/backend/frontend/src/cards/RecentEntriesCard.tsx` with the version below, and
add `LedgerElsewhere` to the `types` import and a second `useApiData` call. The
full component after editing:

```tsx
import { formatBRL } from "../format";
import type { EntryData, LedgerElsewhere } from "../types";
import EmptyState from "../components/EmptyState";
import { openChat } from "../chat";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
  /** Same query string the card is rendered with, so "elsewhere" means
   *  "not the month on screen" rather than "not this calendar month". */
  elsewhereUrl: string;
}

export default function RecentEntriesCard({ apiUrl, elsewhereUrl }: Props) {
  const data = useApiData<EntryData[]>(apiUrl);
  const elsewhere = useApiData<LedgerElsewhere>(elsewhereUrl);

  if (!data)
    return (
      <div className="card bg-base-200 border border-base-200 animate-pulse h-48" />
    );

  if (data.length === 0) {
    // D05: a household with entries in another month is not an empty ledger, and
    // telling it that its first receipt did nothing is what made the walkthrough
    // participant re-enter the same purchase by hand.
    const other = elsewhere?.has_any ? elsewhere.nearest : null;
    return (
      <div className="card bg-base-200 border border-base-200">
        <div className="card-body p-4">
          <h3 className="text-[11px] uppercase tracking-wide opacity-60">Últimas Entradas</h3>
          {other ? (
            <EmptyState
              emoji="📅"
              title="Nada neste mês"
              description={`Seus lançamentos mais próximos estão em ${other.label}.`}
              actionLabel={`Ver ${other.label}`}
              actionHref={`/?year=${other.year}&month=${other.month}`}
            />
          ) : (
            <EmptyState
              emoji="📷"
              title="Nada lançado ainda"
              description="Fotografe um cupom fiscal — o app lê os itens, separa por categoria e lança tudo aqui."
              actionLabel="Fotografar um cupom"
              onAction={() => openChat()}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="card bg-base-200 border border-base-200">
      <div className="card-body p-4">
        <h3 className="text-[11px] uppercase tracking-wide opacity-60">Últimas Entradas</h3>
        <div className="space-y-1">
          {data.map((entry, i) => {
            const amount = parseFloat(entry.amount);
            return (
              <div
                key={i}
                className="flex justify-between text-xs py-1 border-b border-base-200 last:border-0"
              >
                <span className={amount < 0 ? "text-success" : "opacity-70"}>
                  {entry.date} {entry.description}
                </span>
                <span
                  className={`font-bold whitespace-nowrap ${amount < 0 ? "text-success" : "text-error"}`}
                >
                  {formatBRL(entry.amount)}
                </span>
              </div>
            );
          })}
        </div>
        <a
          href="/entries/"
          className="text-xs text-primary font-bold text-center mt-2 block"
        >
          Ver todas →
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Pass the new prop where the card is mounted**

Find the mount site: `grep -rn "RecentEntriesCard" src/backend/frontend/src/mount.tsx`.
It is mounted with `apiUrl` built from the template's `api_params`. Add the
sibling URL alongside it, using the same params:

```tsx
<RecentEntriesCard
  apiUrl={`/api/dashboard/recent-entries/?${params}`}
  elsewhereUrl={`/api/dashboard/ledger-elsewhere/?${params}`}
/>
```

Match whatever local variable `mount.tsx` already uses for the query string
rather than introducing a new one.

- [ ] **Step 4: Typecheck and build**

Run: `cd src/backend/frontend && pnpm build`
Expected: `tsc` clean, then `vite build` writes `../static/frontend/mount.js`.
A type error here means the prop was not threaded through step 3.

- [ ] **Step 5: Rebuild Tailwind**

Run from the repo root: `uv run python src/backend/manage.py tailwind build --force`
Expected: `Built production stylesheet '.../static/css/tailwind.css'.`

`--force` is required: without it the CLI can skip a rebuild and ship a stylesheet
missing any class the new markup introduced.

- [ ] **Step 6: Commit, including the build artifacts**

```bash
git add src/backend/frontend/src/types.ts \
        src/backend/frontend/src/cards/RecentEntriesCard.tsx \
        src/backend/frontend/src/mount.tsx \
        src/backend/static/frontend/mount.js \
        src/backend/static/css/tailwind.css
git commit -m "fix(dashboard): an empty month no longer claims an empty ledger"
```

Both artifacts are git-tracked and served directly in production. Committing the
`.tsx` without them ships the old bundle.

---

### Task 6: Replay the walkthrough, then close the defect

The DoD's last assertion is not a unit test: *the 2023 receipt from the
walkthrough, replayed, produces a confirmation a stranger could act on.* Tasks 2
and 3 already assert the strings; this task proves the two halves work together on
the real shape, and records the result where the walkthrough lives.

**Files:**
- Test: `src/backend/assistant/tests/test_receipt_billing_month.py` (append)
- Modify: `docs/superpowers/evidence/e11-walkthrough/README.md`
- Modify: `docs/backlog/D05-a-backdated-receipt-activates-into-an-invisible-month.md`
- Modify: `docs/backlog/INDEX.md`

- [ ] **Step 1: Write the end-to-end replay test**

Append to `src/backend/assistant/tests/test_receipt_billing_month.py`:

```python
def test_the_walkthrough_receipt_end_to_end(scope, household):
    """The 2026-08-16 walkthrough, replayed: a real coupon dated 2023-06-04,
    proposed and then committed, on a dashboard showing August 2026.

    Asserts the property the defect is about rather than exact copy — a stranger
    must be told the month and be given one thing to tap, at both moments.
    """
    pix = baker.make(
        PaymentMethod, household=household, name="Pix", type=PaymentType.PIX, closing_day=None
    )
    category = baker.make(Category, household=household, name="Alimentação")
    _pending_draft(household, pix, category, when="2023-06-04")

    proposal = propose_receipt(scope)
    confirmation = commit_receipt(scope)

    # Asked before writing...
    assert "junho/2023" in proposal
    assert proposal.rstrip().endswith("Confirma?")
    # ...and told after, with somewhere to go.
    assert "junho/2023" in confirmation
    assert "/?year=2023&month=6" in confirmation
    # And the rows are where both strings said they would be.
    assert Entry.objects.for_household(household).filter(billing_month=date(2023, 6, 1)).count() == 1
```

- [ ] **Step 2: Run it**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_billing_month.py::test_the_walkthrough_receipt_end_to_end -q`
Expected: PASS

- [ ] **Step 3: Run the Definition of Done in full**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: all pass. Fix anything that does not before continuing — this is the
gate, not a formality.

- [ ] **Step 4: Prove the suite is still time-stable**

```bash
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/assistant src/backend/finances -q -m "not current_date"
```

Expected: same result as unshifted. Every test added here freezes its own clock,
so a failure means one of them leaked a real `date.today()`.

- [ ] **Step 5: Record the outcome in the walkthrough evidence**

Append a section to `docs/superpowers/evidence/e11-walkthrough/README.md` stating
what D05 changed, in the same voice as the rest of that file: the participant's
114-second detour is now answered in two places, the proposal asks before filing
into a past invoice, and the empty dashboard names the month that has the data.
Link to this plan.

- [ ] **Step 6: Close the defect in the backlog**

In `docs/backlog/D05-a-backdated-receipt-activates-into-an-invisible-month.md`:
set `status: done` in the front matter, tick all four Observable assertions, and
answer both Open questions with what was decided (see *Decisions taken before this
plan* above) rather than deleting them — a question with a recorded answer is
worth more than a deleted one.

In `docs/backlog/INDEX.md`, change D05's row in the Defects table from `ready¹⁰`
to `**done** (2026-08-16)` with a footnote in the established style, saying what
shipped and naming this plan.

- [ ] **Step 7: Commit**

```bash
git add docs/ src/backend/assistant/tests/test_receipt_billing_month.py
git commit -m "docs(D05): close the defect; the walkthrough's receipt is now visible"
```

---

## Self-review

**Spec coverage**

| Spec requirement | Where |
|---|---|
| SD05-1 · confirmation says which invoice, offers a link | Task 3 |
| SD05-2 · empty state distinguishes the two cases, names the nearest month | Tasks 4 and 5 |
| SD05-2 · E11's wedge empty state stays for the genuinely empty case | Task 5, the `else` branch, asserted by `test_a_household_with_nothing_has_nothing_anywhere` plus the unchanged copy |
| DoD · committing into a non-current month says which month | Task 3 |
| DoD · a dashboard with data elsewhere does not claim the ledger is empty | Tasks 4 and 5 |
| DoD · both covered by test, clock frozen | Every test file sets an autouse `time_machine` fixture at midday UTC |
| DoD · the 2023 receipt replayed produces an actionable confirmation | Task 6 |
| Open question 1 | Decided: prompt, past-only, on the existing confirm turn (Task 2) |
| Open question 2 | Decided: both surfaces, because they fail in different places |
| Out of scope · `billing_month` derivation unchanged | No task touches `Entry.save`, `compute_billing_month`, or `billing_month_override`; Task 1 only *reads* the same derivation |
| Out of scope · no month-picker redesign | No task touches `DashboardView`'s selects |
| Out of scope · the walkthrough's 06/2023 rows are not moved | No task writes to existing entries |

**Adjacent bug, deliberately not fixed here.** The observer's notes on the
walkthrough (added 2026-08-16) record that the dashboard's year selector
**cannot reach 2023 at all** — `DashboardView` builds its options as
`range(2024, today.year + 2)` (`finances/views/dashboard.py:18`). Both remedies
in this plan still work, because the view reads `?year=` straight from the query
string and does not validate it against the selector's options; verify that when
implementing Task 5 rather than assuming it. Widening `year_range` is a
month-picker change, which D05's Out of scope explicitly excludes — it is filed
as candidate **D06** in the walkthrough record. Do not fold it into this plan; a
user who follows the link will land on 06/2023 correctly and then find the
selector snapping back to 2024, which is D06's problem to fix.

**Naming consistency:** `prospective_billing_month`, `plan_entry_date`,
`month_label`, `dashboard_url_for` are defined in Task 1 and used under those exact
names in Tasks 2, 3 and 4. `LedgerElsewhere` / `has_any` / `nearest` are defined in
Task 4's response and consumed under those keys in Task 5. `elsewhereUrl` is
introduced as a prop in Task 5 step 2 and passed in step 3.

**Known risk, flagged rather than hidden:** Tasks 2 and 3 change strings that
existing receipt tests may assert on exactly. Both tasks include a step that runs
the full assistant suite and say plainly which side to fix — the assertion, not
the warning.
