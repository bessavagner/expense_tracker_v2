# Runbook

Operator procedures for the production deployment. Copy-paste as written.

Production is Cloud Run service `expense-tracker`, GCP project
`expense-tracker-482807`, region `southamerica-east1`, fronted by
<https://expense-tracker-654941182076.southamerica-east1.run.app>.

**No load balancer sits in front of this service** (ingress `all`, direct to Cloud Run) — if that ever changes, `core.security.client_ip` (E01's login lockout) must switch from trusting the *last* `X-Forwarded-For` entry to the second-from-right one; see its docstring.

> `gcloud`'s active project defaults to something else on this machine — always
> pass `--project expense-tracker-482807` explicitly.

---

## Deploy a new revision

```bash
gcloud run deploy expense-tracker --source . \
  --project expense-tracker-482807 \
  --region southamerica-east1 \
  --quiet
```

A **bare** deploy (no `--set-env-vars` / `--set-secrets`) preserves the existing
env vars and secrets on the new revision. Prints a long `Building Container...`
progress line, then:

```
Service [expense-tracker] revision [expense-tracker-000NN-xxx] has been deployed
and is serving 100 percent of traffic.
```

**Common failure:** using `gcloud run services update --set-env-vars` instead of
`--update-env-vars`. `--set-env-vars` *replaces the entire env list*, wiping
`DATABASE_URL`, `LLM_MODEL`, and friends. Use `--update-env-vars` (merge) plus
`--remove-env-vars`.

### Smoke test after deploying

```bash
B=https://expense-tracker-654941182076.southamerica-east1.run.app
for p in /healthz/ / /.well-known/assetlinks.json; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" -m 60 "$B$p"
done
```

Expect `200`, `302`, `200`. The assetlinks `200` matters beyond the web app: it
is what lets the Android TWA open without a URL bar. If it breaks, the phone app
starts showing a Chrome address bar.

---

## When something breaks

Three vendors, each doing one job (ADR-005): **Sentry** has the exception,
**Cloud Logging** has the request that produced it, **Logfire** has the agent run
inside it. They are joined by one value — the **request ID**.

> **Status (2026-08-14):** the application side of E06 is merged. The vendor
> accounts, the uptime check and the alert policies are E06 Task 7 and have
> **not** been provisioned yet. Until they are, `SENTRY_DSN` and `LOGFIRE_TOKEN`
> are unset on Cloud Run, which means Sentry and Logfire transmit nothing — the
> Cloud Logging half below works today, the other two do not. Delete this note
> once Task 7 has run.

### Start from the request ID

Every response carries it, including error responses:

```bash
curl -sI https://expense-tracker-654941182076.southamerica-east1.run.app/healthz/ \
  | grep -i x-request-id
```

```
x-request-id: 4f2c9a1e6b7d40f8a3c25e91d7b0c846
```

Ask the reporting user for that header (the browser devtools Network tab shows
it), or read it off the failing response. Then:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision"
   jsonPayload.request_id="4f2c9a1e6b7d40f8a3c25e91d7b0c846"' \
  --project expense-tracker-482807 --limit 50 --freshness 1d \
  --format="value(timestamp,jsonPayload.severity,jsonPayload.message)"
```

Every log line from that one request, in order. `jsonPayload.user_id` and
`jsonPayload.household_id` are on each line too, so
`jsonPayload.household_id="<uuid>"` widens the same query to "everything that
happened to this tenant".

**Common failure:** the query returns nothing and you assume the request never
arrived. Check `textPayload` instead — structured JSON only applies when
`DEBUG=False`; a local run logs plain text, and so does anything that logs
before Django's `LOGGING` config is installed.

**An inbound `X-Request-ID` is adopted, not overwritten** — but only if it is 32
hex characters. Anything else is replaced with a fresh ID, because the value
lands in a log field and a caller does not get to write 500 arbitrary bytes
there.

### The Sentry issue for the same request

Sentry's issue search, with the tag the middleware attaches:

```
request_id:4f2c9a1e6b7d40f8a3c25e91d7b0c846
```

Each event's `release` is the **Cloud Run revision name** (`expense-tracker-000NN-xxx`),
taken from the `K_REVISION` env var Cloud Run injects. To see what that revision
actually contains:

```bash
gcloud run revisions describe expense-tracker-000NN-xxx \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(metadata.annotations['client.knative.dev/user-image'])"
```

**What a Sentry event deliberately does NOT contain.** `core.observability.scrub_event`
strips the request body, cookies, headers, stack-frame locals, `extra`, and
breadcrumb data before anything is transmitted. `url` and `method` survive on
purpose — an event nobody can locate is as useless as no event. So if you are
looking for "what did the user actually type", it is not in Sentry by design;
it is in Logfire.

### The Logfire trace for an agent failure

A run span holds the tool calls in order, the latency of each, the model name,
and the token counts — plus **the full prompt and completion text**, which is
captured by explicit operator decision (2026-08-14, E06 open question 2). That
decision is what makes "read the bad extraction" possible instead of
"reproduce it from scratch".

Turn text capture off without a deploy:

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --update-env-vars LOGFIRE_CAPTURE_CONTENT=0
```

**Receipt photographs are not captured** (`LOGFIRE_CAPTURE_BINARY=0`). That is a
separate flag from the text decision, and turning it on uploads every receipt
image the product has ever seen to a third party.

> **Privacy consequence, for E13:** because prompts and completions are
> captured, Logfire holds chat content and receipt descriptions. That makes
> Pydantic a **data sub-processor** of personal financial data. E13's privacy
> notice must name it, and E13's deletion story must say what happens to trace
> data.

### What is deliberately not reported, so nobody re-adds it

Three sites in `assistant/views.py` call `logger.exception(...)` and have **no**
`sentry_sdk.capture_exception()` next to them — audio transcription failure, and
the two receipt-extraction failures. Sentry's logging integration already turns
an ERROR-level record into an event; adding an explicit capture would
double-report the same failure. Each site carries a comment saying so.

The sites that *do* capture explicitly are the ones that were silent: the
generic chat-stream failure, the `data_changed` computation, and CSV import row
failures (reported **once** per import with a count and the distinct exception
types — never the exception strings, which are built from the offending cell
and would leak user content by a route the scrubber cannot see).

### Who gets alerted, and how

**Pending Task 7.** Two Cloud Monitoring notification channels are planned:
GCP mobile-app **push** (wakes the operator) and **email** to
`bessavagner@gmail.com` (durable record). To test the path without waiting for a
real outage, point the uptime check at a path that 404s until it fires, confirm
the push arrives on the phone, then restore it. An alert that has never fired is
a hypothesis, not an alert.

---

## Spend ceilings

Three independent caps. Each is set to hold if the other two fail, and the app
layer (E01's throttle) sits below all of them.

| Ceiling | Value | Status | Effect when hit |
|---|---|---|---|
| Cloud Run `--max-instances` | 3 (was `20`) | **Live** — carried onto revision `expense-tracker-00040-x7q` | New requests queue rather than starting a 4th billable instance |
| GCP budget alert | BRL 50/month (target was USD 50, see below) | **Live**, alert path **proven** — see below | **Notifies only.** Email at 50%, 80%, 100% |
| OpenAI org monthly limit | USD 30/month hard, USD 20 soft | **Live** — set by the owner in the console (no CLI) | API returns errors — the actual stop |

### Cloud Run max-instances

Applied. Reversal (pre-task value): `--max-instances 20`.

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --max-instances 3
```

Lowering `--max-instances` on a live production service is a real availability
change (it can start queuing requests under a real spike) — run it with a
human watching, not from an unattended session. Confirmed live via the read
command below, which returns `3`.

### The GCP budget alert is billed in BRL, not USD

`gcloud billing projects describe expense-tracker-482807` shows the linked
billing account ("pessoal") bills in **BRL**, not USD, so a USD-denominated
budget cannot be created via this API at all — take the plan's "USD 50/month"
as a target to convert, not a literal value. `gcloud billing budgets create`
requires `--budget-amount`'s currency to match the billing account's currency
and fails with a bare `INVALID_ARGUMENT` (no mention of currency) if it
doesn't. The owner set the live budget at **BRL 50/month**. This is a
deliberate development-phase figure — tight on purpose while the app is in
single-user dogfooding — not the final ceiling; the owner intends to raise it
once self-use ends. Do not "fix" it back up to a closer USD 50 equivalent
without checking with the owner first. It is also a fixed BRL amount that
will not track future FX moves, so revisit it periodically or the day
USD/BRL moves meaningfully.

**Alert path proven:** to confirm the notification actually fires, the
budget was temporarily dropped to `1BRL` at `2026-08-08T16:07:54Z` (ours,
precise, UTC). The owner confirmed receipt of the resulting 50%-threshold
alert email, subject `Budget alert: expense-tracker monthly ceiling`,
displaying the timestamp `Aug 8, 2026, 9:27 AM` as rendered by Google. That
displayed time is in the billing account's configured timezone, not UTC —
Google does not state which timezone in the email itself — so it cannot be
compared directly against the UTC drop time above; do not convert it or
assume an offset. The clock reading is not what proves this was the right
alert — the identifying details in the email are: it names the budget
"expense-tracker monthly ceiling", billing account `01EAA6-4C3E7C-8FE819`,
and project `expense-tracker-482807`. A correctly-identified alert for this
budget arrived after the threshold was crossed, and the owner confirmed
receiving it — that is what the notification path being proven rests on.
The budget has since been restored to BRL 50 — no further action needed.
The restore command, for reference if the budget is ever dropped again to
re-test:

```bash
gcloud billing budgets update <name from the read command below> \
  --billing-project=expense-tracker-482807 \
  --budget-amount=50BRL
```

### Read the current values

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"

BILLING=$(gcloud billing projects describe expense-tracker-482807 \
  --format="value(billingAccountName)"); BILLING=${BILLING#billingAccounts/}
gcloud billing budgets list --billing-project=expense-tracker-482807 \
  --billing-account="$BILLING" \
  --format="table(displayName,amount.specifiedAmount.currencyCode,amount.specifiedAmount.units,name)"
```

**Common failure (operator trap):** every `gcloud billing budgets` command
needs `--billing-project=expense-tracker-482807`. Without it, gcloud bills the
quota to the machine's default project (not `expense-tracker-482807`) and
fails with a `SERVICE_DISABLED` / "does not have permission to access
billingAccounts instance" error that reads like a permissions problem but
isn't — it's the missing flag. `--project` also works for this, but
`--billing-project` is the flag documented for this command family.

The OpenAI limit has no CLI — read it at
<https://platform.openai.com/settings/organization/limits>.

### Change them

```bash
# Instance ceiling
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --max-instances <N>

# Budget amount (BRL — see currency note above). Look up the budget's full
# resource name first; its UUID is deliberately not hardcoded here.
BILLING=$(gcloud billing projects describe expense-tracker-482807 \
  --format="value(billingAccountName)"); BILLING=${BILLING#billingAccounts/}
gcloud billing budgets list --billing-project=expense-tracker-482807 \
  --billing-account="$BILLING" --format="value(name)"

gcloud billing budgets update <name from above> \
  --billing-project=expense-tracker-482807 \
  --budget-amount=<N>BRL
```

**Common failure:** raising `--max-instances` without also raising the OpenAI cap
moves the bottleneck to the expensive layer. Raise the OpenAI limit *first*, or
not at all.

**Why max-instances is this low:** the container is 1 vCPU / 1Gi running a single
gunicorn worker with an async uvicorn worker at concurrency 80 (see *Why the
container starts the way it does*). Three instances is ~240 concurrent requests —
far above real demand, and the point is the ceiling, not the headroom.

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

### Upload ceilings

| Var | Default | Applies to |
|---|---|---|
| `MAX_REQUEST_BODY_BYTES` | 62914560 (60 MB) | every path |
| `MAX_CSV_UPLOAD_BYTES` | 10485760 (10 MB) | `/import/*` |

Enforced in two layers, both from `Content-Length`, both before Django parses
the body:

- `core.asgi_body_limit` wraps the ASGI application itself, ahead of Django's
  own request handling. A declared `Content-Length` over the ceiling is
  rejected with HTTP 413 without reading anything from the client; a chunked
  request with no declared length is read and counted as it streams in, and
  aborted with a 413 the moment the running total crosses the ceiling. This
  layer exists because Django's `ASGIHandler` buffers the *entire* body before
  any Django middleware runs, and its own size check never fires for a request
  with no `Content-Length` — that combination left chunked, unauthenticated
  POSTs completely unbounded before this layer was added.
- `core.middleware.max_request_body_middleware` (Django middleware, directly
  after `SecurityMiddleware`) rejects the same declared-oversized case again,
  before Django's multipart parser or the CSV importer's temp-file copy run.

**Common failure:** a user reports "arquivo grande demais" on a legitimate
multi-photo receipt. `MAX_REQUEST_BODY_BYTES` must stay above
`ASSISTANT_MAX_IMAGES × ASSISTANT_MAX_IMAGE_MB` with room for multipart
overhead. Raising the image limits without raising this one is the usual cause.

### `gcloud run deploy` is sometimes blocked in Claude Code agent sessions

The Claude Code auto-mode permission classifier has denied `gcloud run deploy`
for agent sessions — this held for a regular implementer session and for a
controller session with the owner's authorization already given; the controller
session was also blocked from adding a permission rule for itself.

**It is not a reliable block.** On 2026-08-13 the same bare command ran straight
through in an agent session after the owner said "you can run the deploy command,
I allow" — revision `expense-tracker-00043-th4`. So treat the classifier as a
thing that *may* refuse, not a guarantee that an agent cannot deploy. If it
refuses, do not look for a workaround — an agent granting itself deploy rights is
exactly what the guard is for. **Hand it to the owner instead**, to run directly
from a human-driven terminal:

```bash
gcloud run deploy expense-tracker --source . \
  --project expense-tracker-482807 \
  --region southamerica-east1 \
  --quiet
```

A bare deploy like this preserves existing env vars and secrets. If the
post-deploy smoke test (see the top of this document) fails, roll back to
the last known-good revision:

```bash
gcloud run services update-traffic expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --to-revisions expense-tracker-00039-rg6=100
```

`00039-rg6` is the last revision before E01 and E03 shipped, and rolling back to
it was safe against the schema *at the time*: those epics' migrations only *add*
tables and indexes (plus drop three redundant ones), so the older code neither
missed anything it needed nor tripped over what it did not know about. **Do not
unapply the migrations to roll back the code** — they were not the thing that
breaks.

> **That stopped being true at E04 (2026-08-13).** `finances/0018_drop_user` and
> `assistant/0015_drop_user` **remove** the `user` column from twelve domain
> models, and every revision before `00043-th4` reads it. Rolling back the
> revision alone now produces old code against a schema that no longer has what
> it needs — the same broken state, not a fix. **Recovery is: restore the
> database from the pre-migration dump first, and only then roll back the
> revision.** The dump taken before the E04 deploy is
> `~/e04-preflight-backup/ledger-pre-e04-<stamp>.dump` (472K, `-Fc`).
>
> This also means a column-dropping deploy has an **unavoidable broken window**
> in whichever order you go: migrate first and the live revision breaks until the
> new one is up; deploy first and the new code wants a column that does not exist
> yet. Migrating first is the better half — it is the order that keeps the
> irreversible step next to its verification — but budget for the gap and do the
> two steps back to back. For E04 the window was a few minutes and the app is
> family-scale; do not assume that generalises.

---

## Cold starts: the keepalive job

`min-instances` is **0**, so an idle service scales to zero and the next request
pays a cold start (measured: **~15s**). A Cloud Scheduler job pings `/healthz/`
every 5 minutes during waking hours to keep one instance alive.

> **E06 replaces this job with a Cloud Monitoring uptime check.** The uptime
> check pings `/healthz/` on the same 5-minute interval, so it *is* the
> keepalive — running both would be two pingers doing one job. Once Task 7 has
> created the uptime check, delete the Scheduler job:
>
> ```bash
> gcloud scheduler jobs delete expense-tracker-keepalive \
>   --location southamerica-east1 --project expense-tracker-482807
> ```
>
> **Until that has happened, the Scheduler job below is still the live one** and
> everything in this section applies as written. After it happens, "pause the
> keepalive" below means **pause the uptime check** instead — see the note in
> *Measuring cold start*.

Cloud Run only bills CPU/memory while a request is being served, so the pings
cost roughly **$0.07/month** — versus ~$18.40/month for `min-instances=1` in
this region.

### Inspect it

```bash
gcloud scheduler jobs describe expense-tracker-keepalive \
  --project expense-tracker-482807 --location southamerica-east1 \
  --format="value(state,lastAttemptTime,status.code)"
```

Healthy output is `ENABLED`, a `lastAttemptTime` within the last 5 minutes, and
status code `0`. A non-zero status code means the ping itself is failing — check
that `/healthz/` still returns 200.

### Recreate it from scratch

```bash
gcloud services enable cloudscheduler.googleapis.com --project expense-tracker-482807

gcloud scheduler jobs create http expense-tracker-keepalive \
  --project expense-tracker-482807 \
  --location southamerica-east1 \
  --schedule "*/5 6-23 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "https://expense-tracker-654941182076.southamerica-east1.run.app/healthz/" \
  --http-method GET \
  --attempt-deadline 30s \
  --description "Keeps one Cloud Run instance warm during waking hours"
```

`*/5 6-23 * * *` = every 5 minutes, 06:00–23:59 local. Overnight requests still
hit a cold start by design; widen to `*/5 * * * *` for 24/7 coverage (costs
about $0.03/month more).

**Common failure:** `PERMISSION_DENIED` on create means the Cloud Scheduler API
is not enabled — run the `services enable` line above first.

### Pause it (e.g. to measure a real cold start)

```bash
gcloud scheduler jobs pause expense-tracker-keepalive \
  --project expense-tracker-482807 --location southamerica-east1
# ...and resume
gcloud scheduler jobs resume expense-tracker-keepalive \
  --project expense-tracker-482807 --location southamerica-east1
```

### If you want cold starts gone entirely

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --min-instances 1
```

Billed at the São Paulo (Tier 2) min-instance idle rate — $0.0000035/vCPU-s and
$0.0000035/GiB-s — which at 1 vCPU + 1 GiB is **≈ $18.40/month**. Dropping to
`--memory 512Mi` brings it to ≈ $13.80. The keepalive above gets most of the
benefit for a fraction of that, so prefer it unless a guaranteed-warm SLA
matters.

---

## Measuring cold start

The keepalive must be paused first, then the service needs ~15 minutes of zero
traffic to scale to zero:

> **Pause the right pinger.** Once E06's uptime check exists and the Scheduler
> job is gone, pausing the job below silently succeeds at nothing and the uptime
> check keeps the instance warm — so the "cold" number you measure is a warm
> one. Disable the uptime check instead: *Monitoring → Uptime checks →
> expense-tracker-healthz → Edit → uncheck Enabled*, or
> `gcloud monitoring uptime delete <CHECK_ID>` and recreate it afterwards.
> **Re-enable it when you are done**, because it is also the keepalive.

```bash
gcloud scheduler jobs pause expense-tracker-keepalive \
  --project expense-tracker-482807 --location southamerica-east1
sleep 1020
curl -s -o /dev/null -w "COLD: %{time_total}s\n" -m 120 \
  https://expense-tracker-654941182076.southamerica-east1.run.app/healthz/
```

To see where the time goes, read the boot sequence:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="expense-tracker"' \
  --project expense-tracker-482807 --limit 30 --freshness 20m \
  --format="value(timestamp,textPayload)" | tac
```

The interesting timestamps are `Starting new instance` → `Starting gunicorn` →
`Application startup complete` → the first served request. As of revision
`00038`, everything from the port opening to the first response is ~0.4s; the
remaining ~14s is image pull plus importing the app. **Remember to resume the
keepalive afterwards.**

### Why the container starts the way it does

`Dockerfile`'s `CMD` uses `--workers 1 --preload` deliberately:

- `--preload` makes gunicorn load the app in the master *before* it binds the
  socket. Cloud Run routes the first request the instant the port opens, so
  binding late is what stops a request arriving mid-import.
- `config/warmup.py` (called from `config/asgi.py`) resolves the URLconf at
  import time. Django otherwise does it lazily on the first request, which
  stranded ~14s of view/LLM-SDK imports *after* the startup probe had passed.
- `--workers 1` because the container has 1 vCPU and the uvicorn worker is async
  at concurrency 80; a second worker added no throughput and doubled boot
  imports and memory.

Removing any of these re-introduces the slow cold start.

---

## Rebuilding the committed frontend artifacts

`src/backend/static/frontend/mount.js` and `src/backend/static/css/tailwind.css`
are **tracked in git**. They are committed so local dev and the Docker build work
without a Node toolchain. CI fails if they drift from their source, so rebuild
and commit both whenever you touch `src/backend/frontend/src/**`,
`src/backend/templates/**`, or `src/backend/static/css/input.css`.

```bash
# React islands
cd src/backend/frontend
CI=true pnpm install --frozen-lockfile
pnpm build            # runs tsc, then vite build -> ../static/frontend/mount.js
cd -

# Tailwind — --force is NOT optional
uv run python src/backend/manage.py tailwind build --force

git add src/backend/static/frontend/mount.js src/backend/static/css/tailwind.css
```

**Both builds are reproducible, but only because both toolchains are pinned.**
`settings.TAILWIND_CLI_VERSION = "2.8.3"` (the tailwind-cli-extra release
carrying tailwindcss 4.2.2) and the Dockerfile's `pnpm@10.23.0` / Node 22, which
CI mirrors. Unpinned, `django-tailwind-cli` resolves *latest* from GitHub at
build time: that is how the committed CSS came to be un-reproducible, built by
4.2.2 while this machine's CLI had moved to 4.3.3 and emitted a file ~32 KB
larger. Upgrading Tailwind is therefore deliberate: bump the pin, rebuild with
`--force`, look at the site, and commit the new CSS in the same commit.

**Common failure #1:** dropping `--force`. Tailwind v4 trusts its cache and emits
CSS that is missing any class you just added to a template. The page renders
unstyled in exactly one place and looks like a template bug.

**Common failure #2:** `ERR_PNPM_IGNORED_BUILDS` (or, on an older pnpm,
`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`) from `pnpm install`. Both mean the
pnpm on your PATH is not the pinned one — pnpm 11 replaced the
`onlyBuiltDependencies` key that `pnpm-workspace.yaml` uses with `allowBuilds`,
fails the frozen install, and **rewrites that tracked file**. Use pnpm 10.23.0.
Note `npx -y pnpm@10.23.0` does not help: it silently runs whatever pnpm is
already on PATH. `npm install --prefix /tmp/pnpm10 pnpm@10.23.0` and run
`/tmp/pnpm10/node_modules/.bin/pnpm`, or install 10.23.0 globally.

**Common failure #3:** a local `vite build --watch` service (systemd `--user`
`expense-tracker-js`) rewriting `mount.js` under you mid-commit. Stop it before
rebuilding by hand.

