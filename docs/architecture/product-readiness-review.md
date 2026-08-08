# Product Readiness Architecture Review — Ledger

**Date:** 2026-08-07
**Reviewed at commit:** `3bbc5ca` (main)
**Scope:** whole system, viewed through one question — *what breaks when this stops being one family's tool and becomes a product other people pay for?*
**Verification:** every finding below cites a file/line or a command output. Test suite was run (`818 passed, 1 failed, 2 skipped`), `manage.py check --deploy` was run clean, migrations were grepped for indexes.

---

## 1. The reframe

Today's architecture is **correct for what it is**: a well-tested, single-operator financial ledger where the operator is also the developer, the DBA, and the only person whose money is at stake. That's not a criticism — a lot of the design choices are right *because* of that framing, and several should survive productization untouched.

Productization changes four premises at once:

| Premise today | Premise as a product |
|---|---|
| One trusted user; `user` FK is the only boundary | Untrusted strangers; a leak is a breach of *someone else's* bank history |
| LLM spend is your own bill, self-limiting | LLM spend is unbounded and adversarial; it must be metered before it's monetized |
| Downtime is an annoyance you notice yourself | Downtime is churn you learn about from a support email |
| You are the auth system (`/admin/login/`) | Signup, recovery, verification, and abuse controls must exist |

Everything in §3 falls out of those four rows.

---

## 2. Requirements

### 2.1 Functional (as-built, verified)

Conversational entry registration (text / voice / receipt photo) via a single PydanticAI agent with ~30 tools; monthly cockpit (income, systematic expenses, installment plans, card due dates); analytics dashboard over 10 DRF endpoints; budgets with ceilings and alerts; 4-step CSV importer; run-rate projection with what-if simulation; pgvector-backed user memory rules; PWA + Android TWA delivery.

### 2.2 Functional gaps that are *product* requirements, not features

Self-service signup, email verification, password reset. Household / shared-ledger access. Subscription and payment. Usage metering and quota display. Data export and account deletion. Privacy policy and terms. Support/impersonation tooling that doesn't mean handing out Django admin.

### 2.3 Non-functional targets (proposed — these are the numbers to argue about)

| Category | Target | Current state |
|---|---|---|
| Availability | 99.5% (≈3.6h/mo) at launch, 99.9% at 500 paying users | Unmeasured; Cloud Run `min-instances=0` means cold start on first request |
| Page load (dashboard, p95) | < 2.5s including 10 card fetches | Unmeasured |
| API latency (p95) | < 300ms per dashboard card | Unmeasured; no indexes (§3 H1) |
| Assistant first token (p95) | < 3s text, < 12s receipt photo | Unmeasured |
| RPO / RTO | RPO 24h → 1h; RTO 4h | Supabase automated backups only, retention unverified, restore never rehearsed |
| LLM cost per active user | Hard ceiling, enforced, < 30% of subscription price | **No ceiling of any kind** |
| Data residency | `southamerica-east1` + Supabase BR region (LGPD) | Already true — keep it |
| Security | No cross-tenant read path; all writes CSRF-protected; login rate-limited | Isolation is good (§4); CSRF and rate-limit gaps (§3 B2, B3) |

---

## 3. Findings

Severity is "what happens if you launch without fixing it."

### BLOCKERS — do not take a paying external user until these are closed

#### B1 · There is no product authentication surface; Django admin is the front door

`config/settings.py:168` → `LOGIN_URL = "/admin/login/"`. A grep across `config/`, `core/`, and `finances/urls.py` for `signup|register/|password_reset|allauth|invite` returns nothing. `config/urls.py:16` routes `admin/` publicly, and the Cloud Run service is deployed `--allow-unauthenticated` (`docs/deploy/next-session-kickoff.md:62`).

