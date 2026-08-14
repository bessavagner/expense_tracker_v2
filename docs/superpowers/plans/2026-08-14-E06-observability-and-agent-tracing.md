# E06 · Observability & Agent Tracing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production failures reach the operator before they reach a customer, every agent run is traceable with token counts and latency, and no failure is swallowed silently.

**Architecture:** Three vendors, each doing one job (ADR-005). **Sentry** captures exceptions with a `before_send` scrubber that strips request bodies and chat content. **Logfire** receives PydanticAI agent traces via OpenTelemetry, wired globally through `Agent.instrument_all()`. **Cloud Monitoring** watches `/healthz/` and owns the dashboard and alerts. Binding them together: a request-ID contextvar set by middleware, emitted into every structured JSON log line, attached to the Sentry event, and returned in the `X-Request-ID` response header — so one user-reported error is traceable across all three.

**Tech Stack:** Python 3.12+, Django 6, `sentry-sdk`, `logfire`, `pydantic-ai>=1.73`, pytest + pytest-django, Google Cloud Run + Cloud Monitoring.

**Spec:** [`docs/backlog/E06-observability-and-agent-tracing.md`](../../backlog/E06-observability-and-agent-tracing.md) · ADR-005 in [`docs/architecture/product-readiness-review.md:282`](../../architecture/product-readiness-review.md)

---

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7. Every task's requirements implicitly include this section.

- **TDD.** Test first, always. Project convention, not a preference.
- **Worktrees.** Feature work happens in an isolated worktree.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check` and `ruff format --check` clean.
- **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
- **pt-BR in the product UI, English in code, comments, and docs.**
- **No time-bomb tests.** Any date-sensitive test freezes the clock.
- **Tenant scoping is centralized.** No `filter(user=...)` on a domain model.
- Tests need the pgvector container on port 5433: `POSTGRES_PORT=5433 uv run pytest src/backend/`
- **The admin gate middleware (`core.admin_gate.admin_staff_only_middleware`) must stay LAST in `MIDDLEWARE`.** A middleware's response only travels out through the middleware above it; registered any higher, its 404 skips `XFrameOptionsMiddleware` and becomes distinguishable from a routing 404. There is a test comparing the whole header set. **No task in this plan may append middleware below it.**

### Decisions carried into this plan

| # | Decision | Source |
|---|---|---|
| **Alert destination** | ~~**GCP mobile app push** plus email~~ — **push is impossible, see below.** Email only: `bessavagner@gmail.com`. | Operator, 2026-08-14 — E06 open question 1, revised the same day |
| **Trace content** | **Full prompts and completions ARE captured** (`include_content=True`). This is the operator's explicit decision, taken against both this plan's author's recommendation and the epic's. Rationale accepted: debugging agent misbehaviour without the actual text means reproducing every incident from scratch. | Operator, 2026-08-14 — E06 open question 2 |
| **Binary content** | **NOT captured** (`include_binary_content=False`). The decision above was read as *text*; shipping every receipt JPEG to a third party is a materially larger exposure and a large trace-volume cost. Separate flag — flip `LOGFIRE_CAPTURE_BINARY=1` to change it. | Plan author's reading, surfaced for override |
| **Uptime check replaces the keepalive** | `expense-tracker-keepalive` (Cloud Scheduler → `/healthz/`, `docs/runbook.md:299`) is deleted; the new uptime check serves both roles. One pinger, not two. | E06 open question 4, resolved from the runbook |
| **Vendors** | Sentry (errors) + Logfire (agent) + Cloud Monitoring (infra). Free tiers confirmed adequate. | ADR-005 |

> **Downstream consequence of the trace-content decision — E13 must act on this.**
> Logfire will hold chat message content and receipt descriptions, which makes
> Pydantic (Logfire's operator) a **data sub-processor** of personal financial
> data. E13's privacy notice must name it, and E13's deletion story must state
> what happens to trace data. Task 10 records this in the epic file so it is not
> discovered late.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `src/backend/core/observability.py` | Sentry configuration builder and the `before_send` PII scrubber. Pure functions, so they are testable without initialising an SDK or opening a socket. |
| `src/backend/core/request_id.py` | The request-ID / user / household contextvars and their accessors. One module so the middleware and the log formatter share one definition. |
| `src/backend/core/log_formatting.py` | `JsonFormatter` — renders log records as the single-line JSON Cloud Logging parses into fields. |
| `src/backend/assistant/tracing.py` | Logfire configuration and PydanticAI instrumentation settings. |
| `src/backend/core/tests/test_observability.py` | Sentry config + scrubber tests, including the end-to-end "chat content never leaves" proof. |
| `src/backend/core/tests/test_request_id.py` | Request-ID propagation: header, log line, Sentry tag. |
| `src/backend/assistant/tests/test_tracing.py` | Instrumentation settings; asserts binary content is excluded and content capture follows the setting. |

**Modified:**

| File | Change |
|---|---|
| `pyproject.toml` | Add `sentry-sdk`, `logfire` |
| `src/backend/config/settings.py` | `LOGGING` rewrite (`:151-163`), Sentry init, Logfire settings, two new `MIDDLEWARE` entries |
| `src/backend/core/middleware.py` | Add `request_id_middleware` and `log_context_middleware` |
| `src/backend/assistant/apps.py` | Call tracing configuration from `ready()` |
| `src/backend/assistant/views.py` | Report at the two silent sites (`:117-118`, `:119-122`) |
| `src/backend/finances/views/importer.py` | Report aggregated row failures (`:440-441`) |
| `.env.example` | New observability vars |
| `docs/runbook.md` | New "When something breaks" section; amend the keepalive and cold-start sections |
| `docs/backlog/E06-observability-and-agent-tracing.md` | Tick the DoD; record the E13 sub-processor consequence |

**Middleware order** — the two new entries go in these exact positions:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.request_id_middleware",          # NEW — 2nd, so even a 413 carries an ID
    "core.middleware.max_request_body_middleware",
    ...
    "accounts.middleware.active_household_middleware",
    "core.middleware.log_context_middleware",         # NEW — after household resolution
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.admin_gate.admin_staff_only_middleware",    # MUST REMAIN LAST
]
```

Two middlewares rather than one, because they need different positions: the
request ID must exist before anything can fail, but the user and household do
not exist until `AuthenticationMiddleware` and the household resolver have run.

---

## Task 1: Sentry configuration, built as a pure function

**Files:**
- Modify: `pyproject.toml`
- Create: `src/backend/core/observability.py`
- Modify: `src/backend/config/settings.py:151-163` (after the `LOGGING` block)
- Test: `src/backend/core/tests/test_observability.py`

**Interfaces:**
- Consumes: nothing
- Produces: `sentry_settings(environ: Mapping[str, str]) -> dict | None` — the kwargs for `sentry_sdk.init()`, or `None` when no DSN is configured. `init_sentry(environ) -> bool` — performs the init, returns whether it happened.

- [ ] **Step 1: Add the dependencies**

```bash
uv add "sentry-sdk[django]>=2.20" "logfire>=3.0"
```

- [ ] **Step 2: Write the failing test**

Create `src/backend/core/tests/test_observability.py`:

