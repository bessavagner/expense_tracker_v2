---
id: E01
title: Spend & abuse containment
release: R0
status: done
depends_on: []
blocks: [E06]
wedge_critical: false
---

# E01 · Spend & abuse containment

## Outcome

A single authenticated account cannot generate unbounded OpenAI spend, cannot write ledger data through an unprotected endpoint, and cannot brute-force the login — and the infrastructure has a hard ceiling that holds even if the application logic fails.

## Why now

Review findings **B2** and **B3**. This is the highest-consequence gap in the entire product: an unmetered LLM behind an unthrottled, CSRF-exempt endpoint. Everything else in this backlog can wait behind a slow quarter; this cannot wait behind a single bad afternoon.

Deliberately split from E07 (full metering): E07 needs household tenancy and observability to attribute cost properly. E01 is the **crude ceiling that stops the bleeding today** with no dependencies. Ship the blunt instrument first.

## Evidence in the codebase

| What | Where |
|---|---|
| `@csrf_exempt` on the write-capable chat endpoint | `src/backend/assistant/views.py:138` |
| The tools that endpoint can reach (create/update/delete money) | `src/backend/assistant/views.py:24-28` (`MUTATING_TOOLS`) |
| Per-request media limits that exist (5 images × 10MB) | `src/backend/config/settings.py:198-200`, enforced `assistant/views.py:275-287` |
| Vision model default — the expensive path | `src/backend/config/settings.py:187` (`openai:gpt-5.4`) |
| No throttle/quota anywhere | `grep -rniE 'throttle|ratelimit|rate_limit|quota' src/backend --include='*.py'` → zero hits |
| Login is Django admin, unthrottled | `src/backend/config/settings.py:168`, `config/urls.py:16` |
| Cloud Run deployed without `--max-instances` | `docs/deploy/next-session-kickoff.md:62` |
| `SESSION_COOKIE_SAMESITE` never set (relies on Django's `Lax` default) | absent from `src/backend/config/settings.py` |

## Stories

### S01-1 · Infrastructure hard ceiling

Pure configuration, no code. Do this first — it is the only story here that caps risk without a deploy.

- **Given** the Cloud Run service `expense-tracker` in project `expense-tracker-482807`
- **When** it is redeployed or updated
- **Then** `--max-instances` is set to an explicit low value, and a GCP budget alert exists on the billing account that notifies at 50%, 80%, and 100% of an agreed monthly threshold
- **And** an OpenAI organisation-level monthly spend limit is configured as a second, independent backstop
- **And** all three values are recorded in `docs/runbook.md`

### S01-2 · Restore CSRF protection on the chat endpoint

- **Given** the React `ChatWidget` already sends `X-CSRFToken` from the cookie
- **When** `@csrf_exempt` is removed from `chat_view`
- **Then** a POST carrying a valid CSRF token succeeds
- **And** a POST with a missing or invalid token returns 403
- **And** the existing multipart (image + audio) paths still succeed with a valid token
- **And** `SESSION_COOKIE_SAMESITE` and `CSRF_COOKIE_SAMESITE` are set explicitly in settings rather than inherited, with a test asserting their values
- **And** the Android TWA still authenticates and chats successfully after deploy

> The endpoint is `async`. Verify Django's CSRF middleware interacts correctly with the async view and the `StreamingHttpResponse`; if the token must move to a header-only check, document why in the plan.

### S01-3 · Per-account assistant throttling

- **Given** an authenticated user
- **When** they exceed an agreed number of assistant turns in a rolling window
- **Then** the request is rejected **before any model call is made**, with a clear pt-BR message and HTTP 429
- **And** the image/receipt path has its own, tighter limit, because it costs roughly an order of magnitude more per turn than a text turn
- **And** the limit is configurable by environment variable, defaulting to a value generous enough that ordinary daily use never encounters it
- **And** a test asserts that exceeding the limit produces zero calls to the model

### S01-4 · Login brute-force protection

- **Given** the login form
- **When** repeated failed attempts arrive for the same account or IP
- **Then** further attempts are throttled
- **And** the throttle applies to whatever login view is active, so it keeps working after E05 replaces `/admin/login/`

### S01-5 · Upload size ceiling

- **Given** the CSV importer and the chat media endpoints
- **When** a request carries a body larger than an agreed maximum
- **Then** it is rejected before the payload is written to disk or held in memory
- **And** the limit accounts for Cloud Run's RAM-backed filesystem against the configured `--memory` (currently 1Gi)

## Definition of Done

```bash
# Suite green, coverage and lint gates hold
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# Deploy hardening intact
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com uv run python src/backend/manage.py check --deploy

# No throttle bypass: the string must now appear
grep -rniE 'throttle|ratelimit' src/backend --include='*.py' | grep -v tests

# csrf_exempt is gone from application code (scoped past the regression-guard test,
# which necessarily contains the string it asserts against)
grep -rn 'csrf_exempt' src/backend/assistant/ --include='*.py' | grep -v '/tests/'
```

Observable assertions:

- [ ] `grep -rn 'csrf_exempt' src/backend/assistant/ --include='*.py' | grep -v '/tests/'` returns nothing (the unscoped form necessarily matches the regression-guard test in `assistant/tests/test_chat_csrf.py`, which asserts this same property)
- [ ] A test proves an over-limit assistant request makes **zero** model calls
- [ ] A test asserts `SESSION_COOKIE_SAMESITE` and `CSRF_COOKIE_SAMESITE` values
- [ ] `gcloud run services describe` shows an explicit `maxScale`
- [ ] A GCP budget alert exists and has fired at least once in a test (lower the threshold temporarily to prove the notification path works, then restore it)
- [ ] The Android TWA is verified working against the deployed revision
- [ ] `docs/runbook.md` documents all three ceilings and how to change them

## Out of scope

- Per-household cost attribution or token accounting → **E07**
- Model downgrading to reduce cost → **E09**
- Replacing `/admin/login/` with a real login page → **E05**
- Moving the vision call off the request → **E10**

## Open questions

1. **What is the monthly spend threshold** for the budget alert and the OpenAI org limit? Needs a number from the owner.
2. **What throttle limits** count as "generous enough that real use never hits them"? Derive from actual usage: query `ChatMessage` grouped by day for the existing user and set the ceiling well above the observed p99.
3. **Django throttling for a non-DRF async view** — DRF throttle classes assume DRF views. Decide between a custom middleware, a decorator, or moving `chat_view` under DRF. Surface the choice in the plan; do not pick silently.

## Skill pipeline

1. `superpowers:writing-plans` — the epic is the spec; open questions 1-2 need owner input first, question 3 is a design decision for the plan
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development`
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `/security-review` — this epic *is* a security change; an independent pass is mandatory
7. `superpowers:verification-before-completion`
8. `superpowers:finishing-a-development-branch`
