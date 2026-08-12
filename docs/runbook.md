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

### `gcloud run deploy` is blocked in Claude Code agent sessions

The Claude Code auto-mode permission classifier denies `gcloud run deploy`
for agent sessions — this held true both for a regular implementer session
and for a controller session with the owner's authorization already given;
the controller session was also blocked from adding a permission rule for
itself. There is no agent-side workaround, and none should be attempted —
an agent granting itself deploy rights is exactly what the guard is for.
**The owner must run the deploy directly**, from a human-driven terminal:

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
it is safe against the current schema: those epics' migrations only *add* tables
and indexes (plus drop three redundant ones), so the older code neither misses
anything it needs nor trips over what it does not know about. **Do not unapply
the migrations to roll back the code** — they are not the thing that breaks.

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

E04 phase 2 gives all 13 domain models a `household` column and back-fills it
from `user`. It runs over real financial records, so it gets rehearsed against a
throwaway copy of production before it goes anywhere near the live database.

Row counts do not prove a migration was lossless — this project has a documented
history of reconciliation issues where the counts matched and the balances did
not. The rehearsal therefore compares **balances and the monthly acumulado**, via
`manage.py dump_ledger_totals --json`. Phase 2 changes no read path, so the two
fingerprints must be **byte-identical**.

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

The dump holds every row of the real ledger, so it is written to a `0700` temp
directory that an `EXIT` trap removes on **any** exit — including the
fingerprint-mismatch exit. The container goes with it. If the script is killed
with `SIGKILL`, clean up by hand: `docker rm -f e04-rehearsal-<pid>` and
`rm -rf /tmp/e04-rehearsal.*`.

`pg_restore` errors on Supabase's own schemas (`auth`, `vault`, `graphql`) are
expected and tolerated — vanilla Postgres has neither those extensions nor those
roles. What matters is the `public` schema, which is where every Django table
lives; the printed entry counts are the check that it arrived.

**Ran for real against production on 2026-08-12**: 3 users, 2320 entries,
sum 344529.48. Production had neither E04 phase, so `migrate` applied
`accounts.0001`–`0003` and both phases' six migrations in one go; fingerprint
identical, no unfilled rows, six indexes present.

Three outputs to check:

1. `OK — counts, sums and acumulado identical across the migration.`
2. `unfilled rows: none`
3. six index rows: `entry_hh_billing_type_idx`, `entry_hh_date_recent_idx`,
   `income_hh_month_idx`, `chat_hh_recent_idx`, `draft_hh_status_recent_idx`,
   `usage_hh_kind_recent_idx`

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

**Rehearsing without Supabase credentials.** The same script runs against the
local ledger copy. It is already migrated, so it needs rewinding first —
`REWIND=1` does that (`migrate finances 0012`, `migrate assistant 0009`) before
the BEFORE fingerprint:

```bash
PGHOST=172.17.0.1 PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres \
PGSSLMODE=prefer SOURCE_DB=expense_tracker REWIND=1 \
  scripts/rehearse-e04-migration.sh
```

`172.17.0.1`, not `localhost`: `pg_dump` runs inside a container, where
`localhost` is the container itself. `SOURCE_DB` names the database to dump —
`postgres` on Supabase, `expense_tracker` locally. Weaker evidence than the real
thing, since the local copy may lag production, but it exercises the whole
migration path on real records.

---

## Signing in, and clearing a lockout

The family's login page is **`/login/`**. It used to be `/admin/login/`, which is
why the app opened on a Django admin screen; that URL still exists and still
works, but it is the maintainer's door now. `LOGIN_URL` and `LogoutView` both
point at `/login/`, so an unauthenticated request to any page lands there with
`?next=` preserved.

**After deploying this change, tell the family nothing.** Their bookmarks and the
installed TWA point at `/`, which redirects correctly. Only a bookmark saved
directly on `/admin/login/` keeps working as-is (it does; it just skips the
branded page).

Brute-force lockout is **10 failed attempts in 15 minutes**, counted by username
*and* by IP, enforced in `core.auth_backends.LockoutModelBackend`. While locked,
even the correct password is refused, and `/login/` now says so in Portuguese
instead of showing the same message as a typo.

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