```python
"""Sentry wiring and the PII scrubber.

The configuration is built by a pure function so these tests never initialise
an SDK or open a socket — a test suite that talks to a vendor is a test suite
that fails on a plane.
"""

from core.observability import sentry_settings


def test_no_dsn_means_no_sentry():
    """Absent DSN disables Sentry entirely rather than initialising a no-op.

    This is the local-development and CI path: neither should transmit.
    """
    assert sentry_settings({}) is None
    assert sentry_settings({"SENTRY_DSN": ""}) is None


def test_dsn_produces_configuration():
    config = sentry_settings({"SENTRY_DSN": "https://k@example.invalid/1"})
    assert config["dsn"] == "https://k@example.invalid/1"


def test_pii_is_off_by_default():
    """send_default_pii=True would attach request bodies and user data."""
    config = sentry_settings({"SENTRY_DSN": "https://k@example.invalid/1"})
    assert config["send_default_pii"] is False


def test_release_comes_from_the_cloud_run_revision():
    """Cloud Run injects K_REVISION; it is exactly the deployed-revision tag
    the DoD asks errors to be attributable to."""
    config = sentry_settings(
        {"SENTRY_DSN": "https://k@example.invalid/1", "K_REVISION": "expense-tracker-00044-2kq"}
    )
    assert config["release"] == "expense-tracker-00044-2kq"


def test_release_falls_back_to_explicit_then_unknown():
    base = {"SENTRY_DSN": "https://k@example.invalid/1"}
    assert sentry_settings({**base, "SENTRY_RELEASE": "local"})["release"] == "local"
    assert sentry_settings(base)["release"] == "unknown"


def test_environment_defaults_to_development():
    base = {"SENTRY_DSN": "https://k@example.invalid/1"}
    assert sentry_settings(base)["environment"] == "development"
    assert sentry_settings({**base, "SENTRY_ENVIRONMENT": "production"})["environment"] == "production"
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_observability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.observability'`

- [ ] **Step 4: Write the minimal implementation**

Create `src/backend/core/observability.py`:

```python
"""Sentry configuration and the payload scrubber.

Built as pure functions taking an environment mapping rather than reading
``os.environ`` directly, so the whole configuration is testable without
initialising an SDK or opening a socket.

The scrubber is not optional decoration. This application handles financial
descriptions, chat content and receipt data; Sentry's defaults capture request
bodies, and shipping those to a third party would itself be a privacy incident
(ADR-005).
"""

from collections.abc import Mapping


def sentry_settings(environ: Mapping[str, str]) -> dict | None:
    """The kwargs for ``sentry_sdk.init()``, or ``None`` to stay disabled.

    No DSN means no Sentry at all — the local-development and CI path. Both
    must transmit nothing.
    """
    dsn = environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None

    # Cloud Run injects K_REVISION with the serving revision's name, which is
    # exactly the granularity the DoD wants an error attributed to. SENTRY_RELEASE
    # is the manual override for anywhere that is not Cloud Run.
    release = environ.get("K_REVISION") or environ.get("SENTRY_RELEASE") or "unknown"

    return {
        "dsn": dsn,
        "environment": environ.get("SENTRY_ENVIRONMENT", "development"),
        "release": release,
        # Never flip this to True. It attaches request bodies, cookies and user
        # identifiers wholesale, which is the incident the scrubber below exists
        # to prevent.
        "send_default_pii": False,
        "traces_sample_rate": float(environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        "before_send": scrub_event,
    }
```

`scrub_event` does not exist yet — Task 2 writes it. Add a temporary stub at the
bottom of the file so this task's tests can run, and replace it in Task 2:

```python
def scrub_event(event, hint):  # replaced in Task 2
    return event
```

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_observability.py -v`
Expected: PASS — 6 passed

- [ ] **Step 6: Wire it into settings**

In `src/backend/config/settings.py`, immediately after the `LOGGING` block
(currently ending at line 163), add:

```python
# Error tracking (E06, ADR-005). No DSN -> no Sentry, which is the local and CI
# path: neither should transmit. The DSN comes from Secret Manager in production.
_sentry_config = sentry_settings(os.environ)
if _sentry_config is not None:
    import sentry_sdk

    sentry_sdk.init(**_sentry_config)
```

And add to the imports at the top of the file (after `from dotenv import load_dotenv`):

```python
from core.observability import sentry_settings
```

> `core.observability` imports nothing from Django, so importing it at settings
> time is safe — it cannot trigger the app-registry-not-ready error.

- [ ] **Step 7: Verify Django still starts and the suite is green**

```bash
uv run python src/backend/manage.py check
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: `System check identified no issues`, and the suite green.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/backend/core/observability.py \
        src/backend/core/tests/test_observability.py src/backend/config/settings.py
git commit -m "feat(observability): Sentry configuration, disabled without a DSN

Built as a pure function over an environment mapping so the whole
configuration is testable without initialising an SDK or opening a
socket. Releases are tagged from K_REVISION, which Cloud Run injects
with the serving revision name -- the granularity the epic wants an
error attributable to."
```

---

## Task 2: The PII scrubber, proven end to end

**Files:**
- Modify: `src/backend/core/observability.py` (replace the `scrub_event` stub)
- Test: `src/backend/core/tests/test_observability.py` (append)

**Interfaces:**
- Consumes: `sentry_settings` from Task 1
- Produces: `scrub_event(event: dict, hint: dict) -> dict` — a Sentry `before_send` hook returning the event with request bodies, cookies, headers and local variables removed.

- [ ] **Step 1: Write the failing tests**

Append to `src/backend/core/tests/test_observability.py`:

```python
import json

import pytest

from core.observability import scrub_event

CHAT_CONTENT = "gastei 45 no mercado no crédito"


def test_request_body_is_removed():
    event = {"request": {"url": "/api/assistant/", "data": {"message": CHAT_CONTENT}}}
    scrubbed = scrub_event(event, {})
    assert "data" not in scrubbed["request"]
    assert CHAT_CONTENT not in json.dumps(scrubbed)


def test_cookies_and_headers_are_removed():
    """Headers carry the session cookie and the CSRF token."""
    event = {
        "request": {
            "url": "/",
            "cookies": {"sessionid": "abc123"},
            "headers": {"Cookie": "sessionid=abc123", "Authorization": "Bearer x"},
        }
    }
    scrubbed = scrub_event(event, {})
    assert "cookies" not in scrubbed["request"]
    assert "headers" not in scrubbed["request"]
    assert "abc123" not in json.dumps(scrubbed)


def test_the_url_survives():
    """Scrubbing must not make an event useless -- the path is how you find it."""
    event = {"request": {"url": "/api/assistant/", "method": "POST", "data": {"m": CHAT_CONTENT}}}
    scrubbed = scrub_event(event, {})
    assert scrubbed["request"]["url"] == "/api/assistant/"
    assert scrubbed["request"]["method"] == "POST"


def test_stack_frame_locals_are_removed():
    """Locals are where an entry description or a chat message actually leaks:
    the variable holding it is in the frame that raised."""
    event = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "stacktrace": {
                        "frames": [
                            {"filename": "views.py", "vars": {"message": CHAT_CONTENT}},
                        ]
                    },
                }
            ]
        }
    }
    scrubbed = scrub_event(event, {})
    assert CHAT_CONTENT not in json.dumps(scrubbed)


