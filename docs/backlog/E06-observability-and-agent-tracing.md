---
id: E06
title: Observability & agent tracing
release: R1
status: review
depends_on: [E01]
blocks: [E07, E10, E14, E16]
wedge_critical: false
---

# E06 · Observability & agent tracing

## Outcome

Production failures reach you before they reach a customer, every agent run is traceable with its token counts and latency, and the NFR targets in the architecture review become measured numbers instead of aspirations.

## Why now

Review finding **H3** and **ADR-005**. Logging today is one console handler at INFO (`config/settings.py:115-127`). No error tracker, no request IDs, no metrics, no LLM tracing.

This blocks four epics for a concrete reason: **you cannot meter what you have not instrumented** (E07), you cannot debug asynchronous work you cannot trace (E10), you cannot measure activation without an event pipeline (E14), and you cannot operate a service whose health you cannot see (E16). Observability is infrastructure for the rest of R1 through R4.

## Evidence in the codebase

| What | Where |
|---|---|
| The entire logging configuration | `config/settings.py:115-127` |
| No error tracker in dependencies | `pyproject.toml` — no `sentry-sdk` |
| PydanticAI's native tracing unused | `pydantic-ai>=1.73.0` in `pyproject.toml`; no Logfire configuration anywhere |
| Errors swallowed with no telemetry — the stream fails silently to a generic message | `assistant/views.py:104-107` |
| `data_changed` detection failure swallowed | `assistant/views.py:102-103` |
| Transcription failure logged but not tracked | `assistant/views.py:214-223` |
| Extraction failure logged but not tracked | `assistant/views.py:319-320, 331-332` |
| Import row failures counted, never reported | `finances/views/importer.py:363-364` |
| Health endpoint that nothing watches | `core/views.py:8` (`health_check`), routed at `config/urls.py:12` |

## Stories

### S06-1 · Error tracking with PII discipline

- **Given** this application handles financial descriptions, chat content, and receipt data
- **When** Sentry is integrated
- **Then** unhandled exceptions are reported with enough context to debug
- **And** PII scrubbing is **configured and tested** — request bodies, chat message content, and entry descriptions must not be transmitted by default
- **And** a test asserts that a deliberately-triggered error does not carry chat content in its payload
- **And** the DSN comes from Secret Manager, not source
- **And** releases are tagged so an error can be attributed to a deployed revision

> Default Sentry configuration captures request bodies. For this application that would itself be a privacy incident. Scrubbing is a story requirement, not a follow-up.

### S06-2 · Structured logging with request correlation

- **Given** Cloud Run aggregates stdout
- **When** logging is restructured
- **Then** logs are emitted as structured JSON that Cloud Logging parses into fields
- **And** middleware assigns a request ID, included in every log line for that request
- **And** the request ID is attached to the Sentry event and returned in a response header, so a user-reported error can be traced
- **And** the household and user are included as log fields once E04 has landed (guard for the pre-E04 state if this ships first)

### S06-3 · Agent tracing and token accounting

- **Given** PydanticAI exposes per-run usage
- **When** Logfire is wired to the agent
- **Then** every agent run produces a trace with its tool calls, latency, and input/output token counts
- **And** the receipt extraction and transcription paths are traced too, not only the chat agent
- **And** traces carry the model name, so E09's routing decisions are visible in production
- **And** the same PII discipline as S06-1 applies — decide explicitly what prompt content is captured, and record the decision

> This story is the direct input to **E07**. The usage numbers Logfire surfaces are what `UsageRecord` will persist. Design them together; do not instrument twice.

### S06-4 · Stop swallowing failures silently

- **Given** the swallowed-exception sites listed in the evidence table
- **When** they are reviewed
- **Then** each either reports to the error tracker or is documented as intentionally silent with a reason
- **And** the generic `"Erro ao processar mensagem"` path (`assistant/views.py:104-107`) reports the underlying exception before returning the friendly message
- **And** the user-facing message is unchanged — this story improves *observability*, not UX

### S06-5 · Uptime, alerting, and the golden-signals dashboard

- **Given** `/healthz/` exists and nothing watches it
- **When** monitoring is configured
- **Then** an uptime check polls it and alerts on failure through a channel that actually reaches you
- **And** a dashboard shows request rate, error rate, p95 latency, assistant turns per day, and estimated LLM spend per day
- **And** alerts exist for error-rate spikes and for the LLM spend threshold agreed in E01
- **And** the alerting path has been tested by deliberately triggering it

> Note the existing cost-conscious keepalive arrangement — a Scheduler ping rather than `min-instances=1`. The uptime check may serve both purposes; check before adding a second pinger, and be aware the ping affects any cold-start measurement.

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Evidence at `f3faa6f` on `main`, 2026-08-14: **1357 passed, 3 skipped, 90%
coverage**; `ruff check` and `ruff format --check` clean; `manage.py check` and
`check --deploy` report no issues; `makemigrations --check` reports no changes.

Deployed as **`expense-tracker-00045-zjs`** with `SENTRY_DSN` and
`LOGFIRE_TOKEN` mounted from Secret Manager (`sentry-dsn`, `logfire-token`).
Smoke test green: `/healthz/` 200, `/` 302, assetlinks 200, `/accounts/login/`
200. Startup logs carry no `Sentry disabled` warning, so the DSN parsed.