Consequences: no way for a user to create an account, recover a password, or verify an email. Worse, every model is registered in admin (`finances/admin.py`, 8 registrations; `assistant/admin.py` registers `ChatMessage` — i.e. every user's raw conversation). One compromised staff password reads every tenant's complete financial history and chat log. There is no login rate limiting anywhere (grep for `throttle|ratelimit|quota` across the backend: zero hits) — your own backlog already flags this (`docs/deploy/next-session-kickoff.md:39`).

#### B2 · The LLM path has no rate limit, no quota, and no cost accounting

`assistant/views.py:140` `chat_view` accepts, per request, up to `ASSISTANT_MAX_IMAGES=5` images at `ASSISTANT_MAX_IMAGE_MB=10` each, and routes them to a vision model (`settings.LLM_VISION_MODEL`, default `openai:gpt-5.4`). There is no cap on requests per user per day, no token accounting, no spend ceiling, and Cloud Run is deployed without `--max-instances` (default 100).

A single authenticated user in a loop — or a buggy client retrying — can generate essentially unbounded OpenAI charges against your key. There is also no record of *what any user cost you*, which means you cannot price the product, cannot detect abuse, and cannot answer "is this customer profitable?"

This is the highest-consequence gap in the review. Monetizing an unmetered LLM is how AI products die.

#### B3 · CSRF verification is disabled on the endpoint that can create and delete money

`assistant/views.py:138` → `@csrf_exempt` on `chat_view`. The comment above it says the React widget sends `X-CSRFToken` from the cookie — but nothing on the server checks it. The agent behind this endpoint can call `register_entry`, `update_entry`, `delete_entry`, `commit_receipt`, `set_income` (the `MUTATING_TOOLS` set at `assistant/views.py:24`).

The only thing protecting it today is Django's default `SESSION_COOKIE_SAMESITE = "Lax"`, which is implicit — it isn't set in `settings.py`, isn't asserted by `core/tests/test_deploy_settings.py`, and is exactly the kind of default that gets changed to `"None"` when someone needs a third-party embed or a webview to work. Fix: drop `csrf_exempt`, keep sending the header, and pin `SESSION_COOKIE_SAMESITE`/`CSRF_COOKIE_SAMESITE` explicitly with a test.

#### B4 · The CSV importer is instance-affine and size-unbounded — it will break on Cloud Run under load

`finances/views/importer.py:35-60`: step 1 writes the upload to `tempfile.NamedTemporaryFile(delete=False)` on **local disk** and stores the *filesystem path* in the session. Step 2 (`:131`) re-opens that path.

Three failures:
1. **Cross-instance.** Cloud Run runs concurrency-80 with up to 100 instances. Step 2 can land on an instance that has never seen that file → `FileNotFoundError`, unhandled. This is latent today only because traffic is one user on one warm instance.
2. **Unbounded size.** No limit on the upload. Cloud Run's writable filesystem is RAM-backed against a 1Gi limit (`--memory 1Gi`) — a large CSV OOM-kills the instance, taking every concurrent request with it.
3. **Session bloat.** The entire parsed row set is serialized into the DB-backed session (`:181`, `:186`) and rewritten on each step. A few thousand rows makes every request in the wizard read and write a multi-megabyte session row.

Fix: a durable `ImportJob` model + object storage (GCS) for the file, with an explicit size cap. See ADR-006.

#### B5 · The data model has no tenant above the individual user — decide this before you have customers

Every model is `FK(settings.AUTH_USER_MODEL)`: `Entry`, `Income`, `Category`, `PaymentMethod`, `Budget`, `InstallmentPlan`, `SystemicExpense`, plus `ChatMessage`, `MemoryRule`, `MemoryEmbedding`, `ReceiptDraft`. `docs/deploy/production-roadmap.md:4` states the design premise outright: *"usuário único (`bessavagner`)"*.

The product you described — family finances — almost certainly needs two people sharing one ledger. Retrofitting a `Household` tenant after launch means a data migration across 10 models, rewriting the scoping predicate in 6 view modules and 40+ functions in `assistant/agents/tools.py`, and doing it on live customer data. Doing it now, pre-launch, is a bounded refactor with a green test suite to catch you. See ADR-001.

---

### HIGH — fix inside the first two months of paid operation

#### H1 · The database has zero indexes

`grep -rn 'Index' */migrations/*.py` returns **nothing** across all 16 migrations, and no model declares `Meta.indexes`. The only indexes that exist are the automatic FK indexes and the unique constraints.

`billing_month` is the single hottest predicate in the application — the dashboard fires 10 API calls, and nearly every one filters `user + billing_month` (`finances/api/views.py:33, 96, 161, 231, 271, 295`). Those queries can only use the `user_id` index and then filter the rest in memory. At one user with ~2000 entries that's invisible; at 1000 users it's the first thing that falls over.

Add: `(user, billing_month)`, `(user, date)`, `(user, entry_type, billing_month)` on `Entry`; `(user, month)` on `Income`; `(user, status, -created_at)` on `ReceiptDraft`.

#### H2 · No pgvector index on the embedding column

`assistant/models.py:114` declares `VectorField(dimensions=1536)`; no migration creates an `HnswIndex` or `IvfflatIndex`. `find_semantic_matches` (`assistant/agents/memory.py:28`) therefore computes cosine distance across every one of the user's embeddings sequentially, on every assistant turn that consults memory. Correct, just linear. Add an HNSW index with `vector_cosine_ops` before memory rules become a selling point.

#### H3 · There is no observability

`config/settings.py:115-127` is the whole story: one `StreamingHandler` to console at INFO, `django.request` at ERROR. No error tracker (no Sentry in `pyproject.toml`), no request IDs, no structured logging, no metrics, no alerting, no LLM tracing — despite PydanticAI shipping first-class Logfire integration that would give you per-run token counts and tool traces for free.

Practical consequence: production failures are discovered when a customer emails you, and diagnosed by scrolling Cloud Run logs. That is survivable for one user who is also the developer. It is not survivable for a paid product, and it's a prerequisite for B2 (you cannot meter what you don't instrument).

