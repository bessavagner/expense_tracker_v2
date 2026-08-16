# E10 · Async work pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Cloud Tasks rails — authenticated task endpoints, one typed enqueue helper, idempotent handlers, a configured retry and dead-letter path, and a GCP-free local mode — and prove them by moving memory-rule embedding generation off the request.

**Architecture:** A single `/tasks/<name>/` Django view dispatches to handlers registered by name. Every unit of work is a `TaskRun` row holding its own payload, attempt count and attempt ceiling, so the retry/dead-letter decision is made by the application against a queryable record rather than by a queue that silently drops exhausted tasks. Cloud Tasks carries only the row's id, which keeps the wire format tiny and makes the 1 MiB task ceiling a non-issue for the transport. An eager in-process backend runs the same code path locally, so `CLOUD_TASKS_ENABLED=0` is a complete setup rather than a degraded one.

**Tech Stack:** Django 6, Python 3.12, `google-cloud-tasks` (new dependency), Postgres 17 + pgvector, pytest + pytest-django + model-bakery, Sentry, Logfire.

**Spec:** `docs/backlog/E10-async-work-pipeline.md`

---

## Brainstorming outcome — read this before Task 1

The spec's skill pipeline marks brainstorming **required**, because open questions 1 and 2 could change scope substantially. They did. Three findings were verified against the code and the Cloud Tasks documentation on 2026-08-15, and three decisions follow from them. **Every task below assumes these; do not re-litigate them mid-execution.**

### F1 · Cloud Tasks caps a task at 1 MiB, and the limit is fixed

`https://cloud.google.com/tasks/docs/quotas` lists **"Maximum task size: 1 MiB"** under *System limits*, which the page states "can't be changed."

This app's media does not fit:

| Payload | Ceiling | Source |
|---|---|---|
| Audio upload | 25 MB | `ASSISTANT_MAX_AUDIO_MB`, `config/settings.py:465` |
| Raw images | 10 MB × 5 | `ASSISTANT_MAX_IMAGE_MB` / `ASSISTANT_MAX_IMAGES`, `config/settings.py:463-464` |
| Prepared images | grayscale JPEG q90, max 2000px, ×5 — routinely several MB | `assistant/services/image_prep.py` |

So neither the voice note nor the receipt photos can travel in a task payload. Moving those workloads off-request first needs somewhere to park the bytes — object storage — which is **E12 S12-2**, and E12 declares `depends_on: [E10]`. The dependency as written is circular.

### F2 · There is no channel to push an async result into

`ChatWidget.tsx:413` and `:474` consume the chat response with `fetch` + `response.body.getReader()` — not `EventSource`. The "SSE channel" is the POST's own chunked response body. There is no reconnect, no event ids, no `Last-Event-ID`. When the response ends the channel is gone.

So S10-3's "reuse the existing SSE channel rather than adding polling" is not available. And holding the stream open while a task runs would pin **two** concurrent requests (the stream plus the task handler) where there was one, on `--cpu 1 --concurrency 80` — the opposite of the epic's stated goal.

### F3 · S10-4's premise does not hold in the code

`create_memory_rule` (`assistant/agents/tools.py:1259`) creates a `MemoryRule` and **never generates an embedding**. Grep for `MemoryEmbedding` outside tests and migrations finds only `assistant/agents/memory.py` (reads) and `finances/management/commands/seed_perf_data.py` (writes). The single inline `get_embedding` call is the **query** embedding in `lookup_memory_async` (`assistant/agents/tools.py:1245`), which the agent blocks on and cannot be deferred.

There is no write-path embedding to move. Semantic memory search queries an empty table outside the perf seed.

### Decisions

**D1 — E10 delivers the rails; media workloads are deferred.** Build the full Cloud Tasks infrastructure and move only work that fits comfortably under the ceiling. Transcription and receipt extraction stay inline until E12 lands GCS; the epic that moves them then consumes these rails, which is what ADR-004 intended. This resolves the circularity in the honest direction and keeps every scope line the spec drew.

**D2 — when a media workload does go async, the client polls a status endpoint.** This is the settled answer to open question 1: the POST returns immediately with a job id and an honest interim state, and the widget polls a small GET until the job resolves. It is the only option of the three that actually frees the instance. **It is not built in E10** — there is no consumer yet, and a polling endpoint with no caller is exactly the speculative machinery YAGNI forbids. The decision is recorded so E12 does not have to rediscover it.

**D3 — S10-4 is rewritten as generate-on-write.** `create_memory_rule` enqueues an embedding task. This makes memory rules semantically searchable for the first time, fits far under 1 MiB, and gives the rails a real workload rather than a test-only one. The spec's graceful-degradation assertion then means something: while the embedding is pending, `find_matching_rules`' substring path still works.

### Which Definition-of-Done boxes this plan closes

| Spec DoD box | Status in this plan |
|---|---|
| Task handlers reject requests without a valid OIDC token, asserted by test | **Closed** — Task 3, Task 4 |
| A handler invoked twice with the same payload produces one result | **Closed** — Task 4, Task 6 |
| The one-pending-draft invariant holds under concurrent uploads and a retried task | **Deferred to E12** (media path, F1) |
| A transient transcription failure is retried and succeeds without user action | **Deferred to E12** (media path, F1) |
| A memory rule created while its embedding is pending is still matched by the substring path | **Closed** — Task 6 |
| A task execution's trace links back to its originating request ID | **Closed** — Task 5 |
| A deliberately failed task lands in the dead-letter path and is visible | **Closed** — Task 4, Task 7 |
| Local development works without GCP credentials | **Closed** — Task 2 |
| `docs/runbook.md` documents inspecting and replaying dead-lettered tasks | **Closed** — Task 7 |

Task 7 writes the two deferred boxes back into the epic document, so the deferral is recorded where the next reader will look.

---

## Global Constraints

Copied from the spec and the repository's standing rules. Every task's requirements implicitly include this section.

- **The full test suite and lint gate must pass before any task is considered done:**
  `POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80`
  `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
- **Coverage floor is 80%.** New modules need tests, not just the happy path.
- **Postgres for tests and local dev is the pgvector container on port 5433**, not the system Postgres. Every pytest invocation in this plan carries `POSTGRES_PORT=5433`.
- **Ruff line length is 100**, target `py312` (`pyproject.toml`).
- **No `Celery`, `Redis`, or database-backed queue** — rejected in ADR-004.
- **Do not make the chat conversation asynchronous.** Streaming stays. `_sse_response` in `assistant/views.py` is not touched by this plan.
- **Do not replace `sync_to_async` in the agent.** Out of scope, separate refactor.
- **Do not move CSV import.** That is E12.
- **Comments and docstrings in English; all user-facing copy in pt-BR.** Tests in English, with pt-BR only inside assertions about user-facing strings (`docs/testing-conventions.md`).
- **Never commit secrets.** No service-account keys, no `.env` values, no license keys.
- **Commit messages carry no AI attribution** — no `Co-Authored-By: Claude`, no "Generated with" line, no mention of Claude/Anthropic/AI.
- **Do not create or modify GCP resources.** Task 7 writes the `gcloud` commands into the runbook for the operator to run; the implementer does not execute them.

---

## File Structure

New package `src/backend/core/tasks/`. `core` is the right home — it already holds the cross-cutting infrastructure (`middleware.py`, `request_id.py`, `observability.py`, `asgi_body_limit.py`), and E12 will call `enqueue` from `finances`. `TaskRun` lives in `core/models.py`, which also keeps it outside `accounts.tests.test_cross_household_isolation.test_every_domain_model_is_household_owned` — that check covers only the `finances` and `assistant` apps, and correctly so: a task row is infrastructure, not a household's money.

| File | Responsibility |
|---|---|
| `core/tasks/__init__.py` | Public surface: `enqueue`, `task_handler`. Nothing else imports the internals. |
| `core/tasks/registry.py` | Name → handler mapping, attempt ceilings, autodiscovery. |
| `core/tasks/execution.py` | Run one `TaskRun` and record the outcome. Shared by both backends. |
| `core/tasks/backends.py` | `EagerBackend` and the settings-driven backend choice. |
| `core/tasks/enqueue.py` | The single scheduling entry point: payload ceiling, idempotency key, request-ID capture. |
| `core/tasks/auth.py` | OIDC verification of an inbound task request. |
| `core/tasks/views.py` | The one HTTP dispatch view. |
| `core/tasks/urls.py` | `/tasks/<name>/`. |
| `core/tasks/cloud.py` | The Cloud Tasks backend. Imported lazily so the SDK is not needed locally. |
| `core/models.py` | *(modify)* `TaskStatus`, `TaskRun`. |
| `core/admin.py` | *(modify)* `TaskRun` admin, for dead-letter visibility. |
| `core/apps.py` | *(modify)* call `autodiscover()` from `ready()`. |
| `core/management/commands/replay_task.py` | Re-enqueue a dead-lettered task. |
| `assistant/tasks.py` | The assistant's handlers. Today: memory-rule embedding. |
| `assistant/agents/tools.py` | *(modify)* `create_memory_rule` enqueues the embedding. |
| `config/settings.py` | *(modify)* `CLOUD_TASKS_*`, `TASK_PAYLOAD_MAX_BYTES`. |
| `config/urls.py` | *(modify)* include `core.tasks.urls` at `tasks/`. |
| `pyproject.toml` | *(modify)* add `google-cloud-tasks`. |
| `docs/runbook.md` | *(modify)* provisioning, inspection, replay. |
| `docs/backlog/E10-async-work-pipeline.md` | *(modify)* record D1–D3 and the deferred boxes. |

---

### Task 1: `TaskRun` and the handler registry

The vocabulary everything else is written in: what a task *is* on disk, and how a name becomes runnable code.

**Files:**
- Create: `src/backend/core/tasks/__init__.py`
- Create: `src/backend/core/tasks/registry.py`
- Modify: `src/backend/core/models.py` (append at end of file)
- Modify: `src/backend/core/apps.py:1-9`
- Create: `src/backend/core/migrations/00XX_taskrun.py` (generated)
- Test: `src/backend/core/tests/test_task_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `core.models.TaskStatus` — `TextChoices` with `PENDING = "pending"`, `DONE = "done"`, `DEAD = "dead"`.
  - `core.models.TaskRun` — fields `id: UUID` (pk), `name: str`, `idempotency_key: str` (unique), `payload: dict`, `status: str`, `attempts: int`, `max_attempts: int`, `request_id: str`, `last_error: str`, `created_at`, `updated_at`.
  - `core.tasks.registry.task_handler(name: str, *, max_attempts: int = 5)` — decorator, returns the function unchanged.
  - `core.tasks.registry.get_task(name: str) -> TaskDefinition` — raises `UnknownTask`.
  - `core.tasks.registry.TaskDefinition` — frozen dataclass `(name: str, handler: Callable[[dict], None], max_attempts: int)`.
  - `core.tasks.registry.UnknownTask(LookupError)`, `core.tasks.registry.DuplicateTask(RuntimeError)`.
  - `core.tasks.registry.registered_names() -> list[str]`.
  - `core.tasks.registry.autodiscover() -> None`.

- [ ] **Step 1: Write the failing registry tests**

Create `src/backend/core/tests/test_task_registry.py`:

```python
"""The registry is the contract between an enqueue call and the code that runs.

A name travels through Cloud Tasks as a URL segment, so it outlives the
process. These tests pin the two failures that matter: a typo must be loud, and
two handlers must never quietly share a name.
"""

import pytest

from core.tasks.registry import (
    DuplicateTask,
    UnknownTask,
    get_task,
    registered_names,
    task_handler,
)


def test_registered_handler_is_retrievable_by_name():
    @task_handler("test.retrievable", max_attempts=3)
    def handler(payload):
        return payload

    definition = get_task("test.retrievable")

    assert definition.name == "test.retrievable"
    assert definition.handler is handler
    assert definition.max_attempts == 3


def test_decorator_returns_the_function_unchanged():
    """The handler stays directly callable, so a test can invoke it plainly."""

    @task_handler("test.unchanged")
    def handler(payload):
        return payload["x"]

    assert handler({"x": 7}) == 7


def test_default_max_attempts_is_five():
    @task_handler("test.default-attempts")
    def handler(payload):
        pass

    assert get_task("test.default-attempts").max_attempts == 5


def test_unknown_name_raises():
    with pytest.raises(UnknownTask):
        get_task("test.never-registered")


def test_two_handlers_cannot_claim_one_name():
    @task_handler("test.contested")
    def first(payload):
        pass

    with pytest.raises(DuplicateTask):

        @task_handler("test.contested")
        def second(payload):
            pass


def test_registered_names_are_sorted():
    @task_handler("test.zzz")
    def last(payload):
        pass

    @task_handler("test.aaa")
    def first(payload):
        pass

    names = registered_names()

    assert names.index("test.aaa") < names.index("test.zzz")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_registry.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'core.tasks'`

