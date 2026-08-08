# E01 · Spend & Abuse Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single authenticated account cannot generate unbounded OpenAI spend, cannot write ledger data through an unprotected endpoint, and cannot brute-force the login — with an infrastructure ceiling that holds even if the application logic fails.

**Architecture:** Four independent layers, cheapest first. (1) Cloud Run `--max-instances` plus a GCP budget alert plus an OpenAI org spend cap — pure configuration, no deploy, caps the worst case before any code ships. (2) CSRF protection restored on the async streaming chat endpoint, with `SameSite` stated explicitly instead of inherited. (3) A per-account rolling-window throttle backed by a new `AssistantUsageEvent` row written *before* the model call, with a tighter budget for image turns. (4) A login lockout enforced in a custom authentication backend, so it follows `authenticate()` rather than a URL, and survives E05 replacing `/admin/login/`. A body-size middleware rejects oversized uploads from `Content-Length` before Django parses them.

**Tech Stack:** Django 6.0 (async views, ASGI/gunicorn+uvicorn), pytest + pytest-django + model-bakery, PydanticAI, PostgreSQL (Supabase in prod, local pgvector container on `:5433`), Cloud Run + Cloud Scheduler, `gcloud` CLI, `uv` for packaging, Ruff for lint/format.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7. Violating any of these fails review even if every task's tests pass.

- **TDD.** Test first, always. Project convention, not a preference.
- **Worktrees.** Feature work happens in an isolated worktree.
- **The money boundary holds.** The LLM proposes structured intent; Python computes every number. No arithmetic moves into a prompt.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean. Line length 100, double quotes, `target-version = "py312"`.
- **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
- **pt-BR in the product UI, English in code, comments, and docs.** User-facing strings (including the 429 body and the 413 body) are pt-BR; identifiers, docstrings, and this plan are English.
- **Migrations are reversible.**
- **No time-bomb tests.** Any date-sensitive test freezes the clock.
- **Tests run against the local pgvector container on port 5433**, not system Postgres: prefix every pytest invocation with `POSTGRES_PORT=5433`.

### Out of scope — do not drag these in

- Per-household cost attribution or token accounting → **E07**
- Model downgrading to reduce cost → **E09**
- Replacing `/admin/login/` with a real login page → **E05**
- Moving the vision call off the request → **E10**

---

## Decisions this plan locks in

The epic left three questions open. All three are answered here; do not re-litigate them mid-task.

**Open question 1 — spend thresholds.** Owner-confirmed conservative defaults:

| Ceiling | Value | Where set |
|---|---|---|
| Cloud Run max instances | `3` | `gcloud run services update --max-instances 3` |
| GCP budget alert | `USD 50/month`, notifying at 50% / 80% / 100% | Cloud Billing budget |
| OpenAI org monthly hard limit | `USD 30/month` | OpenAI console (no CLI exists) |
| OpenAI org soft alert | `USD 20/month` | OpenAI console |

These are assumptions to confirm with the owner *before* running the Task 1 commands, not after. They are deliberately independent: the GCP budget covers Cloud Run and Supabase egress; the OpenAI cap covers the thing the budget alert cannot stop (a budget alert *notifies*, it does not *block*).

**Open question 2 — throttle limits.** Measured, not guessed. Against the local copy of production data:

```
total user turns: 14      peak day: 5 turns      peak hour: 3 turns
image turns: 5            peak day: 3 images     peak hour: 3 images
```

The defaults below sit roughly 20× above the observed peak, so ordinary daily use never meets them, while a runaway client loop or a stolen session is capped within the hour. Task 4 re-runs this query against production before the numbers are frozen.

| Setting | Default |
|---|---|
| `ASSISTANT_THROTTLE_TEXT_PER_HOUR` | 60 |
| `ASSISTANT_THROTTLE_TEXT_PER_DAY` | 300 |
| `ASSISTANT_THROTTLE_IMAGE_PER_HOUR` | 15 |
| `ASSISTANT_THROTTLE_IMAGE_PER_DAY` | 50 |

Two buckets, not three: audio turns count against the *text* budget. Transcription is roughly two orders of magnitude cheaper per turn than a vision call, so it does not warrant its own ceiling — the image path is the only one that does.

**Open question 3 — how to throttle a non-DRF async view.** An explicit async guard function called from `chat_view`. Not DRF: `chat_view` is a plain async Django view returning a `StreamingHttpResponse`, DRF's throttle classes hang off `APIView`, and DRF has no async view support — adopting them means rewriting the streaming endpoint, which is exactly the kind of risk R0 exists to avoid. Not middleware: the image limit is tighter than the text limit, so middleware would have to parse the multipart body to tell them apart, before the view parses it again. An explicit call site keeps the "no model call before the check" guarantee visible in the code a reviewer reads.

---

## File Structure

| File | Responsibility |
|---|---|
| `docs/runbook.md` (modify) | Operator record of all three spend ceilings and how to change them |
| `src/backend/config/settings.py` (modify) | Explicit `SameSite`, throttle limits, body ceilings, `AUTHENTICATION_BACKENDS`, middleware registration |
| `src/backend/assistant/views.py` (modify) | Remove `@csrf_exempt`; call the throttle guard before any model work |
| `src/backend/assistant/models.py` (modify) | `AssistantUsageKind`, `AssistantUsageEvent` |
| `src/backend/assistant/migrations/0006_assistant_usage_event.py` (create) | The usage table + its index |
| `src/backend/assistant/throttling.py` (create) | Rolling-window rules and the exceeded-rule query. No HTTP knowledge |
| `src/backend/core/models.py` (modify) | `LoginAttempt` |
| `src/backend/core/migrations/0002_login_attempt.py` (create) | The login-attempt table + its indexes |
| `src/backend/core/security.py` (create) | `client_ip`, `is_locked` — pure functions over `LoginAttempt` |
| `src/backend/core/auth_backends.py` (create) | `LockoutModelBackend` |
| `src/backend/core/signals.py` (create) | Record failures, clear them on success |
| `src/backend/core/apps.py` (modify) | Connect the signals in `ready()` |
| `src/backend/core/middleware.py` (create) | `max_request_body_middleware` |
| `.env.example` (modify) | Every new env var, documented |

Tests:

| File | Covers |
|---|---|
| `src/backend/assistant/tests/test_chat_csrf.py` (create) | Task 2 |
| `src/backend/core/tests/test_deploy_settings.py` (modify) | Task 2 — `SameSite` assertions |
| `src/backend/assistant/tests/test_throttling.py` (create) | Tasks 3 and 4 |
| `src/backend/core/tests/test_login_lockout.py` (create) | Task 5 |
| `src/backend/core/tests/test_request_body_limit.py` (create) | Task 6 |

---

### Task 1: Infrastructure hard ceiling

Pure configuration and documentation. No code, no deploy, no test suite run. Do this first — it is the only task that caps risk without shipping anything.

**Files:**
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks import. The runbook section it adds is titled `## Spend ceilings`; Task 4 and Task 6 append their env vars to that section.

- [ ] **Step 1: Confirm the numbers with the owner**

Post exactly this and wait for a yes or a correction. Do not proceed on silence.

```
E01 Task 1 needs three ceilings confirmed before I set them:
  - Cloud Run --max-instances: 3
  - GCP budget alert: USD 50/month, notifying at 50% / 80% / 100%
  - OpenAI org limit: USD 30/month hard, USD 20/month soft alert
Confirm or give me different numbers.
```

If the owner gives different numbers, use theirs everywhere below and in the runbook.

- [ ] **Step 2: Record the current state, so you can reverse this**

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="yaml(spec.template.metadata.annotations)"
```

Expected: the annotation map has **no** `autoscaling.knative.dev/maxScale` key, which is the finding this task closes. Paste the output into the task's notes.

- [ ] **Step 3: Set the Cloud Run instance ceiling**

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --max-instances 3
```

Expected: `Service [expense-tracker] revision [expense-tracker-000NN-xxx] has been deployed and is serving 100 percent of traffic.`

**Common failure:** `gcloud`'s active project on this machine defaults to something else. Always pass `--project expense-tracker-482807` explicitly.