**Surprise worth knowing:** Tailwind v4 scans *every* source file under
`src/backend`, including `.py`. A prose word in a Python comment that happens to
match a utility name adds that utility to the CSS — a comment containing the word
"grow" is what put `.grow{flex-grow:1}` in the stylesheet. So a commit that
touches only comments can legitimately require a CSS rebuild, and the CI gate
will say so.

---

## Applying a migration to Supabase

Migrations go through the **direct/session connection on port 5432**, never the
transaction pooler on 6543 — the pooler is pgbouncer in transaction mode and does
not support everything a migration needs. The app runtime uses 6543; migrations
do not.

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  uv run python src/backend/manage.py migrate
```

For anything schema-heavy — a new index, a column type change — rehearse it on a
restored copy first:

```bash
pg_dump "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  --no-owner --no-acl -Fc -f /tmp/ledger-prod.dump
createdb -h HOST -p 5432 -U USER ledger_rehearsal
pg_restore -h HOST -p 5432 -U USER -d ledger_rehearsal --no-owner /tmp/ledger-prod.dump
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/ledger_rehearsal?sslmode=require" \
  uv run python src/backend/manage.py migrate
dropdb -h HOST -p 5432 -U USER ledger_rehearsal
```

The dump contains every entry, income and chat message in the product. Treat
`/tmp/ledger-prod.dump` as production data: delete it when the rehearsal is done.

All five commands above were run for real on 2026-08-09. Everything below is a
failure that actually happened doing it, in the order it bit.

**Common failure #1: `pg_dump: aborting because of server version mismatch`.**
Supabase runs **PostgreSQL 17.6**; Ubuntu 24.04 ships client 16, and `pg_dump`
refuses to talk to a newer server. Use a matching client from Docker rather than
installing one:

```bash
docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE \
  -e PGSSLMODE=require -v "$PWD:/work" postgres:17 \
  pg_dump --no-owner --no-acl -Fc -f /work/ledger-prod.dump
