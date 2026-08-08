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

## Spend ceilings

Three independent caps. Each is set to hold if the other two fail, and the app
layer (E01's throttle) sits below all of them.

| Ceiling | Value | Status | Effect when hit |
|---|---|---|---|
| Cloud Run `--max-instances` | 3 (was `20`) | **Live** — revision `expense-tracker-00039-rg6` | New requests queue rather than starting a 4th billable instance |
| GCP budget alert | BRL 275/month (target was USD 50, see below) | **Live**, alert-path test in progress — see below | **Notifies only.** Email at 50%, 80%, 100% |
| OpenAI org monthly limit | USD 30/month hard, USD 20 soft | **Pending** — console-only, owner action | API returns errors — the actual stop |

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
doesn't. The owner set the live budget at **BRL 275/month** — the round
number they picked as the closer BRL equivalent of the USD 50 target. This is
a fixed BRL amount; it will not track future FX moves, so revisit it
periodically or the day USD/BRL moves meaningfully.

**Alert-path test in progress:** to prove the notification actually fires,
the budget was temporarily dropped to `1BRL` at `2026-08-08T16:07:54Z`. It has
**not** been restored yet. Once the alert email (subject like `Budget alert:
expense-tracker monthly ceiling`) is confirmed in the billing account admin's
inbox, restore it:

```bash
gcloud billing budgets update <name from the read command below> \
  --billing-project=expense-tracker-482807 \
  --budget-amount=275BRL
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

---

## Cold starts: the keepalive job

`min-instances` is **0**, so an idle service scales to zero and the next request
pays a cold start (measured: **~15s**). A Cloud Scheduler job pings `/healthz/`
every 5 minutes during waking hours to keep one instance alive.

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