#### H4 · No background job infrastructure — all slow, failure-prone work runs inline

Audio transcription (`assistant/services/transcription.py`), receipt vision extraction (`assistant/agents/extraction.py`), and embedding generation (`assistant/services/embedding.py`) all execute inside the HTTP request, and the SSE stream holds the connection for the whole agent run (`--timeout 300`). Every DB-touching agent tool is wrapped in `sync_to_async` (~30 call sites in `assistant/agents/assistant.py`), so each turn occupies threadpool slots on a 1-CPU instance serving up to 80 concurrent requests.

There is also no retry and no dead-letter path: `_handle_audio` catches the transcription failure and returns a 502 with the user's voice note gone (`assistant/views.py:214-223`) — the media is discarded by design, so the user must re-record. Fine for you; a support ticket from a customer.

#### H5 · Swallowed exceptions inside `@transaction.atomic` will abort whole imports

`finances/views/importer.py:268` wraps `ImportExecuteView.post` in `@transaction.atomic`; the per-row loop at `:363-364` does `except Exception: error_count += 1`. If any row raises a *database* error (an `IntegrityError` from a unique constraint, say), the Postgres transaction is already poisoned. The loop keeps issuing queries, every one raises `TransactionManagementError`, and the import dies — reporting a misleading `error_count` on the way out. Wrap each row in its own `with transaction.atomic():` savepoint.

#### H6 · CI on main is red, from a time-bomb test

The suite currently reports `1 failed, 818 passed, 2 skipped` (README claims "817 passing, 1 skipped" — stale). The failure is `finances/tests/test_views_projection.py::TestEstimateToggle::test_teto_param_uses_ceiling`, which hardcodes `?start=2026-07`. That month is now in the past, so the ceiling estimator no longer applies and `diverse_estimated` comes back `Decimal("0")` instead of `Decimal("9999")`. Two sibling tests in the same class share the hardcoded month and will rot the same way.

The bug isn't the assertion, it's that date-sensitive tests read the wall clock. Freeze time (a `freezegun`/`time_machine` fixture, or inject `today`) — `_parse_start(request, today)` already takes `today` as a parameter, so the seam exists.

#### H7 · A single settings module where one env var un-hardens production

All production hardening lives behind `if not DEBUG:` (`config/settings.py:108-110, 234-244`). A stray `DEBUG=True` in the Cloud Run environment silently disables SSL redirect, secure cookies, HSTS, and nosniff — simultaneously and without an error. `core/tests/test_deploy_settings.py` guards against regression, which is genuinely good, but it's testing around a fragile shape. Split `settings/{base,dev,prod}.py` so production hardening is unconditional in the module prod actually loads.

---

### MEDIUM — plan for these, they shape the roadmap