```

**Common failure #2: `unexpected spaces found in "...", use percent-encoded
spaces (%20) instead`.** The production password contains a space. `psql` 16
tolerates it inside a URL, `pg_dump` 17 does not, and Django's URL parser would
mangle it too. Do not hand-encode it — pass the parts as libpq variables
(`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`, `PGSSLMODE`) and, for
`manage.py`, as `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` /
`POSTGRES_PASSWORD` / `POSTGRES_DB`. Both tools then need no URL at all.

**Common failure #3: `pg_restore: warning: errors ignored on restore: 2`,
`permission denied for table secrets`.** Those two errors are Supabase's internal
`vault` schema, which the pooler user cannot write. They do **not** affect
application data — check the row counts rather than the exit code:

```bash
psql -tAc "SELECT 'entries', count(*) FROM finances_entry
   UNION ALL SELECT 'incomes', count(*) FROM finances_income
   UNION ALL SELECT 'chat', count(*) FROM assistant_chatmessage;"
```

**Common failure #4: `dropdb` fails with `database "..." is being accessed by
other users — There is 1 other session using the database`, and
`pg_stat_activity` shows nobody.** The connection is held by Supabase's pooler,
not by a client, so `pg_terminate_backend` cannot clear it. Use:

```bash
psql -c 'DROP DATABASE IF EXISTS ledger_rehearsal WITH (FORCE);'
```

**Common failure #5:** `CREATE EXTENSION vector` is denied on a restored copy.
Supabase enables extensions per database — run
`CREATE EXTENSION IF NOT EXISTS vector;` on the copy as its owner first, before
restoring.

**Common failure #2:** the HNSW index build (`assistant/0009_memory_hnsw_index`)
exhausts `maintenance_work_mem` on a small instance. It will not at the current
few thousand embeddings; if it ever does, `SET maintenance_work_mem = '256MB';`
in the session before migrating.

**Verifying the E03 indexes landed**, after migrating any copy:

```bash
psql "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require" -c "
  SELECT tablename, indexname FROM pg_indexes
   WHERE indexname IN ('entry_user_billing_type_idx','entry_user_date_recent_idx',
                       'income_user_month_idx','chat_user_recent_idx',
                       'draft_user_status_recent_idx',
                       'memory_embed_hnsw_cosine_idx')
   ORDER BY tablename;"