- [ ] **Step 3: Write the registry**

Create `src/backend/core/tasks/__init__.py`:

```python
"""Deferred work: how it is scheduled, and how it comes back.

The public surface is deliberately two names. Everything else in this package
is internal, so that the payload ceiling, the idempotency key and the backend
choice cannot be bypassed by importing something one layer down.
"""

from core.tasks.enqueue import enqueue
from core.tasks.registry import task_handler

__all__ = ["enqueue", "task_handler"]
```

> The `enqueue` import will fail until Task 2 creates that module. Leave the
> file with only the `task_handler` import for now and add the rest in Task 2:

```python
"""Deferred work: how it is scheduled, and how it comes back.

The public surface is deliberately small. Everything else in this package is
internal, so that the payload ceiling, the idempotency key and the backend
choice cannot be bypassed by importing something one layer down.
"""

from core.tasks.registry import task_handler

__all__ = ["task_handler"]
```

Create `src/backend/core/tasks/registry.py`:

```python
"""Which names are runnable, and what runs them.

A task's *name* travels through Cloud Tasks as a URL segment, so it is the one
piece of the contract that outlives the process. Keeping the mapping in one
place is what makes a typo fail at enqueue time — inside the request that made
it — rather than as a 404 in a dispatch nobody is watching.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.utils.module_loading import autodiscover_modules


class UnknownTask(LookupError):
    """No handler is registered under this name."""


class DuplicateTask(RuntimeError):
    """Two different handlers claimed the same name."""


@dataclass(frozen=True)
class TaskDefinition:
    """A runnable name.

    ``max_attempts`` lives here rather than only on the Cloud Tasks queue
    because the queue's ceiling is shared by every task in it, and because
    Cloud Tasks has no dead-letter queue — an exhausted task is simply dropped.
    The application has to own the ceiling to be able to record the giving-up.
    """

    name: str
    handler: Callable[[dict], None]
    max_attempts: int


_REGISTRY: dict[str, TaskDefinition] = {}


def task_handler(name: str, *, max_attempts: int = 5):
    """Register ``name`` as runnable, and return the function unchanged.

    Unchanged on purpose: the handler stays an ordinary function, so a test can
    call it directly without going anywhere near HTTP or a queue.
    """

    def decorator(func):
        existing = _REGISTRY.get(name)
        if existing is not None and existing.handler is not func:
            raise DuplicateTask(
                f"Task '{name}' is already registered to "
                f"{existing.handler.__module__}.{existing.handler.__qualname__}."
            )
        _REGISTRY[name] = TaskDefinition(name=name, handler=func, max_attempts=max_attempts)
        return func

    return decorator


def get_task(name: str) -> TaskDefinition:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownTask(name) from None


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


def autodiscover() -> None:
    """Import every app's ``tasks`` module, so decorators have run.

    Same mechanism Django's admin uses, and for the same reason: registration
    by import side effect only works if something guarantees the import.
    """
    autodiscover_modules("tasks")
```

- [ ] **Step 4: Run the registry tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: Write the failing model tests**

Append to `src/backend/core/tests/test_task_registry.py`:

```python
@pytest.mark.django_db
class TestTaskRun:
    """The durable record. Everything an operator needs is on this row."""

    def test_a_new_run_starts_pending_with_no_attempts(self):
        from core.models import TaskRun, TaskStatus

        run = TaskRun.objects.create(
            name="test.model",
            idempotency_key="test.model:1",
            payload={"a": 1},
            max_attempts=4,
        )

        assert run.status == TaskStatus.PENDING
        assert run.attempts == 0
        assert run.last_error == ""
        assert run.request_id == ""

    def test_the_idempotency_key_is_unique(self):
        from django.db import IntegrityError

        from core.models import TaskRun

        TaskRun.objects.create(
            name="test.model", idempotency_key="test.model:dup", payload={}, max_attempts=4
        )

        with pytest.raises(IntegrityError):
            TaskRun.objects.create(
                name="test.model", idempotency_key="test.model:dup", payload={}, max_attempts=4
            )

    def test_str_shows_the_attempt_budget(self):
        from core.models import TaskRun

        run = TaskRun.objects.create(
            name="test.model",
            idempotency_key="test.model:str",
            payload={},
            max_attempts=4,
            attempts=2,
        )

        assert str(run) == "test.model (pending, 2/4)"
```

- [ ] **Step 6: Run the model tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_registry.py -v -k TaskRun`
Expected: FAIL with `ImportError: cannot import name 'TaskRun' from 'core.models'`

- [ ] **Step 7: Add the model**

Append to `src/backend/core/models.py`:

```python
class TaskStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    DONE = "done", "Concluída"
    DEAD = "dead", "Descartada"


class TaskRun(models.Model):
    """One unit of deferred work, and everything an operator needs about it.

    Cloud Tasks has no dead-letter queue: when a task exhausts its attempts the
    service simply drops it. So the attempt ceiling lives here, on a row that
    can be queried, listed in admin and replayed — rather than only in the
    queue's ``retryConfig``, where "it gave up" leaves no trace. It also makes
    the whole retry and dead-letter path testable without the cloud.

    ``idempotency_key`` is the at-least-once defence. Cloud Tasks may deliver
    the same task more than once; ``core.tasks.enqueue`` upserts on this column
    and the dispatch view refuses to re-run a row that already reached DONE.

    ``payload`` lives on the row rather than in the task body on purpose: only
    the row's id crosses the wire, so the fixed 1 MiB Cloud Tasks task ceiling
    stops being something every caller has to reason about.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=10, choices=TaskStatus.choices, default=TaskStatus.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    # The request that scheduled this work (E06, S10-5). Same 32-hex shape as
    # `core.request_id`, so one Cloud Logging filter finds the originating
    # request and the task it spawned.
    request_id = models.CharField(max_length=32, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "execução de tarefa"
        verbose_name_plural = "execuções de tarefa"
        ordering = ["-created_at"]
        indexes = [
            # The dead-letter sweep the runbook documents.
            models.Index(fields=["status", "-created_at"], name="taskrun_status_recent_idx"),
            # "How is this particular handler doing?"
            models.Index(fields=["name", "-created_at"], name="taskrun_name_recent_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.status}, {self.attempts}/{self.max_attempts})"
```

Add `import uuid` to the top of `core/models.py` if it is not already there.

- [ ] **Step 8: Generate and inspect the migration**

Run: `POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations core`
Expected: `Create model TaskRun` plus the two indexes. Open the generated file and confirm it creates one table and adds no column to an existing one.

- [ ] **Step 9: Run the model tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_registry.py -v`
Expected: 9 passed

- [ ] **Step 10: Wire autodiscovery into app startup**

Modify `src/backend/core/apps.py`:

```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Imported for the side effect of registering the login-failure receivers.
        from core import signals  # noqa: F401

        # Import every app's `tasks` module so its @task_handler decorators
        # have run. Without this, a name is only registered if something
        # happened to import the module first — which is exactly the kind of
        # order dependence that works locally and 404s in production.
        from core.tasks.registry import autodiscover

        autodiscover()
```

- [ ] **Step 11: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass, no new failures (autodiscovery finds no `tasks` module yet, which is fine — `autodiscover_modules` skips apps that have none).

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 12: Commit**

```bash
git add src/backend/core/tasks/ src/backend/core/models.py src/backend/core/apps.py \
        src/backend/core/migrations/ src/backend/core/tests/test_task_registry.py
git commit -m "feat(tasks): TaskRun and the handler registry

Cloud Tasks has no dead-letter queue, so the attempt ceiling and the
record of giving up live on a row we can query rather than in the
queue's retryConfig."
```

---

### Task 2: `enqueue`, the eager backend, and the payload ceiling

The single way application code schedules work — and the reason it works on a laptop with no GCP credentials.

**Files:**
- Create: `src/backend/core/tasks/execution.py`
- Create: `src/backend/core/tasks/backends.py`
- Create: `src/backend/core/tasks/enqueue.py`
- Modify: `src/backend/core/tasks/__init__.py`
- Modify: `src/backend/config/settings.py` (append near the other assistant/limit settings, after `MAX_CSV_UPLOAD_BYTES`)
- Test: `src/backend/core/tests/test_task_enqueue.py`

> **On S10-1's "do not invent a second mechanism".** The spec warns against
> reinventing the duplicate-prevention machinery that already exists — the
> one-pending-draft invariant and `find_registered_duplicate`. Those are
> *domain* duplicate detection: "is this receipt already in the ledger?" The
> `idempotency_key` here is *transport* idempotency: "has this exact unit of
> work already been scheduled or run?" They sit at different layers and both
> are needed; when E12 moves receipt extraction onto these rails, the handler
> will call `find_registered_duplicate` exactly as `_dispatch_extraction` does
> today. Do not replace one with the other.

**Interfaces:**
- Consumes: `core.models.TaskRun`, `core.models.TaskStatus`, `core.tasks.registry.get_task`, `core.tasks.registry.task_handler`, `core.request_id.get_request_id`.
- Produces:
  - `core.tasks.execution.run_task_run(task_run: TaskRun) -> str` — executes once, saves the row, returns the resulting `TaskStatus` value. Never raises.
  - `core.tasks.backends.EagerBackend` — has `dispatch(task_run: TaskRun) -> None`.
  - `core.tasks.backends.backend_for_settings() -> EagerBackend | CloudTasksBackend`.
  - `core.tasks.enqueue.enqueue(name: str, payload: dict, *, idempotency_key: str | None = None) -> TaskRun`.
  - `core.tasks.enqueue.PayloadTooLarge(ValueError)`.
  - `core.tasks.enqueue.default_idempotency_key(name: str, payload: dict) -> str`.
  - Settings `CLOUD_TASKS_ENABLED: bool`, `TASK_PAYLOAD_MAX_BYTES: int`.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_task_enqueue.py`:

```python
"""`enqueue` is the only door. These tests pin what it guarantees at that door.

