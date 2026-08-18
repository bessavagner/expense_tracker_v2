# E16 S16-5 — a restore that was performed and timed

**Date:** 2026-08-18
**Performed by:** Vagner Bessa
**Source:** `gs://ledger-backups-expense-tracker-482807/ledger-2026-08-18T17-28-30Z.dump`
— the nightly `ledger-backup` job's output, written 17:28:30Z (by the
Scheduler-triggered execution `ledger-backup-54t7z`, not by hand).
**Target:** `ledger_restore_rehearsal`, a scratch database in the **staging**
Supabase project. Never staging's own database; never production.

## The measured RTO

| Phase | Duration |
|---|---|
| Download the backup from GCS | 2.6 s |
| `CREATE DATABASE` + `CREATE EXTENSION vector` | 2.5 s |
| `pg_restore` | 46.8 s |
| Verify with `dump_ledger_totals` | 3.6 s |
| Confirm no schema drift | 16.4 s |
| **Total — data recovered and verified** | **1 min 45 s** |

`docs/architecture/product-readiness-review.md` proposed **4 hours**. The
measured number is **1 minute 45 seconds**, and the reason it is so far off is
that the estimate was made without knowing the size of the database: the dump is
**545 KiB**. This product's data is three households and 2,326 entries. There is
no large-data problem to solve here, and no warm standby to buy.

**What that number is, precisely.** It is the time to get the data back, intact
and verified, into a database. **It is not the time to have the product serving
users again.** That additionally requires re-pointing `DATABASE_URL`, deploying a
revision, and re-provisioning three Cloud Run Jobs — see *What this does not
prove*. On the measurements taken during this epic, a `--source` deploy is ~7–8
minutes, so an honest end-to-end **service** RTO is **on the order of 15 minutes**,
of which the data recovery is under two. Both numbers matter and they are
different; quoting only the first would be the same mistake as quoting only the
estimate.

## The RPO, made visible

The backup was written at **17:28:30Z**; the production fingerprint was taken at
**17:30:37Z** — a gap of **2 min 07 s**, and the diff across that gap was
**empty**, because nothing wrote to the ledger in those two minutes. That is what
a near-zero RPO looks like when you happen to measure it right after a backup.

**The real RPO is the schedule, not this measurement.** With one backup at 03:00
America/Sao_Paulo, the worst case is **~24 hours of entries**: a failure at 02:55
loses everything entered since the previous 03:00. Whether that is acceptable is
a product decision, not a technical one. Halving it costs one more Scheduler job
and one more object per day.

## Integrity verification

Not row counts. `manage.py dump_ledger_totals --json` compares every household's
entry count, entry sum, income sum, and **every month's total, income and
acumulado** — because this project has a documented history of reconciliation
issues where the counts matched and the balances did not, which is why that
command exists.

Compared: **3 households, 110 household-months**. The largest household:

```
entries      2326
entry_sum    344935.85
income_sum   583823.66
months       38
```

```
$ diff <(python3 -m json.tool e16-before.json) <(python3 -m json.tool e16-after.json)
IDENTICAL — entry counts, sums, and every month's acumulado
```

Zero lines of diff. `FIXED_TODAY = date(2026, 8, 12)` was **not** changed, per
D12 — a drifting clock would have produced a spurious diff in `build_projection`'s
past/future split and made the comparison meaningless.

The application also starts against the restored database:

```
$ manage.py check_migration_drift
ledger_drift_check_ran: no drift
exit=0
```

That is E16 Task 2's command doing exactly the job it was written for, against a
database whose entire provenance is a backup file.

## Failures encountered

**`pg_restore: error: could not execute query: ERROR: permission denied for table
secrets` — 2 errors ignored, exit code 0.** Supabase's internal `vault` schema,
which the pooler user cannot write. It does **not** affect application data, and
the proof is the empty diff above rather than the exit code. Anticipated by the
plan and already recorded in the runbook (§ *Applying a migration to Supabase*,
failure #3). **Do not treat `errors ignored on restore: 2` as a failed restore,
and do not treat exit 0 as a successful one — verify the money.**

**`extension "vector" is not available` did NOT occur.** pgvector was available on
the staging project and `CREATE EXTENSION IF NOT EXISTS vector` succeeded in
under a second. Worth recording as a negative result: the plan flagged this as a
possible real RTO finding, and it is not one for this project today.

**Nothing else bit.** The two failures the plan warned about for the *backup*
side — a mis-set size floor and a broken upload — both happened, and are recorded
in `docs/runbook.md` § *Backups* rather than here, because they are failures of
taking the backup, not of restoring it.

## What this does not prove

The restore went into a scratch database. **Cutting production over to a restored
database has not been rehearsed** — that additionally requires re-pointing
`DATABASE_URL`, redeploying, and re-provisioning the `ledger-purge`,
`ledger-drift-check` and `ledger-backup` jobs against the new host. The runbook's
§ *Restoring from backup* documents that sequence; nobody has executed it.

Two further limits worth naming:

- **The restore target was the staging Supabase project.** A real incident in
  which the *production project itself* is unavailable would need a new project
  created first, and that step is untimed.
- **A 545 KiB dump is not a load test.** These numbers will change if the data
  grows by orders of magnitude, and `pg_restore` — 47 s of the 105 s — is the term
  that will grow.

## Cleanup

```
DROP DATABASE IF EXISTS ledger_restore_rehearsal WITH (FORCE);
```

`WITH (FORCE)` is required: the connection is held by Supabase's pooler rather
than by a client, so a plain `DROP DATABASE` fails with "is being accessed by
other users" while `pg_stat_activity` shows nobody (existing runbook, failure #4).

The downloaded dump and both totals files were deleted — every one of them is
production financial data. Staging's own database was confirmed untouched
afterwards (121 fabricated entries, as seeded).