```

Expect six rows. Note the vector index is `memory_embed_hnsw_cosine_idx` — the
longer name the E03 plan specifies exceeds Django's 31-character index-name limit
and will not migrate.

### Rehearsing the E04 tenancy migration

E04 moves tenancy from `user` to `household`: phase 2 adds the column and
back-fills it, phase 4 makes it `NOT NULL` and drops `user` outright. Production
is still pre-E04 — it has no `household` column at all — so the next deploy
applies **the whole chain in one go**, over real financial records:

- `accounts/0001` – `0003`
- `finances/0013` – `0019`
- `assistant/0010` – `0016`

That chain is what this script rehearses, against a throwaway copy, before any
of it goes near the live database.

Row counts do not prove a migration was lossless — this project has a documented
history of reconciliation issues where the counts matched and the balances did
not. The rehearsal therefore compares **balances and the monthly acumulado**, via
`manage.py dump_ledger_totals --json`. No E04 phase changes what a read path
*reports*, so the two fingerprints must match exactly.

Required env — libpq variables, **never** a connection URL, because the password
contains a space (Common failure #2 above). Take them from
`SUPABASE_SESSION_POOLER` in `.env` (port **5432**, not the 6543 transaction
pooler), URL-decoding the password:

```bash
export PGHOST=aws-1-sa-east-1.pooler.supabase.com PGPORT=5432
export PGUSER=postgres.<project-ref> PGPASSWORD='...' PGSSLMODE=require
scripts/rehearse-e04-migration.sh
```

Also needs `docker`: the script uses `postgres:17` for the dump (the system
`pg_dump` is older than the server) and `pgvector/pgvector:pg17` for the copy.

The script touches production exactly once, read-only, with `pg_dump`. It then
restores into a **throwaway local container** (`ledger_rehearsal`, bound to
`127.0.0.1:55432`), fingerprints it, migrates it, fingerprints it again, and
diffs. Nothing creates, migrates or drops a database on the production server.

**Two observers, one experiment — and the keys are normalised between them.**
Through phases 2 and 3 the observer was pinned and only the schema varied.
Phase 4 drops `user`, so no single version of `dump_ledger_totals` can read both
sides: the pinned one reads `finances_entry.user_id`, gone after the migration;
the working-tree one reads `household_id`, absent before it. Each side is
therefore read by the observer that fits its schema:

| side | observer | keyed by |
|---|---|---|
| BEFORE | `BEFORE_REF` (default `de143a1`, the phase-2 merge) in a temporary worktree | username |
| AFTER | your working tree | household name |

The script's `normalise_before` maps the BEFORE keys through the rule the seed
migration used — `accounts/migrations_helpers.py::_household_name_for`, which
names a household `Casa de <username>`, clipped to 120 characters. The **values**
are byte-identical in shape between the two versions; only the key changes.

**So a fingerprint diff is not automatically a data problem.** If the two sides
differ only in their keys, the normalisation is wrong, not the ledger. The
commonest cause by far: **someone renamed a household** in the app, so its name
is no longer `Casa de <username>`. Check that before suspecting the migration.
Set `BEFORE_REF=` (empty) to use the working tree on both sides, which is only
meaningful against a source that is already migrated.

**`REWIND=1` is dead as of phase 4, and the script now refuses it.** It used to
roll an already-migrated copy back with `migrate finances 0012` /
`migrate assistant 0009`. Since `finances/0018_drop_user` that rewind re-adds
`user` as an **all-NULL** column — 0018 threw the data away, exactly as its
docstring says. The BEFORE observer then reports zero entries for every user (a
clean-looking file full of zeros); `finances/0014_backfill_household` has no
`user` to derive `household` from; and `finances/0017_household_required`'s
NOT NULL guard fails the migrate. It looks like corruption and is not.
Rehearse against a genuinely pre-E04 source instead — production is one, or
restore a pre-E04 dump into a scratch database and point `SOURCE_DB` at it.

The dump holds every row of the real ledger, so it is written to a `0700` temp
directory that an `EXIT` trap removes on **any** exit — including the
fingerprint-mismatch exit. The container goes with it. If the script is killed
with `SIGKILL`, clean up by hand: `docker rm -f e04-rehearsal-<pid>` and
`rm -rf /tmp/e04-rehearsal.*`.

`pg_restore` errors on Supabase's own schemas (`auth`, `vault`, `graphql`) are
expected and tolerated — vanilla Postgres has neither those extensions nor those
roles. What matters is the `public` schema, which is where every Django table
lives; the printed entry counts are the check that it arrived.

**Ran for real against production on 2026-08-12** (phase 2): 3 users, 2320
entries, sum 344529.48. Production had neither E04 phase, so `migrate` applied
`accounts.0001`–`0003` and both phases' six migrations in one go; fingerprint
identical, no unfilled rows, six indexes present.

**Ran for real against production on 2026-08-13** (the whole chain, phases 2 and
4 together): 3 households, **2324 entries, sum 344718.86**; fingerprint
identical, `unfilled rows: none`, all six index assertions as listed below.
`migrate` applied 17 migrations in one pass — `accounts.0001`–`0003`,
`assistant.0010`–`0016`, `finances.0013`–`0019` — which is exactly what the next
deploy will do.

Four entries and R$189.38 more than the 2026-08-12 phase-2 run: the ledger grew,
as expected. What matters is that BEFORE and AFTER matched *within* the run.

The two empty households (`Casa de claude-bessavagner`, `Casa de tester`)
normalised as cleanly as the populated one, which is the check that the
`Casa de <username>` rule holds for every user and not just the busy one.

**Applied to production for real on 2026-08-13**, and the rehearsal predicted it
exactly. Backup first (`~/e04-preflight-backup/`), then the 17 migrations through
the session connection, then `gcloud run deploy` → revision
`expense-tracker-00043-th4`. Counts and money identical across the migration:

| | before | after |
|---|---|---|
| entries | 2324 | 2324 |
| incomes | 91 | 91 |
| chat messages | 282 | 282 |
| users | 3 | 3 |
| **sum(amount)** | **344718.86** | **344718.86** |

`unfilled rows: none`. `Casa de bessavagner` owns all 2324 entries as `owner`.
`user_id` survives on `assistant_assistantusageevent` alone — the actor column,
by design. Seven indexes present: the six household-leading ones plus
`usage_user_kind_recent_idx`.

Six outputs to check:

1. `OK — counts, sums and acumulado identical across the migration.`
2. `unfilled rows: none`
3. six index rows: `entry_hh_billing_type_idx`, `entry_hh_date_recent_idx`,
   `income_hh_month_idx`, `chat_hh_recent_idx`, `draft_hh_status_recent_idx`,
   `usage_hh_kind_recent_idx`
4. one row for `usage_user_kind_recent_idx` — the actor-scoped index, deliberately
   still leading with `user`, because the throttle counts per *person*. Scoping it
   by household would give two members one shared rate-limit budget.
5. **no** rows for the five user-leading indexes (`entry_user_billing_type_idx`,
   `entry_user_date_recent_idx`, `income_user_month_idx`, `chat_user_recent_idx`,
   `draft_user_status_recent_idx`) — they went with the column they led on.
6. **no** rows for a standalone index on `household_id`. E03 removed Django's
   implicit per-FK index on the tenant column for Entry, Income, ChatMessage and
   ReceiptDraft; E04 phase 2 silently re-created all four by adding `household` as
   an ordinary `ForeignKey`, and only a product-scale measurement caught it.
   Dropped again in `finances/0019` and `assistant/0016`. The check matches by
   index *definition*, not name — Django's name carries a hash suffix.

**A non-empty diff means the back-fill is wrong. Never apply to production on a
non-empty diff.** Read it instead: a changed `acumulado` with an unchanged
`entry_sum` means rows moved between billing months; a changed `entry_count`
means the migration deleted or duplicated.

**If `unfilled rows` is non-empty**, some user has no owner `Membership` — the
E04 phase 1 seed (`accounts.0003`) did not cover them. Re-run it on the copy and
rehearse again.

**The `--months` window and the pinned clock.** `dump_ledger_totals` pins `today`
to a literal date so two runs days apart still compare; if the rehearsal happens
long after 2026-08-12, update `FIXED_TODAY` in the command. `--months` is a
*floor*, not a cap: the window always stretches to cover the newest entry or
income, so the ledger's tail can never silently drop out of the comparison.

**Rehearsing without Supabase credentials.** The script can dump any database,
not just production — `SOURCE_DB` names it (`postgres` on Supabase,
`expense_tracker` locally):

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres \
PGSSLMODE=prefer SOURCE_DB=<a pre-E04 database> \
  scripts/rehearse-e04-migration.sh
```

