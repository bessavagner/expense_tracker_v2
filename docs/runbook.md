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

> **Status (2026-08-14):** Sentry and Logfire are **live** on revision
> `expense-tracker-00045-zjs` — secrets `sentry-dsn` and `logfire-token` in
> Secret Manager, mounted as `SENTRY_DSN` / `LOGFIRE_TOKEN`. Logfire confirmed
> the connection at startup by printing its project URL,
> <https://logfire-us.pydantic.dev/cactarus/expense-tracker>. Still **not**
> provisioned: the uptime check, the two notification channels, the alert
> policies and the dashboard — so **nothing pages you yet**. Delete this note
> once those exist.

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

**Common failure — read this before concluding the request never arrived.**
`jsonPayload` exists only for lines **the application itself logged**. A
request that succeeds logs nothing at application level, so a healthy request
has **no** `jsonPayload.request_id` entry at all; verified empty on
`00045-zjs` after a clean smoke test. What you will see for such a request is
gunicorn's plain-text access line (`"GET /healthz/ HTTP/1.1" 200`) under
`textPayload`, which carries no request ID. The structured line appears when
something logs a WARNING or above — which is exactly the case you are
debugging.

So: an empty result means "nothing went wrong on that request", not "that
request never happened". To see the request regardless, drop the
`jsonPayload` filter and search `textPayload` by path and timestamp.

Two further reasons a line can be plain text: `DEBUG=True` selects the `plain`
formatter (a local run), and anything logging before Django installs `LOGGING`
misses the formatter entirely.

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