The eager backend is not a test double — it is the local-development backend,
and it shares `run_task_run` with the HTTP path precisely so that "what happens
on the third failure" cannot differ between a laptop and production.
"""

import pytest
from django.test import override_settings

from core.models import TaskRun, TaskStatus
from core.tasks.enqueue import PayloadTooLarge, default_idempotency_key, enqueue
from core.tasks.registry import UnknownTask, task_handler

CALLS: list[dict] = []


@task_handler("test.enqueue.records", max_attempts=3)
def _records(payload):
    CALLS.append(payload)


@task_handler("test.enqueue.always-fails", max_attempts=2)
def _always_fails(payload):
    raise RuntimeError("nope")


@pytest.fixture(autouse=True)
def _clear_calls():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.mark.django_db
class TestEnqueue:
    def test_an_unknown_name_fails_at_enqueue_time(self):
        """A typo must die in the request that made it, not in the cloud."""
        with pytest.raises(UnknownTask):
            enqueue("test.enqueue.no-such-handler", {})

    def test_it_creates_a_run_and_executes_it_eagerly(self):
        run = enqueue("test.enqueue.records", {"value": 1})

        run.refresh_from_db()
        assert CALLS == [{"value": 1}]
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1
        assert run.max_attempts == 3

    def test_the_same_work_enqueued_twice_runs_once(self):
        first = enqueue("test.enqueue.records", {"value": 2})
        second = enqueue("test.enqueue.records", {"value": 2})

        assert first.pk == second.pk
        assert CALLS == [{"value": 2}]
        assert TaskRun.objects.filter(name="test.enqueue.records").count() == 1

    def test_a_caller_supplied_key_overrides_the_content_hash(self):
        """Lets a caller say 'this rule, this value' instead of 'these bytes'."""
        first = enqueue("test.enqueue.records", {"value": 3}, idempotency_key="rule:7")
        second = enqueue("test.enqueue.records", {"value": 4}, idempotency_key="rule:7")

        assert first.pk == second.pk
        assert CALLS == [{"value": 3}]

    def test_the_content_hash_is_insensitive_to_key_order(self):
        assert default_idempotency_key("n", {"a": 1, "b": 2}) == default_idempotency_key(
            "n", {"b": 2, "a": 1}
        )

    @override_settings(TASK_PAYLOAD_MAX_BYTES=64)
    def test_an_oversized_payload_is_refused_with_an_actionable_message(self):
        """Cloud Tasks caps a task at 1 MiB and the limit cannot be raised.

        Refusing here, with the reason, is what stops someone discovering it as
        a dispatch failure in production with no idea why.
        """
        with pytest.raises(PayloadTooLarge) as excinfo:
            enqueue("test.enqueue.records", {"blob": "x" * 500})

        assert "object storage" in str(excinfo.value)
        assert not TaskRun.objects.filter(name="test.enqueue.records").exists()

    def test_a_failing_handler_below_the_ceiling_stays_pending(self):
        run = enqueue("test.enqueue.always-fails", {"n": 1})

        run.refresh_from_db()
        assert run.status == TaskStatus.PENDING
        assert run.attempts == 1
        assert "RuntimeError: nope" in run.last_error

    def test_a_failing_handler_at_the_ceiling_is_dead_lettered(self):
        run = enqueue("test.enqueue.always-fails", {"n": 2})
        from core.tasks.execution import run_task_run

        run.refresh_from_db()
        run_task_run(run)  # second and final attempt

        run.refresh_from_db()
        assert run.status == TaskStatus.DEAD
        assert run.attempts == 2

    def test_a_handler_failure_never_reaches_the_caller(self):
        """Scheduling work must not be able to break the request that did it."""
        run = enqueue("test.enqueue.always-fails", {"n": 3})

        assert run.pk is not None

    def test_it_records_the_originating_request_id(self):
        from core.request_id import set_request_id

        set_request_id("ab" * 16)
        try:
            run = enqueue("test.enqueue.records", {"value": 5})
        finally:
            set_request_id(None)

        assert run.request_id == "ab" * 16

    def test_a_done_run_is_not_re_executed(self):
        from core.tasks.execution import run_task_run

        run = enqueue("test.enqueue.records", {"value": 6})
        run.refresh_from_db()

        assert run_task_run(run) == TaskStatus.DONE
        assert CALLS == [{"value": 6}]


class TestBackendSelection:
    @override_settings(CLOUD_TASKS_ENABLED=False)
    def test_it_is_eager_when_cloud_tasks_is_off(self):
        """The local answer to open question 4: a synchronous fallback, not an
        emulator. `CLOUD_TASKS_ENABLED=0` must be a complete setup."""
        from core.tasks.backends import EagerBackend, backend_for_settings

        assert isinstance(backend_for_settings(), EagerBackend)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_enqueue.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'core.tasks.enqueue'`

- [ ] **Step 3: Write the execution module**

Create `src/backend/core/tasks/execution.py`:

```python
"""Run one TaskRun and record what happened.

Shared by the eager backend and the HTTP dispatch view on purpose: "what
happens on the third failure" must not be able to differ between a laptop and
production. That divergence is how a retry bug survives until it is an
incident.
"""

import logging

import sentry_sdk

from core.models import TaskRun, TaskStatus
from core.tasks.registry import get_task

logger = logging.getLogger(__name__)

# Long enough to identify the failure, short enough that a pathological
# exception message cannot bloat the row.
MAX_ERROR_CHARS = 2000


def run_task_run(task_run: TaskRun) -> str:
    """Execute ``task_run`` once. Returns its status afterwards. Never raises.

    Returning rather than raising is what lets the caller choose the HTTP
    status without re-deriving the decision: PENDING means "retry me", DONE and
    DEAD both mean "stop".
    """
    if task_run.status == TaskStatus.DONE:
        # An at-least-once redelivery of work that already finished. Normal,
        # not an error, and the one case a second run must not duplicate.
        return TaskStatus.DONE

    definition = get_task(task_run.name)
    task_run.attempts += 1
    try:
        definition.handler(task_run.payload)
    except Exception as exc:
        task_run.last_error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        if task_run.attempts >= task_run.max_attempts:
            task_run.status = TaskStatus.DEAD
            # The one report that matters in this module: silently dropping a
            # user's work is the exact failure this epic exists to end.
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Task '%s' dead-lettered after %d attempts (task_run=%s): %s",
                task_run.name,
                task_run.attempts,
                task_run.id,
                task_run.last_error,
            )
        else:
            task_run.status = TaskStatus.PENDING
            logger.warning(
                "Task '%s' attempt %d/%d failed (task_run=%s): %s",
                task_run.name,
                task_run.attempts,
                task_run.max_attempts,
                task_run.id,
                task_run.last_error,
            )
    else:
        task_run.status = TaskStatus.DONE
        task_run.last_error = ""
    task_run.save(update_fields=["attempts", "status", "last_error", "updated_at"])
    return task_run.status
```

- [ ] **Step 4: Write the backends module**

Create `src/backend/core/tasks/backends.py`:

```python
"""Where an enqueued task actually goes.

Two backends, one contract. ``EagerBackend`` runs the handler in-process the
moment it is enqueued; it is what makes ``CLOUD_TASKS_ENABLED=0`` a complete
local setup rather than a degraded one — no emulator, no GCP credentials — and
it keeps the same bookkeeping as production because both backends go through
``run_task_run``.

The trade it makes is honest and worth stating: eagerly-run work happens
*inside* the request that scheduled it, so locally there is no instance relief
and no real retry. What is identical is the code path, the attempt accounting
and the dead-letter decision, which are the parts that are hard to get right.
"""

from django.conf import settings

from core.models import TaskRun
from core.tasks.execution import run_task_run


class EagerBackend:
    """Run it now, in this process."""

    def dispatch(self, task_run: TaskRun) -> None:
        run_task_run(task_run)


def backend_for_settings():
    """Pick a backend from configuration.

    The Cloud Tasks backend is imported lazily so that ``google-cloud-tasks``
    is never needed to import this module — a developer with no GCP setup runs
    the whole application without it.
    """
    if settings.CLOUD_TASKS_ENABLED:
        from core.tasks.cloud import CloudTasksBackend

        return CloudTasksBackend()
    return EagerBackend()
```

- [ ] **Step 5: Write the enqueue module**

Create `src/backend/core/tasks/enqueue.py`:

```python
"""The single way application code schedules deferred work.

One function, so that the payload ceiling, the idempotency key, the
request-ID capture and the backend choice are decided in exactly one place. A
second enqueue path is how one of those four silently stops applying.
"""

import hashlib
import json
import logging

from django.conf import settings

from core.models import TaskRun
from core.request_id import get_request_id
from core.tasks.backends import backend_for_settings
from core.tasks.registry import get_task

logger = logging.getLogger(__name__)


class PayloadTooLarge(ValueError):
    """The encoded payload exceeds what a Cloud Tasks task can carry."""


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()


def default_idempotency_key(name: str, payload: dict) -> str:
    """A stable key for "this exact work".

    Content-addressed deliberately: enqueuing identical work twice — a
    double-tapped button, a retried request — must produce one row, and a
    caller should not have to remember to ask for that.

    ``sort_keys`` matters. Two dicts that differ only in insertion order are
    the same work, and hashing their raw serialisations would say otherwise.
    """
    return f"{name}:{hashlib.sha256(_encode(payload)).hexdigest()}"


def enqueue(name: str, payload: dict, *, idempotency_key: str | None = None) -> TaskRun:
    """Schedule ``name`` to run with ``payload``. Returns the durable record.

    ``idempotency_key`` overrides the content hash when the caller has a better
    notion of sameness than "these exact bytes" — for example "this rule, at
    this value", which should re-run when the value changes and not otherwise.
    """
    definition = get_task(name)  # raises UnknownTask on a typo, here, now

    body = _encode(payload)
    if len(body) > settings.TASK_PAYLOAD_MAX_BYTES:
        raise PayloadTooLarge(
            f"Task '{name}' payload is {len(body)} bytes; the ceiling is "
            f"{settings.TASK_PAYLOAD_MAX_BYTES}. Cloud Tasks caps a task at 1 MiB "
            "and that is a fixed system limit — put the bytes in object storage "
            "and pass a reference instead (E12)."
        )

    key = idempotency_key or default_idempotency_key(name, payload)
    task_run, created = TaskRun.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "name": name,
            "payload": payload,
            "max_attempts": definition.max_attempts,
            # Captured at enqueue time rather than read at dispatch time: by the
            # time the task runs, the request that wanted it is long gone.
            "request_id": get_request_id() or "",
        },
    )
    if not created:
        logger.info("Task '%s' already enqueued as %s; not scheduling again.", name, task_run.pk)
        return task_run

    backend_for_settings().dispatch(task_run)
    return task_run
```

- [ ] **Step 6: Widen the package's public surface**

Modify `src/backend/core/tasks/__init__.py`:

```python
"""Deferred work: how it is scheduled, and how it comes back.

The public surface is deliberately two names. Everything else in this package
is internal, so that the payload ceiling, the idempotency key and the backend
choice cannot be bypassed by importing something one layer down.
"""

from core.tasks.enqueue import enqueue
from core.tasks.registry import task_handler

__all__ = ["enqueue", "task_handler"]
```

- [ ] **Step 7: Add the settings**

Append to `src/backend/config/settings.py`, immediately after the `MAX_CSV_UPLOAD_BYTES` / `DATA_UPLOAD_MAX_NUMBER_FILES` block:

```python
# Async work pipeline (E10, ADR-004).
#
# Off by default, and that default is the whole local story: with
# CLOUD_TASKS_ENABLED=0 the eager backend runs handlers in-process, so the
# application needs no GCP credentials and no emulator to be complete. This is
# the answer to E10 open question 4 — a synchronous fallback beat waiting for
# an emulator that does not exist.
CLOUD_TASKS_ENABLED = os.environ.get("CLOUD_TASKS_ENABLED", "0") == "1"
# Half of Cloud Tasks' fixed 1 MiB task ceiling, which cannot be raised
# (https://cloud.google.com/tasks/docs/quotas, "Maximum task size"). Only the
# TaskRun id crosses the wire, so this guards the ROW: a multi-megabyte
# JSONField on a pooled Supabase connection is its own problem, and refusing
# here — with a message naming object storage — is what stops someone
# discovering the limit as an unexplained dispatch failure. Receipt photos and
# voice notes are far over it by design; they wait for E12's GCS bucket.
TASK_PAYLOAD_MAX_BYTES = int(os.environ.get("TASK_PAYLOAD_MAX_BYTES", str(512 * 1024)))
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_enqueue.py -v`
Expected: 12 passed

- [ ] **Step 9: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 10: Commit**

```bash
git add src/backend/core/tasks/ src/backend/config/settings.py \
        src/backend/core/tests/test_task_enqueue.py
git commit -m "feat(tasks): one enqueue helper, an eager backend, a payload ceiling

The eager backend is the local answer to open question 4 — a synchronous
fallback, not an emulator — and it shares run_task_run with the HTTP path
so the third-failure behaviour cannot drift between laptop and production."
```

---

### Task 3: OIDC verification of inbound task requests

This service is deployed `--allow-unauthenticated` because it is a public web app, so Cloud Run will not check the token. Without this module, `/tasks/<name>/` is an unauthenticated RPC endpoint any stranger can drive.

**Files:**
- Create: `src/backend/core/tasks/auth.py`
- Modify: `src/backend/config/settings.py` (append to the E10 block from Task 2)
- Test: `src/backend/core/tests/test_task_auth.py`

**Interfaces:**
- Consumes: settings only.
- Produces:
  - `core.tasks.auth.rejection_reason(request) -> str | None` — `None` means the request is a genuine Cloud Tasks dispatch; a short reason string otherwise.
  - `core.tasks.auth.verify_id_token(token: str, audience: str) -> dict` — module-level name, replaced wholesale in tests.
  - `core.tasks.auth.BEARER_PREFIX = "Bearer "`.
  - Settings `CLOUD_TASKS_OIDC_SERVICE_ACCOUNT: str`, `CLOUD_TASKS_AUDIENCE: str`.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_task_auth.py`:

```python
"""The only thing between a stranger and the task handlers.