`172.17.0.1`, not `localhost`: `pg_dump` runs inside a container, where
`localhost` is the container itself.

**The source must be genuinely pre-E04.** The local dev ledger is already
migrated and cannot be rewound into one — see the `REWIND=1` note above. To
rehearse locally you need a pre-E04 dump restored into a scratch database on
`:5433`. Weaker evidence than the real thing either way, since the local copy
lags production, but it exercises the whole migration path on real records.

### Proving E04 phase 3 moved no money

Phase 3 adds **no migration**. It re-points every read path from `filter(user=…)`
to the household-scoped manager, so the question it has to answer is not "did the
migration lose rows" but "does household scoping select the same rows user
scoping did". That is a *code*-version comparison on one unchanging database, and
the rehearsal above cannot express it.

```bash
POSTGRES_PORT=5433 scripts/verify-e04-phase3-money.sh          # vs main
POSTGRES_PORT=5433 scripts/verify-e04-phase3-money.sh <ref>    # vs any baseline
```

It checks out the baseline ref into a temporary worktree, runs
`dump_ledger_totals --json` from both it and your working tree against the same
local ledger, and diffs. Read-only — the command only aggregates. Expect:

```
OK — counts, sums and acumulado identical across the re-scoping.
```

**A non-empty diff means a conversion bug**, not a migration bug: on a
single-household ledger `for_household(household_for_user(u))` must select
exactly what `filter(user=u)` used to. A changed `acumulado` with an unchanged
`entry_sum` usually means one service is still scoping by the actor.