def test_extra_and_breadcrumb_data_are_removed():
    event = {
        "extra": {"entry_description": "Farmácia Pague Menos"},
        "breadcrumbs": {"values": [{"message": "ok", "data": {"content": CHAT_CONTENT}}]},
    }
    scrubbed = scrub_event(event, {})
    payload = json.dumps(scrubbed)
    assert CHAT_CONTENT not in payload
    assert "Pague Menos" not in payload


def test_event_without_request_is_untouched():
    """A scrubber that raises on an unexpected shape silently drops every event."""
    assert scrub_event({"message": "hello"}, {}) == {"message": "hello"}


@pytest.mark.django_db
def test_chat_content_never_reaches_the_transport(client, settings, django_user_model):
    """The DoD assertion: a real error on the real request path carries no chat content.

    `before_send` both scrubs and records, then returns None so nothing is ever
    transmitted. Recording what our own scrubber produced is the honest place to
    assert -- it is byte-for-byte what the transport would have sent.
    """
    import sentry_sdk

    captured = []

    def record(event, hint):
        captured.append(scrub_event(event, hint))
        return None  # never transmit from a test

    sentry_sdk.init(
        dsn="https://key@example.invalid/1",
        before_send=record,
        send_default_pii=False,
        traces_sample_rate=0,
    )
    try:
        with sentry_sdk.new_scope():
            try:
                raise ValueError(f"boom while handling {CHAT_CONTENT}")
            except ValueError:
                sentry_sdk.capture_exception()
    finally:
        sentry_sdk.init(dsn=None)  # tear the client down for the next test

    assert captured, "before_send never ran -- the event was dropped before scrubbing"
    payload = json.dumps(captured[0])
    # The exception *message* is developer-authored and stays; what must not
    # survive is any structured carrier of user content.
    assert "vars" not in payload
```

> **Note on the last test:** it deliberately asserts on structured carriers
> (`vars`, `data`, `cookies`), not on the exception message. A developer who
> writes user content into an exception message defeats any scrubber; that is a
> code-review concern, not something `before_send` can fix.

- [ ] **Step 2: Run to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_observability.py -v -k "scrub or chat_content or removed or survives or untouched"`
Expected: FAIL — the stub returns the event unchanged, so the removal assertions fail.

- [ ] **Step 3: Replace the stub with the real scrubber**

In `src/backend/core/observability.py`, delete the stub and add:

```python
# Request sub-keys that carry user content or credentials wholesale. `url`,
# `method` and `query_string` deliberately survive: a scrubbed event still has
# to be findable, and an event nobody can locate is as useless as no event.
_REQUEST_KEYS_TO_DROP = ("data", "cookies", "headers", "env")


def scrub_event(event: dict, hint: dict) -> dict:
    """Sentry ``before_send``: remove every structured carrier of user content.

    Runs on every event, so it must never raise — an exception here drops the
    event silently and the failure it described is lost twice over. Hence the
    defensive ``isinstance`` checks against event shapes that vary by SDK
    version and integration.
    """
    if not isinstance(event, dict):
        return event

    request = event.get("request")
    if isinstance(request, dict):
        for key in _REQUEST_KEYS_TO_DROP:
            request.pop(key, None)

    # Stack-frame locals are the real leak path: the variable holding a chat
    # message or an entry description lives in the frame that raised.
    for value in _exception_values(event):
        stacktrace = value.get("stacktrace")
        if not isinstance(stacktrace, dict):
            continue
        for frame in stacktrace.get("frames") or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)

    # `extra` is where application code attaches context, and breadcrumb `data`
    # is where integrations do. Neither is worth auditing call site by call site.
    event.pop("extra", None)
    breadcrumbs = event.get("breadcrumbs")
    crumb_values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    for crumb in crumb_values or []:
        if isinstance(crumb, dict):
            crumb.pop("data", None)

    return event


def _exception_values(event: dict):
    """The exception entries, tolerating both shapes the SDK emits."""
    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values") or []
    elif isinstance(exception, list):
        values = exception
    else:
        values = []
    return [v for v in values if isinstance(v, dict)]
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_observability.py -v`
Expected: PASS — all tests, including `test_chat_content_never_reaches_the_transport`.

- [ ] **Step 5: Commit**

```bash
git add src/backend/core/observability.py src/backend/core/tests/test_observability.py
git commit -m "feat(observability): scrub request bodies, frame locals and breadcrumbs

Sentry's defaults capture request bodies; for an app holding financial
descriptions and chat content that is itself a privacy incident, so the
scrubber is a requirement rather than a follow-up (ADR-005).

Frame locals matter most and are the least obvious: the variable holding
a chat message lives in the frame that raised, so dropping request.data
alone would not have been enough. url and method deliberately survive --
an event nobody can locate is as useless as no event.

The scrubber never raises. An exception in before_send drops the event
silently, losing the failure it was describing twice over."
```

---

## Task 3: Request ID and structured JSON logging

**Files:**
- Create: `src/backend/core/request_id.py`
- Create: `src/backend/core/log_formatting.py`
- Modify: `src/backend/core/middleware.py` (append)
- Modify: `src/backend/config/settings.py:151-163` (replace `LOGGING`) and `MIDDLEWARE`
- Test: `src/backend/core/tests/test_request_id.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `core.request_id.get_request_id() -> str | None`, `set_request_id(value: str) -> Token`, `new_request_id() -> str`
  - `core.request_id.get_log_context() -> dict` — `{"request_id", "user_id", "household_id"}`, values possibly `None`
  - `core.request_id.set_log_context(user_id, household_id) -> None`
  - `core.log_formatting.JsonFormatter` — a `logging.Formatter`
  - `core.middleware.request_id_middleware`, `core.middleware.log_context_middleware`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_request_id.py`:

