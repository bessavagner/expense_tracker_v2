# Runbook

Operator procedures for the production deployment. Copy-paste as written.

Production is Cloud Run service `expense-tracker`, GCP project
`expense-tracker-482807`, region `southamerica-east1`, fronted by
<https://expense-tracker-654941182076.southamerica-east1.run.app>.

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