Run it at both phase-3 gates (3a, after the Django surface converts; 3b, after
the agent). Needs the pgvector container on `:5433` and a `.env`; the temporary
worktree inherits your `.env` and is removed on exit.

### Rehearsing the E05 email-unique migration

`core/0003_customuser_email_unique` puts a UNIQUE constraint on
`core_customuser.email`, a column that has held `''` for every account that
never set an address. `ALTER TABLE … ADD CONSTRAINT UNIQUE` aborts the whole
deploy the moment two rows share a value, and `''` is the value they would
share — so the migration back-fills blanks with
`<username>@sem-email.invalid` (RFC 2606 reserves `.invalid`, so a placeholder
can neither collide with a real address nor receive mail) before adding the
constraint.

```bash
scripts/rehearse-e05-email-unique.sh
```

Same shape as the E04 script: production is read once by `pg_dump`, restored
into a throwaway `pgvector/pgvector:pg17` container on `127.0.0.1:55433`,
migrated there, and inspected. Nothing on the production server is created,
migrated or dropped. Credentials come from `SUPABASE_SESSION_POOLER` in `.env`
if `PGHOST` is unset — the script splits the URL itself because the password
contains a space and the URL form is therefore malformed for libpq.

It fails loudly, before migrating, if two accounts share a **non-blank**
address. The back-fill cannot repair that case and resolving it is an operator
decision, not a code one.

**Run for real on 2026-08-13.** Production held 3 accounts, of which 1 had a
blank address; the migration applied cleanly and left zero duplicates.

**The one account that needs a human afterwards.** `claude-bessavagner`
(`is_staff=True`) is the blank one, so it becomes
`claude-bessavagner@sem-email.invalid` — an address that can never receive
mail. From E05 the login identifier *is* the email, so **that account cannot
log in until someone gives it a real one**, and it is a staff account, which
means it is also the one that reaches the admin. Repair it in the same
maintenance window as the deploy:

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  uv run python src/backend/manage.py shell -c "
from core.models import CustomUser
u = CustomUser.objects.get(username='claude-bessavagner')
u.email = 'seu-endereco@gmail.com'
u.save(update_fields=['email'])
print(u.username, u.email)
"
```

Then check nothing else was left behind:

```sql
SELECT id, username, email, is_staff FROM core_customuser
 WHERE email LIKE '%@sem-email.invalid';