Cloud Run does not check the token for us — the service is deployed
--allow-unauthenticated because it is a public web app. Every one of these
tests is a way the door could be left open.
"""

from unittest import mock

import pytest
from django.test import RequestFactory, override_settings

from core.tasks import auth

SERVICE_ACCOUNT = "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"
AUDIENCE = "https://ledger.example.com"

CONFIGURED = override_settings(
    CLOUD_TASKS_OIDC_SERVICE_ACCOUNT=SERVICE_ACCOUNT,
    CLOUD_TASKS_AUDIENCE=AUDIENCE,
)


@pytest.fixture
def post():
    return RequestFactory().post("/tasks/test.name/")


def _with_token(request, token="a-token"):
    request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return request


@override_settings(CLOUD_TASKS_OIDC_SERVICE_ACCOUNT="", CLOUD_TASKS_AUDIENCE="")
def test_it_fails_closed_with_no_service_account_configured(post):
    """A missing setting must mean 'refuse everything', never 'allow everything'."""
    assert auth.rejection_reason(_with_token(post)) is not None


@CONFIGURED
def test_a_request_with_no_authorization_header_is_refused(post):
    assert auth.rejection_reason(post) == "missing bearer token"


@CONFIGURED
def test_a_non_bearer_authorization_header_is_refused(post):
    post.META["HTTP_AUTHORIZATION"] = "Basic dXNlcjpwYXNz"

    assert auth.rejection_reason(post) == "missing bearer token"


@CONFIGURED
def test_an_empty_bearer_token_is_refused(post):
    post.META["HTTP_AUTHORIZATION"] = "Bearer    "

    assert auth.rejection_reason(post) == "empty bearer token"


@CONFIGURED
def test_a_token_google_rejects_is_refused(post):
    with mock.patch.object(auth, "verify_id_token", side_effect=ValueError("bad signature")):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "token rejected: ValueError"


@CONFIGURED
def test_a_token_for_another_service_account_is_refused(post):
    claims = {"email": "someone-else@example.com", "email_verified": True}

    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "wrong service account"


@CONFIGURED
def test_an_unverified_service_account_email_is_refused(post):
    claims = {"email": SERVICE_ACCOUNT, "email_verified": False}

    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "unverified service account email"


@CONFIGURED
def test_a_genuine_cloud_tasks_dispatch_is_accepted(post):
    claims = {"email": SERVICE_ACCOUNT, "email_verified": True}

    with mock.patch.object(auth, "verify_id_token", return_value=claims) as verifier:
        reason = auth.rejection_reason(_with_token(post, "the-real-token"))

    assert reason is None
    verifier.assert_called_once_with("the-real-token", AUDIENCE)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_auth.py -v`
Expected: collection error — `ImportError: cannot import name 'auth' from 'core.tasks'`

- [ ] **Step 3: Write the auth module**

Create `src/backend/core/tasks/auth.py`:

```python
"""Prove an inbound /tasks/ request really came from Cloud Tasks.

This service runs with ``--allow-unauthenticated`` because it is a public web
app, so Cloud Run will not verify the token for us — the check has to happen
here. Without it, ``/tasks/<name>/`` is an unauthenticated RPC endpoint that
any stranger can drive, with the application's own database behind it.

Fails closed: with no service account configured, every request is refused. An
endpoint that silently accepts everything when a setting is missing is worse
than one that is switched off, because nothing about it looks wrong.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

BEARER_PREFIX = "Bearer "


def _google_verifier(token: str, audience: str) -> dict:
    """The real check. Isolated so no test needs a network round trip.

    Imported inside the function so that ``google-auth`` is not required to
    import this module — a developer with CLOUD_TASKS_ENABLED=0 never reaches
    this line.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)


# Module-level so a test can replace it. Replacing the object rather than
# wrapping it is what makes the patch total — the same trick `conftest.py`
# uses for `assistant.services.embedding.async_client`.
verify_id_token = _google_verifier


def rejection_reason(request) -> str | None:
    """``None`` when the request is a genuine Cloud Tasks dispatch.

    Returns a short reason otherwise. The caller logs it and never returns it
    to the client: telling an attacker *which* check failed is free help.
    """
    expected = settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT
    if not expected:
        return "no service account configured"

    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return "missing bearer token"

    token = header[len(BEARER_PREFIX) :].strip()
    if not token:
        return "empty bearer token"

    try:
        claims = verify_id_token(token, settings.CLOUD_TASKS_AUDIENCE)
    except Exception as exc:
        # Broad on purpose: google-auth raises several unrelated exception
        # types for "this token is not good", and every one of them means the
        # same thing here.
        return f"token rejected: {type(exc).__name__}"

    if claims.get("email") != expected:
        return "wrong service account"
    # Checked separately from the address: an unverified email claim means
    # Google is not vouching for the identity, which makes the address match
    # worth nothing.
    if claims.get("email_verified") is not True:
        return "unverified service account email"
    return None
```

- [ ] **Step 4: Add the settings**

Append to the E10 block in `src/backend/config/settings.py`:

```python
# The identity Cloud Tasks mints its OIDC token as. `core.tasks.auth` refuses
# every task request when this is unset, which is the correct default on a
# developer machine.
CLOUD_TASKS_OIDC_SERVICE_ACCOUNT = os.environ.get("CLOUD_TASKS_OIDC_SERVICE_ACCOUNT", "")
# The `aud` claim the token is minted for. Must equal the audience configured
# on the task itself — this service's public base URL. A mismatch here is the
# most common cause of a 403 on a task that looks correctly configured.
CLOUD_TASKS_AUDIENCE = os.environ.get("CLOUD_TASKS_AUDIENCE", "")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_auth.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add src/backend/core/tasks/auth.py src/backend/config/settings.py \
        src/backend/core/tests/test_task_auth.py
git commit -m "feat(tasks): verify the OIDC token on inbound task requests

The service is deployed --allow-unauthenticated, so Cloud Run does not
check the token. Fails closed when no service account is configured."
```

---

### Task 4: the dispatch view, idempotency, and the dead-letter path

The one HTTP door deferred work comes back through. The response code *is* the protocol: 5xx means "retry me", 2xx means "stop".

**Files:**
- Create: `src/backend/core/tasks/views.py`
- Create: `src/backend/core/tasks/urls.py`
- Modify: `src/backend/config/urls.py:15` (add before the `finances` catch-all)
- Test: `src/backend/core/tests/test_task_views.py`

**Interfaces:**
- Consumes: `core.tasks.auth.rejection_reason`, `core.tasks.execution.run_task_run`, `core.tasks.registry.get_task`, `core.tasks.registry.UnknownTask`, `core.models.TaskRun`, `core.models.TaskStatus`.
- Produces:
  - `core.tasks.views.task_dispatch_view(request, name)` — POST-only, CSRF-exempt.
  - URL name `tasks:dispatch`, path `/tasks/<str:name>/`.
  - Wire format: request body `{"task_run_id": "<uuid>"}`; response body `{"status": "<TaskStatus value>"}` or `{"error": "<slug>"}`.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/core/tests/test_task_views.py`:

```python
"""The dispatch view, where at-least-once delivery meets a real database.

The response code is the whole protocol between this app and Cloud Tasks, so
each test here is really asserting "and therefore Cloud Tasks will / will not
try again".
"""

import json
import uuid
from unittest import mock

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from core.models import TaskRun, TaskStatus
from core.tasks import auth
from core.tasks.registry import task_handler

SERVICE_ACCOUNT = "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"
AUDIENCE = "https://ledger.example.com"

CONFIGURED = override_settings(
    CLOUD_TASKS_OIDC_SERVICE_ACCOUNT=SERVICE_ACCOUNT,
    CLOUD_TASKS_AUDIENCE=AUDIENCE,
)

CALLS: list[dict] = []
FAILURES: list[dict] = []


@task_handler("test.view.records", max_attempts=3)
def _records(payload):
    CALLS.append(payload)


@task_handler("test.view.always-fails", max_attempts=2)
def _always_fails(payload):
    FAILURES.append(payload)
    raise RuntimeError("handler exploded")


@pytest.fixture(autouse=True)
def _clear():
    CALLS.clear()
    FAILURES.clear()
    yield
    CALLS.clear()
    FAILURES.clear()


@pytest.fixture
def accepted():
    """Make the OIDC check pass, so a test can be about anything else."""
    claims = {"email": SERVICE_ACCOUNT, "email_verified": True}
    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        yield


def _post(name, task_run_id):
    return Client().post(
        reverse("tasks:dispatch", args=[name]),
        data=json.dumps({"task_run_id": str(task_run_id)}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer a-token",
    )


def _run(name="test.view.records", payload=None, max_attempts=3):
    return TaskRun.objects.create(
        name=name,
        idempotency_key=f"{name}:{uuid.uuid4()}",
        payload=payload if payload is not None else {},
        max_attempts=max_attempts,
    )


@pytest.mark.django_db
@CONFIGURED
class TestAuthentication:
    def test_a_request_with_no_token_is_refused(self):
        """The DoD box: handlers reject requests not carrying a valid OIDC token."""
        run = _run()

        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": str(run.pk)}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert CALLS == []

    def test_a_request_with_a_bad_token_is_refused(self):
        run = _run()

        with mock.patch.object(auth, "verify_id_token", side_effect=ValueError("bad")):
            response = _post("test.view.records", run.pk)

        assert response.status_code == 403
        assert CALLS == []

    def test_the_reason_is_not_disclosed_to_the_caller(self):
        run = _run()

        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": str(run.pk)}),
            content_type="application/json",
        )

        assert response.json() == {"error": "forbidden"}


@pytest.mark.django_db
@CONFIGURED
class TestDispatch:
    def test_get_is_not_allowed(self, accepted):
        response = Client().get(reverse("tasks:dispatch", args=["test.view.records"]))

        assert response.status_code == 405

    def test_an_unregistered_name_is_a_404(self, accepted):
        """404 rather than 500: an unknown name will never become known by
        retrying, and Cloud Tasks stops on a 4xx."""
        run = _run()

        response = _post("test.view.no-such-handler", run.pk)

        assert response.status_code == 404

    def test_a_malformed_body_is_a_400(self, accepted):
        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data="not json",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer a-token",
        )

        assert response.status_code == 400

    def test_a_task_run_id_that_is_not_a_uuid_is_a_400(self, accepted):
        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": "banana"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer a-token",
        )

        assert response.status_code == 400

    def test_an_unknown_task_run_is_a_404(self, accepted):
        response = _post("test.view.records", uuid.uuid4())

        assert response.status_code == 404

    def test_a_valid_dispatch_runs_the_handler_and_returns_200(self, accepted):
        run = _run(payload={"value": 1})

        response = _post("test.view.records", run.pk)

        run.refresh_from_db()
        assert response.status_code == 200
        assert response.json() == {"status": "done"}
        assert CALLS == [{"value": 1}]
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1


@pytest.mark.django_db
@CONFIGURED
class TestIdempotency:
    def test_the_same_task_delivered_twice_produces_one_result(self, accepted):
        """The DoD box: a handler invoked twice with the same payload produces
        one result. Cloud Tasks delivers at least once, so this is the normal
        case, not the exceptional one."""
        run = _run(payload={"value": 2})

        first = _post("test.view.records", run.pk)
        second = _post("test.view.records", run.pk)

        run.refresh_from_db()
        assert first.status_code == 200
        assert second.status_code == 200
        assert CALLS == [{"value": 2}]
        assert run.attempts == 1

    def test_a_run_belonging_to_another_name_is_a_404(self, accepted):
        """The name in the URL and the name on the row must agree, or a
        mis-routed task would run the wrong handler's code on this payload."""
        run = _run(name="test.view.always-fails")

        response = _post("test.view.records", run.pk)

        assert response.status_code == 404
        assert FAILURES == []


