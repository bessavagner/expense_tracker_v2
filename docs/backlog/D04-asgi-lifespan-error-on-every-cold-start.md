---
id: D04
title: Every cold start reports a ValueError to Sentry because the lifespan scope reaches Django
release: R2
status: ready
depends_on: [E06]
blocks: []
wedge_critical: false
---

# D04 · The ASGI lifespan scope reaches Django and reports an error on every cold start

## Outcome

A cold start produces no error report, so the next unexplained entry in Sentry
is a real one.

## Symptom

Sentry issue `EXPENSE-TRACKER-1`, seen 2026-08-15:

```
ValueError: Django can only handle ASGI/HTTP connections, not lifespan.
  django.core.handlers.asgi in __call__
```

Two events over one day, unhandled. Nothing breaks — the service serves traffic
normally — but every container start files an error report.

## Root cause

`Dockerfile:87` runs the app under gunicorn's uvicorn worker:

```
gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker ...
```

Uvicorn opens by sending a `lifespan` scope. `config/asgi.py` wraps Django in
`request_body_ceiling_asgi` (E01 Task 6, which has to sit ahead of Django to
enforce the body ceiling before `ASGIHandler.read_body` buffers), and that
wrapper forwards every scope to Django. `ASGIHandler.__call__` accepts only
`http` and raises on anything else.

Uvicorn's `lifespan="auto"` then catches the exception and disables lifespan,
which is why the service is unaffected. But Sentry's ASGI integration sees the
exception first, so it is reported before it is swallowed.

## Why it is worth fixing despite being harmless

It is two events a day of guaranteed noise in the tool whose entire job is to
tell you when something is wrong. E06's own DoD spent a day unable to prove
that container-raised exceptions reach Sentry; this one was reaching it the
whole time and was indistinguishable from background noise. A recurring
benign error trains you to skim past the list — which is the failure mode that
matters, not the ValueError itself.

## What to do

- [ ] The wrapper in `core/asgi_body_limit.py` answers the lifespan protocol
      itself, or passes non-`http` scopes somewhere other than Django
- [ ] A cold start files no Sentry event
- [ ] A test drives the wrapper with a `lifespan` scope and asserts Django is
      never called
- [ ] The chosen approach is written down — whether lifespan is answered or
      declined, and why

Answering the protocol (`lifespan.startup` → `lifespan.startup.complete`,
`lifespan.shutdown` → `lifespan.shutdown.complete`) is the conventional fix and
leaves a place to hang future startup work. Declining it — a gunicorn worker
subclass setting `lifespan: "off"` — is smaller but pushes the decision into the
Dockerfile, away from the code it constrains.

## Out of scope

Moving the body ceiling back inside Django middleware. It sits ahead of Django
deliberately; see the comment in `config/asgi.py` and `core/asgi_body_limit.py`.

## Note on provenance

Found on 2026-08-15 while checking Sentry to confirm that the `accounts.0005`
schema-drift outage had reported correctly. It had been firing for at least a
day and nobody had looked at the issue list.