```

Expected after the repair: zero rows.

---

## Signing in, and clearing a lockout

The family's login page is **`/accounts/login/`**, and it is now the *only*
one. It was `/admin/login/` before E01, then `/login/` after it; E05 moved it
to allauth's URL, because allauth owns signup, verification and password reset
and the login form has to share their session flow. `/login/` still answers —
as a permanent redirect, because the installed Android TWA points at it and
there is no way to push a URL change to a phone that already has the app.

`/admin/login/` is **closed**: see *Reaching the admin*. Staff sign in at the
same page as everyone else.

**After deploying this change, tell the family nothing.** Their bookmarks and the
installed TWA point at `/`, which redirects correctly. Only a bookmark saved
directly on `/admin/login/` keeps working as-is (it does; it just skips the
branded page).

Brute-force lockout is **10 failed attempts in 15 minutes**, counted by
identifier *and* by IP, enforced in
`core.auth_backends.LockoutAuthenticationBackend`. While locked, even the
correct password is refused, and the login page says so in Portuguese instead
of showing the same message as a typo.

From E05 the identifier is the **email address**, not the username — allauth
keys the submitted credential by the login method, so `LoginAttempt.username`
holds an address for anything submitted through the login page. allauth's own
login throttle is switched off (`ACCOUNT_RATE_LIMITS = {"login_failed": None}`)
because it is stricter than this one and would fire first, showing its own
generic error and hiding the explanation.

Clear a lockout for one person:

```bash
# Locally (dev DB on :5433)
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import LoginAttempt
print(LoginAttempt.objects.filter(username='NOME').delete())"
```

In production, run the same statement through the session connection (port 5432,
never the 6543 pooler) using the `POSTGRES_*` variables — see *Applying a
migration to Supabase* for why a URL will not do. Deleting **all** rows
(`LoginAttempt.objects.all().delete()`) clears every lockout, including the IP
arm, which is what you want when you have locked yourself out by IP.

Set or reset a password:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py changepassword NOME
POSTGRES_PORT=5433 uv run python src/backend/manage.py createsuperuser
```

**A user created this way gets no `Membership`**, and since E04 the ledger
belongs to a household rather than a person. The middleware handles it: on their
first authenticated request they are given **their own** household, named
`Casa de <username>`, with themselves as owner — the same rule the E04 seed
migration used. They land in an empty ledger, not somebody else's.

To put a new person into an **existing** household instead — the whole point of
E04 — there is currently no command or UI; it takes a hand-written `Membership`
row. Invitations are E05. Until then:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from django.contrib.auth import get_user_model
from accounts.models import Household, Membership, Role
u = get_user_model().objects.get(username='NOME')
h = Household.objects.get(name='Casa de OUTRO')
Membership.objects.get_or_create(user=u, household=h, defaults={'role': Role.MEMBER})
print(h, '->', u)
"
```

Their **oldest** membership is the default household, so if they already have
one of their own from a first login, that one keeps winning until they switch.

## Reaching the admin

**`/admin/` is gone, and that is deliberate.** It answers 404 now, to everyone,
forever. The service is deployed `--allow-unauthenticated` because the product
needs to be, so admin — which holds every household's financial records and
every user's raw chat with the assistant — was sitting on the open internet at
the first path any scanner tries.

Two independent controls replaced it:

1. **An unguessable path**, from the `ADMIN_URL_PATH` env var.
2. **`core.admin_gate.admin_staff_only_middleware`**, which answers **404** —
   not 403 — to anyone who is not staff. A 403 would confirm the path is
   admin; a 404 tells a scanner nothing, which is the whole value of moving it.

Guessing the path correctly still gets you nothing, and being staff on the
wrong path still gets you nothing.

### Set the path on Cloud Run

```bash
gcloud run services update expense-tracker --region=southamerica-east1 \
  --project=expense-tracker-482807 \
  --set-env-vars=ADMIN_URL_PATH=gestao-4f9c2a/
```

Pick your own suffix; do not reuse the one above, and do not commit it. The dev
default is `gestao-dev/` — deliberately not `admin/`, so a missing env var is
loud rather than a silent restoration of the old front door.

### Enrol a second factor BEFORE the first admin visit

Staff without an authenticator are redirected to enrolment rather than 404'd —
locking the only operator out of their own admin with no explanation is how
this feature gets reverted at 2am. But the enrolment page itself asks you to
re-authenticate first, so do this while you still remember the password:

1. Sign in normally at `/accounts/login/`.
2. Go to **`/accounts/2fa/totp/activate/`**. Confirm the password when asked.
3. Scan the QR with your authenticator app and enter the code.
4. Go to **`/accounts/2fa/recovery-codes/`** and save the codes **somewhere
   that is not the phone holding the TOTP app**. A phone is a single point of
   failure for both halves otherwise, and there is no other way back in.

From the next login, the correct password alone does not sign staff in: allauth
answers it with the 2FA challenge.

### Failure modes, and what they actually mean

| What you see | What it means |
|---|---|
| 404 at the admin path while signed in | The account is not `is_staff`. The gate cannot tell you that, by design. |
| Redirect loop to the MFA page | The authenticator was never *activated* — a scanned QR that was never confirmed with a code leaves no `Authenticator` row. Finish step 3. The gate is not broken. |
| 404 at `/admin/` | Correct. That path is retired. |
| Signed in fine but admin still 404s | Wrong path — check `ADMIN_URL_PATH` on the revision matches the URL you typed, trailing slash included. |

### What gets logged

Every staff request admin actually answers writes an `AdminAccessLog` row —
actor, path, method, IP, timestamp — readable at
`<ADMIN_URL_PATH>core/adminaccesslog/` and **not** deletable or editable from
admin. Refused requests are deliberately not logged: a 404 disclosed nothing,
and logging those would drown the rows that record a human actually reading
someone's money.

**`ChatMessage` is no longer registered in admin at all.** Raw conversations
with the assistant — receipts, salaries, arguments about money — are not an
admin list column. E17 owns the deliberate, consented, logged way to look at a
customer's account.

## Transactional email

E05 made email the login identifier, so mail is not a nicety here: an account
that cannot receive a verification message cannot be created, and an invitation
that lands in Spam is an invitation that was never sent. The provider is
**Resend, over plain SMTP** — Django already speaks SMTP, so switching provider
is an environment change rather than a deploy.

**Locally, nothing is sent.** With `EMAIL_HOST` unset the settings pick the
console backend and every message is printed to the terminal, links included.
That branch exists because Django's own default is an SMTP backend pointed at
`localhost:25`, where mail is swallowed with no exception — you would see
"e-mail enviado" and an empty inbox forever.

### 1. The sending domain — `cactarus.com`, verified 2026-08-14

**This step is yours; nothing in the repo can do it, and nothing below works
until it is done.** In the Resend dashboard, add the sending domain and publish
the DNS records it issues at the registrar. The live values, in the
**`cactarus.com`** zone at Hostinger (region `sa-east-1`, São Paulo):

| Type | Name | Value | Priority |
|---|---|---|---|
| `TXT` | `resend._domainkey` | the DKIM public key Resend shows (218 chars, starts `p=MIGf…`) | — |
| `TXT` | `send` | `v=spf1 include:amazonses.com ~all` | — |
| `MX` | `send` | `feedback-smtp.sa-east-1.amazonses.com` | 10 |

Resend prints the exact values — copy them, never retype the DKIM key.

**This is not optional and it is not cosmetic.** Unauthenticated mail from a
financial app is exactly the profile Gmail files under Spam. An unverified
domain does not get "slightly worse delivery"; it gets a signup funnel where
nobody ever confirms their address, and you will read it as a bug in the code.

#### The two traps this actually hit

**Wrong zone.** The first attempt failed with all three records correct and the
DKIM key byte-identical — published on **`cactarus.com.br`** while Resend was
verifying **`cactarus.com`**. They are separate Hostinger zones on different
nameservers (`hermes`/`artemis` vs `helios`/`aster`), so editing one never
touches the other. Nothing in the Resend UI can tell you this; the records
simply never appear. Check which domain the DNS editor has selected, then
confirm from outside:

```bash
for r in hermes.dns-parking.com 8.8.8.8 1.1.1.1; do
  dig +short @$r TXT resend._domainkey.cactarus.com
  dig +short @$r TXT send.cactarus.com
  dig +short @$r MX  send.cactarus.com