@pytest.mark.django_db
@CONFIGURED
class TestRetryAndDeadLetter:
    def test_a_failure_below_the_ceiling_asks_for_a_retry(self, accepted):
        run = _run(name="test.view.always-fails", max_attempts=2)

        response = _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert response.status_code == 500
        assert run.status == TaskStatus.PENDING
        assert run.attempts == 1

    def test_the_final_failure_dead_letters_and_stops_the_retries(self, accepted):
        """The DoD box: a deliberately failed task lands in the dead-letter
        path and is visible.

        200 on the last failure is deliberate. The app owns the attempt
        ceiling; letting Cloud Tasks keep retrying past it would spend money
        re-running work we have already recorded as given up on.
        """
        run = _run(name="test.view.always-fails", max_attempts=2)

        _post("test.view.always-fails", run.pk)
        response = _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert response.status_code == 200
        assert response.json() == {"status": "dead"}
        assert run.status == TaskStatus.DEAD
        assert run.attempts == 2
        assert "RuntimeError: handler exploded" in run.last_error
        assert TaskRun.objects.filter(status=TaskStatus.DEAD).count() == 1

    def test_a_dead_lettered_task_is_not_run_again(self, accepted):
        run = _run(name="test.view.always-fails", max_attempts=2)

        _post("test.view.always-fails", run.pk)
        _post("test.view.always-fails", run.pk)
        _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert run.attempts == 2
        assert len(FAILURES) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_views.py -v`
Expected: FAIL with `django.urls.exceptions.NoReverseMatch: 'tasks' is not a registered namespace`

- [ ] **Step 3: Write the view**

Create `src/backend/core/tasks/views.py`:

```python
"""The one HTTP door deferred work comes back through.

Cloud Tasks delivers a task by POSTing to a URL, so every handler shares this
view and the name in the path selects which. The response code is the whole
protocol: 5xx means "retry me", 2xx means "stop".

That is why a dead-lettered task answers 200. The application owns the attempt
ceiling — Cloud Tasks has no dead-letter queue, so if the queue kept retrying
past our own limit it would spend money re-running work we have already
recorded as abandoned, and the TaskRun row would say DEAD while the queue said
otherwise.
"""

import json
import logging
import uuid

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import TaskRun, TaskStatus
from core.tasks.auth import rejection_reason
from core.tasks.execution import run_task_run
from core.tasks.registry import UnknownTask, get_task

logger = logging.getLogger(__name__)