Observable assertions:

- [ ] A deliberately raised exception appears in Sentry, tagged with the release — **partial.** A real event was transmitted through the production DSN on 2026-08-14, `release=expense-tracker-00045-zjs`, `request_id` tag set, and the scrubber demonstrably stripped frame locals (`vars` absent from the transmitted payload). What is **not** yet proven is an exception raised *inside the deployed container*: Cloud Run routes on `Host`, so the usual `DisallowedHost` trick 404s before reaching Django, and the app has no deliberate-error endpoint. Container→vendor egress is separately evidenced by Logfire printing its project URL at startup. Closes on the first real production error, or by adding a temporary debug route.
- [x] A test proves chat content and entry descriptions are scrubbed from error payloads — `core/tests/test_observability.py`: `test_chat_content_never_reaches_the_transport` drives a real `sentry_sdk` client and asserts on what `before_send` actually produced, plus six unit tests for the individual carriers (body, cookies, headers, frame locals, `extra`, breadcrumbs).
- [ ] A request ID appears in the response header, the structured log line, and the Sentry event for the same request — **header proven in production**: `curl -sI …/healthz/` on `00045-zjs` returned `x-request-id: 6608b6f3fbfd40788732aa4d59d94837`. Log line and Sentry tag are proven by test (`core/tests/test_request_id.py`) but **not yet observed in production for one shared request**, because a successful request emits no application log line — `jsonPayload.request_id!=""` returns empty on a healthy service, by design. Closes with the same real error as the box above.
- [ ] An agent run appears in Logfire with tool calls, latency, model name, and token counts — **transport proven, trace not yet.** Logfire configured successfully on `00045-zjs`, printing its project URL at startup (<https://logfire-us.pydantic.dev/cactarus/expense-tracker>). The capture *policy* is proven in `assistant/tests/test_tracing.py`. Closes on the first authenticated chat turn against the deployed revision.
- [ ] The uptime check has alerted at least once in a deliberate test — **blocked on Task 7**.
- [ ] The dashboard shows all five golden signals with real data — **blocked on Task 7**.
- [x] `docs/runbook.md` documents where to look when something breaks, and who gets alerted — §"When something breaks": the request-ID join key across all three vendors, the Cloud Logging and Sentry queries, what a Logfire span holds, what is deliberately *not* reported, and the alert channels. The alert subsection is marked pending until Task 7 provisions the channels.

## Out of scope

- Persisting usage to the database for billing → **E07**
- Product analytics events (activation, retention) → **E14**; this epic covers *operational* telemetry
- Distributed tracing across services — there is one service (ADR-002)
- Self-hosted observability — rejected in ADR-005
- **Handed to E13:** the operator's decision to capture full prompts and
  completions (2026-08-14) makes Logfire a **data sub-processor** holding chat
  content and receipt descriptions. E13's privacy notice must name Pydantic as a
  sub-processor, and E13's deletion story must state what happens to trace data.
  Recorded here because it is not discoverable from E13's own file.

## Open questions — all resolved 2026-08-14

1. ~~**What is the alert destination?**~~ **Resolved 2026-08-14, then half of it became impossible.** The decision was GCP mobile-app push (wakes the operator) plus email (durable record). **`mobile_push` no longer exists** — Google retired the Cloud Console mobile app and its channel type; `gcloud beta monitoring channel-descriptors describe mobile_push` returns `NOT_FOUND`, and there is no "Mobile devices" entry in the console. Only the email channel was created (`Operator email`, id `5857707555791637518`). **Operator's call, same day: email only for now**, accepting that nothing wakes them. SMS is the identified replacement when that becomes unacceptable; see the runbook for the supported channel list and why `gcloud` cannot finish the SMS flow.
2. ~~**How much prompt content should traces capture?**~~ **Resolved, against this epic's own recommendation:** full prompts and completions ARE captured (`LOGFIRE_CAPTURE_CONTENT=1`). Operator's explicit decision — debugging agent misbehaviour without the actual text means reproducing every incident from scratch. Binary content is a *separate* flag and stays off (`LOGFIRE_CAPTURE_BINARY=0`): that decision was about text, and shipping every receipt JPEG to a third party is a materially larger exposure. See the Out-of-scope handoff to E13 above.
3. ~~**Sentry's free tier event quota**~~ **Resolved by ADR-005:** both vendors' free tiers are adequate for launch scale. Performance traces sample at `SENTRY_TRACES_SAMPLE_RATE=0.1`.
4. ~~**Does the existing Scheduler keepalive conflict with a new uptime check?**~~ **Resolved:** one pinger, not two. The uptime check replaces `expense-tracker-keepalive`; the Scheduler job is deleted in Task 7 and `docs/runbook.md` is amended so the cold-start procedure pauses the uptime check instead.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development` — the testable assertions here are the scrubbing rules and request-ID propagation
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `superpowers:verification-before-completion` — paste a real trace and a real scrubbed error payload as evidence
7. `superpowers:finishing-a-development-branch`