done
```

All three resolvers must agree. An empty answer means the record is in another
zone, or the name was typed as an FQDN — Hostinger's *Name* field is relative,
so `send.cactarus.com` becomes `send.cactarus.com.cactarus.com`.

**Re-adding the domain rotates the key.** Resend generates the DKIM keypair per
domain, so deleting and re-adding a domain issues a *new* `resend._domainkey`
value and silently invalidates the one already published.

**No conflict with the Hostinger mailboxes.** `cactarus.com` keeps its apex SPF
(`v=spf1 include:_spf.mail.hostinger.com ~all`) and apex MX (`mx1`/`mx2`).
Resend's records live on the `send` subdomain — a different name, so the two
SPF records coexist rather than compete. Do not merge them.

### 2. Store the key and point the service at it

The key must never reach a shell history, a process listing, or a chat
transcript. `read -rs` keeps it off the command line and `printf` keeps the
trailing newline out of the secret:

```bash
read -rs RESEND_KEY && printf '%s' "$RESEND_KEY" | \
  gcloud secrets create resend-api-key \
    --project=expense-tracker-482807 \
    --replication-policy=automatic \
    --data-file=- ; unset RESEND_KEY

gcloud secrets add-iam-policy-binding resend-api-key \
  --project=expense-tracker-482807 \
  --member=serviceAccount:654941182076-compute@developer.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

gcloud run services update expense-tracker --region=southamerica-east1 \
  --project=expense-tracker-482807 \
  --update-env-vars=EMAIL_HOST=smtp.resend.com,DEFAULT_FROM_EMAIL='Ledger <nao-responda@cactarus.com>' \
  --update-secrets=RESEND_API_KEY=resend-api-key:latest
```

**`--update-env-vars`, never `--set-env-vars`** — the latter replaces the whole
list and would wipe `DATABASE_URL`, `ALLOWED_HOSTS` and the rest. Same for
`--update-secrets`. This is the trap already recorded at the top of this file.

The IAM binding is separate because the runtime service account is *not*
granted access by creating the secret; without it the revision starts and then
fails to mount, which surfaces as a container startup error rather than an
email error.

`gcloud secrets create` prints `Created version [1] of the secret
[resend-api-key].`; the `run services update` prints the new revision name and
`Service [expense-tracker] revision [expense-tracker-000NN-xxx] has been
deployed and is serving 100 percent of traffic.`

**`printf`, not `echo`.** `echo` appends a newline, the newline goes into the
secret, and SMTP then fails with `535 Authentication failed` — an error that
reads like a wrong key and is really a wrong *byte*. If you see 535, suspect
this before you suspect Resend.

The sending address must be **at the verified domain**. A `DEFAULT_FROM_EMAIL`
at a domain Resend has not verified is rejected outright.

### 3. Send a test message from the deployed revision

```bash
gcloud run services proxy expense-tracker --region=southamerica-east1 \
  --project=expense-tracker-482807 &
# then, in a Django shell on the revision:
#   from django.core.mail import send_mail
#   send_mail("Teste", "corpo", None, ["seu-endereco@gmail.com"])
```

`send_mail` returns `1`. A return of `0`, or a `SMTPAuthenticationError`, means
the key or the from-address is wrong — see above.

### 4. The deliverability check (S05-2's last bullet)

Not a formality, and not satisfiable by a passing test. Send to a **real Gmail
address** and confirm:

- [ ] it arrives in **Inbox** — not Promotions, not Spam;
- [ ] "Show original" reports `spf=pass` and `dkim=pass`;
- [ ] the `Authentication-Results` header is pasted below as evidence.

```
Authentication-Results: mx.google.com;
       <paste the real header here after the first successful send>
```

An empty block above means this check has not been done, whatever the test
suite says.

**Status 2026-08-14: arrived, header not captured.** A real signup completed in
production against revision `00044-2kq` — the verification email reached
`bessavagner.dev@gmail.com`, was opened, and the link was clicked
(`EmailAddress.verified = True`). So delivery works and the message was
findable. Nobody read "Show original", so the block above is still empty and
`spf=pass`/`dkim=pass` remains **unverified** rather than passed. Fill it in on
the next send; it is a thirty-second job and it is the difference between
evidence and inference.

## Import batches

Each confirmed column mapping creates one `finances_importbatch` row, and the
execute step locks it so a double-tapped or replayed "Importar" cannot import the
same file twice (`executed_at` records that it already ran, and the second
request renders the first one's counts instead of importing again).

Consequence for the operator: abandoned imports — someone who reached the preview
and closed the tab — leave rows with `executed_at IS NULL` forever. They are
tiny and harmless. Prune them if they ever bother you:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from datetime import timedelta
from django.utils import timezone
from finances.models import ImportBatch
print(ImportBatch.objects.filter(
    executed_at__isnull=True,
    created_at__lt=timezone.now() - timedelta(days=30)).delete())"
```

Do **not** delete executed batches that a user might still re-POST — a browser
that replays the execute step against a missing batch is sent back to the upload
step, which is safe but looks like the import vanished.