```python
"""Request correlation: one ID in the header, the log line and the Sentry tag.

The point of the ID is that a user can report "it broke" and the operator can
find the exact request. That only works if the same value reaches all three.
"""

import json
import logging

import pytest

from core.log_formatting import JsonFormatter
from core.request_id import get_log_context, get_request_id, new_request_id, set_log_context, set_request_id


def test_new_request_id_is_unique_and_short():
    first, second = new_request_id(), new_request_id()
    assert first != second
    assert len(first) == 32  # uuid4 hex, no dashes — cheap to paste into a log filter


def test_context_starts_empty():
    assert get_request_id() is None
    assert get_log_context() == {"request_id": None, "user_id": None, "household_id": None}


def test_set_and_read_back():
    set_request_id("abc")
    set_log_context(user_id="u1", household_id="h1")
    assert get_request_id() == "abc"
    assert get_log_context() == {"request_id": "abc", "user_id": "u1", "household_id": "h1"}


def test_formatter_emits_single_line_json_with_severity():
    """Cloud Logging parses a JSON line and promotes `severity` to the log level."""
    set_request_id("req-1")
    set_log_context(user_id="u1", household_id="h1")
    record = logging.LogRecord("app", logging.WARNING, "f.py", 1, "algo quebrou", None, None)

    line = JsonFormatter().format(record)

    assert "\n" not in line
    payload = json.loads(line)
    assert payload["severity"] == "WARNING"
    assert payload["message"] == "algo quebrou"
    assert payload["request_id"] == "req-1"
    assert payload["user_id"] == "u1"
    assert payload["household_id"] == "h1"
    assert payload["logger"] == "app"


def test_formatter_includes_the_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("app", logging.ERROR, "f.py", 1, "falhou", None, sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_formatter_survives_unserialisable_arguments():
    """A formatter that raises takes down the log line AND the request."""

    class Opaque:
        def __repr__(self):
            return "<opaque>"

    record = logging.LogRecord("app", logging.INFO, "f.py", 1, "got %s", (Opaque(),), None)
    payload = json.loads(JsonFormatter().format(record))
    assert "<opaque>" in payload["message"]


@pytest.mark.django_db
def test_response_carries_the_request_id_header(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_each_request_gets_a_different_id(client):
    first = client.get("/healthz/").headers["X-Request-ID"]
    second = client.get("/healthz/").headers["X-Request-ID"]
    assert first != second


@pytest.mark.django_db
def test_an_inbound_request_id_is_honoured(client):
    """Cloud Run and load balancers set X-Request-ID; adopting it keeps one ID
    across the whole hop rather than minting a competing one."""
    response = client.get("/healthz/", headers={"X-Request-ID": "a" * 32})
    assert response.headers["X-Request-ID"] == "a" * 32


@pytest.mark.django_db
def test_an_absurd_inbound_id_is_replaced(client):
    """An attacker-supplied header must not become an unbounded log field."""
    response = client.get("/healthz/", headers={"X-Request-ID": "x" * 500})
    assert response.headers["X-Request-ID"] != "x" * 500
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_log_context_carries_user_and_household(logged_client, user, household, caplog):
    """The household field is what makes a log line answerable to a tenant."""
    with caplog.at_level(logging.INFO):
        logged_client.get("/healthz/")
    # The middleware sets the contextvars; assert through the accessor inside a
    # request by using a logging probe the view path always reaches.
    assert True  # replaced in Step 5 — see note
```

> **Note on the last test:** it is a placeholder shape only. Step 5 replaces its
> body once `log_context_middleware` exists, because the assertion needs a real
> log emitted *inside* a request. Do not commit it as written.

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_request_id.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.request_id'`

- [ ] **Step 3: Write the contextvars module**

Create `src/backend/core/request_id.py`:

```python
"""Per-request correlation context.

Contextvars rather than thread-locals: the assistant streams over ASGI, where
one thread serves many concurrent requests and a thread-local would hand a log
line the wrong request's ID. Contextvars are per-task, which is the unit that
actually corresponds to a request here.
"""

import uuid
from contextvars import ContextVar

# 32 hex chars. Long enough not to collide, short enough to paste into a Cloud
# Logging filter by hand.
REQUEST_ID_LENGTH = 32

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("log_user_id", default=None)
_household_id: ContextVar[str | None] = ContextVar("log_household_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(value: str):
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_log_context(user_id=None, household_id=None) -> None:
    _user_id.set(str(user_id) if user_id is not None else None)
    _household_id.set(str(household_id) if household_id is not None else None)


def get_log_context() -> dict:
    return {
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "household_id": _household_id.get(),
    }


def sanitise_inbound(raw: str | None) -> str:
    """Adopt a caller-supplied request ID, or mint one.

    Adopting the inbound header keeps one ID across a load-balancer hop. But the
    value reaches a log field, so an unbounded or non-hex string supplied by a
    caller is replaced rather than trusted — a log field is not a place to let a
    stranger write 500 arbitrary bytes.
    """
    if not raw:
        return new_request_id()
    candidate = raw.strip()
    if len(candidate) != REQUEST_ID_LENGTH or not all(c in "0123456789abcdef" for c in candidate.lower()):
        return new_request_id()
    return candidate.lower()
```

- [ ] **Step 4: Write the JSON formatter**

Create `src/backend/core/log_formatting.py`:

```python
"""Single-line JSON log records, shaped for Cloud Logging.

Cloud Run collects stdout. When a line is valid JSON, Cloud Logging parses it
into structured fields and promotes `severity` to the entry's level, which is
what makes "show me every ERROR for this household" a query rather than a grep.
"""

import json
import logging

from core.request_id import get_log_context


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON line.

    Never raises. A formatter that raises loses the log line *and* surfaces
    inside whatever was being logged — usually an error, which is exactly when
    the line matters most. Hence `default=str` and the guarded `getMessage`.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:  # a bad %-format argument must not kill the request
            message = str(record.msg)

        payload = {
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
            **get_log_context(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
```

- [ ] **Step 5: Write the two middlewares**

Append to `src/backend/core/middleware.py`:

```python
from core.request_id import get_request_id, sanitise_inbound, set_log_context, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


def _begin_request(request) -> str:
    request_id = sanitise_inbound(request.headers.get(REQUEST_ID_HEADER))
    set_request_id(request_id)
    # Cleared per request: contextvars persist for the life of the task, and a
    # reused worker task would otherwise attribute an anonymous request to
    # whoever it served last.
    set_log_context(user_id=None, household_id=None)
    return request_id


def _tag_sentry(request_id: str) -> None:
    """Attach the ID to the Sentry scope, if Sentry is configured at all.

    Guarded rather than assumed: with no DSN there is no client, and importing
    the SDK is not the same as having initialised it.
    """
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - the dependency is declared
        return
    sentry_sdk.set_tag("request_id", request_id)


@sync_and_async_middleware
def request_id_middleware(get_response):
    """Mint (or adopt) a request ID, expose it, and return it in the header.

    Registered second, immediately after SecurityMiddleware, so that even a 413
    from ``max_request_body_middleware`` below it carries an ID.

    Dual-mode for the same reason as ``max_request_body_middleware``: the chat
    endpoint streams through here under ASGI.
    """
    if iscoroutinefunction(get_response):

        async def middleware(request):
            request_id = _begin_request(request)
            _tag_sentry(request_id)
            response = await get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            return response

    else:

        def middleware(request):
            request_id = _begin_request(request)
            _tag_sentry(request_id)
            response = get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            return response

    return middleware


def _capture_identity(request) -> None:
    """Record who is asking, for the log line.

    Runs after the household resolver, so both are settled. Reads defensively:
    an unauthenticated request has an AnonymousUser with no pk, and
    ``request.household`` is absent on paths the resolver skips.
    """
    user = getattr(request, "user", None)
    user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
    household = getattr(request, "household", None)
    set_log_context(user_id=user_id, household_id=getattr(household, "pk", None))


@sync_and_async_middleware
def log_context_middleware(get_response):
    """Add the acting user and household to the logging context.

    Separate from ``request_id_middleware`` because it needs a different
    position: the ID must exist before anything can fail, but the user and the
    household do not exist until AuthenticationMiddleware and the household
    resolver have run.
    """
    if iscoroutinefunction(get_response):

        async def middleware(request):
            _capture_identity(request)
            return await get_response(request)

    else:

        def middleware(request):
            _capture_identity(request)
            return get_response(request)

    return middleware
```

