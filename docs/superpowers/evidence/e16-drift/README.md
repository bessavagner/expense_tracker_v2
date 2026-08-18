# E16 S16-9 — drift detected without a user hitting it

**Date:** 2026-08-18
**Environment:** staging (`expense-tracker-staging`), against a **genuinely
drifted database** — not a mock, not a patched function.

## What was done

`core.0009_policy_acceptance_and_consent` was un-recorded on staging's database
with `migrate core 0008 --fake`. `--fake` on both sides because the schema never
changed — only the `django_migrations` rows did, which is byte-for-byte the shape
production was in on 2026-08-15: the column present, the row saying so absent.

## 1. The command names the migration and exits non-zero

```
$ manage.py check_migration_drift
CommandError: ledger_drift_check_ran: schema drift — the database has not applied
1 migration(s): core.0009_policy_acceptance_and_consent. Fix with:
DATABASE_URL=<direct connection, port 5432> uv run python src/backend/manage.py migrate
exit=1
```

The exit code is the contract — Cloud Scheduler decides the job failed from the
process status. A command that printed a warning and exited 0 would make the
nightly check decorative.

## 2. The deployed service degrades to 503, from outside

```
$ curl -s -o /dev/null -w '%{http_code}' https://expense-tracker-staging-654941182076.southamerica-east1.run.app/healthz/
503

$ curl -s .../healthz/ | python3 -m json.tool
{
    "status": "degraded",
    "database": "ok",
    "migrations": "drift",
    "unapplied": [
        "core.0009_policy_acceptance_and_consent"
    ]
}
```

**This is the assertion S16-9's DoD asks for.** No user had to hit a broken page,
no exception was raised, and the response says exactly which migration to run.
`"database": "ok"` alongside `"migrations": "drift"` is the distinction that
sends an operator to the right runbook section — an unreachable database and a
drifted one are different outages.

Because the uptime check polls this endpoint every five minutes (policy
`17994738960177318338`, notifying *Operator email*), a 503 here means detection
in **≤5 minutes**. On 2026-08-15 the same condition went unnoticed for about a
day.

## 3. Recovery needs no redeploy

```
$ manage.py migrate --fake
  Applying core.0009_policy_acceptance_and_consent... FAKED
$ manage.py check_migration_drift
ledger_drift_check_ran: no drift
exit=0

$ curl -s -o /dev/null -w '%{http_code}' .../healthz/
200
```

The code was always correct; only the database was behind. The service returned
to rotation on its own.

## The nightly check

Cloud Run Job `ledger-drift-check`, Cloud Scheduler `ledger-drift-check-nightly`
at **03:50 America/Sao_Paulo** — not the 03:40 the plan proposed, which is
already taken by `ledger-usage-metrics-daily`. Alert *E16 schema-drift check has
not run* is `18431338427365827134`.

Proven end to end rather than assumed: the Scheduler was fired by hand and the
resulting **execution** was read, because the Scheduler reports success as soon
as an execution is *created*.

```
EXECUTION                 SUCCEEDED_COUNT  FAILED_COUNT
ledger-drift-check-d6s54  1
ledger-drift-check-689x6  1
```

## The three-way coverage this completes

| Where | Catches | Latency |
|---|---|---|
| `/healthz/` 503 | drift at any moment, including after a rollback | ≤5 min |
| Pipeline `Migrate production` + HTTP startup probe | drift a deploy would create | before the revision serves |
| `ledger-drift-check` nightly | drift that arrived without a deploy | ≤24h |

The middle row only became true during this epic: the startup probe was a
**TCP check on port 8080**, which cannot see a 503, so a drifted revision would
have gone live and served errors. Both services now probe `/healthz/` over HTTP.

## What this does not prove

The nightly job has been executed on demand and by the Scheduler on demand, but
has not yet run on its own schedule — the first unattended run is 03:50 the
morning after 2026-08-18. The silence alert cannot be observed firing without
waiting 36 hours with the job disabled, which was not done.