def _task_run_id(request) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(json.loads(request.body)["task_run_id"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None


# CSRF-exempt because Cloud Tasks is not a browser and carries no cookie or
# token. The OIDC check below is the authentication, and it is strictly
# stronger than CSRF for this caller.
@csrf_exempt
@require_POST
def task_dispatch_view(request, name):
    reason = rejection_reason(request)
    if reason is not None:
        # Logged, not returned: naming the failed check would tell an attacker
        # exactly what to fix.
        logger.warning("Refused /tasks/%s/: %s", name, reason)
        return JsonResponse({"error": "forbidden"}, status=403)

    try:
        get_task(name)
    except UnknownTask:
        logger.error("Dispatch for unregistered task '%s'.", name)
        return JsonResponse({"error": "unknown task"}, status=404)

    task_run_id = _task_run_id(request)
    if task_run_id is None:
        return JsonResponse({"error": "invalid body"}, status=400)

    # Checked before the lock so that "no such row" and "someone else holds the
    # row" stay distinguishable — they need opposite answers.
    if not TaskRun.objects.filter(pk=task_run_id, name=name).exists():
        logger.error("Dispatch for unknown task_run %s (task '%s').", task_run_id, name)
        return JsonResponse({"error": "unknown task_run"}, status=404)

    with transaction.atomic():
        task_run = (
            TaskRun.objects.select_for_update(skip_locked=True)
            .filter(pk=task_run_id, name=name)
            .first()
        )
        if task_run is None:
            # Another dispatch of the same task holds the row. At-least-once
            # delivery makes this normal rather than exceptional, and it is
            # precisely the case a second run must not duplicate. 200, because
            # the work is already being done — retrying would just race again.
            logger.info("Concurrent delivery of task_run %s ignored.", task_run_id)
            return HttpResponse(status=200)
        # The row lock is held for the duration of the handler. That bounds how
        # long a handler may run: it must be short. Long, media-shaped work
        # belongs behind object storage and its own job state (E12), which is
        # the other reason this epic does not move it.
        status = run_task_run(task_run)

    if status == TaskStatus.PENDING:
        return JsonResponse({"status": status}, status=500)
    return JsonResponse({"status": status}, status=200)
```

- [ ] **Step 4: Write the URL conf**

Create `src/backend/core/tasks/urls.py`:

```python
from django.urls import path

from core.tasks.views import task_dispatch_view

app_name = "tasks"

urlpatterns = [
    # The task name is a path segment because that is what Cloud Tasks routes
    # on: one queue can drive many handlers by URL alone, with no per-handler
    # queue to provision.
    path("<str:name>/", task_dispatch_view, name="dispatch"),
]
```

- [ ] **Step 5: Register the URLs**

Modify `src/backend/config/urls.py` — add this entry immediately after the `path("healthz/", ...)` line, so it is well ahead of the `path("", include("finances.urls"))` catch-all:

```python
    # Cloud Tasks dispatch (E10). Public by necessity — the service is deployed
    # --allow-unauthenticated — so `core.tasks.auth` verifies the OIDC token
    # in-app on every request.
    path("tasks/", include("core.tasks.urls")),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_views.py -v`
Expected: 15 passed

- [ ] **Step 7: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add src/backend/core/tasks/views.py src/backend/core/tasks/urls.py \
        src/backend/config/urls.py src/backend/core/tests/test_task_views.py
git commit -m "feat(tasks): the dispatch view, with idempotency and dead-lettering

The response code is the protocol: 5xx asks Cloud Tasks to retry, 2xx
stops it. A dead-lettered task answers 200 because the app owns the
attempt ceiling — Cloud Tasks has no dead-letter queue of its own."
```

---

### Task 5: the Cloud Tasks backend and request-ID propagation

Real enqueuing, plus the one line that makes S10-5's traceability box fall out of machinery that already exists.

**Files:**
- Create: `src/backend/core/tasks/cloud.py`
- Modify: `src/backend/config/settings.py` (append to the E10 block)
- Modify: `pyproject.toml:7-25` (dependencies)
- Test: `src/backend/core/tests/test_task_cloud.py`

**Interfaces:**
- Consumes: `core.middleware.REQUEST_ID_HEADER`, `core.models.TaskRun`, settings.
- Produces:
  - `core.tasks.cloud.CloudTasksBackend(client=None)` — has `dispatch(task_run: TaskRun) -> None` and a lazily built `.client`.
  - Settings `CLOUD_TASKS_PROJECT`, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE`, `CLOUD_TASKS_TARGET_BASE_URL`.
  - Dependency `google-cloud-tasks>=2.18`.

- [ ] **Step 1: Add the dependency**

Modify `pyproject.toml`, adding to the `dependencies` list after `"logfire>=3.0",`:

```toml
    # E10 / ADR-004. Brings `google-auth` transitively, which core.tasks.auth
    # uses to verify the inbound OIDC token.
    "google-cloud-tasks>=2.18",
```

Run: `uv sync`
Expected: `google-cloud-tasks` and `google-auth` resolve and install.

- [ ] **Step 2: Write the failing tests**

Create `src/backend/core/tests/test_task_cloud.py`:

```python
"""The shape of the request we hand to Cloud Tasks.

Asserted against an injected client rather than the real API: this is about
what we ask for, and getting the OIDC audience or the target URL wrong is a
403 in production that no amount of local running would surface.
"""

import json
import uuid
from unittest import mock

import pytest
from django.test import override_settings

from core.models import TaskRun
from core.tasks.cloud import CloudTasksBackend

CLOUD = override_settings(
    CLOUD_TASKS_ENABLED=True,
    CLOUD_TASKS_PROJECT="expense-tracker-482807",
    CLOUD_TASKS_LOCATION="southamerica-east1",
    CLOUD_TASKS_QUEUE="ledger-default",
    CLOUD_TASKS_TARGET_BASE_URL="https://ledger.example.com/",
    CLOUD_TASKS_AUDIENCE="https://ledger.example.com",
    CLOUD_TASKS_OIDC_SERVICE_ACCOUNT="ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com",
)


@pytest.fixture
def fake_client():
    client = mock.Mock()
    client.queue_path.side_effect = lambda p, loc, q: f"projects/{p}/locations/{loc}/queues/{q}"
    return client


def _run(**extra):
    return TaskRun(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        name="assistant.embed_memory_rule",
        idempotency_key="k",
        payload={"rule_id": "abc"},
        max_attempts=4,
        **extra,
    )


def _sent_task(fake_client):
    return fake_client.create_task.call_args.args[0].task


@CLOUD
class TestCloudTasksBackend:
    def test_it_targets_the_handler_url_for_the_task_name(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        http = _sent_task(fake_client).http_request
        assert http.url == "https://ledger.example.com/tasks/assistant.embed_memory_rule/"

    def test_it_sends_only_the_task_run_id(self, fake_client):
        """The payload lives on the row. Keeping the wire format to one id is
        what makes the fixed 1 MiB task ceiling a non-issue for transport."""
        CloudTasksBackend(client=fake_client).dispatch(_run())

        body = json.loads(_sent_task(fake_client).http_request.body)
        assert body == {"task_run_id": "11111111-2222-3333-4444-555555555555"}

    def test_it_attaches_an_oidc_token_for_the_configured_service_account(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        token = _sent_task(fake_client).http_request.oidc_token
        assert token.service_account_email == (
            "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"
        )
        assert token.audience == "https://ledger.example.com"

    def test_it_forwards_the_originating_request_id(self, fake_client):
        """The DoD box: a task execution's trace links back to its originating
        request ID. No new plumbing — `request_id_middleware` already adopts a
        well-formed inbound X-Request-ID, so the task's own log lines inherit
        the value under one Cloud Logging filter."""
        CloudTasksBackend(client=fake_client).dispatch(_run(request_id="ab" * 16))

        headers = _sent_task(fake_client).http_request.headers
        assert headers["X-Request-ID"] == "ab" * 16

    def test_it_omits_the_header_when_there_was_no_request(self, fake_client):
        """Work scheduled from a management command has no originating request,
        and an empty header would be adopted as garbage rather than ignored."""
        CloudTasksBackend(client=fake_client).dispatch(_run(request_id=""))

        assert "X-Request-ID" not in _sent_task(fake_client).http_request.headers

    def test_it_enqueues_onto_the_configured_queue(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        request = fake_client.create_task.call_args.args[0]
        assert request.parent == (
            "projects/expense-tracker-482807/locations/southamerica-east1/queues/ledger-default"
        )


@CLOUD
def test_backend_for_settings_picks_cloud_tasks_when_enabled():
    from core.tasks.backends import backend_for_settings

    assert isinstance(backend_for_settings(), CloudTasksBackend)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_cloud.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'core.tasks.cloud'`

- [ ] **Step 4: Write the Cloud Tasks backend**

Create `src/backend/core/tasks/cloud.py`:

```python
"""Hand a TaskRun to Cloud Tasks.

Only the row's *id* travels in the body. The payload already lives on the
TaskRun, so the wire format stays tiny no matter what the work is, and the
fixed 1 MiB task ceiling stops being something every caller has to reason
about. ``enqueue`` still refuses an oversized payload, because the row is not
free either.
"""

import json

from django.conf import settings

from core.middleware import REQUEST_ID_HEADER
from core.models import TaskRun


class CloudTasksBackend:
    def __init__(self, client=None):
        # Injectable so a test can assert the request shape without
        # credentials, a network, or a GCP project.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google.cloud import tasks_v2

            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def dispatch(self, task_run: TaskRun) -> None:
        from google.cloud import tasks_v2

        base = settings.CLOUD_TASKS_TARGET_BASE_URL.rstrip("/")
        url = f"{base}/tasks/{task_run.name}/"

        headers = {"Content-Type": "application/json"}
        # The originating request's ID, forwarded so the task's own log lines
        # carry it (S10-5). `request_id_middleware` adopts a well-formed
        # inbound value via `core.request_id.sanitise_inbound`, so no new
        # plumbing is needed — and both are 32 hex chars, which is exactly what
        # that function accepts. Omitted when empty: an empty header would be
        # replaced by a fresh ID, silently breaking the link it exists to make.
        if task_run.request_id:
            headers[REQUEST_ID_HEADER] = task_run.request_id

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=url,
                headers=headers,
                body=json.dumps({"task_run_id": str(task_run.id)}).encode(),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT,
                    # Must match CLOUD_TASKS_AUDIENCE, which `core.tasks.auth`
                    # verifies the token against. A mismatch is a 403 that
                    # looks like a configuration problem somewhere else.
                    audience=settings.CLOUD_TASKS_AUDIENCE,
                ),
            ),
        )
        self.client.create_task(
            tasks_v2.CreateTaskRequest(
                parent=self.client.queue_path(
                    settings.CLOUD_TASKS_PROJECT,
                    settings.CLOUD_TASKS_LOCATION,
                    settings.CLOUD_TASKS_QUEUE,
                ),
                task=task,
            )
        )
```

- [ ] **Step 5: Add the remaining settings**

Append to the E10 block in `src/backend/config/settings.py`:

```python
CLOUD_TASKS_PROJECT = os.environ.get("CLOUD_TASKS_PROJECT", "")
# The queue must live in the same region as the service, or every dispatch
# pays a cross-region hop it does not need.
CLOUD_TASKS_LOCATION = os.environ.get("CLOUD_TASKS_LOCATION", "southamerica-east1")
CLOUD_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE", "ledger-default")
# This service's public base URL. Cloud Tasks calls back in over the internet,
# so this is a real host name, not a loopback address.
CLOUD_TASKS_TARGET_BASE_URL = os.environ.get("CLOUD_TASKS_TARGET_BASE_URL", "")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_cloud.py -v`
Expected: 7 passed

- [ ] **Step 7: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/backend/core/tasks/cloud.py \
        src/backend/config/settings.py src/backend/core/tests/test_task_cloud.py
git commit -m "feat(tasks): the Cloud Tasks backend, carrying the request ID

Only the TaskRun id crosses the wire. The originating request ID rides
as X-Request-ID, which request_id_middleware already adopts — so one
Cloud Logging filter finds the request and the task it spawned."
```

---

### Task 6: memory-rule embeddings, generated off the request

The rails' first real workload, and the fix for finding F3: memory rules have never had embeddings, so semantic recall has been searching an empty table.

**Files:**
- Create: `src/backend/assistant/tasks.py`
- Modify: `src/backend/assistant/agents/tools.py:1259-1279` (`create_memory_rule`)
- Test: `src/backend/assistant/tests/test_memory_embedding_task.py`

**Interfaces:**
- Consumes: `core.tasks.task_handler`, `core.tasks.enqueue`, `assistant.services.embedding.get_embedding`, `assistant.models.MemoryRule`, `assistant.models.MemoryEmbedding`.
- Produces:
  - `assistant.tasks.EMBED_MEMORY_RULE = "assistant.embed_memory_rule"`.
  - `assistant.tasks.embed_memory_rule(payload: dict) -> None` — payload `{"rule_id": "<uuid str>"}`. Raises on provider failure.
  - `assistant.tasks.embedding_id_for(rule_id) -> uuid.UUID`.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_memory_embedding_task.py`:

```python
"""Memory rules become semantically searchable — off the request.

Finding F3 behind this epic: `create_memory_rule` never generated an embedding,
so `MemoryEmbedding` was empty outside the perf seed and the semantic fallback
in `lookup_memory_async` searched nothing. These tests pin both halves: the
vector now gets generated, and the feature still works while it has not.
"""

from unittest import mock

import pytest
from asgiref.sync import sync_to_async

from assistant.models import MemoryEmbedding, MemoryRule
from assistant.tasks import EMBED_MEMORY_RULE, embed_memory_rule, embedding_id_for
from core.models import TaskRun, TaskStatus

VECTOR = [0.05] * 1536


@pytest.fixture
def fake_embedding():
    """Patch where the handler looks it up, not where it is defined.

    `embed_memory_rule` imports `get_embedding` inside the function body
    precisely so this patch is total — and so the module keeps importing
    cleanly under the autouse `no_real_embedding_calls` guard.
    """

    async def _embed(text, *, scope=None):
        return VECTOR

    with mock.patch("assistant.services.embedding.get_embedding", side_effect=_embed) as patched:
        yield patched


@pytest.mark.django_db
class TestCreateMemoryRuleEnqueues:
    def test_creating_a_rule_generates_its_embedding(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        rule = MemoryRule.objects.get(trigger="cosmos")
        embedding = MemoryEmbedding.objects.get(id=embedding_id_for(rule.pk))
        assert embedding.household_id == scope.household.pk
        assert embedding.metadata["rule_id"] == str(rule.pk)
        assert embedding.metadata["field"] == "category"
        assert embedding.metadata["value"] == "Alimentação"
        assert "cosmos" in embedding.text

    def test_the_task_run_is_recorded_as_done(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        run = TaskRun.objects.get(name=EMBED_MEMORY_RULE)
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1

    def test_re_saving_the_same_rule_and_value_does_not_re_embed(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")
        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        assert TaskRun.objects.filter(name=EMBED_MEMORY_RULE).count() == 1
        assert fake_embedding.call_count == 1

    def test_changing_the_value_re_embeds_into_the_same_row(self, scope, fake_embedding):
        """The key is 'this rule, at this value'. A correction must produce a
        fresh vector, and must not leave the stale one behind."""
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")
        create_memory_rule(scope, "cosmos", "category", "Mercado")

        rule = MemoryRule.objects.get(trigger="cosmos")
        assert TaskRun.objects.filter(name=EMBED_MEMORY_RULE).count() == 2
        assert MemoryEmbedding.objects.count() == 1
        assert MemoryEmbedding.objects.get(id=embedding_id_for(rule.pk)).metadata["value"] == (
            "Mercado"
        )

    def test_an_unavailable_queue_does_not_break_teaching_a_rule(self, scope, fake_embedding):
        """A rule the user just taught us must survive an outage in the thing
        that indexes it. The substring matcher works either way."""
        from assistant.agents import tools

        with mock.patch.object(tools, "enqueue", side_effect=RuntimeError("queue is down")):
            result = tools.create_memory_rule(scope, "cosmos", "category", "Alimentação")

        assert MemoryRule.objects.filter(trigger="cosmos").exists()
        assert "criada" in result

    def test_an_invalid_field_still_enqueues_nothing(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        result = create_memory_rule(scope, "cosmos", "nao_existe", "x")

        assert "inválido" in result
        assert not TaskRun.objects.exists()


@pytest.mark.django_db
class TestHandler:
    def test_running_it_twice_leaves_one_embedding(self, scope, household, fake_embedding):
        """Cloud Tasks delivers at least once. The embedding id is derived from
        the rule id, so exactly-one-row is a property of the id rather than a
        convention someone has to keep."""
        rule = MemoryRule.objects.create(
            household=household, trigger="cosmos", field="category", value="Alimentação"
        )

        embed_memory_rule({"rule_id": str(rule.pk)})
        embed_memory_rule({"rule_id": str(rule.pk)})

        assert MemoryEmbedding.objects.count() == 1

    def test_a_rule_deleted_before_dispatch_is_not_an_error(self, db, fake_embedding):
        """Retrying will not bring it back, so this must not look like failure."""
        import uuid

        embed_memory_rule({"rule_id": str(uuid.uuid4())})

        assert MemoryEmbedding.objects.count() == 0

    def test_a_provider_failure_raises_so_the_rails_retry(self, scope, household):
        """Raising is the signal that earns a retry. Returning quietly would
        leave a rule permanently unsearchable with nothing in the tracker —
        the exact failure S10-4 names."""
        rule = MemoryRule.objects.create(
            household=household, trigger="cosmos", field="category", value="Alimentação"
        )

        async def _none(text, *, scope=None):
            return None

        with mock.patch("assistant.services.embedding.get_embedding", side_effect=_none):
            with pytest.raises(RuntimeError):
                embed_memory_rule({"rule_id": str(rule.pk)})


@pytest.mark.django_db
def test_a_rule_with_no_embedding_yet_is_still_matched_by_substring(scope, household):
    """The DoD box: a memory rule created while its embedding is pending is
    still matched by the substring path — so the feature degrades to
    'exact trigger only' rather than breaking."""
    from assistant.agents.tools import lookup_memory

    MemoryRule.objects.create(
        household=household, trigger="cosmos", field="category", value="Alimentação"
    )

    result = lookup_memory(scope, "comprei no cosmos hoje")

    assert MemoryEmbedding.objects.count() == 0
    assert "Alimentação" in result


@pytest.mark.anyio
@pytest.mark.django_db(transaction=True)
async def test_it_works_through_the_agent_s_sync_to_async_wrapper(fake_embedding):
    """`create_memory_rule` reaches the handler from inside `sync_to_async`
    (assistant/agents/assistant.py:369), and the handler calls back into async
    to reach the embeddings API. asgiref supports that nesting, but it is
    exactly the kind of thing that only breaks in the real call path.

    The user and household are built inside the test rather than taken from the
    `scope` fixture: those fixtures depend on pytest-django's `db`, which wraps
    the test in an atomic block on the main connection — and `sync_to_async`
    runs in a worker thread with a connection of its own that would not see any
    of it. `transaction=True` is what makes the rows visible across threads, and
    it cannot be combined with a fixture that requested `db`.
    """
    from model_bakery import baker

    from accounts.resolution import household_for_user
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import create_memory_rule

    def _build_scope():
        user = baker.make("core.CustomUser", username="vagner", email="vagner@example.com")
        return AgentScope(household=household_for_user(user), user=user)

    scope = await sync_to_async(_build_scope)()

    await sync_to_async(create_memory_rule)(scope, "cosmos", "category", "Alimentação")

    count = await sync_to_async(MemoryEmbedding.objects.count)()
    assert count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_memory_embedding_task.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'assistant.tasks'`

- [ ] **Step 3: Write the handler**

Create `src/backend/assistant/tasks.py`:

```python
"""Deferred work the assistant schedules.

Discovered by ``core.tasks.registry.autodiscover()`` at startup, so the module
name is part of the contract: this file must stay ``assistant/tasks.py``.
"""

import logging
import uuid

from asgiref.sync import async_to_sync

from core.tasks import task_handler

logger = logging.getLogger(__name__)

EMBED_MEMORY_RULE = "assistant.embed_memory_rule"

# A fixed namespace, so `embedding_id_for` is stable across processes and
# deploys. Any UUID would do; this one is arbitrary and must never change,
# because changing it orphans every embedding already written.
EMBEDDING_NAMESPACE = uuid.UUID("6f8a1c02-3c2e-5f7a-9b4d-2a1f0e5c7d31")


def embedding_id_for(rule_id) -> uuid.UUID:
    """The one embedding row a rule is allowed to have.

    Derived from the rule id rather than stored alongside it: that makes
    exactly-one-row a property of the identifier itself, which cannot drift the
    way a nullable foreign key plus a uniqueness convention can. It is also
    what makes a redelivered task an update instead of a duplicate.
    """
    return uuid.uuid5(EMBEDDING_NAMESPACE, str(rule_id))


@task_handler(EMBED_MEMORY_RULE, max_attempts=4)
def embed_memory_rule(payload: dict) -> None:
    """Give a memory rule a vector, so semantic search can reach it.

    Raises on provider failure — that is the signal that earns a retry.
    Returning quietly would leave the rule permanently unsearchable with
    nothing in the error tracker, which is the exact failure S10-4 names.

    The imports are function-local so that this module stays importable at
    startup (``autodiscover`` runs inside ``AppConfig.ready``) and so that a
    test patching ``assistant.services.embedding.get_embedding`` is patching
    the object this function will actually reach.
    """
    from assistant.models import MemoryEmbedding, MemoryRule
    from assistant.services import embedding as embedding_service

    rule = MemoryRule.objects.filter(pk=payload["rule_id"]).first()
    if rule is None:
        # Deleted between enqueue and dispatch. Retrying will not bring it
        # back, so this is a completed task, not a failed one.
        logger.info("Memory rule %s is gone; skipping its embedding.", payload["rule_id"])
        return

    # The trigger alone is what the substring matcher already covers, so the
    # indexed text includes the conclusion too — that is what makes "onde eu
    # compro comida" reach a rule triggered by "cosmos".
    text = f"{rule.trigger} → {rule.field}={rule.value}"
    vector = async_to_sync(embedding_service.get_embedding)(text)
    if vector is None:
        raise RuntimeError(f"Embedding provider returned nothing for memory rule {rule.pk}.")

    MemoryEmbedding.objects.update_or_create(
        id=embedding_id_for(rule.pk),
        defaults={
            "household": rule.household,
            "text": text,
            "embedding": vector,
            # `lookup_memory_async` reads `field` and `value` straight off this
            # dict to render the match, so the shape is load-bearing.
            "metadata": {
                "rule_id": str(rule.pk),
                "field": rule.field,
                "value": rule.value,
            },
        },
    )
```

- [ ] **Step 4: Make `create_memory_rule` enqueue**

Modify `src/backend/assistant/agents/tools.py`. Add to the imports at the top of the file, next to the existing `from assistant.services.embedding import get_embedding`:

```python
import sentry_sdk

from assistant.tasks import EMBED_MEMORY_RULE
from core.tasks import enqueue
```

Then replace the body of `create_memory_rule` (currently `tools.py:1259-1279`) with:

```python
def create_memory_rule(scope, trigger: str, field: str, value: str) -> str:
    """Create or update a memory rule from user correction."""
    if field not in VALID_MEMORY_FIELDS:
        valid = ", ".join(sorted(VALID_MEMORY_FIELDS))
        return f"Erro: campo '{field}' inválido. Válidos: {valid}."

    rule, created = MemoryRule.objects.update_or_create(
        household=scope.household,
        trigger=trigger.lower(),
        field=field,
        defaults={
            "value": value,
            "confidence": 1.0,
            "source": MemorySource.USER_CORRECTION,
            "created_by": scope.user,
        },
    )
    # The vector is generated off the request (E10 S10-4). Until it lands, the
    # substring matcher in `find_matching_rules` still finds this rule, so the
    # feature degrades to "exact trigger only" rather than breaking.
    #
    # The key is "this rule, at this value", not a hash of the payload: a
    # correction that changes the value must re-embed, and re-saving the same
    # value must not.
    try:
        enqueue(
            EMBED_MEMORY_RULE,
            {"rule_id": str(rule.pk)},
            idempotency_key=f"{EMBED_MEMORY_RULE}:{rule.pk}:{rule.value}",
        )
    except Exception:
        # A rule the user just taught us must survive an unavailable queue.
        # Only semantic recall is delayed; Sentry gets the reason.
        sentry_sdk.capture_exception()

    action = "criada" if created else "atualizada"
    return f"Regra de memória {action}: '{trigger}' → {field}='{value}'."
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_memory_embedding_task.py -v`
Expected: 12 passed

- [ ] **Step 6: Run the memory and tools suites to check for regressions**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_memory.py src/backend/assistant/tests/test_memory_tools.py src/backend/assistant/tests/test_category_memory.py src/backend/assistant/tests/test_semantic_memory.py src/backend/assistant/tests/test_tools.py -v`
Expected: all pass. If a test fails because it now finds a `MemoryEmbedding` row it did not expect, that test was asserting the *absence* caused by finding F3 — update it to assert the new behaviour, and say so in the commit.

- [ ] **Step 7: Run the full suite and the lint gate**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/ -q`
Expected: all pass

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add src/backend/assistant/tasks.py src/backend/assistant/agents/tools.py \
        src/backend/assistant/tests/test_memory_embedding_task.py
git commit -m "feat(memory): generate rule embeddings off the request

create_memory_rule never generated one, so MemoryEmbedding was empty
outside the perf seed and the semantic fallback searched nothing. The
embedding id is derived from the rule id, which makes a redelivered
task an update rather than a duplicate."
```

---

### Task 7: operational visibility — admin, replay, runbook, and the epic record

A dead-letter path nobody can inspect is not a dead-letter path. This task closes the last two DoD boxes and writes the deferred scope back into the epic.

**Files:**
- Modify: `src/backend/core/admin.py`
- Create: `src/backend/core/management/commands/replay_task.py`
- Modify: `docs/runbook.md` (new section, placed after "Spend ceilings")
- Modify: `docs/backlog/E10-async-work-pipeline.md`
- Test: `src/backend/core/tests/test_task_replay.py`

**Interfaces:**
- Consumes: `core.models.TaskRun`, `core.models.TaskStatus`, `core.tasks.enqueue`.
- Produces: management command `replay_task <task_run_id> [--force]`; `TaskRunAdmin`.

- [ ] **Step 1: Write the failing replay tests**

Create `src/backend/core/tests/test_task_replay.py`:

```python
"""Replaying a task that gave up.

Cloud Tasks has no replay: once it has exhausted a task, the task is gone. The
record that survives is the TaskRun row, so replaying means enqueuing the same
work again — as a NEW run, so the failure it replaces stays on the record.
"""

import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import TaskRun, TaskStatus
from core.tasks.registry import task_handler

REPLAYED: list[dict] = []


@task_handler("test.replay.records", max_attempts=3)
def _records(payload):
    REPLAYED.append(payload)


@pytest.fixture(autouse=True)
def _clear():
    REPLAYED.clear()
    yield
    REPLAYED.clear()


def _dead(**extra):
    return TaskRun.objects.create(
        name="test.replay.records",
        idempotency_key=f"test.replay.records:{uuid.uuid4()}",
        payload={"value": 9},
        status=TaskStatus.DEAD,
        attempts=3,
        max_attempts=3,
        **extra,
    )


@pytest.mark.django_db
class TestReplayTask:
    def test_it_re_enqueues_a_dead_lettered_task(self):
        dead = _dead()

        call_command("replay_task", str(dead.pk))

        assert REPLAYED == [{"value": 9}]
        assert TaskRun.objects.count() == 2

    def test_the_original_failure_stays_on_the_record(self):
        """Replaying must not overwrite the evidence of what went wrong."""
        dead = _dead()

        call_command("replay_task", str(dead.pk))

        dead.refresh_from_db()
        assert dead.status == TaskStatus.DEAD
        assert dead.attempts == 3

    def test_it_refuses_a_task_that_has_not_given_up(self):
        run = TaskRun.objects.create(
            name="test.replay.records",
            idempotency_key="test.replay.records:pending",
            payload={},
            max_attempts=3,
        )

        with pytest.raises(CommandError, match="not dead-lettered"):
            call_command("replay_task", str(run.pk))

        assert REPLAYED == []

    def test_force_replays_a_task_that_has_not_given_up(self):
        run = TaskRun.objects.create(
            name="test.replay.records",
            idempotency_key="test.replay.records:forced",
            payload={"value": 10},
            max_attempts=3,
        )

        call_command("replay_task", str(run.pk), "--force")

        assert REPLAYED == [{"value": 10}]

    def test_an_unknown_id_is_a_clear_error(self):
        with pytest.raises(CommandError, match="No TaskRun"):
            call_command("replay_task", str(uuid.uuid4()))

    def test_a_malformed_id_is_a_clear_error(self):
        with pytest.raises(CommandError, match="No TaskRun"):
            call_command("replay_task", "banana")

    def test_a_double_typed_command_replays_once(self):
        """The replay key is (task_run, attempts), so running the command twice
        for the same failure is deduplicated — while a task that failed *again*
        later replays as a genuinely new run."""
        dead = _dead()

        call_command("replay_task", str(dead.pk))
        call_command("replay_task", str(dead.pk))

        # Two rows total: the original dead one, and one replay.
        assert TaskRun.objects.count() == 2
        assert REPLAYED == [{"value": 9}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_replay.py -v`
Expected: FAIL with `CommandError: Unknown command: 'replay_task'`

- [ ] **Step 3: Write the replay command**

Create `src/backend/core/management/commands/replay_task.py`:

```python
"""Re-run a task that gave up.

Cloud Tasks has no dead-letter queue and no replay: once it has exhausted a
task, the task is gone. The record that survives is the TaskRun row, so
replaying is enqueuing the same work again.

Deliberately a NEW run rather than a reset of the old one: the failure is
evidence, and an operator debugging "why did this rule never get indexed"
needs the attempt count and the last error to still be there afterwards.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import TaskRun, TaskStatus
from core.tasks import enqueue


class Command(BaseCommand):
    help = "Re-enqueue a dead-lettered task by its TaskRun id."

    def add_arguments(self, parser):
        parser.add_argument("task_run_id", help="The TaskRun UUID, from admin or the logs.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replay even when the task has not been dead-lettered.",
        )

    def handle(self, *args, **options):
        raw = options["task_run_id"]
        try:
            task_run = TaskRun.objects.get(pk=raw)
        except (TaskRun.DoesNotExist, ValidationError, ValueError):
            raise CommandError(f"No TaskRun {raw}.") from None

        if task_run.status != TaskStatus.DEAD and not options["force"]:
            raise CommandError(
                f"TaskRun {task_run.pk} is '{task_run.status}', not dead-lettered. "
                "Pass --force to replay it anyway."
            )

        # A key of its own, because the original's is taken and its attempt
        # budget is spent. Including the attempt count means replaying the same
        # failure twice is deduplicated (a double-typed command), while a task
        # that failed again later replays as a genuinely new run.
        replay = enqueue(
            task_run.name,
            task_run.payload,
            idempotency_key=f"replay:{task_run.pk}:{task_run.attempts}",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Re-enqueued '{task_run.name}' from {task_run.pk} as TaskRun {replay.pk} "
                f"(status: {replay.status})."
            )
        )
```

- [ ] **Step 4: Run the replay tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_task_replay.py -v`
Expected: 7 passed

- [ ] **Step 5: Register the admin**

Append to `src/backend/core/admin.py`:

```python
@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    """Where a dead-lettered task becomes visible.

    Read-only throughout: the way to act on a failed task is `replay_task`,
    which leaves the failure on the record. Editing `status` by hand would
    erase the evidence and enqueue nothing.
    """

    list_display = ("name", "status", "attempts", "max_attempts", "created_at")
    list_filter = ("status", "name")
    search_fields = ("id", "idempotency_key", "request_id")
    readonly_fields = (
        "id",
        "name",
        "idempotency_key",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "request_id",
        "last_error",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

Add `TaskRun` to the model imports at the top of `core/admin.py`.

- [ ] **Step 6: Verify the admin registration does not break the admin tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_admin.py src/backend/core/tests/test_admin_isolation.py -v`
Expected: all pass

- [ ] **Step 7: Write the runbook section**

Insert into `docs/runbook.md`, immediately before the `## Cold starts: the keepalive job` heading:

````markdown
## Async tasks (E10)

Slow, retryable work runs off the request through Cloud Tasks. The queue calls
back into this same service at `/tasks/<name>/`, verified by OIDC — the service
is deployed `--allow-unauthenticated`, so Cloud Run does not check the token and
`core/tasks/auth.py` does.

**What actually runs off-request today: memory-rule embedding generation, and
nothing else.** Transcription and receipt extraction are still inline. That is
not an oversight — Cloud Tasks caps a task at 1 MiB, a fixed system limit, and a
voice note is up to 25 MB. Those move when E12 lands a GCS bucket to park the
bytes in.

### Provisioning (one-off, per environment)

```bash
PROJECT=expense-tracker-482807
REGION=southamerica-east1

# 1. The identity Cloud Tasks mints its OIDC token as.
gcloud iam service-accounts create ledger-tasks \
  --display-name="Cloud Tasks OIDC identity for the ledger service" \
  --project="$PROJECT"

# 2. Let the Cloud Run runtime service account create tasks, and mint tokens
#    as the identity above. Both are needed: enqueuer alone gets you a task
#    with no token, and the handler will then 403 it.
RUNTIME_SA="$(gcloud run services describe expense-tracker \
  --project="$PROJECT" --region="$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/cloudtasks.enqueuer"

gcloud iam service-accounts add-iam-policy-binding \
  "ledger-tasks@${PROJECT}.iam.gserviceaccount.com" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --project="$PROJECT"

# 3. The queue. Every limit here is chosen, not defaulted — the default
#    maxAttempts is 100 and the default dispatch rate is 500/s, and this queue
#    shares a 1-CPU instance with every page load.
gcloud tasks queues create ledger-default \
  --location="$REGION" --project="$PROJECT" \
  --max-attempts=8 \
  --min-backoff=10s \
  --max-backoff=600s \
  --max-doublings=4 \
  --max-concurrent-dispatches=4 \
  --max-dispatches-per-second=5 \
  --log-sampling-ratio=1.0
```

`--max-attempts=8` is deliberately **higher** than any handler's own ceiling
(`@task_handler(..., max_attempts=N)`, 4 for the embedding task). The
application's ceiling is meant to win: when it is reached the handler answers
200, the queue stops, and the `TaskRun` row records `dead`. If the queue's
ceiling were the lower of the two, tasks would vanish with no row saying so —
which is the failure the whole dead-letter path exists to prevent.

### Deploy variables

Add to `gcloud run deploy --set-env-vars` (see *Deploy a new revision*; keep the
`^@^` separator, these values contain no commas but the existing ones do):

```
CLOUD_TASKS_ENABLED=1
CLOUD_TASKS_PROJECT=expense-tracker-482807
CLOUD_TASKS_LOCATION=southamerica-east1
CLOUD_TASKS_QUEUE=ledger-default
CLOUD_TASKS_TARGET_BASE_URL=https://<service-host>
CLOUD_TASKS_AUDIENCE=https://<service-host>
CLOUD_TASKS_OIDC_SERVICE_ACCOUNT=ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com
```

`CLOUD_TASKS_AUDIENCE` must equal the base URL exactly, with no trailing slash.
A mismatch is the single most common cause of a 403 on a task that otherwise
looks correctly configured — the log line reads `Refused /tasks/…: token
rejected: ValueError`.

### Locally, and in CI

Leave `CLOUD_TASKS_ENABLED` unset. The eager backend runs handlers in-process
the moment they are enqueued: no GCP credentials, no emulator, no queue. The
attempt accounting and the dead-letter decision are the same code
(`core/tasks/execution.py`), so behaviour on the third failure does not differ
between a laptop and production. What *does* differ, and is worth remembering:
eager work runs inside the request that scheduled it, so locally there is no
instance relief and no real backoff.

### What it costs

Cloud Tasks bills per operation and the first million per month are free. At
this scale — a handful of memory rules a week — it is free. The cost that is
real is the *embedding call* each task makes, which is already metered as a
`UsageRecord` with `kind=embedding`; see *Spend ceilings*.

### Inspecting a failed task

Every task is a `TaskRun` row. Start in admin, at
`https://<host>/<ADMIN_URL_PATH>/core/taskrun/`, filtered by status `Descartada`
(dead). Or from a shell:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import TaskRun, TaskStatus
for r in TaskRun.objects.filter(status=TaskStatus.DEAD).order_by('-created_at')[:20]:
    print(r.pk, r.name, r.attempts, r.request_id, r.last_error[:120])
"
```

The `request_id` column is the link back to the request that scheduled the
work. Paste it into the Cloud Logging filter from *Start from the request ID* —
it returns both the originating request and the task's own log lines, because
`CloudTasksBackend` forwards it as `X-Request-ID` and `request_id_middleware`
adopts it.

Every dead-lettered task is also a Sentry event
(`core/tasks/execution.py` calls `capture_exception` on the final failure), so
the tracker is the other place to start.

### Replaying a dead-lettered task

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py replay_task <TASK_RUN_UUID>
```

In production, run it through the Cloud Run job or a `gcloud run services
update`-style one-off — the same route as any other management command.

The replay is a **new** `TaskRun`. The original keeps its `dead` status, its
attempt count and its `last_error`, because that is the evidence you were
reading a minute ago and overwriting it would be the wrong trade. Running the
command twice for the same failure is deduplicated, so a double-typed command
costs nothing.

`--force` replays a task that has not been dead-lettered. Reach for it only when
you know a task is stuck — for example a row left `pending` because the process
died mid-handler.

### How this misleads

- **A `done` row does not mean the user got what they wanted.** It means the
  handler returned without raising. For the embedding task that is a genuine
  success; for a future handler, check what the handler actually asserts.
- **`attempts` counts *dispatches this app saw*, not queue retries.** A task the
  queue dropped before delivery — a bad URL, a 403 — never increments it. If a
  `TaskRun` sits at `pending` with `attempts=0` and never moves, the problem is
  between Cloud Tasks and the endpoint, not in the handler. Check the queue's
  own logs:
  `gcloud logging read 'resource.type="cloud_tasks_queue" resource.labels.queue_id="ledger-default"' --limit=20 --project=expense-tracker-482807`
````

- [ ] **Step 8: Add the runbook pointer to the README quickstart**

Confirm `README.md` already points at `docs/runbook.md`. If it does not, add one line to the quickstart:

```markdown
Operational procedures — deploys, spend ceilings, async tasks, migrations — live in [`docs/runbook.md`](docs/runbook.md).
```

- [ ] **Step 9: Record the decisions in the epic document**

Modify `docs/backlog/E10-async-work-pipeline.md`. Replace the `## Open questions` section with:

```markdown
## Open questions — resolved 2026-08-15

1. **How does an async result reach a streaming SSE connection?** **Resolved:
   the client polls a status endpoint.** The widget consumes the chat response
   with `fetch` + `response.body.getReader()` (`ChatWidget.tsx:413`), not
   `EventSource` — the "SSE channel" is the POST's own chunked body, with no
   reconnect and no `Last-Event-ID`. There is nothing to push into. Holding the
   stream open while a task runs would pin two concurrent requests where there
   was one, which is the opposite of this epic's goal on `--cpu 1
   --concurrency 80`. **Not built in E10** — there is no async workload with a
   user waiting on it yet. E12 builds it alongside the media workloads.
2. **Does moving extraction off-request actually help?** **Moot for now, and
   the answer is "not yet".** Cloud Tasks caps a task at 1 MiB (a fixed system
   limit), audio is capped at 25 MB and five prepared receipt JPEGs run to
   several MB — so extraction and transcription cannot move at all until there
   is object storage to park the bytes in. That is E12 S12-2. E10 therefore
   builds the rails and defers the media workloads.
3. **What is the retry policy for a paid API call?** **Resolved: the
   application owns the ceiling.** `@task_handler(..., max_attempts=N)` is the
   real limit (4 for the embedding task); the Cloud Tasks queue is provisioned
   at `--max-attempts=8` so the application's limit always wins and the giving-
   up is recorded. `--max-concurrent-dispatches=4` keeps task traffic from
   competing with page loads on the same 1-CPU instance. Costs stay visible
   through E07's existing `UsageRecord` metering — the embedding task's
   provider call is metered exactly as the inline one was.
4. **Cloud Tasks emulation locally?** **Resolved: a synchronous fallback.**
   `CLOUD_TASKS_ENABLED=0` selects `EagerBackend`, which runs handlers
   in-process through the same `run_task_run` as production, so attempt
   accounting and the dead-letter decision are identical. No emulator, no GCP
   credentials.
```

Then replace the `Observable assertions` checklist with:

```markdown
Observable assertions:

- [x] Task handlers reject requests not carrying a valid OIDC token, asserted by test
      — `core/tests/test_task_auth.py`, `core/tests/test_task_views.py::TestAuthentication`.
      Fails closed: with no service account configured, everything is refused.
- [x] A handler invoked twice with the same payload produces one result, asserted by test
      — `TestIdempotency::test_the_same_task_delivered_twice_produces_one_result`,
      and for the moved workload,
      `test_memory_embedding_task.py::TestHandler::test_running_it_twice_leaves_one_embedding`.
- [ ] The one-pending-draft invariant holds under concurrent uploads and a retried task
      — **deferred to E12.** Receipt extraction cannot move off the request
      until there is object storage: Cloud Tasks caps a task at 1 MiB and five
      prepared receipt JPEGs run to several MB.
- [ ] A transient transcription failure is retried and succeeds without user action
      — **deferred to E12**, same reason. Audio is capped at 25 MB.
- [x] A memory rule created while its embedding is pending is still matched by the substring path
      — `test_a_rule_with_no_embedding_yet_is_still_matched_by_substring`.
- [x] A task execution's trace links back to its originating request ID
      — `enqueue` captures `get_request_id()` onto the row; `CloudTasksBackend`
      forwards it as `X-Request-ID`, which `request_id_middleware` already
      adopts. `test_task_cloud.py::test_it_forwards_the_originating_request_id`.
- [x] A deliberately failed task lands in the dead-letter path and is visible
      — `TestRetryAndDeadLetter::test_the_final_failure_dead_letters_and_stops_the_retries`,
      plus the read-only `TaskRun` admin and a Sentry event on the final failure.
- [x] Local development works without GCP credentials
      — `CLOUD_TASKS_ENABLED=0` selects `EagerBackend`;
      `TestBackendSelection::test_it_is_eager_when_cloud_tasks_is_off`.
- [x] `docs/runbook.md` documents inspecting and replaying dead-lettered tasks
      — plus the two ways it misleads: a `done` row that only means "did not
      raise", and an `attempts=0` row that means the queue never reached us.

**Found while building the rails, still open:**

- `create_memory_rule` had **never** generated an embedding, so
  `MemoryEmbedding` was empty outside `seed_perf_data` and the semantic
  fallback in `lookup_memory_async` was searching nothing. S10-4 was written on
  the assumption that it did. Fixed here as generate-on-write, which is what
  gave the rails their first real workload — but every memory rule created
  before this epic still has no vector. A backfill command is not an E10
  deliverable and needs its own ticket.
- The dispatch view holds a `select_for_update` row lock for the duration of the
  handler. That is correct and cheap for sub-second work, and it is a real
  constraint on what may be moved: a handler that takes minutes would hold a
  pooled Supabase connection for minutes. E12's import execution needs a
  claim-and-release design rather than this one.
```

Finally, add this note directly under the `## Outcome` heading:

```markdown
> **Scope, decided 2026-08-15.** This epic builds the rails and moves one
> workload. Transcription and receipt extraction are **deferred to E12**:
> Cloud Tasks caps a task at 1 MiB — a fixed system limit — and this app's
> audio (25 MB) and prepared receipt images (several MB) are far over it, so
> they cannot move until E12 S12-2 provides object storage to park the bytes
> in. E12 declares `depends_on: [E10]`; that stays true, because E12 consumes
> these rails. See `docs/superpowers/plans/2026-08-15-E10-async-work-pipeline.md`.
```

- [ ] **Step 10: Run the full suite, the coverage gate and the lint gate**

Run: `POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80`
Expected: all pass, coverage at or above 80

Run: `uv run ruff check src/backend/ && uv run ruff format --check src/backend/`
Expected: clean

- [ ] **Step 11: Prove the suite is still time-stable**

Run: `TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"`
Expected: same result as the unshifted run (`docs/testing-conventions.md`)

- [ ] **Step 12: Commit**

```bash
git add src/backend/core/admin.py \
        src/backend/core/management/commands/replay_task.py \
        src/backend/core/tests/test_task_replay.py \
        docs/runbook.md docs/backlog/E10-async-work-pipeline.md README.md
git commit -m "feat(tasks): dead-letter visibility, replay, and the runbook

Cloud Tasks has no replay, so replaying is re-enqueuing from the TaskRun
row — as a new run, so the failure stays on the record. Records in the
epic why transcription and extraction are deferred to E12."
```

---

## Verification

Before declaring E10 done, run the spec's Definition of Done verbatim and paste the output as evidence:

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Then demonstrate the rails end to end locally, with no GCP credentials:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from accounts.resolution import household_for_user
from assistant.agents.scope import AgentScope
from assistant.agents.tools import create_memory_rule
from assistant.models import MemoryEmbedding
from core.models import CustomUser, TaskRun

user = CustomUser.objects.first()
scope = AgentScope(household=household_for_user(user), user=user)
print(create_memory_rule(scope, 'cosmos', 'category', 'Alimentação'))
print(TaskRun.objects.latest('created_at'))
print(MemoryEmbedding.objects.count(), 'embeddings')
"
```

Expected: the rule is created, one `TaskRun` reads
`assistant.embed_memory_rule (done, 1/4)`, and the embedding count has gone up
by one. This spends one real embeddings API call (`text-embedding-3-small`,
fractions of a cent) — it is the one part of the rails that cannot be proven
without a provider.

**Do not claim the deferred boxes are done.** Two DoD assertions — the
one-pending-draft invariant under a retried task, and transcription retry — are
E12's, for the reason recorded in the epic. Say so plainly when reporting.