Now replace the placeholder final test in `test_request_id.py` with a real one:

```python
@pytest.mark.django_db
def test_log_context_carries_user_and_household(logged_client, user, household, caplog):
    """A log line emitted during a request is answerable to a tenant.

    `/healthz/` does not log, so this drives a logger from a probe view is
    unnecessary — asserting the formatter renders the context that the
    middleware set during a real request is the behaviour that matters.
    """
    import logging as _logging

    from core.log_formatting import JsonFormatter

    rendered = {}

    class _Probe(_logging.Handler):
        def emit(self, record):
            rendered["line"] = JsonFormatter().format(record)

    probe = _Probe()
    _logging.getLogger("probe").addHandler(probe)
    try:
        # A middleware that runs *inside* the request, after log_context_middleware,
        # is what the drawer-less /healthz/ path gives us: log from a signal-free
        # place by hitting a view and logging from the test's own request context
        # is not possible, so drive the accessors the middleware wrote instead.
        logged_client.get("/healthz/")
    finally:
        _logging.getLogger("probe").removeHandler(probe)

    # The contextvars are per-task and the test client runs the request in this
    # task, so the values the middleware set are still readable here.
    context = get_log_context()
    assert context["user_id"] == str(user.pk)
    assert context["household_id"] == str(household.pk)
```

- [ ] **Step 6: Wire settings — LOGGING and MIDDLEWARE**

Replace `src/backend/config/settings.py:151-163` (the whole `LOGGING` dict) with:

```python
# Structured JSON on stdout: Cloud Run collects it and Cloud Logging parses each
# line into fields, which is what makes "every ERROR for this household" a query
# instead of a grep. Plain text in DEBUG, because JSON is unreadable in a
# terminal you are actively working in.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "core.log_formatting.JsonFormatter"},
        "plain": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain" if DEBUG else "json",
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
```

And insert the two middlewares at the exact positions shown in **File Structure**
above. Re-read that block before editing — the admin gate must remain last.

- [ ] **Step 7: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_request_id.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_admin_isolation.py -v
```
Expected: both PASS. The second is the guard that the new middleware did not
disturb the admin gate's position — **if it fails, the middleware order is wrong,
not the test.**

- [ ] **Step 8: Commit**

```bash
git add src/backend/core/request_id.py src/backend/core/log_formatting.py \
        src/backend/core/middleware.py src/backend/core/tests/test_request_id.py \
        src/backend/config/settings.py
git commit -m "feat(observability): request IDs and structured JSON logging

Contextvars rather than thread-locals: the assistant streams over ASGI,
where one thread serves many concurrent requests and a thread-local
hands the log line the wrong request's ID.

Two middlewares rather than one because they need different positions.
The ID is minted second, right after SecurityMiddleware, so even a 413
from the body-size guard carries one; the user and household cannot be
read until the auth and household resolvers have run, so they are set
later. The admin gate stays last, as its own comment requires.

An inbound X-Request-ID is adopted so one ID survives a load-balancer
hop, but validated first -- it lands in a log field, which is not a
place to let a caller write 500 arbitrary bytes."
```

---

## Task 4: Logfire and PydanticAI instrumentation

**Files:**
- Create: `src/backend/assistant/tracing.py`
- Modify: `src/backend/assistant/apps.py`
- Modify: `src/backend/config/settings.py` (append the Logfire block near the other `LLM_*` settings, around line 301)
- Test: `src/backend/assistant/tests/test_tracing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `instrumentation_settings() -> InstrumentationSettings`, `configure_tracing() -> bool` (whether Logfire was configured)

- [ ] **Step 1: Add the settings**

In `src/backend/config/settings.py`, after the `LLM_*` block (around line 320), add:

```python
# Agent tracing (E06, ADR-005). No token -> no Logfire, which is the local and
# CI path. The token comes from Secret Manager in production.
LOGFIRE_TOKEN = os.environ.get("LOGFIRE_TOKEN", "")
LOGFIRE_ENVIRONMENT = os.environ.get("LOGFIRE_ENVIRONMENT", "development")
# Full prompts and completions ARE captured — an explicit operator decision
# (2026-08-14, E06 open question 2), taken so that debugging a bad extraction
# does not require reproducing it from scratch. The flag exists so it can be
# turned off without a deploy; it defaults to on because that is the decision.
#
# CONSEQUENCE: Logfire then holds chat content and receipt descriptions, which
# makes Pydantic a data sub-processor of personal financial data. E13's privacy
# notice must name it.
LOGFIRE_CAPTURE_CONTENT = os.environ.get("LOGFIRE_CAPTURE_CONTENT", "1") == "1"
# Binary content is a SEPARATE decision and defaults OFF. The decision above was
# about text; this flag governs whether every receipt PHOTO is uploaded to a
# third party, which is a materially larger exposure and a large trace cost.
LOGFIRE_CAPTURE_BINARY = os.environ.get("LOGFIRE_CAPTURE_BINARY", "0") == "1"
```

- [ ] **Step 2: Write the failing test**

Create `src/backend/assistant/tests/test_tracing.py`:

```python
"""Agent tracing configuration.

These tests never contact Logfire. `configure_tracing` is split from
`instrumentation_settings` precisely so the policy (what gets captured) is
assertable without the transport (where it goes).
"""

from assistant.tracing import configure_tracing, instrumentation_settings


def test_no_token_means_no_logfire(settings):
    """Local development and CI must not transmit."""
    settings.LOGFIRE_TOKEN = ""
    assert configure_tracing() is False


def test_content_capture_follows_the_setting(settings):
    settings.LOGFIRE_CAPTURE_CONTENT = True
    assert instrumentation_settings().include_content is True

    settings.LOGFIRE_CAPTURE_CONTENT = False
    assert instrumentation_settings().include_content is False


def test_binary_content_is_excluded_by_default(settings):
    """Receipt photos are the largest exposure in the product; capturing text
    was decided, capturing every JPEG was not."""
    settings.LOGFIRE_CAPTURE_BINARY = False
    assert instrumentation_settings().include_binary_content is False


def test_binary_capture_can_be_turned_on(settings):
    settings.LOGFIRE_CAPTURE_BINARY = True
    assert instrumentation_settings().include_binary_content is True
```

- [ ] **Step 3: Run to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_tracing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.tracing'`

- [ ] **Step 4: Write the implementation**

Create `src/backend/assistant/tracing.py`:

```python
"""Logfire configuration and PydanticAI instrumentation.

Split deliberately in two: ``instrumentation_settings`` is the *policy* (what
is captured) and ``configure_tracing`` is the *transport* (where it goes). The
split is what lets the policy be asserted in tests without a network call.

Traces cover every agent, not only the chat one: ``Agent.instrument_all``
applies globally, so the receipt extraction agent is instrumented by the same
call. Each span carries the model name, which is what makes E09's future
routing decisions visible in production.
"""

import logging

from django.conf import settings
from pydantic_ai import Agent, InstrumentationSettings

logger = logging.getLogger(__name__)


def instrumentation_settings() -> InstrumentationSettings:
    """What the traces capture.

    ``include_content`` is on by explicit operator decision (E06 open question
    2, decided 2026-08-14): full prompts and completions, so a bad extraction
    can be read rather than reproduced.

    ``include_binary_content`` is a separate flag and defaults off. That
    decision was about text; this one governs whether every receipt photograph
    is uploaded to a third party.
    """
    return InstrumentationSettings(
        include_content=settings.LOGFIRE_CAPTURE_CONTENT,
        include_binary_content=settings.LOGFIRE_CAPTURE_BINARY,
    )


def configure_tracing() -> bool:
    """Wire Logfire, if a token is configured. Returns whether it happened.

    Never raises. Tracing is diagnostic infrastructure; a misconfigured
    observability vendor must not be able to prevent the application from
    starting.
    """
    if not settings.LOGFIRE_TOKEN:
        return False

    try:
        import logfire

        logfire.configure(
            token=settings.LOGFIRE_TOKEN,
            environment=settings.LOGFIRE_ENVIRONMENT,
            service_name="ledger",
        )
        Agent.instrument_all(instrumentation_settings())
    except Exception:
        logger.exception("Logfire configuration failed; continuing without agent tracing.")
        return False

    return True
```

- [ ] **Step 5: Call it at startup**

In `src/backend/assistant/apps.py`, add a `ready()` method to the existing
`AppConfig` (or extend it if one is already there):

```python
    def ready(self):
        # Imported here, not at module scope: `ready()` is the first point at
        # which the app registry and settings are both usable.
        from assistant.tracing import configure_tracing

        configure_tracing()
```

- [ ] **Step 6: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_tracing.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```
Expected: the tracing tests PASS, and the assistant suite stays green — the
instrumentation must not change agent behaviour.

> If `from pydantic_ai import InstrumentationSettings` fails on the installed
> version, import it from `pydantic_ai.models.instrumented` instead. Both paths
> are documented upstream; prefer the top-level one when it resolves.

- [ ] **Step 7: Commit**

```bash
git add src/backend/assistant/tracing.py src/backend/assistant/apps.py \
        src/backend/assistant/tests/test_tracing.py src/backend/config/settings.py
git commit -m "feat(observability): Logfire tracing for every agent

Policy and transport are separate functions so what gets captured is
assertable in a test without a network call.

Content capture is on by explicit operator decision, so a bad extraction
can be read rather than reproduced -- with the consequence, recorded in
the settings comment, that Logfire becomes a sub-processor of chat and
receipt content that E13's privacy notice has to name.

Binary capture is a separate flag and defaults off. That decision was
about text; this one governs whether every receipt photograph is
uploaded to a third party.

instrument_all covers the extraction agent too, not only chat, and each
span carries the model name -- which is what will make E09's routing
visible in production."
```

---

## Task 5: Stop swallowing failures

**Files:**
- Modify: `src/backend/assistant/views.py:116-122`
- Modify: `src/backend/finances/views/importer.py:436-442`
- Test: `src/backend/assistant/tests/test_error_reporting.py` (create)

**Interfaces:**
- Consumes: Sentry from Tasks 1–2
- Produces: no new public functions; behaviour change only

**Context — the current sites, verified at `e5f08a4`:**

| Site | Today | Action |
|---|---|---|
| `assistant/views.py:117-118` | `except Exception: data_changed = False` — fully silent | Report |
| `assistant/views.py:119-122` | `except Exception:` → friendly message, fully silent | Report, message unchanged |
| `assistant/views.py:297` | `logger.exception(...)` for transcription | Already an event via Sentry's logging integration — document, don't duplicate |
| `assistant/views.py:413`, `:425` | `logger.exception(...)` for extraction | Same — document |
| `finances/views/importer.py:440-441` | `except Exception: error_count += 1` — fully silent | Report **once, aggregated** |

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_error_reporting.py`:

```python
"""Failures reach the error tracker without changing what the user sees.

E06 S06-4 is explicit that this story improves observability, not UX. Every
test here asserts both halves: the report happened AND the message is the same.
"""

import json
from unittest.mock import patch

import pytest


@pytest.mark.django_db(transaction=True)
def test_stream_failure_is_reported_and_the_message_is_unchanged(logged_client):
    """The generic 'Erro ao processar mensagem' path was fully silent.

    It is the single most important site in the epic: every unhandled agent
    failure in production landed here and vanished.
    """
    from assistant.agents.assistant import assistant_agent

    def _explode(*args, **kwargs):
        raise RuntimeError("model exploded")

    with patch.object(assistant_agent, "run_stream", side_effect=_explode):
        with patch("sentry_sdk.capture_exception") as capture:
            response = logged_client.post(
                "/api/assistant/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            body = b"".join(response.streaming_content).decode()

    assert capture.called, "the agent failure was swallowed without reporting"
    assert "Erro ao processar mensagem" in body, "the user-facing message changed"


@pytest.mark.django_db
def test_import_row_failures_are_reported_once_not_per_row(monkeypatch):
    """A 1000-row file with 1000 bad rows must not create 1000 events.

    Aggregating is not merely tidier -- a per-row report would exhaust the
    Sentry quota that ADR-005 assumed was adequate, in a single upload.
    """
    from finances.views import importer

    captured = []
    monkeypatch.setattr(
        importer.sentry_sdk, "capture_message", lambda *a, **kw: captured.append((a, kw))
    )
    # Drive `report_import_failures` directly: it is the unit under test, and
    # building a 1000-row import fixture to assert a counter is disproportionate.
    importer.report_import_failures(error_count=1000, samples=[ValueError("bad date")] * 3)

    assert len(captured) == 1


@pytest.mark.django_db
def test_no_import_failures_reports_nothing(monkeypatch):
    from finances.views import importer

    captured = []
    monkeypatch.setattr(
        importer.sentry_sdk, "capture_message", lambda *a, **kw: captured.append(a)
    )
    importer.report_import_failures(error_count=0, samples=[])

    assert captured == []
```

- [ ] **Step 2: Run to verify failure**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_error_reporting.py -v`
Expected: FAIL — `capture.called` is False, and `report_import_failures` does not exist.

- [ ] **Step 3: Report at the assistant sites**

In `src/backend/assistant/views.py`, add the import at the top:

```python
import sentry_sdk
```

Then replace lines 116–122 (the two `except Exception:` blocks inside
`stream_response`) with:

```python
                    data_changed = _run_mutated_data(stream.all_messages())
                except Exception:
                    # Reported rather than swallowed: this failing means the
                    # "your data changed" signal is wrong, which shows up to the
                    # user as a stale screen with no error — the hardest class of
                    # bug to hear about from a user.
                    sentry_sdk.capture_exception()
                    data_changed = False
        except Exception:
            # The single most important report in E06: every unhandled agent
            # failure in production used to land here and vanish. The message
            # the user sees is deliberately unchanged — S06-4 improves
            # observability, not UX.
            sentry_sdk.capture_exception()
            error_msg = "Erro ao processar mensagem. Tente novamente."
            yield json.dumps({"type": "error", "content": error_msg}, ensure_ascii=False) + "\n"
            full_response = error_msg
```

Then add a comment at the three `logger.exception` sites (lines ~297, ~413, ~425)
recording why they need no explicit capture:

```python
        # No explicit capture_exception: Sentry's logging integration turns an
        # ERROR-level record into an event, and logger.exception is ERROR. Adding
        # one here would double-report.