**One channel today: email.** `Operator email` →
`bessavagner@gmail.com`, channel id `5857707555791637518`, enabled, no
verification needed (it is the project owner's address).

```bash
gcloud beta monitoring channels list --project=expense-tracker-482807 \
  --format="table(displayName,type,labels.email_address,enabled)"
```

**Nothing wakes you.** That is a known, accepted gap, not an oversight —
E06 planned a second channel that no longer exists (below). Email is a durable
record you read when you go looking; it will not reach you at 3am.

**`mobile_push` is gone — do not go looking for it.** Google retired the Cloud
Console mobile app and its notification channel type along with it. There is no
"Mobile devices" entry under *Monitoring → Alerting → Notification channels*
any more, and the API agrees:

```bash
gcloud beta monitoring channel-descriptors describe mobile_push --project=expense-tracker-482807
# ERROR: NOT_FOUND: Requested entity was not found.
```

Checked 2026-08-14. What this project *can* use, from
`gcloud beta monitoring channel-descriptors list`: `email`, `sms`, `slack`,
`pubsub`, `webhook_basicauth`, `webhook_tokenauth` (all GA), plus
`google_chat` and `pagerduty` (beta). **SMS** is the closest replacement for
waking someone — create it with `gcloud beta monitoring channels create
--type=sms --channel-labels=number=+55...`, then verify the texted code in the
console, because `gcloud` has no `channels verify` subcommand. A webhook into
ntfy.sh or Pushover is the other realistic option.

When a waking channel does exist, test the path rather than trusting it: point
the uptime check at a path that 404s until it fires, confirm the notification
arrives, then restore it. An alert that has never fired is a hypothesis, not an
alert.

### The alert policies

Both notify `Operator email` and auto-close after 30 minutes.

| Policy | Fires when | Id |
|---|---|---|
| `expense-tracker is down (/healthz/ uptime check failing)` | the uptime check fails more than once in a 5-minute window | `17994738960177318338` |
| `expense-tracker 5xx error rate elevated` | more than 5 `5xx` responses in 5 minutes | `4509450462948742746` |

```bash
gcloud alpha monitoring policies list --project=expense-tracker-482807 \
  --format="table(displayName,enabled,conditions[0].displayName)"
```

Each policy carries its own triage steps in `documentation.content`, so the
alert email points you at the right place without needing this file open.

**Neither has ever fired.** They are hypotheses until one does — see the
paragraph above on testing the path.

### The dashboard

**expense-tracker — golden signals**, id `450cfbfa-635f-487b-9893-83947ab91b9b`:

<https://console.cloud.google.com/monitoring/dashboards/builder/450cfbfa-635f-487b-9893-83947ab91b9b?project=expense-tracker-482807>

Four tiles, all from Cloud Run's built-in metrics: request rate by response
class, 5xx rate, p95 latency, and container instance count.

**Four of the five signals E06 asked for, not five** — and the dashboard says
so on its own face rather than quietly omitting them. *Assistant turns per day*
and *LLM spend per day* are absent because there is nothing to build a
log-based metric from: a successful request logs no application line, so there
is no `jsonPayload` to count, and assistant turns are recorded as
`UsageInteraction` rows in Postgres, which Cloud Monitoring cannot read.
Turning those rows into a metric is **E07**'s job.

Until then LLM spend is *capped rather than graphed* — the OpenAI org limit
plus the BRL 50/mo budget alert, see §"Spend ceilings" — and the instance-count
tile is a proxy for infrastructure spend only, not for model spend.

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
  --update-env-vars ASSISTANT_ABUSE_IMAGE_PER_HOUR=25
```

| Var | Default | Bucket |
|---|---|---|
| `ASSISTANT_ABUSE_TEXT_PER_HOUR` | 60 | text + audio turns |
| `ASSISTANT_ABUSE_TEXT_PER_DAY` | 300 | text + audio turns |
| `ASSISTANT_ABUSE_IMAGE_PER_HOUR` | 15 | receipt photo turns |
| `ASSISTANT_ABUSE_IMAGE_PER_DAY` | 50 | receipt photo turns |

Use `--update-env-vars` (merge), never `--set-env-vars` — the latter replaces the
whole env list and wipes `DATABASE_URL`.

### Who is hitting the limit

```bash
DATABASE_URL="<supabase session URL, port 5432>" \
  uv run python src/backend/manage.py shell -c "
from django.db.models import Count
from django.db.models.functions import TruncDate
from assistant.models import UsageInteraction
print(list(UsageInteraction.objects.annotate(d=TruncDate('created_at'))
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

---

## Cold starts: the keepalive job

`min-instances` is **0**, so an idle service scales to zero and the next request
pays a cold start (measured: **~15s**). A Cloud Scheduler job pings `/healthz/`
every 5 minutes during waking hours to keep one instance alive.

> **DONE 2026-08-14 — the Scheduler job is gone.** A Cloud Monitoring uptime
> check replaced it: `expense-tracker-healthz--qVSHox7iq8`, `/healthz/`, every
> 5 minutes, expecting 2xx. It *is* the keepalive now, and it covers more than
> the old job did — 24/7 from several regions, where `*/5 6-23 * * *` skipped
> midnight to 06:00.
>
> **The rest of this section is history, kept for the recreate command** in case
> the uptime check is ever removed without a replacement. `gcloud scheduler jobs
> list` returns nothing today, so `describe`/`pause` below will fail with
> `NOT_FOUND` — that is expected, not a fault.
>
> **"Pause the keepalive" now means pause the uptime check.** See the note in
> *Measuring cold start*.
>
> ```bash
> # What exists instead:
> gcloud monitoring uptime list-configs --project expense-tracker-482807 \
>   --format="table(displayName,httpCheck.path,period)"
> ```

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

> **Pause the right pinger — the command below no longer exists.** As of
> 2026-08-14 the Scheduler job is deleted and a Cloud Monitoring uptime check
> is the keepalive, so `gcloud scheduler jobs pause` fails with `NOT_FOUND`.
> Worse, if you skip that step and measure anyway, the uptime check keeps an
> instance warm and the "cold" number you get is a warm one.
>
> Disable the uptime check instead: *Monitoring → Uptime checks →
> `expense-tracker-healthz` → Edit → uncheck Enabled*. **Re-enable it when you
> are done** — it is also the keepalive, and it is what the two alert policies
> watch, so leaving it off means nothing is monitoring the service.

```bash
# Historic — the job is gone; disable the uptime check in the console instead.
# gcloud scheduler jobs pause expense-tracker-keepalive \
#   --project expense-tracker-482807 --location southamerica-east1
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

## Usage, credits and cost (E07)

### Run the cost report

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py usage_report \
  --by-kind --since 2026-08-01
```

Prints cost per household in USD sorted by spend, then `casas ativas` and
p50/p90/p99 **across households** (not across calls — a p99 is what one
expensive household pays, which is the number a price has to clear), then a
per-call-kind breakdown answering "what does receipt OCR cost relative to text
chat?".

`--since` is inclusive, `--until` exclusive, both `YYYY-MM-DD` in local time.
Omit both for all time.

Common failure: an empty report means `UsageRecord` has no rows in the window,
**not** that costs were zero. Widen `--since`. The second thing to check is
`sem preço` — see the known gap below; those calls are counted and deliberately
not summed.

### Emit the daily usage metric

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py emit_usage_metrics
```

Prints exactly one JSON line for **yesterday** — whole and closed, so the
newest point on the dashboard never dips just because today is still running:

```json
{"metric": "assistant_usage_daily", "day": "2026-08-13", "turns": 7, "cost_usd": "0.412300"}
```

`--day 2026-03-14` backfills a specific date. A quiet day still prints the line
with zeroes: **a missing line is indistinguishable from a broken job**, so a
gap in the metric means the job did not run, never that nobody used the
assistant.

This is what closes E06's two missing golden-signal tiles. E06 could not build
*assistant turns/day* or *LLM spend/day* because a successful request emits no
application log line and the counts lived only in Postgres, which Cloud
Monitoring cannot read. A structured line on stdout is already how this service
talks to Cloud Logging (`core/log_formatting.py`), so this needs no new IAM
role and no new client library.

**Still to provision (console/gcloud, not code):**

```bash
gcloud logging metrics create assistant_turns_daily \
  --project expense-tracker-482807 \
  --description="Assistant turns per day (E07)" \
  --log-filter='jsonPayload.metric="assistant_usage_daily"' \
  --value-extractor='EXTRACT(jsonPayload.turns)'

gcloud logging metrics create assistant_cost_daily \
  --project expense-tracker-482807 \
  --description="LLM spend USD per day (E07)" \
  --log-filter='jsonPayload.metric="assistant_usage_daily"' \
  --value-extractor='EXTRACT(jsonPayload.cost_usd)'
```

Then add two tiles to dashboard `450cfbfa-635f-487b-9893-83947ab91b9b`
(`expense-tracker — golden signals`) and **delete the note on its face saying
those two tiles are impossible** — true for E06, stale now. Schedule the daily
run with Cloud Scheduler against a Cloud Run job, or as a step in the existing
cron path; record whichever you pick here.

Common failure: the metric flatlines at zero after a deploy. Check the value
extractors first — they read the literal keys `turns` and `cost_usd`, and
`test_the_line_carries_every_field_the_metric_extracts` is what stops a rename
from silently breaking them.

### Change a model's price

Prices live in the database (`ModelPrice`), so this needs no deploy: Django
admin → Preços de modelo → add a row with a new `effective_from`. Never edit an
existing row — history is what makes an old `UsageRecord` explicable, and each
record froze its cost at write time anyway, so a correction is never
retroactive.

**Always re-check the provider's live pricing page first, and put its URL in
`source_url`.** Never write a price from memory: model catalogues churn faster
than anyone's recall, and a wrong number here becomes an authoritative-looking
figure in the report above. Same rule when choosing the Essential tier's free
and cheapest-paid models at `openrouter.ai/models`.

A price row has **three** rates, not two: `input_per_mtok`, `output_per_mtok`,
and `cached_input_per_mtok`. Providers bill tokens they served from their
prompt cache at a large discount — OpenAI listed 10% of the input rate across
the gpt-5.x family on 2026-08-15 — and `input_tokens` already **includes** those
tokens, so pricing the whole prompt at the full rate over-reports. It over-
reported by roughly 4× on the E09 matrix, which is how D03 was found.

Leaving `cached_input_per_mtok` empty is safe but wrong-ish: the call is billed
entirely at the full input rate, exactly as before D03, so the figure errs high.
`test_every_configured_chat_model_has_a_cached_input_rate` fails when a model in
settings has a price row without one, so this cannot be forgotten silently.

`UsageRecord.cache_read_tokens` records how much of each prompt was served from
cache. To see the discount a household is actually getting:

```sql
SELECT model,
       SUM(input_tokens) AS input_tokens,
       SUM(cache_read_tokens) AS cached,
       ROUND(100.0 * SUM(cache_read_tokens) / NULLIF(SUM(input_tokens), 0), 1) AS pct_cached
FROM assistant_usagerecord
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY model ORDER BY input_tokens DESC;
```

Costs already written are **not** re-priced when a cached rate is added:
`cost_usd` is frozen at write time by design, so rows created before
2026-08-15 keep the old over-estimate. Compare periods across that date with
that in mind.

If a model appears in settings with no price row it meters at `cost_usd = NULL`
forever and the report quietly under-reports.
`test_every_configured_chat_model_has_a_seeded_price` is the ratchet that
catches it — including the case where `.env` overrides `LLM_MODEL` to something
the seed migration never priced.

### Change the credit grant or the credit prices

- Admin → Planos → `monthly_credits` — the grant per household per **calendar
  month**. Deliberately not the domain's `billing_month`, which means a credit
  card's closing cycle in this codebase.
- Admin → Preços em créditos → the (tier × kind) grid.

Both take effect on the next request; no deploy, no restart. The balance is
**derived** (`grant − Σ credits_charged this month`), so there is no reset job
to forget, no counter to drift, and no race between two members of the same
household spending at once.

Credits are a **product currency, not tokens**. Real token counts and USD live
in `UsageRecord`. Retuning either table never rewrites what a household has
already spent — `UsageInteraction.credits_charged` is frozen at write time.

The current grant (3000) was derived from real usage; see
`accounts/migrations/0007_beta_credit_grant_from_real_usage.py` for the
measurement and its caveats. Re-derive from `usage_report` once households have
more than one member.

### The three tiers

| Tier | pt-BR | Model setting | Credits per text / image turn |
|---|---|---|---|
| Advanced | Avançado | `LLM_TIER_ADVANCED` | 3 / 12 |
| Standard | Padrão | `LLM_TIER_STANDARD` | 1 / 4 |
| Essential | Essencial | `LLM_TIER_ESSENTIAL` (+ `_FALLBACK`) | 0 / 0 |

A household picks its tier (`Household.preferred_tier`). When credits run out
the chokepoint (`assistant/quota.py::decide`) forces Essential — it **degrades,
it does not refuse** — and the user is told so by a `notice` event before the
answer streams.

Essential's primary is a free OpenRouter model with one paid fallback, retried
only when nothing has reached the client yet. Without `OPENROUTER_API_KEY` both
resolve back to Standard rather than failing, which is what makes local dev and
CI work.

The **abuse ceiling** (`ASSISTANT_ABUSE_TEXT_PER_HOUR`, `_TEXT_PER_DAY`,
`_IMAGE_PER_HOUR`, `_IMAGE_PER_DAY`) is a different thing and *does* refuse,
with a 429, on every tier including Essential. It is counted per **user** over
a rolling window, while credits are pooled per **household** — one member must
not be able to lock the other out. It is what keeps R0's "no unbounded LLM
spend" guarantee true.

> Cloud Run may still carry the older `ASSISTANT_THROTTLE_*` variable names
> from E01. The code reads `ASSISTANT_ABUSE_*`; the defaults are identical
> (60/300/15/50), so behaviour only changes if a value was customised.

## Evaluating a model (E08)

The question this answers is "can we ship on a cheaper model?", with a number
instead of an opinion. It does **not** change which model production uses —
that is E09.

### Run it

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 uv run python src/backend/manage.py eval_models \
  --models "openai:gpt-5.4,openrouter:qwen/qwen3.7-flash" \
  --suite both \
  --out docs/superpowers/evidence/eval/2026-08-14.md
```

- `--suite extraction` reads receipt photos and scores the read.
- `--suite behaviour` drives the real assistant through seven conversations and
  scores the **ledger rows** it produced.
- `--cases a,b` narrows to specific case ids while iterating.
- `--stub` runs the whole thing against `TestModel`, for free, when you are
  changing the harness rather than measuring a model.
- Without `RUN_LLM_TESTS=1` the command refuses. That is deliberate: it spends
  money.

Set `EVAL_FIXTURES_DIR` first, or the private receipt photos are missing and
most of the dataset is skipped — see `docs/eval-dataset.md`.

### Before you compare: two things that will mislead you

**Smoke-test a new model on one case first.**

```bash
RUN_LLM_TESTS=1 POSTGRES_PORT=5433 EVAL_FIXTURES_DIR=~/ledger-eval-fixtures \
uv run python src/backend/manage.py eval_models \
  --models "<the new model>" --suite extraction --cases americanas-2026-06-12
```

Two of the three models first pointed at this dataset returned HTTP 400 on
*every* call — they refuse tool calling under their default reasoning settings,
and every agent here uses tool calling. The workarounds live in
`assistant/agents/model_compat.py`; add an entry there rather than at the call
site. `docs/eval-dataset.md` § *Provider quirks* has the two known refusals and
their exact provider messages.

**One run does not rank two models.** `gpt-5.4` scored 0.97, then 0.83, then
0.84 on the same seven cases within an hour. One case is 14% of the score and
the money invariant is pass/fail per case, so the run-to-run swing is wider than
the gap between two serious candidates — in one pair of runs the winner and
loser swapped places. Run each candidate **at least three times**, compare the
spread, and treat a gap narrower than that spread as unmeasured.

### What it costs

One full `--suite both` run is 7 vision calls plus roughly 9 chat turns per
model. Read the actual figure from the `USD` column of
`docs/superpowers/evidence/eval/baseline-2026-08-14.md` rather than from this
sentence, which will rot. Multiply by the number of models in `--models`. A cell
showing `0` with a non-zero `unpriced` note means the model has no `ModelPrice`
row, not that it was free.

### Reading the output

| Column | What it means |
|---|---|
| `Score` | 0–1. Extraction: weighted across the dimensions. Behaviour: fraction of cases whose ledger was exactly right. |
| `money_ok_rate` | Fraction of receipts whose items reconciled with the amount paid. **A model below 1.0 here is disqualified regardless of the rest** — a case that fails it scores 0 overall. |
| `item_recall` | Lines the model found, over lines that exist. A miss is a missing expense. |
| `item_precision` | Lines the model found that are real. Low means invention. |
| `amount_accuracy` | Matched lines whose value was exactly right. |
| `category_accuracy` | Matched lines filed under the right category. |
| `cases_passed` | Behaviour only. Out of `n`. |
| `USD` | Priced calls only. Unpriced calls are counted in a note, never as zero. |

Under each table is a **"what it got wrong"** list naming every case that failed
and why. Read it — an aggregate of 0.85 built from one catastrophic case and six
perfect ones is a different model from one that is uniformly mediocre.

On two of the receipts the money invariant runs **inverted**: the Mercado Livre
order screen prints no total, so the correct answer is `null` and a model that
supplies a number fails. See `docs/eval-dataset.md`.

If the report says cases were **skipped**, the private photos are missing. See
`docs/eval-dataset.md` and set `EVAL_FIXTURES_DIR`. A skipped case is never a
failure, but a run with skips is not comparable to one without.

### Safety

Everything the behavioural suite writes — households, users, categories,
entries, receipt drafts — happens inside a transaction that is **always** rolled
back, so the command is safe to point at any database. It also writes no
`UsageRecord`: a harness run has no household to bill, and a cost row nobody can
be charged for would corrupt the operator report above. `test_eval_command.py`
asserts both; if you change the command, keep those tests.

To confirm after a run:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from accounts.models import Household
print('eval households left behind:', Household.objects.filter(name__startswith='eval-').count())
"
```

Expected: `0`. Anything else means the rollback did not hold — stop and fix the
command before trusting any number in the report.

### Adding a case

`docs/eval-dataset.md`. Ground truth is committed, receipt photos are not.

### Known gap: transcription cost is null

Providers price transcription per minute of audio; `ModelPrice` models token
pricing only. Transcription records carry `ok`, `model` and latency but
`cost_usd = NULL`, and the report counts them under `sem preço`. Bounded on
purpose: a transcription is roughly two orders of magnitude cheaper than a
vision call (E01), so it does not move p50/p90/p99. `test_pricing_gaps_are_declared`
keeps it a decision rather than an oversight. Revisit if audio volume grows.

## The production model mix (E09)

Which model runs where, why, and how to change it. Evidence:
`docs/superpowers/evidence/eval/matrix-2026-08-15.md`.

| Path | Setting | Model | Why |
|---|---|---|---|
| Text, strong | `LLM_TIER_ADVANCED` → `LLM_ASSISTANT_MODEL` | `openai:gpt-5.4` | 1.000 on the behavioural suite, spread 0.000. Both cheaper candidates dropped to 0.952 by failing the category-split case one run in three — the exact production bug the product exists to prevent. |
| Text, standard | `LLM_TIER_STANDARD` | `openai:gpt-5.4` | Same. Deliberately equal to ADVANCED until something measures better. |
| Text, degraded | `LLM_TIER_ESSENTIAL` | `openrouter:nvidia/nemotron-3-super-120b-a12b:free` | E07. Out of credits gets a cheap answer, never a refusal. |
| **Vision, first read** | `LLM_VISION_MODEL` | **`openai:gpt-5.6-luna`** | Every photo. Cheap and, alone, not good enough: 0.508, reconciles 53%. |
| **Vision, escalation** | `LLM_VISION_ESCALATION_MODEL` | **`openai:gpt-5.4-mini`** | The ~1/3 of receipts the cheap read cannot reconcile. Equals gpt-5.4 on the money invariant for 2.48× less. |

**The two vision settings are one decision.** Alone, neither ships: luna scores
0.508, and mini misses the 3× cost gate at 2.48×. Together they measured
**0.719 at 3.75× cheaper** than gpt-5.4's 0.699 — better quality *and* lower
cost. Changing one without the other ships half a decision, and the half that
ships alone is the bad one.

### Changing a model

Every model is an environment variable, so this needs no deploy:

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --update-env-vars LLM_VISION_MODEL=<new model>
```

Use `--update-env-vars`, never `--set-env-vars`: the latter replaces the whole
env list and wipes `DATABASE_URL` and friends.

**Seed the `ModelPrice` row in the same change**, or the cost report reads zero
for every call to the new model, which looks like an answer. And **measure
before you switch** — read *Evaluating a model (E08)* above, then run three
sweeps, not one.

### Rolling back

The same command with the previous value. Both together:

```bash
gcloud run services update expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --update-env-vars LLM_VISION_MODEL=openai:gpt-5.4,LLM_VISION_ESCALATION_MODEL=openai:gpt-5.4
```

Setting both to the same model is the pre-E09 behaviour: one model, and a second
attempt only when the first raises. Old `ModelPrice` rows are deliberately kept,
so historical `UsageRecord`s still price correctly.

### Is escalation working?

```sql
SELECT escalation_reason, count(*)
FROM assistant_usagerecord
WHERE kind = 'extraction' AND created_at > now() - interval '7 days'
GROUP BY escalation_reason;
```

Blank rows are first attempts; everything else is a second call on the same
receipt. Divide the non-blank total by the blank total for the escalation rate.

**Measured at 33% when the mix was chosen** (27–40% across three sweeps), so
roughly 1.33 calls per receipt. What the numbers mean:

| Reading | What it means | What to do |
|---|---|---|
| ~30–40% | Normal. This is what the 3.75× saving already accounts for. | Nothing. |
| Near 100% | The cheap model is not cheap — you are paying for two calls on every receipt. | Roll back the mix. |
| Near 0% | Suspect, not good. Either the cheap model got much better, or the escalation rule stopped firing. | Check `money_ok_rate` on a fresh sweep before believing it. |

The **reason** matters as much as the rate, which is why it is a column:

- `discount_mismatch` — the lines and the stated discount disagree with the
  total. The pharmacy shape, and the most common reason here.
- `inconsistent` — the lines do not cover the amount paid. A line was missed.
- `low_confidence` — the model said so itself. Tune with
  `ASSISTANT_ESCALATE_MIN_CONFIDENCE`, which is deliberately **not**
  `ASSISTANT_RECEIPT_MIN_CONFIDENCE`; that one decides whether to ask the user
  field by field, and asking is cheap where retrying is not.
- `no_items` / `error` — the cheap read returned nothing, or raised.

A rate that climbs with `low_confidence` dominating is a threshold to tune. A
rate that climbs with `discount_mismatch` dominating is a worse cheap model, or
a new receipt shape worth adding to the golden dataset.