- [ ] **Step 4: Verify the ceiling took**

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"
```

Expected: `3`

- [ ] **Step 5: Create the GCP budget alert**

```bash
gcloud services enable billingbudgets.googleapis.com --project expense-tracker-482807

BILLING=$(gcloud billing projects describe expense-tracker-482807 \
  --format="value(billingAccountName)")
BILLING=${BILLING#billingAccounts/}

gcloud billing budgets create \
  --billing-account="$BILLING" \
  --display-name="expense-tracker monthly ceiling" \
  --budget-amount=50USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.8 \
  --threshold-rule=percent=1.0 \
  --filter-projects="projects/expense-tracker-482807"
```

Expected: a `name: billingAccounts/.../budgets/<uuid>` line. Record that budget ID — Step 6 and the runbook need it.

**Common failure:** `PERMISSION_DENIED` means the Billing Budget API is not enabled, or the account lacks `roles/billing.admin`. Run the `services enable` line first; if it still fails, the owner must grant billing admin on the billing account (not the project).

- [ ] **Step 6: Prove the notification path actually fires**

A budget that never notified is an untested alarm. Temporarily drop the threshold below current spend, wait for the email, then restore.

```bash
BUDGET=<the uuid from step 5>
gcloud billing budgets update "billingAccounts/$BILLING/budgets/$BUDGET" \
  --budget-amount=1USD
# wait for the alert email to the billing account admins (up to ~1 hour), then:
gcloud billing budgets update "billingAccounts/$BILLING/budgets/$BUDGET" \
  --budget-amount=50USD
```

Expected: an email titled like `Budget alert: expense-tracker monthly ceiling`. Record that it arrived — this is a DoD assertion.

**Common failure:** no email because the billing account's notification preferences exclude budget alerts, or because you are looking at the project owner's inbox rather than the *billing account* admin's. Check `https://console.cloud.google.com/billing/$BILLING/budgets`.

- [ ] **Step 7: Set the OpenAI organisation spend limit**

No CLI exists. In the OpenAI console at <https://platform.openai.com/settings/organization/limits>, set the monthly budget to **USD 30** (hard) with a **USD 20** notification threshold.

This is the backstop that matters most: the GCP budget alert only *notifies*, while the OpenAI limit *stops serving requests*. Confirm the values are saved by reloading the page.

- [ ] **Step 8: Write the runbook section**

Add this to `docs/runbook.md`, after the `## Deploy a new revision` section:

````markdown
## Spend ceilings

Three independent caps. Each is set to hold if the other two fail, and the app
layer (E01's throttle) sits below all of them.

| Ceiling | Value | Effect when hit |
|---|---|---|
| Cloud Run `--max-instances` | 3 | New requests queue rather than starting a 4th billable instance |
| GCP budget alert | USD 50/month | **Notifies only.** Email at 50%, 80%, 100% |
| OpenAI org monthly limit | USD 30/month hard, USD 20 soft | API returns errors — the actual stop |

### Read the current values

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"

BILLING=$(gcloud billing projects describe expense-tracker-482807 \
  --format="value(billingAccountName)"); BILLING=${BILLING#billingAccounts/}
gcloud billing budgets list --billing-account="$BILLING" \
  --format="table(displayName,amount.specifiedAmount.units)"
```

The OpenAI limit has no CLI — read it at
<https://platform.openai.com/settings/organization/limits>.

### Change them

```bash
# Instance ceiling
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --max-instances <N>

# Budget amount
gcloud billing budgets update "billingAccounts/$BILLING/budgets/<BUDGET_UUID>" \
  --budget-amount=<N>USD
```

Budget UUID: `<paste the uuid from creation>`.

**Common failure:** raising `--max-instances` without also raising the OpenAI cap
moves the bottleneck to the expensive layer. Raise the OpenAI limit *first*, or
not at all.

**Why max-instances is this low:** the container is 1 vCPU / 1Gi running a single
gunicorn worker with an async uvicorn worker at concurrency 80 (see *Why the
container starts the way it does*). Three instances is ~240 concurrent requests —
far above real demand, and the point is the ceiling, not the headroom.
````

Replace `<paste the uuid from creation>` with the budget ID from Step 5 — it is
the one value in that section a future operator cannot look up from the commands
above.

- [ ] **Step 9: Commit**

```bash
git add docs/runbook.md
git commit -m "docs(runbook): record the three spend ceilings and how to change them"
```

---

### Task 2: Restore CSRF protection and state SameSite explicitly

**Files:**
- Modify: `src/backend/assistant/views.py:135-140` (drop the `csrf_exempt` import and decorator)
- Modify: `src/backend/config/settings.py` (add `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE`)
- Create: `src/backend/assistant/tests/test_chat_csrf.py`
- Modify: `src/backend/core/tests/test_deploy_settings.py` (add a `TestCookieSameSite` class)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks import. Task 4 edits the same `chat_view` body, so land this first to keep the diffs separable.

**Background the implementer needs:** the React widget already sends the token. `src/backend/frontend/src/api.ts:2-12` and `src/backend/frontend/src/cards/ChatWidget.tsx:376,505` read `csrftoken` from `document.cookie` and send it as `X-CSRFToken` with `credentials: "same-origin"`. No frontend change is required. The endpoint is `async` and returns a `StreamingHttpResponse`; Django's `CsrfViewMiddleware` runs entirely in `process_view`, before the view is called, so it never touches the response body — verified behaviour, but the test below pins it.

The Django test `Client` ignores CSRF unless constructed with `enforce_csrf_checks=True`. A GET of `/` sets a 32-character `csrftoken` cookie (verified); Django accepts that unmasked 32-char secret directly as the `X-CSRFToken` header value.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_chat_csrf.py`:

```python
"""CSRF must be enforced on the write-capable chat endpoint.

``chat_view`` can reach every mutating tool in ``assistant.views.MUTATING_TOOLS``.
It was ``@csrf_exempt`` because the React widget sends the token in a header
rather than a form field — but the middleware reads the header too, so the
exemption bought nothing and cost the protection.
"""

import json

import pytest
from django.test import Client
from pydantic_ai.models.test import TestModel

from assistant.agents.assistant import agents_override
from assistant.models import ChatMessage


@pytest.fixture
def csrf_client(user):
    """A client that enforces CSRF and already holds a csrftoken cookie."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    client.get("/")  # any rendered page sets the cookie
    return client


@pytest.mark.django_db
class TestChatCsrf:
    def test_post_without_token_is_rejected(self, csrf_client, user):
        response = csrf_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert response.status_code == 403
        assert not ChatMessage.objects.filter(user=user).exists()

    def test_post_with_invalid_token_is_rejected(self, csrf_client, user):
        response = csrf_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
            headers={"x-csrftoken": "x" * 64},
        )
        assert response.status_code == 403
        assert not ChatMessage.objects.filter(user=user).exists()

    def test_post_with_valid_token_succeeds(self, csrf_client, user):
        token = csrf_client.cookies["csrftoken"].value
        with agents_override(TestModel()):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"

    def test_multipart_image_with_valid_token_succeeds(self, csrf_client, user):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from assistant.agents.assistant import assistant_agent
        from assistant.agents.extraction import extraction_agent

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        token = csrf_client.cookies["csrftoken"].value
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data={"image": image},
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200

    def test_multipart_audio_with_valid_token_succeeds(self, csrf_client, user, monkeypatch):
        from django.core.files.uploadedfile import SimpleUploadedFile

        async def fake_transcribe(data, filename, content_type, *, client=None):
            return "mercado 80 no pix"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        token = csrf_client.cookies["csrftoken"].value
        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        with agents_override(TestModel()):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data={"audio": audio},
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200


def test_no_csrf_exempt_remains_in_the_assistant_app():
    """A regression guard: the exemption must not come back by copy-paste."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent
    offenders = [
        path.name
        for path in app_dir.rglob("*.py")
        if "tests" not in path.parts and "csrf_exempt" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
```

Add to `src/backend/core/tests/test_deploy_settings.py`, at the end of the file:

```python
class TestCookieSameSite:
    """SameSite must be stated, not inherited.

    Django's current default is ``Lax`` and ``Lax`` is what this app wants — the
    React widget and the Android TWA are both same-origin. The point of pinning
    it is that a Django default change, or an ``os.environ`` override applied by
    mistake, becomes a failing test rather than a silent CSRF weakening.
    """

    def test_session_cookie_samesite_is_lax(self):
        assert settings.SESSION_COOKIE_SAMESITE == "Lax"

    def test_csrf_cookie_samesite_is_lax(self):
        assert settings.CSRF_COOKIE_SAMESITE == "Lax"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_chat_csrf.py \
  src/backend/core/tests/test_deploy_settings.py::TestCookieSameSite -v
```

Expected failures:
- `test_post_without_token_is_rejected` — FAIL, `assert 200 == 403` (the exemption is still there)
- `test_post_with_invalid_token_is_rejected` — FAIL, `assert 200 == 403`
- `test_no_csrf_exempt_remains_in_the_assistant_app` — FAIL, `assert ['views.py'] == []`
- `test_session_cookie_samesite_is_lax` — FAIL, `AttributeError`/`assert None == 'Lax'`
- `test_csrf_cookie_samesite_is_lax` — FAIL, same
- The three "with valid token succeeds" tests — PASS already (the exemption makes everything pass); they exist to prove the *next* step does not break the happy paths.

- [ ] **Step 3: Remove the exemption**

In `src/backend/assistant/views.py`, delete the import on line 7:

```python
from django.views.decorators.csrf import csrf_exempt
```

and replace the decorator block at lines 135-140:

```python
# csrf_exempt: o widget React envia o token CSRF via header X-CSRFToken (lido do
# cookie). credentials: same-origin garante envio do cookie. Testes usam o test
# client do Django, que ignora CSRF.
@csrf_exempt
@require_http_methods(["POST"])
async def chat_view(request):
```

with:

```python
# CSRF is enforced. The React widget sends the token as the X-CSRFToken header
# (read from the cookie, with credentials: same-origin), which is exactly what
# CsrfViewMiddleware checks — the exemption bought nothing. The middleware runs
# in process_view, before the view, so it never touches the streaming response.
@require_http_methods(["POST"])
async def chat_view(request):
```

- [ ] **Step 4: State SameSite explicitly**

In `src/backend/config/settings.py`, immediately after the `CSRF_TRUSTED_ORIGINS` line (line 16), add:

```python
# Stated rather than inherited. Lax is correct here — the React widget and the
# Android TWA are both same-origin — but a setting that is only correct by
# default breaks silently when the default changes. Tests pin these values.
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_chat_csrf.py \
  src/backend/core/tests/test_deploy_settings.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole assistant app — the existing tests use a non-enforcing client and must still pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```

Expected: no new failures. The existing `src/backend/assistant/tests/test_views.py` builds `Client()` without `enforce_csrf_checks`, so those tests are unaffected by design.

- [ ] **Step 7: Confirm the grep assertion from the epic's DoD**

```bash
grep -rn 'csrf_exempt' src/backend/assistant/
```

Expected: no output at all (exit status 1).

- [ ] **Step 8: Commit**

```bash
git add src/backend/assistant/views.py src/backend/config/settings.py \
        src/backend/assistant/tests/test_chat_csrf.py \
        src/backend/core/tests/test_deploy_settings.py
git commit -m "fix(assistant): enforce CSRF on the chat endpoint and pin SameSite"
```

---

### Task 3: Usage events and the rolling-window counter

The data layer the throttle reads. Deliberately separate from Task 4 so the counting logic gets its own tests without an HTTP client in the way.

**Files:**
- Modify: `src/backend/assistant/models.py` (append)
- Create: `src/backend/assistant/migrations/0006_assistant_usage_event.py` (generated)
- Create: `src/backend/assistant/throttling.py`
- Modify: `src/backend/config/settings.py` (four throttle settings)
- Modify: `.env.example`
- Create: `src/backend/assistant/tests/test_throttling.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, for Task 4:
  - `assistant.models.AssistantUsageKind` — a `TextChoices` with members `TEXT = "text"` and `IMAGE = "image"`
  - `assistant.models.AssistantUsageEvent` — fields `id: UUID`, `user: FK`, `kind: str`, `created_at: datetime`
  - `assistant.throttling.ThrottleRule` — frozen dataclass with `limit: int`, `window: timedelta`, `label: str`
  - `assistant.throttling.rules_for(kind: str) -> list[ThrottleRule]`
  - `async assistant.throttling.exceeded_rule(user, kind: str, *, now: datetime | None = None) -> ThrottleRule | None`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_throttling.py`:

```python
"""Rolling-window counting for the assistant throttle.

The window is rolling rather than calendar-bucketed on purpose: a calendar hour
lets a caller spend the whole hourly budget at 10:59 and the whole next budget at
11:00, doubling the real ceiling at exactly the moment that matters.
"""

from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from assistant.models import AssistantUsageEvent, AssistantUsageKind
from assistant.throttling import exceeded_rule, rules_for


def _burn(user, kind, count, *, age=timedelta(0)):
    """Create ``count`` usage events, backdated by ``age``."""
    stamp = timezone.now() - age
    for _ in range(count):
        event = AssistantUsageEvent.objects.create(user=user, kind=kind)
        AssistantUsageEvent.objects.filter(pk=event.pk).update(created_at=stamp)


@pytest.mark.django_db
class TestRulesFor:
    def test_image_rules_are_tighter_than_text_rules(self, settings):
        text_hourly = rules_for(AssistantUsageKind.TEXT)[0]
        image_hourly = rules_for(AssistantUsageKind.IMAGE)[0]
        assert image_hourly.limit < text_hourly.limit

    def test_rules_read_current_settings(self, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 7
        assert rules_for(AssistantUsageKind.TEXT)[0].limit == 7

    def test_each_kind_has_an_hourly_and_a_daily_rule(self):
        for kind in (AssistantUsageKind.TEXT, AssistantUsageKind.IMAGE):
            windows = {rule.window for rule in rules_for(kind)}
            assert windows == {timedelta(hours=1), timedelta(days=1)}


@pytest.mark.django_db
class TestExceededRule:
    def test_no_usage_is_never_throttled(self, user):
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_under_the_hourly_limit_is_allowed(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 4)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_at_the_hourly_limit_is_blocked(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 5)
        rule = async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT)
        assert rule is not None
        assert rule.limit == 5
        assert rule.label == "hora"

    def test_events_outside_the_window_do_not_count(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 5, age=timedelta(hours=2))
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_daily_limit_blocks_even_when_hourly_is_clear(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 6
        _burn(user, AssistantUsageKind.TEXT, 6, age=timedelta(hours=5))
        rule = async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT)
        assert rule is not None
        assert rule.label == "dia"

    def test_kinds_have_independent_budgets(self, user, settings):
        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 2
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.IMAGE, 2)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.IMAGE) is not None
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_other_users_usage_does_not_count(self, user, settings):
        from model_bakery import baker

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 2
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        stranger = baker.make("core.CustomUser", username="stranger")
        _burn(stranger, AssistantUsageKind.TEXT, 5)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_throttling.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'assistant.throttling'`.

- [ ] **Step 3: Add the model**

Append to `src/backend/assistant/models.py`:

```python
class AssistantUsageKind(models.TextChoices):
    TEXT = "text", "Texto"
    IMAGE = "image", "Imagem"


class AssistantUsageEvent(models.Model):
    """One admitted assistant turn.

    Written *before* the model call, so the counter records intent to spend
    rather than successful spend — a run that fails halfway still consumed the
    tokens. Audio turns count as ``TEXT``: transcription is roughly two orders of
    magnitude cheaper per turn than a vision call, so only the image path earns a
    budget of its own.

    E07 will extend this row with token counts and a household FK. Keep it
    append-only and cheap to write.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_usage_events",
    )
    kind = models.CharField(max_length=20, choices=AssistantUsageKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de uso do assistente"
        verbose_name_plural = "eventos de uso do assistente"
        indexes = [
            models.Index(
                fields=["user", "kind", "-created_at"],
                name="usage_user_kind_recent_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.kind} {self.created_at:%Y-%m-%d %H:%M}"
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
uv run python src/backend/manage.py makemigrations assistant \
  --name assistant_usage_event
```

Expected: `Migrations for 'assistant': assistant/migrations/0006_assistant_usage_event.py - Create model AssistantUsageEvent`.

Read the generated file. It must contain both `CreateModel` and an `AddIndex` (or the index inside `options`). `CreateModel` is reversible by construction — no `RunPython`, no `RunSQL`, nothing to hand-write.

- [ ] **Step 5: Write the throttling module**

Create `src/backend/assistant/throttling.py`:

```python
"""Per-account rate limiting for the assistant endpoint.

Why not DRF throttling: ``chat_view`` is a plain async Django view returning a
``StreamingHttpResponse``. DRF's throttle classes hang off ``APIView`` and DRF
has no async view support, so adopting them means rewriting the streaming
endpoint — exactly the risk R0 exists to avoid.

Why not middleware: the image budget is tighter than the text budget, so a
middleware would have to parse the multipart body to tell them apart, before the
view parses it again. Calling the guard from ``chat_view`` keeps the "no model
call before the check" guarantee visible where a reviewer reads it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from assistant.models import AssistantUsageEvent, AssistantUsageKind

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@dataclass(frozen=True)
class ThrottleRule:
    limit: int
    window: timedelta
    label: str  # pt-BR noun for the user-facing message


def rules_for(kind: str) -> list[ThrottleRule]:
    """The rules that apply to ``kind``, hourly first.

    Read from settings on every call rather than captured at import time, so the
    ``settings`` fixture can override them in tests and an env change takes
    effect on the next deploy without a code change.
    """
    if kind == AssistantUsageKind.IMAGE:
        return [
            ThrottleRule(settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR, HOUR, "hora"),
            ThrottleRule(settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY, DAY, "dia"),
        ]
    return [
        ThrottleRule(settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR, HOUR, "hora"),
        ThrottleRule(settings.ASSISTANT_THROTTLE_TEXT_PER_DAY, DAY, "dia"),
    ]


async def exceeded_rule(
    user, kind: str, *, now: datetime | None = None
) -> ThrottleRule | None:
    """The first rule this user has already met, or ``None`` when clear.

    "Met", not "exceeded": a user who has spent exactly ``limit`` turns in the
    window is done, because the turn being checked would be number ``limit + 1``.
    """
    now = now or timezone.now()
    for rule in rules_for(kind):
        used = await AssistantUsageEvent.objects.filter(
            user=user, kind=kind, created_at__gte=now - rule.window
        ).acount()
        if used >= rule.limit:
            return rule
    return None
```

- [ ] **Step 6: Add the settings**

In `src/backend/config/settings.py`, after the `ASSISTANT_ALLOWED_AUDIO_TYPES` tuple (line 215), add:

```python
# Assistant throttling — a crude per-account ceiling, deliberately blunt (E01).
# Sized from measured usage: the single production account peaked at 5 turns/day
# and 3 turns/hour, of which 3 were image turns. These defaults sit ~20x above
# that peak, so ordinary daily use never meets them, while a runaway client loop
# or a stolen session is capped within the hour.
# Audio counts against the TEXT budget: transcription is ~100x cheaper per turn
# than a vision call, so only the image path needs its own ceiling.
ASSISTANT_THROTTLE_TEXT_PER_HOUR = int(os.environ.get("ASSISTANT_THROTTLE_TEXT_PER_HOUR", "60"))
ASSISTANT_THROTTLE_TEXT_PER_DAY = int(os.environ.get("ASSISTANT_THROTTLE_TEXT_PER_DAY", "300"))
ASSISTANT_THROTTLE_IMAGE_PER_HOUR = int(os.environ.get("ASSISTANT_THROTTLE_IMAGE_PER_HOUR", "15"))
ASSISTANT_THROTTLE_IMAGE_PER_DAY = int(os.environ.get("ASSISTANT_THROTTLE_IMAGE_PER_DAY", "50"))
```

- [ ] **Step 7: Document the env vars**

In `.env.example`, after the `ASSISTANT_MAX_HISTORY=20` line, add:

```
# --- Assistant throttling (E01) ---
# Rolling-window per-account ceilings. Rejected turns never reach the model.
# Defaults are ~20x measured peak usage; raise only with a reason.
ASSISTANT_THROTTLE_TEXT_PER_HOUR=60
ASSISTANT_THROTTLE_TEXT_PER_DAY=300
ASSISTANT_THROTTLE_IMAGE_PER_HOUR=15
ASSISTANT_THROTTLE_IMAGE_PER_DAY=50
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_throttling.py -v
```

Expected: all PASS.

- [ ] **Step 9: Prove the migration reverses**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0005
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: the down-migration prints `Unapplying assistant.0006_assistant_usage_event... OK`, the re-apply prints `Applying ... OK`, and `makemigrations --check` prints `No changes detected` and exits 0.

- [ ] **Step 10: Commit**

```bash
git add src/backend/assistant/models.py src/backend/assistant/throttling.py \
        src/backend/assistant/migrations/0006_assistant_usage_event.py \
        src/backend/assistant/tests/test_throttling.py \
        src/backend/config/settings.py .env.example
git commit -m "feat(assistant): usage events and rolling-window throttle rules"
```

---

### Task 4: Enforce the throttle in the chat endpoint

**Files:**
- Modify: `src/backend/assistant/views.py:140-151` (`chat_view`)
- Modify: `src/backend/assistant/tests/test_throttling.py` (append an endpoint test class)
- Modify: `docs/runbook.md` (append to `## Spend ceilings`)

**Interfaces:**
- Consumes from Task 3: `AssistantUsageKind`, `AssistantUsageEvent`, `exceeded_rule(user, kind, *, now=None) -> ThrottleRule | None` (async), `ThrottleRule.limit`, `ThrottleRule.label`.
- Produces: `assistant.views.throttle_denial(user, kind) -> JsonResponse | None` (async). Returns a 429 response when blocked; otherwise records the usage event and returns `None`.

- [ ] **Step 1: Re-derive the limits against production before freezing them**

The numbers in Task 3 came from the local copy, which lags production. Confirm against the live database:

```bash
# Uses the Supabase session connection, not the pooler — see docs/runbook.md
DATABASE_URL="<supabase session URL, port 5432>" \
  uv run python src/backend/manage.py shell -c "
from django.db.models import Count
from django.db.models.functions import TruncDate, TruncHour
from assistant.models import ChatMessage
qs = ChatMessage.objects.filter(role='user')
print('turns:', qs.count())
print('peak day:', list(qs.annotate(d=TruncDate('created_at')).values('d')
      .annotate(n=Count('id')).order_by('-n')[:3]))
print('peak hour:', list(qs.annotate(h=TruncHour('created_at')).values('h')
      .annotate(n=Count('id')).order_by('-n')[:3]))
img = qs.filter(content__startswith='📷')
print('image peak day:', list(img.annotate(d=TruncDate('created_at')).values('d')
      .annotate(n=Count('id')).order_by('-n')[:3]))
"
```

If the observed peak hour exceeds 3 turns, raise the defaults so they stay at roughly 20× peak, and update both `settings.py` and `.env.example`. Record the observed numbers in the commit message.

- [ ] **Step 2: Write the failing tests**

Append to `src/backend/assistant/tests/test_throttling.py`:

```python
@pytest.mark.django_db
class TestChatEndpointThrottle:
    """The endpoint must refuse an over-limit turn before spending anything."""

    def _post_text(self, client, monkeypatch):
        """POST a text turn with ``_sse_response`` replaced by a call recorder.

        Replacing ``_sse_response`` is the cheapest place to prove "zero model
        calls": every path that reaches the model goes through it, and nothing
        else does. The stub must return a real ``HttpResponse`` — ``_handle_json``
        returns its result straight to Django, which raises on ``None``.
        """
        import json

        from django.http import HttpResponse

        calls = []

        def _stub_sse(*args, **kwargs):
            calls.append("call")
            return HttpResponse("stubbed", content_type="text/event-stream")

        monkeypatch.setattr("assistant.views._sse_response", _stub_sse)
        response = client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        return response, calls

    def test_under_the_limit_reaches_the_model(self, logged_client, user, monkeypatch, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 2)
        response, calls = self._post_text(logged_client, monkeypatch)
        assert response.status_code == 200
        assert len(calls) == 1

    def test_over_the_limit_makes_zero_model_calls(
        self, logged_client, user, monkeypatch, settings
    ):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        response, calls = self._post_text(logged_client, monkeypatch)
        assert response.status_code == 429
        assert calls == []

    def test_rejection_message_is_pt_br_and_names_the_window(
        self, logged_client, user, monkeypatch, settings
    ):
        import json as _json

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        response, _ = self._post_text(logged_client, monkeypatch)
        body = _json.loads(response.content)
        assert "Limite" in body["error"]
        assert "hora" in body["error"]

    def test_rejected_turn_writes_no_chat_message(
        self, logged_client, user, monkeypatch, settings
    ):
        from assistant.models import ChatMessage

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        self._post_text(logged_client, monkeypatch)
        assert not ChatMessage.objects.filter(user=user).exists()

    def test_admitted_turn_records_one_usage_event(
        self, logged_client, user, monkeypatch, settings
    ):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 10
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        self._post_text(logged_client, monkeypatch)
        assert (
            AssistantUsageEvent.objects.filter(
                user=user, kind=AssistantUsageKind.TEXT
            ).count()
            == 1
        )

    def test_rejected_turn_records_no_usage_event(
        self, logged_client, user, monkeypatch, settings
    ):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        self._post_text(logged_client, monkeypatch)
        assert (
            AssistantUsageEvent.objects.filter(
                user=user, kind=AssistantUsageKind.TEXT
            ).count()
            == 3
        )

    def test_image_turn_spends_the_image_budget_not_the_text_one(
        self, logged_client, user, monkeypatch, settings
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.IMAGE, 1)

        calls = []

        async def _stub_multipart(*args, **kwargs):
            # async, because chat_view awaits it — a plain lambda would raise a
            # confusing TypeError instead of failing this test cleanly.
            from django.http import HttpResponse

            calls.append("call")
            return HttpResponse("stubbed", content_type="text/event-stream")

        monkeypatch.setattr("assistant.views._handle_multipart", _stub_multipart)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        response = logged_client.post("/api/assistant/chat/", data={"image": image})
        assert response.status_code == 429
        assert calls == []
        assert "fotos" in response.content.decode()

    def test_audio_turn_spends_the_text_budget(self, logged_client, user, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 1)
        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        response = logged_client.post("/api/assistant/chat/", data={"audio": audio})
        assert response.status_code == 429
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_throttling.py::TestChatEndpointThrottle -v
```

Expected: every `over the limit` test FAILs with `assert 200 == 429`; the usage-event tests FAIL with `assert 0 == 1`.

- [ ] **Step 4: Add the guard and wire it into `chat_view`**

In `src/backend/assistant/views.py`, add to the imports:

```python
from assistant.models import (
    AssistantUsageEvent,
    AssistantUsageKind,
    ChatMessage,
    MessageRole,
    ReceiptDraft,
)
from assistant.throttling import exceeded_rule
```

(replacing the existing `from assistant.models import ChatMessage, MessageRole, ReceiptDraft` line).

Then add, immediately above `chat_view`:

```python
async def throttle_denial(user, kind: str):
    """Refuse an over-budget turn, or admit it and record the spend.

    Returns a 429 ``JsonResponse`` when blocked and ``None`` when admitted. The
    usage event is written on admission — before any model call — so a request
    that dies mid-stream still counts against the budget it was going to spend.
    """
    rule = await exceeded_rule(user, kind)
    if rule is None:
        await AssistantUsageEvent.objects.acreate(user=user, kind=kind)
        return None
    noun = "fotos" if kind == AssistantUsageKind.IMAGE else "mensagens"
    return JsonResponse(
        {
            "error": (
                f"Limite de {noun} do assistente atingido "
                f"({rule.limit} por {rule.label}). Tente de novo mais tarde."
            )
        },
        status=429,
    )
```

Replace the body of `chat_view` (lines 140-151) with:

```python
@require_http_methods(["POST"])
async def chat_view(request):
    """Chat. Aceita JSON (texto) ou multipart/form-data (áudio/imagem)."""
    from django.contrib.auth import aget_user

    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    content_type = request.content_type or ""
    is_multipart = content_type.startswith("multipart/form-data")
    # The kind is decided here, before any model work, because the image budget
    # is tighter. request.FILES parsing is bounded by MAX_REQUEST_BODY_BYTES,
    # enforced upstream in core.middleware.
    kind = (
        AssistantUsageKind.IMAGE
        if is_multipart and request.FILES.getlist("image")
        else AssistantUsageKind.TEXT
    )
    denial = await throttle_denial(user, kind)
    if denial is not None:
        return denial

    if is_multipart:
        return await _handle_multipart(request, user)
    return await _handle_json(request, user)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_throttling.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the whole assistant app**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```

Expected: no failures. If a pre-existing test now hits the throttle because it posts many turns in one test, that is the throttle working — raise the limit for that test with the `settings` fixture rather than weakening the default.

- [ ] **Step 7: Confirm the DoD grep now matches**

```bash
grep -rniE 'throttle|ratelimit' src/backend --include='*.py' | grep -v tests
```

Expected: hits in `assistant/throttling.py`, `assistant/views.py`, and `config/settings.py`.

- [ ] **Step 8: Extend the runbook**

Append to the `## Spend ceilings` section of `docs/runbook.md`:

````markdown
### The application-layer throttle

Below the three infrastructure ceilings sits a per-account rolling-window limit.
An over-limit turn is refused with HTTP 429 **before any model call**, so it costs
nothing. Limits are env vars — change them without a code change:

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --update-env-vars ASSISTANT_THROTTLE_IMAGE_PER_HOUR=25
```

| Var | Default | Bucket |
|---|---|---|
| `ASSISTANT_THROTTLE_TEXT_PER_HOUR` | 60 | text + audio turns |
| `ASSISTANT_THROTTLE_TEXT_PER_DAY` | 300 | text + audio turns |
| `ASSISTANT_THROTTLE_IMAGE_PER_HOUR` | 15 | receipt photo turns |
| `ASSISTANT_THROTTLE_IMAGE_PER_DAY` | 50 | receipt photo turns |

Use `--update-env-vars` (merge), never `--set-env-vars` — the latter replaces the
whole env list and wipes `DATABASE_URL`.

### Who is hitting the limit

```bash
DATABASE_URL="<supabase session URL, port 5432>" \
  uv run python src/backend/manage.py shell -c "
from django.db.models import Count
from django.db.models.functions import TruncDate
from assistant.models import AssistantUsageEvent
print(list(AssistantUsageEvent.objects.annotate(d=TruncDate('created_at'))
      .values('d','kind','user__username').annotate(n=Count('id')).order_by('-n')[:20]))
"
```

**Common failure:** the numbers look impossibly low because you connected through
the Supabase *transaction* pooler (port 6543) against the wrong database. Use the
session connection on 5432.
````

- [ ] **Step 9: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/tests/test_throttling.py \
        docs/runbook.md
git commit -m "feat(assistant): reject over-limit turns with 429 before any model call"
```

---

### Task 5: Login brute-force lockout

**Files:**
- Modify: `src/backend/core/models.py` (append `LoginAttempt`)
- Create: `src/backend/core/migrations/0002_login_attempt.py` (generated)
- Create: `src/backend/core/security.py`
- Create: `src/backend/core/auth_backends.py`
- Create: `src/backend/core/signals.py`
- Modify: `src/backend/core/apps.py`
- Modify: `src/backend/config/settings.py` (`AUTHENTICATION_BACKENDS`, two limits)
- Modify: `.env.example`
- Create: `src/backend/core/tests/test_login_lockout.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `core.models.LoginAttempt` — fields `username: str`, `ip: str | None`, `created_at: datetime`
  - `core.security.client_ip(request) -> str | None`
  - `core.security.is_locked(username: str | None, ip: str | None, *, now: datetime | None = None) -> bool`
  - `core.auth_backends.LockoutModelBackend`

**Why a backend and not a view or middleware:** the epic requires the throttle to keep working after E05 replaces `/admin/login/`. A backend hooks `authenticate()`, which every login view must call, so it follows the credential check wherever it moves. A middleware or a decorator would be keyed to a URL that is about to change.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_login_lockout.py`:

```python
"""Repeated failed logins must lock the account out for a window.

Enforced in an authentication backend rather than a view, because E05 replaces
``/admin/login/`` with a real login page and the protection has to follow the
credential check, not the URL.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import authenticate
from django.test import Client, RequestFactory
from django.utils import timezone
from model_bakery import baker

from core.models import LoginAttempt
from core.security import client_ip, is_locked


@pytest.fixture
def account(db):
    user = baker.make("core.CustomUser", username="alvo")
    user.set_password("senha-correta-longa-o-suficiente")
    user.save()
    return user


def _fail(username, ip="203.0.113.9", count=1, age=timedelta(0)):
    stamp = timezone.now() - age
    for _ in range(count):
        attempt = LoginAttempt.objects.create(username=username, ip=ip)
        LoginAttempt.objects.filter(pk=attempt.pk).update(created_at=stamp)


@pytest.mark.django_db
class TestIsLocked:
    def test_clean_account_is_not_locked(self):
        assert is_locked("alvo", "203.0.113.9") is False

    def test_under_the_limit_is_not_locked(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", count=4)
        assert is_locked("alvo", "198.51.100.4") is False

    def test_at_the_limit_locks_by_username(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", count=5)
        # locked even from a fresh IP — the username arm is the real protection
        assert is_locked("alvo", "198.51.100.4") is True

    def test_at_the_limit_locks_by_ip(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", ip="203.0.113.9", count=5)
        assert is_locked("outro-usuario", "203.0.113.9") is True

    def test_failures_outside_the_window_are_forgotten(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        settings.LOGIN_FAILURE_WINDOW_MINUTES = 15
        _fail("alvo", count=9, age=timedelta(minutes=20))
        assert is_locked("alvo", "203.0.113.9") is False

    def test_no_identifiers_is_never_locked(self):
        assert is_locked(None, None) is False


class TestClientIp:
    def test_prefers_the_first_forwarded_address(self):
        request = RequestFactory().post(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", REMOTE_ADDR="10.0.0.1"
        )
        assert client_ip(request) == "203.0.113.9"

    def test_falls_back_to_remote_addr(self):
        request = RequestFactory().post("/", REMOTE_ADDR="198.51.100.4")
        assert client_ip(request) == "198.51.100.4"

    def test_garbage_forwarded_header_falls_back_rather_than_crashing(self):
        """X-Forwarded-For is client-controlled — it can be anything at all."""
        request = RequestFactory().post(
            "/", HTTP_X_FORWARDED_FOR="'; DROP TABLE --", REMOTE_ADDR="198.51.100.4"
        )
        assert client_ip(request) == "198.51.100.4"

    def test_no_usable_address_returns_none(self):
        request = RequestFactory().post("/", REMOTE_ADDR="not-an-ip")
        assert client_ip(request) is None


@pytest.mark.django_db
class TestBackendEnforcement:
    def test_correct_password_works_when_not_locked(self, account):
        assert authenticate(username="alvo", password="senha-correta-longa-o-suficiente")

    def test_correct_password_is_refused_while_locked(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail("alvo", count=3)
        assert authenticate(username="alvo", password="senha-correta-longa-o-suficiente") is None

    def test_failed_authenticate_records_an_attempt(self, account):
        authenticate(username="alvo", password="errada")
        assert LoginAttempt.objects.filter(username="alvo").count() == 1

    def test_a_locked_out_attempt_does_not_extend_its_own_lockout(self, account, settings):
        """Otherwise the window slides forever and the lockout never expires."""
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail("alvo", count=3)
        authenticate(username="alvo", password="errada")
        authenticate(username="alvo", password="errada")
        assert LoginAttempt.objects.filter(username="alvo").count() == 3

    def test_successful_login_clears_the_failures(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 10
        _fail("alvo", count=4)
        client = Client()
        assert client.login(username="alvo", password="senha-correta-longa-o-suficiente")
        assert LoginAttempt.objects.filter(username="alvo").count() == 0


@pytest.mark.django_db
class TestAdminLoginIsProtected:
    """The lockout must be live on whatever login view is wired today."""

    def test_repeated_admin_login_failures_lock_the_account(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(3):
            client.post(
                "/admin/login/",
                {"username": "alvo", "password": "errada", "next": "/admin/"},
            )
        response = client.post(
            "/admin/login/",
            {
                "username": "alvo",
                "password": "senha-correta-longa-o-suficiente",
                "next": "/admin/",
            },
        )
        # Still on the login form rather than redirected in — the correct
        # password was never checked.
        assert response.status_code == 200
        assert LoginAttempt.objects.filter(username="alvo").count() == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_login_lockout.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'core.security'`.

- [ ] **Step 3: Add the model**

Append to `src/backend/core/models.py`:

```python
class LoginAttempt(models.Model):
    """A failed authentication, kept only long enough to enforce a lockout.

    Not a security audit log — E17 owns that. Rows here exist to be counted
    inside a short rolling window and are deleted on a successful login.
    """

    username = models.CharField(max_length=254)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tentativa de login"
        verbose_name_plural = "tentativas de login"
        indexes = [
            models.Index(fields=["username", "-created_at"], name="login_username_recent_idx"),
            models.Index(fields=["ip", "-created_at"], name="login_ip_recent_idx"),
        ]

    def __str__(self):
        return f"{self.username}@{self.ip} {self.created_at:%Y-%m-%d %H:%M}"
```

and add `from django.db import models` to the imports (the file currently imports only `AbstractUser`):

```python
from django.contrib.auth.models import AbstractUser
from django.db import models
```

- [ ] **Step 4: Write `core/security.py`**

```python
"""Login lockout primitives. No HTTP responses, no Django views — just counting.

``X-Forwarded-For`` is set by the client and only appended to by Google's load
balancer, so the leftmost entry is spoofable and an attacker can rotate it
freely. The IP arm of the lockout is therefore a speed bump; the username arm is
what actually protects an account. Keep both — they fail differently.
"""

import ipaddress
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.models import LoginAttempt


def client_ip(request) -> str | None:
    """The best available client address, normalised, or ``None``.

    Returns ``None`` rather than a garbage string when nothing parses, because
    ``LoginAttempt.ip`` is a real ``inet`` column and a malformed value would
    raise at insert time.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidates = [forwarded.split(",")[0].strip(), request.META.get("REMOTE_ADDR")]
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except (TypeError, ValueError):
            continue
    return None


def is_locked(
    username: str | None, ip: str | None, *, now: datetime | None = None
) -> bool:
    """True when this username OR this IP has burned the failure budget."""
    if not username and not ip:
        return False
    now = now or timezone.now()
    since = now - timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    limit = settings.LOGIN_FAILURE_LIMIT
    recent = LoginAttempt.objects.filter(created_at__gte=since)
    if username and recent.filter(username=username).count() >= limit:
        return True
    return bool(ip and recent.filter(ip=ip).count() >= limit)
```

- [ ] **Step 5: Write `core/auth_backends.py`**

```python
"""Authentication backend that refuses locked-out credentials."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from core.security import client_ip, is_locked


class LockoutModelBackend(ModelBackend):
    """``ModelBackend`` that will not check the password of a locked account.

    Enforcing here rather than in a view means the lockout follows
    ``authenticate()`` wherever it is called from: the Django admin login today,
    the real login view E05 adds tomorrow. Returning ``None`` (rather than
    raising) keeps the caller on the ordinary "invalid credentials" path, so a
    locked-out attacker learns nothing about whether the password was right.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if is_locked(username, client_ip(request)):
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
```

- [ ] **Step 6: Write `core/signals.py`**

```python
"""Record failed logins; forget them on success."""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from core.models import LoginAttempt
from core.security import client_ip, is_locked


@receiver(user_login_failed)
def record_login_failure(sender, credentials, request=None, **kwargs):
    username = credentials.get("username") or ""
    ip = client_ip(request)
    # A locked-out attempt must not extend its own lockout. The backend already
    # refuses these without checking the password, so counting them would slide
    # the window forever and the lockout would never expire.
    if is_locked(username, ip):
        return
    LoginAttempt.objects.create(username=username, ip=ip)


@receiver(user_logged_in)
def clear_login_failures(sender, user, request=None, **kwargs):
    LoginAttempt.objects.filter(username=user.get_username()).delete()
```

- [ ] **Step 7: Connect the signals**

Replace `src/backend/core/apps.py` with:

```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Imported for the side effect of registering the login-failure receivers.
        from core import signals  # noqa: F401
```

- [ ] **Step 8: Add the settings**

In `src/backend/config/settings.py`, immediately after the `LOGIN_URL` line (line 168), add:

```python
# Brute-force protection lives in the authentication backend, not a view, so it
# keeps working when E05 replaces /admin/login/ with a real login page.
AUTHENTICATION_BACKENDS = ["core.auth_backends.LockoutModelBackend"]
LOGIN_FAILURE_LIMIT = int(os.environ.get("LOGIN_FAILURE_LIMIT", "10"))
LOGIN_FAILURE_WINDOW_MINUTES = int(os.environ.get("LOGIN_FAILURE_WINDOW_MINUTES", "15"))
```

In `.env.example`, under `# --- Core ---`, add:

```
# Login lockout (E01): N failures for the same username or IP inside the window
# stop further attempts, including ones with the correct password.
LOGIN_FAILURE_LIMIT=10
LOGIN_FAILURE_WINDOW_MINUTES=15
```

- [ ] **Step 9: Generate the migration**

```bash
uv run python src/backend/manage.py makemigrations core --name login_attempt
```

Expected: `Migrations for 'core': core/migrations/0002_login_attempt.py - Create model LoginAttempt`.

- [ ] **Step 10: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_login_lockout.py -v
```

Expected: all PASS.

- [ ] **Step 11: Run the core app and the finances app**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/ src/backend/finances/ -q
```

Expected: no new failures. Swapping `AUTHENTICATION_BACKENDS` touches every `client.login()` and `force_login()` in the suite — `force_login` bypasses backends but records `settings.AUTHENTICATION_BACKENDS[0]` on the session, so a wrong dotted path here shows up as widespread failures. If that happens, the path string is the bug, not the tests.

- [ ] **Step 12: Prove the migration reverses**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core 0001
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate core
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: clean unapply/reapply, then `No changes detected`.

- [ ] **Step 13: Commit**

```bash
git add src/backend/core/models.py src/backend/core/security.py \
        src/backend/core/auth_backends.py src/backend/core/signals.py \
        src/backend/core/apps.py src/backend/core/migrations/0002_login_attempt.py \
        src/backend/core/tests/test_login_lockout.py \
        src/backend/config/settings.py .env.example
git commit -m "feat(core): lock out brute-forced logins at the authentication backend"
```

---

### Task 6: Request body ceiling

**Files:**
- Create: `src/backend/core/middleware.py`
- Modify: `src/backend/config/settings.py` (`MIDDLEWARE`, three settings)
- Modify: `.env.example`
- Create: `src/backend/core/tests/test_request_body_limit.py`
- Modify: `docs/runbook.md` (append to `## Spend ceilings`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `core.middleware.max_request_body_middleware` — a `sync_and_async_middleware` factory. Registered in `MIDDLEWARE` directly after `SecurityMiddleware`.

**Why `Content-Length` and not a Django setting:** `DATA_UPLOAD_MAX_MEMORY_SIZE` deliberately does not count file fields, so it caps neither a 5×10MB chat upload nor a large CSV. Cloud Run's filesystem is RAM-backed against the container's 1Gi, so `tempfile.NamedTemporaryFile` in `finances/views/importer.py:34-37` spends memory even though the code says "disk". Rejecting from the declared `Content-Length` stops the payload before Django's parser touches it.

**Why a dual sync/async middleware:** the stack is ASGI, and `chat_view` returns a `StreamingHttpResponse` driven by an async generator. A sync-only middleware forces Django to adapt the whole downstream chain, which is exactly the kind of change that breaks streaming subtly. The `sync_and_async_middleware` factory keeps the async path async.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_request_body_limit.py`:

```python
"""Oversized request bodies are rejected before Django parses them.

Checked from Content-Length, not from the parsed body, because Cloud Run backs
the container's filesystem with its 1Gi of RAM — an upload "written to disk" is
an upload held in memory.
"""

import pytest
from django.test import Client


@pytest.mark.django_db
class TestGlobalBodyCeiling:
    def test_oversized_body_is_rejected_with_413(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert response.status_code == 413

    def test_body_under_the_ceiling_reaches_the_view(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 4096
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b'{"message": ""}',
            content_type="application/json",
        )
        # 400 from the view's own validation — it got there, which is the point.
        assert response.status_code == 400

    def test_rejection_message_is_pt_br(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert "grande demais" in response.content.decode()

    def test_get_requests_are_unaffected(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1
        assert logged_client.get("/").status_code == 200

    def test_unauthenticated_oversized_request_is_rejected_too(self, db, settings):
        """The ceiling runs before authentication — that is the whole point."""
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = Client().post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert response.status_code == 413


@pytest.mark.django_db
class TestImporterCeiling:
    def test_importer_has_a_tighter_ceiling_than_chat(self, settings):
        assert settings.MAX_CSV_UPLOAD_BYTES < settings.MAX_REQUEST_BODY_BYTES

    def test_oversized_csv_is_rejected(self, logged_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.MAX_CSV_UPLOAD_BYTES = 1024
        settings.MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
        big = SimpleUploadedFile("big.csv", b"a,b,c\n" * 2000, content_type="text/csv")
        response = logged_client.post(
            "/import/", {"file": big, "import_type": "regular"}
        )
        assert response.status_code == 413

    def test_small_csv_still_uploads(self, logged_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.MAX_CSV_UPLOAD_BYTES = 1024 * 1024
        small = SimpleUploadedFile(
            "small.csv",
            b"date,description,amount,category,payment_method\n",
            content_type="text/csv",
        )
        response = logged_client.post(
            "/import/", {"file": small, "import_type": "regular"}
        )
        assert response.status_code == 200


class TestUploadDefaults:
    def test_number_of_files_per_request_is_capped(self, settings):
        assert settings.DATA_UPLOAD_MAX_NUMBER_FILES <= 10
```

`logged_client` comes from `src/backend/finances/tests/conftest.py`, which does not apply to `core/tests/`. Add a local fixture at the top of the new file:

```python
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client
```

Place these immediately after the imports, before the first test class.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_request_body_limit.py -v
```

Expected: the 413 tests FAIL (`assert 200 == 413` or `assert 400 == 413`), and `test_number_of_files_per_request_is_capped` FAILs with `assert 100 <= 10`.

- [ ] **Step 3: Write the middleware**

Create `src/backend/core/middleware.py`:

```python
"""Reject oversized request bodies before Django parses them.

``DATA_UPLOAD_MAX_MEMORY_SIZE`` deliberately excludes file fields, so it caps
neither a five-image chat upload nor a large CSV. Cloud Run backs the container
filesystem with its 1Gi of RAM, which means the importer's
``tempfile.NamedTemporaryFile`` spends memory even though the code reads as
"write to disk". Checking the declared ``Content-Length`` stops the payload at
the door.
"""

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import sync_and_async_middleware

IMPORT_PATH_PREFIX = "/import/"


def _too_large(request) -> HttpResponse | None:
    """A 413 when the declared body exceeds this path's ceiling, else ``None``.

    A missing or unparseable ``Content-Length`` is not treated as an attack: the
    ceiling is a cheap first line, and Django's own parser limits still apply
    behind it.
    """
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return None
    limit = (
        settings.MAX_CSV_UPLOAD_BYTES
        if request.path.startswith(IMPORT_PATH_PREFIX)
        else settings.MAX_REQUEST_BODY_BYTES
    )
    if length <= limit:
        return None
    return HttpResponse(
        f"Requisição grande demais (máximo {limit // (1024 * 1024)} MB).",
        status=413,
    )


@sync_and_async_middleware
def max_request_body_middleware(get_response):
    """Dual-mode so the ASGI path stays async — chat streams through here."""
    if iscoroutinefunction(get_response):

        async def middleware(request):
            blocked = _too_large(request)
            return blocked if blocked is not None else await get_response(request)

    else:

        def middleware(request):
            blocked = _too_large(request)
            return blocked if blocked is not None else get_response(request)

    return middleware
```

- [ ] **Step 4: Register it and add the settings**

In `src/backend/config/settings.py`, insert into `MIDDLEWARE` directly after `SecurityMiddleware`:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Before anything reads the body: an oversized upload must not reach the
    # parser, the session store, or Cloud Run's RAM-backed filesystem.
    "core.middleware.max_request_body_middleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

After the `ASSISTANT_ALLOWED_AUDIO_TYPES` block, add:

```python
# Request body ceilings (E01). The container is 1 vCPU / 1Gi with a RAM-backed
# filesystem, so "written to a temp file" still costs memory.
# 60MB covers the widest legitimate chat payload — ASSISTANT_MAX_IMAGES (5) at
# ASSISTANT_MAX_IMAGE_MB (10) each, plus multipart overhead. Raise both together
# or this becomes the thing that rejects a valid upload.
MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(60 * 1024 * 1024)))
# The CSV importer never legitimately needs more than a few MB.
MAX_CSV_UPLOAD_BYTES = int(os.environ.get("MAX_CSV_UPLOAD_BYTES", str(10 * 1024 * 1024)))
# Django's default is 100 files per request; nothing here wants more than the
# assistant's five images plus slack.
DATA_UPLOAD_MAX_NUMBER_FILES = 10
```

In `.env.example`, under `# --- Assistant throttling (E01) ---`, add:

```
# Request body ceilings (E01), in bytes. Keep MAX_REQUEST_BODY_BYTES above
# ASSISTANT_MAX_IMAGES * ASSISTANT_MAX_IMAGE_MB or valid uploads get 413s.
MAX_REQUEST_BODY_BYTES=62914560
MAX_CSV_UPLOAD_BYTES=10485760
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_request_body_limit.py -v
```

Expected: all PASS.

- [ ] **Step 6: Prove the async streaming path still streams**

Adding middleware to an ASGI stack is exactly where streaming breaks. Run the chat tests specifically:

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/assistant/tests/test_views.py \
  src/backend/assistant/tests/test_chat_csrf.py -v
```

Expected: all PASS, including the tests that consume `response.streaming_content` through `consume_streaming`. If any of them hang or raise `SynchronousOnlyOperation`, the middleware is being treated as sync-only — check that `@sync_and_async_middleware` is applied to the factory and that `iscoroutinefunction` is imported from `asgiref.sync`.

- [ ] **Step 7: Extend the runbook**

Append to `## Spend ceilings` in `docs/runbook.md`:

````markdown
### Upload ceilings

| Var | Default | Applies to |
|---|---|---|
| `MAX_REQUEST_BODY_BYTES` | 62914560 (60 MB) | every path |
| `MAX_CSV_UPLOAD_BYTES` | 10485760 (10 MB) | `/import/*` |

Rejected with HTTP 413 from `Content-Length`, before Django parses the body.

**Common failure:** a user reports "arquivo grande demais" on a legitimate
multi-photo receipt. `MAX_REQUEST_BODY_BYTES` must stay above
`ASSISTANT_MAX_IMAGES × ASSISTANT_MAX_IMAGE_MB` with room for multipart
overhead. Raising the image limits without raising this one is the usual cause.
````

- [ ] **Step 8: Commit**

```bash
git add src/backend/core/middleware.py src/backend/config/settings.py \
        src/backend/core/tests/test_request_body_limit.py \
        .env.example docs/runbook.md
git commit -m "feat(core): reject oversized request bodies before parsing"
```

---

### Task 7: Full Definition of Done — gates, deploy, and the TWA

The epic's DoD is not "the tasks are done"; it is a set of commands and observable assertions. This task runs them and produces the evidence.

**Files:**
- Modify: `docs/runbook.md` only if a step reveals a missing procedure.

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: the evidence block pasted into the review.

- [ ] **Step 1: Full suite with the coverage gate**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && \
  uv run coverage report --fail-under=80
```

Expected: `0 failed`, and a `TOTAL` line at or above 80%. Paste the last three lines.

- [ ] **Step 2: Lint and format gates**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: `All checks passed!` and `N files already formatted`.

- [ ] **Step 3: Migration and deploy checks**

```bash
uv run python src/backend/manage.py makemigrations --check --dry-run

DEBUG=False \
SECRET_KEY=$(uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
ALLOWED_HOSTS=example.com \
  uv run python src/backend/manage.py check --deploy
```

Expected: `No changes detected`, then `System check identified no issues (0 silenced).`

- [ ] **Step 4: The epic's grep assertions**

```bash
grep -rn 'csrf_exempt' src/backend/assistant/ ; echo "exit=$?"
grep -rniE 'throttle|ratelimit' src/backend --include='*.py' | grep -v tests
```

Expected: the first prints nothing and `exit=1`; the second lists `assistant/throttling.py`, `assistant/views.py`, and `config/settings.py`.

- [ ] **Step 5: Rebuild the frontend artifacts if any frontend file changed**

No task in this plan touches `src/backend/frontend/src/`, so this should be a no-op — but confirm, because the committed artifacts drift silently:

```bash
git diff --stat main -- src/backend/frontend/
```

Expected: empty. If not, rebuild and commit both artifacts (Tailwind needs `--force`; see `docs/runbook.md`).

- [ ] **Step 6: Deploy**

```bash
gcloud run deploy expense-tracker --source . \
  --project expense-tracker-482807 \
  --region southamerica-east1 \
  --quiet
```

A bare deploy preserves existing env vars and secrets. Expected: `... has been deployed and is serving 100 percent of traffic.`

- [ ] **Step 7: Smoke test the deployed revision**

```bash
B=https://expense-tracker-654941182076.southamerica-east1.run.app
for p in /healthz/ / /.well-known/assetlinks.json; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" -m 60 "$B$p"
done
```

Expected: `200`, `302`, `200`.

- [ ] **Step 8: Verify the TWA still authenticates and chats**

Manual, on the Android device with `com.bessavagner.ledger` installed:

1. Open the app. It must open **without a Chrome address bar** — an address bar means assetlinks broke, not CSRF.
2. Log in.
3. Send a text message to the assistant and confirm a streamed reply.
4. Send a receipt photo and confirm the extraction proposal appears.

Steps 3 and 4 are the CSRF check in the real client: the widget reads the `csrftoken` cookie and sends `X-CSRFToken`, and a `SameSite` or cookie regression shows up here as a 403 that no test would have caught.

If a 403 appears, do not re-add `@csrf_exempt`. Read the response and check whether the `csrftoken` cookie is present in the TWA's cookie jar — a missing cookie is a `SameSite`/`Secure` problem, a present-but-rejected token is a `CSRF_TRUSTED_ORIGINS` problem.

- [ ] **Step 9: Verify the infrastructure ceilings on the live service**

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"
```

Expected: `3`. Confirm the budget alert email from Task 1 Step 6 is in hand, and that the OpenAI org limit reads USD 30 in the console.

- [ ] **Step 10: Update the epic's status**

In `docs/backlog/E01-spend-and-abuse-containment.md`, change the frontmatter `status: ready` to `status: review`, and update the E01 row in the §4 table of `docs/backlog/INDEX.md` to match.

```bash
git add docs/backlog/E01-spend-and-abuse-containment.md docs/backlog/INDEX.md
git commit -m "chore(backlog): E01 to review — DoD commands passing"
```

- [ ] **Step 11: Hand off for review**

Run `superpowers:requesting-code-review`, then `/security-review` — this epic *is* a security change and an independent pass is mandatory, not optional. Then `superpowers:verification-before-completion` with the pasted output from Steps 1-4 and 7-9, then `superpowers:finishing-a-development-branch`.