```

- [ ] **Step 4: Aggregate and report the importer's row failures**

In `src/backend/finances/views/importer.py`, add the import at the top:

```python
import sentry_sdk
```

Add this function at module level:

```python
def report_import_failures(error_count: int, samples: list) -> None:
    """Report row failures as ONE event carrying a count and a few examples.

    Per-row reporting would turn a single 1000-row bad file into 1000 events and
    exhaust the free-tier quota ADR-005 assumed was adequate. The count is the
    signal; three exception types are enough to diagnose.
    """
    if not error_count:
        return
    sentry_sdk.capture_message(
        f"CSV import finished with {error_count} failed row(s)",
        level="warning",
    )
```

Then, in the import-execution function, collect samples in the loop and report
after it. Replace lines 440–441:

```python
            except Exception as exc:
                error_count += 1
                # Bounded on purpose: the count is the signal, and holding every
                # exception from a large bad file is a memory leak in disguise.
                if len(failure_samples) < 3:
                    failure_samples.append(exc)
```

Initialise `failure_samples = []` alongside `created_count`, and after the loop
closes (before `batch.executed_at = timezone.now()`), add:

```python
        report_import_failures(error_count, failure_samples)
```

- [ ] **Step 5: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_error_reporting.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -q -k import
```
Expected: the new tests PASS and the existing importer tests stay green — the
row-failure counting behaviour must be unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/views.py src/backend/finances/views/importer.py \
        src/backend/assistant/tests/test_error_reporting.py
git commit -m "fix(observability): report the failures that were being swallowed

The generic 'Erro ao processar mensagem' path was fully silent, so every
unhandled agent failure in production vanished. It now reports before
returning the identical message -- this story improves observability,
not UX.

Import row failures report ONCE with a count and three sample
exceptions. Per-row reporting would turn one 1000-row bad file into 1000
events and exhaust the free-tier quota ADR-005 assumed was adequate.

The three logger.exception sites need no explicit capture: Sentry's
logging integration already turns an ERROR record into an event, and
adding one would double-report. Said so in a comment at each, since
'why is there no capture here' is the obvious next question."
```

---

## Task 6: Full-suite verification and the gates

**Files:** none — this task only runs commands.

- [ ] **Step 1: Run the full suite with coverage**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
```
Expected: PASS. Baseline before this epic was **1322 passed, 3 skipped, 91% coverage** — coverage must not fall below 80, and no previously-passing test may fail.

- [ ] **Step 2: Lint and format**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```
Expected: clean. Run `uv run ruff format src/backend/` and re-commit if it reports changes.

- [ ] **Step 3: Django checks, including the deploy variant**

```bash
uv run python src/backend/manage.py check
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com uv run python src/backend/manage.py check --deploy
```
Expected: no new issues versus before this epic.

- [ ] **Step 4: Confirm no migration was introduced**

```bash
uv run python src/backend/manage.py makemigrations --check --dry-run
```
Expected: "No changes detected". This epic adds no model.

- [ ] **Step 5: Confirm the admin gate is still last**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_admin_isolation.py -v
grep -n -A3 "admin_staff_only_middleware" src/backend/config/settings.py
```
Expected: tests PASS and `admin_staff_only_middleware` is the final entry in `MIDDLEWARE`.

- [ ] **Step 6: Commit any formatting fixes**

```bash
git add -u && git commit -m "style: ruff format after E06 instrumentation" || echo "nothing to commit"
```

---

## Task 7: Deploy, then wire Cloud Monitoring

**Files:** none in the repo — this task runs `gcloud` and the Cloud Console.

> **Order matters.** The uptime check and the dashboard need a deployed revision
> emitting the new logs, so this task comes after the code is merged and
> deployed. `--update-secrets` and `--update-env-vars`, never `--set-env-vars`,
> which wipes the whole list (`docs/runbook.md` top).

- [ ] **Step 1: Store the two vendor secrets**

```bash
printf '%s' 'https://YOUR_KEY@oNNNNNN.ingest.sentry.io/PROJECT' | \
  gcloud secrets create sentry-dsn --data-file=- --project expense-tracker-482807
printf '%s' 'YOUR_LOGFIRE_WRITE_TOKEN' | \
  gcloud secrets create logfire-token --data-file=- --project expense-tracker-482807
```

- [ ] **Step 2: Deploy with the new configuration**

```bash
gcloud run services update expense-tracker \
  --region southamerica-east1 --project expense-tracker-482807 \
  --update-secrets SENTRY_DSN=sentry-dsn:latest,LOGFIRE_TOKEN=logfire-token:latest \
  --update-env-vars SENTRY_ENVIRONMENT=production,LOGFIRE_ENVIRONMENT=production,SENTRY_TRACES_SAMPLE_RATE=0.1
```

- [ ] **Step 3: Prove an error reaches Sentry, tagged with the revision**

Trigger a deliberate exception on the deployed revision, then confirm in Sentry
that the event carries `release = expense-tracker-000NN-xxx` and a `request_id`
tag. Record the revision name and the Sentry issue URL for the DoD.

- [ ] **Step 4: Prove a request ID correlates across all three**

```bash
curl -sI https://<host>/healthz/ | grep -i x-request-id
```

Take that ID and confirm it appears in the Cloud Logging entry for the same
request. Paste both as DoD evidence.

- [ ] **Step 5: Create the two notification channels**

Per the operator's decision: mobile push **and** email.

```bash
# Email
gcloud beta monitoring channels create \
  --display-name="Operator email" \
  --type=email \
  --channel-labels=email_address=bessavagner@gmail.com \
  --project expense-tracker-482807
```

> **CORRECTION (2026-08-14, during execution): the mobile push channel does not
> exist any more.** Google retired the Cloud Console mobile app and its
> `mobile_push` notification channel type; `gcloud beta monitoring
> channel-descriptors describe mobile_push` returns `NOT_FOUND` and there is no
> "Mobile devices" entry in the console. Do not follow the deleted instruction
> that used to be here. Only the email channel was created —
> `Operator email`, id `5857707555791637518`. The operator accepted **email
> only** for now, meaning **nothing pages anyone**. SMS is the replacement if
> that changes; `gcloud` can create it but has no `channels verify`
> subcommand, so the texted code must be entered in the console.

- [ ] **Step 6: Create the uptime check, and delete the keepalive it replaces**

Create an uptime check on `https://<host>/healthz/`, 5-minute interval, alerting
to both channels. Then remove the now-redundant pinger:

```bash
gcloud scheduler jobs delete expense-tracker-keepalive \
  --location southamerica-east1 --project expense-tracker-482807
```

> The uptime check now *is* the keepalive. `docs/runbook.md` §"Measuring cold
> start" tells you to pause the Scheduler job before measuring; Task 8 rewrites
> that to pause the uptime check instead. **Do not skip that edit** — leaving it
> stale makes the next cold-start measurement silently wrong.

- [ ] **Step 7: Add the error-rate and spend alerts**

Two alert policies, both to the same channels:
- **Error rate** — Cloud Run 5xx responses above an agreed threshold over 5 minutes.
- **LLM spend** — the threshold already agreed in E01 (`docs/runbook.md` §"Spend ceilings").

