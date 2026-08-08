---
id: E10
title: Async work pipeline
release: R2
status: blocked
depends_on: [E06]
blocks: [E12]
wedge_critical: true
---

# E10 · Async work pipeline

## Outcome

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

- [ ] Task handlers reject requests not carrying a valid OIDC token, asserted by test
- [ ] A handler invoked twice with the same payload produces one result, asserted by test for each moved workload
- [ ] The one-pending-draft invariant holds under concurrent uploads and a retried task, asserted by test
- [ ] A transient transcription failure is retried and succeeds without user action
- [ ] A memory rule created while its embedding is pending is still matched by the substring path
- [ ] A task execution's trace links back to its originating request ID
- [ ] A deliberately failed task lands in the dead-letter path and is visible
- [ ] Local development works without GCP credentials
- [ ] `docs/runbook.md` documents inspecting and replaying dead-lettered tasks

## Out of scope

- Moving the CSV import to a task → **E12**, which needs durable job state and object storage first. This epic builds the infrastructure E12 consumes.
- Making the chat conversation itself asynchronous — streaming stays
- Replacing `sync_to_async` throughout the agent — a real cost, and a separate refactor with its own risk
- Celery, Redis, or a database-backed queue — rejected in ADR-004

## Open questions

1. **How does an async result reach a streaming SSE connection** that may have already closed? Options: hold the stream while the task runs, reconnect, or push on the next interaction. This is the epic's central design question and must be resolved before planning.
2. **Does moving extraction off-request actually help,** given the user is waiting anyway? The benefit is retry, tracing, and not pinning an instance — not latency. Confirm the benefit is real before doing the work; if it is not, keep extraction inline and take only the retry and tracing.
3. **What is the retry policy** for a paid API call? An aggressive retry on a vision model multiplies cost. Coordinate the limits with E07's quota accounting.
4. **Cloud Tasks emulation locally** — is there an adequate emulator, or is a synchronous fallback the pragmatic answer?

## Skill pipeline

1. `superpowers:brainstorming` — **required**; open questions 1 and 2 could change the epic's scope substantially
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development` — idempotency and retry behaviour are the tests that matter
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion`
8. `superpowers:finishing-a-development-branch`
