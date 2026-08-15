---
id: E10
title: Async work pipeline
release: R2
status: ready
depends_on: [E06]
blocks: [E12]
wedge_critical: true
---

# E10 · Async work pipeline

## Outcome

> **Scope, decided 2026-08-15.** This epic builds the rails and moves one
> workload. Transcription and receipt extraction are **deferred to E12**:
> Cloud Tasks caps a task at 1 MiB — a fixed system limit — and this app's
> audio (25 MB) and prepared receipt images (several MB) are far over it, so
> they cannot move until E12 S12-2 provides object storage to park the bytes
> in. E12 declares `depends_on: [E10]`; that stays true, because E12 consumes
> these rails. See `docs/superpowers/plans/2026-08-15-E10-async-work-pipeline.md`.

Slow, failure-prone work — transcription, receipt extraction, embeddings, bulk imports — runs off the request with retry and a dead-letter path, so a spike in receipt uploads does not degrade page loads and a transient provider failure does not lose a user's voice note.

## Why now

Review finding **H4** and **ADR-004**. Everything runs inline today on a 1-CPU Cloud Run instance serving up to 80 concurrent requests, with no retry and no dead-letter path.

Wedge-critical because the wedge is AI capture: the receipt and voice paths **are** the product, and they are exactly the slow, failure-prone paths. A user whose voice note vanishes because OpenAI hiccuped has experienced the product failing at the thing it is for.

## Evidence in the codebase

| What | Where |
|---|---|
| Transcription inline in the request | `assistant/views.py:213` |
| Its failure mode: 502 and the audio is gone | `assistant/views.py:214-223` — media is discarded by design, so the user must re-record |
| Receipt extraction inline | `assistant/views.py:318` |
| The expensive inline retry | `assistant/views.py:327-330` |
| Image preprocessing inline, per image, up to 5 | `assistant/views.py:288` — `prepare_receipt_image` |
| Embedding generation inline | `assistant/services/embedding.py:11-22` |
| CSV import executed inline in one request | `finances/views/importer.py:265-383` |
| Every DB-touching agent tool wrapped for async | `assistant/agents/assistant.py` — ~30 `sync_to_async` call sites |
| Deployment shape | `docs/deploy/next-session-kickoff.md:62` — `--cpu 1 --memory 1Gi --timeout 300` |
| SSE holds the connection for the whole run | `assistant/views.py:126-132` |

## Stories

### S10-1 · Task infrastructure on Cloud Tasks

- **Given** ADR-004 chose Cloud Tasks over Celery/Redis to avoid a stateful dependency
- **When** the infrastructure is built
- **Then** authenticated HTTP task endpoints exist on the same Django service, verified by OIDC so only Cloud Tasks can invoke them
- **And** a small, typed enqueue helper is the single way application code schedules work
- **And** handlers are **idempotent** — Cloud Tasks delivers at least once, and a retried receipt extraction must not create duplicate entries
- **And** local development has a synchronous or emulated execution path so the app runs without GCP
- **And** retry policy and dead-letter behaviour are configured, not defaulted

> Idempotency is the story's hard part. This codebase already has hard-won duplicate-prevention machinery — the one-pending-draft invariant (`assistant/views.py:307-310`) and `find_registered_duplicate`. Reuse that thinking; do not invent a second mechanism.

### S10-2 · Move transcription off the request, without breaking the conversation

- **Given** the chat is a streaming conversation and the user is waiting
- **When** transcription is moved
- **Then** a failed transcription is retried automatically rather than returning 502 on the first failure
- **And** the user sees an honest interim state rather than a spinner that ends in nothing
- **And** if it ultimately fails, the user is told clearly, in pt-BR, that they need to re-record
- **And** the existing model fallback (`LLM_TRANSCRIBE_FALLBACK_MODEL`) still applies

> Do not naively make the whole chat asynchronous. Streaming is the product's feel. The goal is that the *work* is retryable and traced, while the *conversation* stays responsive. The plan must state explicitly which parts stay synchronous and why.

### S10-3 · Move receipt extraction and its retry off the request

- **Given** extraction plus a vision retry can occupy an instance for a long time
- **When** extraction is moved to a task
- **Then** the user gets immediate acknowledgement that the photo is being read
- **And** the result arrives without the user reloading — reuse the existing SSE channel rather than adding polling
- **And** the extraction and the escalation retry (E09 S09-3) both happen in the task
- **And** the one-pending-draft invariant still holds under concurrent uploads and task retries, asserted by test

### S10-4 · Move embedding generation off the request

- **Given** embeddings are generated when memory rules are created
- **When** it is moved to a task
- **Then** rule creation returns immediately and the embedding is generated asynchronously
- **And** a rule whose embedding has not yet been generated degrades gracefully — the substring matcher (`assistant/agents/memory.py:14`) still works, so the feature is not broken while the embedding is pending
- **And** a failed embedding is retried and, if it ultimately fails, surfaces in the error tracker rather than leaving a silently unsearchable rule

### S10-5 · Traceability and operational visibility

- **Given** E06 established tracing
- **When** tasks run
- **Then** each task execution is traced with its originating request ID, so a user-reported problem can be followed from the request into the task
- **And** task failures reach the error tracker
- **And** dead-lettered tasks are visible and documented in `docs/runbook.md` — including how to inspect and replay one

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

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

## Out of scope

- Moving the CSV import to a task → **E12**, which needs durable job state and object storage first. This epic builds the infrastructure E12 consumes.
- Making the chat conversation itself asynchronous — streaming stays
- Replacing `sync_to_async` throughout the agent — a real cost, and a separate refactor with its own risk
- Celery, Redis, or a database-backed queue — rejected in ADR-004

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

## Skill pipeline

1. `superpowers:brainstorming` — **required**; open questions 1 and 2 could change the epic's scope substantially
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development` — idempotency and retry behaviour are the tests that matter
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion`
8. `superpowers:finishing-a-development-branch`