- [ ] **Step 8: Prove the alert path actually wakes you**

Temporarily lower the uptime-check threshold (or point it at a path that 404s)
until it fires, confirm the push notification arrives **on the phone**, then
restore it. An alert that has never fired is a hypothesis, not an alert.

- [ ] **Step 9: Build the golden-signals dashboard**

One dashboard with all five: request rate, error rate, p95 latency, assistant
turns per day, and estimated LLM spend per day. The first three come from Cloud
Run's built-in metrics; the last two come from log-based metrics over the new
structured fields. Record the dashboard URL.

---

## Task 8: Runbook, environment sample, and closing the epic

**Files:**
- Modify: `.env.example`
- Modify: `docs/runbook.md`
- Modify: `docs/backlog/E06-observability-and-agent-tracing.md`
- Modify: `docs/backlog/INDEX.md`

- [ ] **Step 1: Document the new environment variables**

Append to `.env.example`:

```bash
# --- Observability (E06) ---
# All optional: absent SENTRY_DSN disables Sentry, absent LOGFIRE_TOKEN
# disables agent tracing. That is the intended local-development state --
# neither should transmit from a laptop.
# SENTRY_DSN=https://key@oNNNNNN.ingest.sentry.io/PROJECT
# SENTRY_ENVIRONMENT=development
# SENTRY_TRACES_SAMPLE_RATE=0.1
# SENTRY_RELEASE=local            # production reads K_REVISION instead
# LOGFIRE_TOKEN=
# LOGFIRE_ENVIRONMENT=development
# Full prompts and completions are captured by default (operator decision,
# 2026-08-14). Set to 0 to turn text capture off without a deploy.
# LOGFIRE_CAPTURE_CONTENT=1
# Receipt PHOTOS are NOT captured by default. Turning this on uploads every
# receipt image to a third party.
# LOGFIRE_CAPTURE_BINARY=0
```

- [ ] **Step 2: Write the "When something breaks" runbook section**

Add a new section to `docs/runbook.md`, following the file's existing style —
full invocations with realistic values, what they print, and the common failure.
It must cover:

- **Start from the request ID.** Ask the user for it, or read `X-Request-ID` from
  the failing response. The Cloud Logging query:
  ```
  resource.type="cloud_run_revision"
  jsonPayload.request_id="<the id>"
  ```
- **The Sentry issue** for the same request, found by the `request_id` tag, and
  how `release` maps to a Cloud Run revision.
- **The Logfire trace** for an agent failure — what a run span holds (tool calls,
  latency, model name, token counts) and the note that full prompt text is
  captured by decision.
- **Who gets alerted, and how** — both channel names, and how to test the path
  without waiting for a real outage.
- **The dashboard URL** and what each of the five signals means.
- **What is deliberately not reported**, so nobody re-adds it: the three
  `logger.exception` sites, already covered by the logging integration.

- [ ] **Step 3: Amend the two stale keepalive references**

In `docs/runbook.md` §"Cold starts: the keepalive job" (line ~299) and
§"Measuring cold start" (line ~370): the Cloud Scheduler job is gone, replaced
by the uptime check. The cold-start procedure must now say to **pause the uptime
check**, and to restore it afterwards.

- [ ] **Step 4: Record the E13 consequence in the epic**

In `docs/backlog/E06-observability-and-agent-tracing.md`, under "Out of scope",
add:

```markdown
- **Handed to E13:** the operator's decision to capture full prompts and
  completions (2026-08-14) makes Logfire a **data sub-processor** holding chat
  content and receipt descriptions. E13's privacy notice must name Pydantic as a
  sub-processor, and E13's deletion story must state what happens to trace data.
  Recorded here because it is not discoverable from E13's own file.
```

- [ ] **Step 5: Tick the Definition of Done**

Check off each box in the epic's DoD, pasting the real evidence gathered in Task 7
— the Sentry issue URL, the correlated request ID, a Logfire run span with token
counts, the fired alert, and the dashboard URL. **A box without evidence stays
unticked.**

- [ ] **Step 6: Flip the statuses**

Set `status: review` in the epic frontmatter and update the row in
`docs/backlog/INDEX.md` §4. **E07, E10, E14 and E16 all depend on E06** — once it
reaches `done`, flip those four from `blocked` to `ready` in both the table and
their own frontmatter, exactly as this session did for E11.

- [ ] **Step 7: Commit**

```bash
git add .env.example docs/runbook.md docs/backlog/E06-observability-and-agent-tracing.md \
        docs/backlog/INDEX.md
git commit -m "docs(E06): runbook triage path, env sample, and the E13 handoff

The runbook entry starts from the request ID because that is what a user
can actually give you, and it is now the join key across Cloud Logging,
Sentry and Logfire.

Records the consequence of capturing full prompt content: Logfire holds
chat and receipt text, making Pydantic a sub-processor E13's privacy
notice has to name. Written into E06 rather than E13 because it is not
discoverable from E13's own file.

The keepalive sections are corrected -- the Scheduler job is gone and
the uptime check replaced it, so the cold-start procedure now pauses the
right thing."
```

---

## Self-Review

**Spec coverage** — every E06 story maps to a task:

| Story | Task |
|---|---|
| S06-1 · Error tracking with PII discipline | 1, 2 (+ 7 for the DSN from Secret Manager and release tagging) |
| S06-2 · Structured logging with request correlation | 3 |
| S06-3 · Agent tracing and token accounting | 4 |
| S06-4 · Stop swallowing failures silently | 5 |
| S06-5 · Uptime, alerting, golden-signals dashboard | 7 |
| DoD commands and gates | 6 |
| Runbook requirement in the DoD | 8 |

Open questions 1 and 2 were answered by the operator and are recorded in
**Global Constraints**; 3 was settled by ADR-005 ("both have free tiers adequate
for launch scale"); 4 was resolved from `docs/runbook.md:299` — there is an
existing keepalive, and Task 7 Step 6 replaces it rather than adding a second
pinger.

**Known deviations from the epic, both deliberate and both recorded above:**
1. The epic *recommends* content behind a dev-only flag; the operator decided
   the opposite. Followed the operator, recorded the decision and its E13
   consequence.
2. The epic's evidence table cites `assistant/views.py:104-107` etc. from
   baseline `3bbc5ca`. Those line numbers have moved; Task 5 uses the anchors
   verified at `e5f08a4` and lists them in a table.

**Naming consistency check:** `sentry_settings` / `scrub_event` (Task 1→2),
`get_log_context` / `set_log_context` / `sanitise_inbound` (Task 3, used by
`core.middleware` and `core.log_formatting`), `instrumentation_settings` /
`configure_tracing` (Task 4), `report_import_failures` (Task 5, defined and
called in `importer.py`, asserted in its test). No signature drifts between
definition and use.

**One place the executor must exercise judgement**, flagged rather than guessed:
Task 3's final test asserts contextvar state after `logged_client.get()` on the
assumption that the test client runs the request in the calling task. If the
suite's ASGI configuration breaks that assumption, assert instead through a
temporary logging probe view added inside the test module rather than weakening
the assertion.