| # | Finding | Evidence |
|---|---|---|
| M1 | **No real i18n.** `USE_I18N=True` and `LOCALE_PATHS` are configured but there is no `locale/` catalog and no `gettext` usage. Portuguese is hardcoded in Python: alert strings (`finances/api/views.py:215-252`), every agent tool return string (`assistant/agents/tools.py`), and all agent prompts (`assistant/agents/prompts.py`). Brazil-only is a legitimate strategy — just make it a decision, not an accident. | grep |
| M2 | **Currency, timezone, and locale are global constants.** `TIME_ZONE = "America/Sao_Paulo"`, `R$` hardcoded in templates, and money is returned from the API pre-formatted as strings (`f"{cur['income']:.2f}"`). Per-user timezone/currency doesn't exist, and string-formatted money means the frontend can't reformat or aggregate. | `settings.py:138`, `api/views.py:75-79` |
| M3 | **`Entry.save()` does hidden per-row queries.** `finances/models/entry.py:59-66` reads `self.payment_method.type` and calls `resolve_closing_day(self.payment_method, ...)`. The importer creates entries one at a time in a Python loop (`importer.py:351`), so a 2000-row import is ~6000 queries. Also: zero `select_related` in `importer.py` and `dashboard.py`. | file:line |
| M4 | **No LGPD posture at all.** No data export, no account deletion, no privacy policy, no terms (all verified absent). Chat history is retained indefinitely — `ChatMessage` has no TTL and no purge command — and its content is transmitted to OpenAI. Holding financial records plus LLM-derived inferences about spending behavior, for money, with no lawful-basis statement and no deletion path is a compliance gap, not a missing feature. | grep |
| M5 | **No audit trail.** After the fact you cannot tell whether an `Entry` was created by the user, by the agent, or by a CSV import. `ChatMessage.metadata` exists and is unused. For a money product, provenance on every mutation is table stakes for support. | `finances/models/entry.py` |
| M6 | **Frontend is unverified in CI.** `pnpm build` runs `tsc` inside the Docker build, so type errors do fail the image — but CI (`.github/workflows/ci.yml`) has no frontend step at all: no lint, no tests, no typecheck. `mount.js` and `tailwind.css` are committed artifacts that drift from source in local dev. | ci.yml, `git ls-files src/backend/static` |
| M7 | **No deploy pipeline, no staging, no rollback.** Deploy is a manual `gcloud run deploy --source .` from a laptop with no git remote (`docs/deploy/next-session-kickoff.md:24`). No staging environment, no migration ordering guarantee, no documented rollback, and `docs/runbook.md` (the operator doc this repo's conventions call for) does not exist. | file:line |
| M8 | **`find_matching_rules` is O(rules) in Python.** `assistant/agents/memory.py:14-24` loads every rule for the user and substring-matches in a loop. Correct, and a latency floor that grows with engagement. | file:line |
| M9 | **User deletion cascades the ledger with no export gate.** `Entry.user` is `on_delete=CASCADE`. Combined with M4, "delete my account" either doesn't exist or is irreversible data destruction with no portability step first. | `finances/models/entry.py:17` |

---

## 4. What is already right — preserve these under refactor pressure

Being specific, because these are the parts that make productization viable at all:

- **Tenant scoping is disciplined *and tested*.** Every DRF view filters on `request.user`; every agent tool takes `user` as its first parameter and receives it from `ctx.deps` — never from LLM-supplied input, which is the mistake that makes agentic apps leak. And it's verified: cross-user isolation tests asserting 404 exist across ~8 modules (`test_entry_edit_modal.py:71`, `test_cockpit_income_views.py:39`, `test_cockpit_vencimentos.py:73`, `test_installment_preview.py:49`, `test_views_entries.py:96`, `test_settings_income_groups.py:73`, `test_installment_month.py:61`, `test_cockpit_parcelamentos_views.py:56`). That habit is the single biggest asset in this codebase for going multi-tenant.
- **"The LLM decides intent; deterministic Python does the arithmetic."** Actually followed, not just claimed. Discount proration, billing-month computation, and projections are Python with unit tests. Keep this line absolutely fixed.
- **The hybrid HTMX + React-islands shape is a good fit** and should not be rewritten. CRUD stays server-rendered; only the dashboard and chat carry React. One deployable, trivial ops.
- **Quality gates are real:** 818 tests, ≥80% coverage enforced in CI, ruff with `flake8-bandit` and `flake8-django`, pre-commit, and `manage.py check --deploy` passes clean (verified — only the injected test SECRET_KEY warning).
- **Hard-won invariants are encoded, not commented:** the one-pending-draft rule (`assistant/views.py:307-310`), duplicate-receipt detection (`find_registered_duplicate`), and the Supabase transaction-pooler workarounds (`settings.py:84-94`) each trace to a specific production incident.
- **Media is processed and discarded.** Privacy-by-default on voice and images is already the behavior, which is a real head start on M4.

---

## 5. Target architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser / Android TWA / iOS PWA                                          │
│  HTMX + Alpine pages          React islands (dashboard, chat)             │
└───────────┬──────────────────────────────┬───────────────────────────────┘
            │ HTML                          │ JSON / SSE
            ▼                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Cloud Run — Django (ASGI)          --max-instances SET, --min-instances 1 │
│                                                                            │
│  NEW: accounts app          finances app          assistant app            │
│  • Household (tenant)       • models/services     • agent + tools          │
│  • Membership/roles         • billing logic       • receipt/voice pipeline │
│  • signup/verify/reset      • DRF API             • quota check PRE-call   │
│  • data export / delete     • audit trail         • UsageRecord POST-call  │
│                                                                            │
│  NEW: billing app                 NEW: middleware                         │
│  • Plan, Subscription             • request ID + structured logs           │
│  • UsageRecord (tokens, $)        • per-user throttle (login + assistant)  │
│  • quota enforcement              • tenant resolution                      │
└──────┬────────────────┬──────────────────┬──────────────────┬────────────┘
       │                │                  │                  │
       ▼                ▼                  ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────────────┐
│ Supabase     │ │ Cloud Tasks  │ │ GCS bucket     │ │ Sentry + Logfire │
│ Postgres     │ │ • transcribe │ │ • CSV imports  │ │ • errors         │
│ + pgvector   │ │ • vision OCR │ │ • data exports │ │ • LLM traces     │
│ + INDEXES    │ │ • embeddings │ │ (lifecycle TTL)│ │ • token counts   │
│ (BR region)  │ │ • retry/DLQ  │ └────────────────┘ └──────────────────┘
└──────────────┘ └──────┬───────┘
                        ▼
              ┌────────────────────┐   ┌─────────────────┐
              │ OpenAI (metered)   │   │ Stripe / Pagar.me│
              └────────────────────┘   └─────────────────┘
```

Deliberately **still one deployable**. Nothing in §3 is solved by splitting services; most of it is solved by adding three Django apps, a queue, indexes, and instrumentation.

---

## 6. Architecture Decision Records

### ADR-001: Introduce `Household` as the tenancy boundary

**Status:** Proposed — **this is the decision to make first; everything else depends on it**

**Context.** All 10 domain models are scoped by `FK(user)`. The product premise is family finance, which implies two or more people sharing one ledger. The current design was explicitly single-user (`docs/deploy/production-roadmap.md:4`). Post-launch this becomes a migration on live financial data touching 6 view modules and 40+ tool functions; pre-launch it's a bounded refactor with 818 tests as a safety net.

**Decision.** Add an `accounts` app with `Household` and `Membership(user, household, role)`. Re-point every domain model's tenant FK from `user` to `household`, keeping `created_by = FK(user)` for provenance (which also delivers M5). Resolve the active household once in middleware onto `request.household`. Enforce scoping in a single place — a `HouseholdScopedQuerySet` manager plus a `TenantScopedMixin` — rather than repeating `filter(user=...)` at ~200 call sites.

For the agent, change `deps_type` from `User` to a small `AgentDeps(user, household)` dataclass. The existing discipline (tools take the scope explicitly, never from model input) transfers directly.

**Consequences.**
- *Positive:* shared ledgers become a feature rather than a rewrite; scoping logic centralizes into one auditable class; `created_by` gives you the audit trail for free; per-household quota (ADR-003) becomes the natural billing unit.
- *Negative:* a large mechanical refactor (~10 models, one data migration, every query, every tool signature) before you ship anything user-visible. Every existing cross-user isolation test needs to become a cross-household test. Roughly 2-3 focused weeks.
- *Neutral:* single-person households are just `Household` with one `Membership` — no special case.

**Alternatives considered.**
- *Keep per-user, add sharing later.* Rejected: it's the same work, done later, on production data, with customers watching. The cost only goes up.
- *Postgres Row-Level Security as the boundary.* Rejected for now: Supabase's transaction pooler already forced off server-side cursors and prepared statements (`settings.py:84-94`), and RLS needs a reliable per-transaction session variable through pgbouncer. Too much coupling to a pooler you've already had to work around. Revisit as defense-in-depth once ADR-001 lands.
- *Schema-per-tenant.* Rejected: absurd operational cost for consumer-scale tenants; migrations become O(tenants).

---

### ADR-002: Keep the modular monolith

**Status:** Proposed (accept — do nothing)

**Context.** Every problem in §3 is a *missing capability* (metering, auth, indexes, observability, queue), not a *coupling* problem. Team size is one. Deployment is one Cloud Run service.

**Decision.** Stay a single Django deployable through at least 10k users. Enforce modularity with app boundaries and service-layer functions (which the codebase already does — `finances/services/`, `assistant/services/`), not network boundaries. Add `accounts`, `billing`, and `observability` as apps.

**Consequences.** *Positive:* one thing to deploy, debug, and pay for; transactional consistency across domains stays free; a solo maintainer can hold it in their head. *Negative:* the whole app scales as one unit, so a receipt-vision spike competes with dashboard traffic for the same instances (mitigated by ADR-004 moving that work off-request); no independent language/runtime choice per component. *Neutral:* if one component genuinely needs separate scaling later, service-layer boundaries make extraction mechanical.

**Alternatives.** *Microservices:* rejected — operational cost exceeds the entire engineering budget at this size. *Extract the assistant as its own service:* rejected for now — it shares the domain models heavily; ADR-004 gets the actual benefit (isolating slow work) at a fraction of the cost.

---

### ADR-003: Meter and cap LLM spend before charging anyone

**Status:** Proposed — **highest-consequence item in this review**

**Context.** B2: no rate limit, no quota, no cost accounting on a path that calls a vision model with up to 50MB of images per request, with Cloud Run scaling to 100 instances. You cannot price a product whose marginal cost you don't measure, and you cannot survive a customer whose marginal cost is unbounded.

**Decision.** Three layers, in this order:

1. **Instrument first.** A `UsageRecord(household, user, kind, model, input_tokens, output_tokens, cost_estimate, created_at)` written after every LLM call. PydanticAI exposes per-run usage (`result.usage()`), so this is a wrapper around the existing call sites, not a rewrite. Wire Logfire simultaneously (ADR-005) for traces.
2. **Then throttle.** DRF throttle classes plus a per-household daily counter for assistant turns, checked *before* the model call. Separate, tighter limits on the image path (it's ~20× the cost of a text turn). Also throttle `/admin/login/` — B1.
3. **Then quota.** A monthly allowance per plan (e.g. 200 assistant turns / 50 receipts), enforced at the same pre-call checkpoint, with remaining balance visible in the UI. Overage either blocks with a clear message or bills — a pricing decision, but the enforcement point is the same.

Also set `--max-instances` on Cloud Run and a GCP billing alert. These are two commands and they cap the blast radius today, before any code lands.

**Consequences.** *Positive:* the marginal cost per customer becomes a number you can query, which is what makes pricing possible; abuse becomes visible and bounded; per-user cost anomalies become a support signal. *Negative:* a real cost ceiling means real "you've hit your limit" UX, which is friction on your best feature. Choose limits generously — the goal is catching pathology, not rationing. *Neutral:* `UsageRecord` doubles as the analytics table for "which features justify their cost."

**Alternatives.** *Trust users, watch the OpenAI dashboard:* rejected — detection lags the bill by hours and there's no per-user attribution. *Per-user API keys:* rejected — unacceptable consumer UX. *Cap at the OpenAI org level only:* rejected — one abusive user then denies service to everyone.

---

### ADR-004: Move slow work off the request with Cloud Tasks

**Status:** Proposed

**Context.** H4: transcription, vision extraction, and embedding all run inline on a 1-CPU Cloud Run instance serving up to 80 concurrent requests, with no retry and no dead-letter path. The SSE stream additionally pins a connection for the whole agent run.

**Decision.** Cloud Tasks with authenticated HTTP targets on the same Django service (`/tasks/<name>/`, OIDC-verified). Move transcription, receipt extraction, embedding generation, CSV import execution, and data export to tasks. Keep the *conversational* agent turn synchronous — streaming is the product — but make everything it waits on cancellable and instrumented.

**Consequences.** *Positive:* no new stateful infrastructure (contrast Redis/Celery); retry, backoff, and dead-lettering are managed; the same container serves web and tasks, so no second image; slow work stops competing with page loads. *Negative:* tasks are HTTP round-trips, so payloads must be small and handlers idempotent; local development needs an emulator or a synchronous fallback path; Cloud Run's request-scoped CPU means a task handler must finish inside its timeout. *Neutral:* couples you to GCP — acceptable, you're already on Cloud Run + Secret Manager.

**Alternatives.** *Celery + Redis:* rejected — adds a stateful dependency to pay for and operate, and the roadmap already deliberately removed Redis (`production-roadmap.md`, Phase 1 item 5). *`django-tasks` / DB-backed queue:* viable and simpler, but needs a worker process Cloud Run doesn't naturally host, and puts queue load on the pooled Supabase connection you've already had to tune. *Do nothing:* rejected — H4 degrades exactly when growth arrives.

---

### ADR-005: Observability — Sentry for errors, Logfire for the agent, Cloud Monitoring for infra

**Status:** Proposed

**Context.** H3: console logging only. This also blocks ADR-003 (can't meter what you don't instrument) and makes every future performance claim unfalsifiable.

**Decision.** Sentry for exceptions and performance traces, with PII scrubbing configured — this app handles financial descriptions and chat content, so default-capturing request bodies would be a privacy incident. Logfire for PydanticAI runs, which gives per-run token counts, tool-call traces, and latency natively. Structured JSON logging with a request-ID middleware so Cloud Logging entries correlate. Uptime check on `/healthz/` with an alert. Golden-signal dashboards: request rate, error rate, p95 latency, assistant turns/day, LLM spend/day.

**Consequences.** *Positive:* MTTR drops from "customer emails you" to minutes; the NFR table in §2.3 becomes measurable instead of aspirational; agent regressions become visible rather than anecdotal. *Negative:* two vendors, two more secrets to rotate, and a real PII-scrubbing config that must be tested, not assumed. Small per-request overhead. *Neutral:* both have free tiers adequate for launch scale.

**Alternatives.** *Cloud Logging + Error Reporting only:* rejected — no LLM-level visibility, weaker triage. *Self-hosted OpenTelemetry + Grafana:* rejected — an infrastructure project competing with the product for the same single engineer.

---

### ADR-006: Durable import/export jobs on object storage

**Status:** Proposed

**Context.** B4: local temp files plus session-stored paths plus multi-megabyte session payloads, on a horizontally-scaled stateless runtime. Also M4 needs a data-export path, which has exactly the same shape.

**Decision.** An `ImportJob(household, created_by, gcs_path, status, mapping, stats, created_at)` model. Uploads go straight to a GCS bucket with an enforced size cap and a lifecycle rule that deletes objects after N days. The wizard reads job state from the database, not the session. Execution runs as a Cloud Task (ADR-004) with per-row savepoints (fixing H5). Data export (M4) reuses the model and bucket in reverse, delivered as a signed, expiring URL.

**Consequences.** *Positive:* correct on any number of instances; large imports stop being an OOM risk; progress and history become visible and resumable; failed rows get a real report; LGPD portability comes almost free. *Negative:* a new GCS dependency plus IAM setup; the wizard's four steps need rewiring from session to job state; local dev needs a filesystem-backed storage fallback. *Neutral:* signed URLs let the browser upload directly, taking the payload off Django entirely.

**Alternatives.** *Sticky sessions:* rejected — Cloud Run doesn't offer them, and it wouldn't fix size or resumability. *Keep everything in the DB-backed session:* rejected — B4's third failure mode.

---

### ADR-007: `django-allauth` for the authentication surface

**Status:** Proposed

**Context.** B1: no signup, no verification, no password reset; `/admin/login/` is the front door; no login rate limiting.

**Decision.** `django-allauth` for email signup, mandatory verification, password reset, and (later) social login. Set `LOGIN_URL` to a product page and separate the admin login entirely. Restrict `/admin/` behind Cloud Run IAM or an IP allowlist plus staff-only 2FA. Add login throttling (allauth ships rate limits; `django-axes` if you want lockout too). Household invitations (ADR-001) ride on allauth's email infrastructure.

**Consequences.** *Positive:* a battle-tested implementation of the flows that are easy to get subtly wrong; email infrastructure shared with invites and export notifications; a clean seam for social login when signup friction matters. *Negative:* a heavyweight dependency with opinionated templates that need restyling to match the DaisyUI design; you now operate transactional email (deliverability, SPF/DKIM, a provider bill). *Neutral:* forces the `/admin/` decision you should make anyway.

**Alternatives.** *Hand-rolled on Django's `contrib.auth` views:* rejected — those flows are exactly where homegrown auth leaks, and you'd rebuild verification and throttling yourself. *Supabase Auth:* rejected — splits identity from the Django user model that 10 models FK to; the impedance mismatch outweighs the convenience. *Keep admin login:* rejected — B1.

---

### Decisions still open (need your input, not mine)

| # | Decision | Why it's yours |
|---|---|---|
| D1 | Single-market pt-BR, or i18n from the start? | Determines whether M1/M2 are a 3-week project or a non-issue. Pricing in BRL and LGPD-only compliance is a coherent, cheaper strategy — just choose it deliberately. |
| D2 | Pricing model — flat, tiered, or usage-based? | ADR-003's enforcement point is the same either way, but the *limits* and the overage UX differ completely. |
| D3 | Payment provider — Stripe or a Brazilian PSP (Pagar.me/Asaas)? | Pix and boleto are effectively mandatory for Brazilian consumers; Stripe's Pix support is narrower. Materially affects the `billing` app. |
| D4 | Is the AI assistant core, or a premium add-on? | If core, ADR-003's quotas must be generous and the cost lands in the base price. If premium, it's a separate metered SKU and the free tier is the HTMX app. |
| D5 | Supabase, or migrate to Cloud SQL? | Supabase's transaction pooler has already cost you two workarounds (`settings.py:84-94`) and blocks the RLS option. Cloud SQL + the Cloud Run connector removes both. Worth costing out before customer data makes it hard. |

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Runaway LLM spend from abuse or a client retry loop | **High** | **Severe** — could exceed all revenue in days | ADR-003. Today, immediately: set `--max-instances` and a GCP billing alert (two commands). |
| Cross-tenant data leak during the household refactor | Medium | **Severe** — breach of financial records, LGPD reportable | Centralize scoping in one manager (ADR-001); convert every existing cross-user test to cross-household; add a test that fails if any domain model lacks the tenant FK. |
| Importer breaks in production once traffic scales past one instance | **High** | Medium — feature-level outage, confusing failure | ADR-006. Until then, cap `--max-instances 1` for the importer path or accept it's single-instance-only. |
| Compromised staff account reads every tenant's finances and chats | Medium | **Severe** | ADR-007: gate `/admin/`, staff 2FA, remove `ChatMessage` from admin or redact it, add admin access logging. |
| Restore has never been rehearsed; RTO/RPO are assumptions | Medium | **Severe** — unrecoverable customer data loss | Rehearse a full Supabase restore into a scratch project, time it, write it into `docs/runbook.md`. Do this before the first paying customer, not after. |
| LGPD complaint or data-subject request you cannot fulfil | Medium | High — fines, forced shutdown | M4 + ADR-006: export, deletion, retention policy, privacy notice, chat-history TTL. |
| Cold start (`min-instances=0`) makes first impressions terrible | **High** | Medium — conversion loss | `--min-instances 1` once revenue covers it; already flagged in your own backlog. |
| Time-bomb tests keep turning CI red, eroding trust in the suite | **High** | Medium | H6: freeze time in date-sensitive tests; add a scheduled nightly CI run so rot surfaces on its own schedule, not during a release. |
| Sole maintainer is a single point of failure | **High** | High | `docs/runbook.md` (doesn't exist yet), automated deploy, ADRs like this one. Bus factor is an architecture concern. |
| OpenAI outage or model deprecation | Medium | High — the headline feature dies | PydanticAI already abstracts the provider; add a configured fallback model and a degraded mode where manual entry stays fully usable. |

---

## 8. Sequenced roadmap

Ordered by dependency, not by appeal. Each phase has an exit test.

**Phase 0 — Stop the bleeding (days, mostly config)**
Set Cloud Run `--max-instances` and a GCP billing alert. Remove `@csrf_exempt`, pin the SameSite settings, add a test (B3). Fix the red test with a frozen clock (H6). Add the `Entry`/`Income` indexes (H1) and the HNSW index (H2) — one migration. Throttle `/admin/login/`.
*Exit:* CI green, `check --deploy` clean, a spend ceiling that exists.

**Phase 1 — Make it a tenanted product (the big one, ~6-8 weeks)**
ADR-001 (household + centralized scoping + `created_by`), ADR-007 (allauth, admin gated), ADR-005 (Sentry + Logfire + request IDs), then ADR-003 step 1-2 (UsageRecord + throttling — Logfire first, because metering needs instrumentation).
*Exit:* two people share a ledger; a stranger can sign up, verify, and reset a password; every LLM call has a cost record; no request escapes tenant scoping.

**Phase 2 — Make it operable and sellable (~4-6 weeks)**
ADR-004 (Cloud Tasks), ADR-006 (import/export jobs, fixes B4 + H5 + LGPD portability), ADR-003 step 3 (plan quotas), the `billing` app against D3's provider, split settings (H7), `docs/runbook.md` with a *rehearsed* restore, staging environment + automated deploy (M7).
*Exit:* someone pays, is charged correctly, hits a quota gracefully, exports their data, deletes their account — and you can restore the database inside your stated RTO.

**Phase 3 — Growth (ongoing)**
Whatever D1 decided about i18n (M1/M2), audit trail surfaced in the UI (M5), frontend CI (M6), query optimization as `UsageRecord` and Sentry traces point at it (M3, M8), per-user timezone/currency.

---

## 9. The short version

The engineering here is better than most side projects that try to become products: the tenant-scoping discipline is real and tested, the "LLM proposes, Python computes" boundary is genuinely held, and 818 tests with an enforced coverage gate is not common. The architecture is *shaped* right — it is a modular monolith that should stay one, and the hybrid HTMX/React split is a good call, not a compromise.

What's missing is not architecture; it's the entire product layer that a single-user tool never needed. Three things gate everything else:

1. **Meter the LLM before you charge for it** (ADR-003). Unbounded marginal cost is the failure mode that kills AI products, and right now there is no ceiling, no quota, and no record of what any user costs.
2. **Decide the tenancy boundary now** (ADR-001). Family finance implies shared ledgers. This refactor is cheap today with a green suite and impossible-feeling later with customer data in it.
3. **Build the front door** (ADR-007). Django admin login is not a signup flow, and `/admin/` reachable by the internet with every model registered is a breach waiting for one weak password.

Everything else in §3 is a well-understood engineering task with a known fix. Those three are decisions, and two of them get more expensive every week you defer them.
