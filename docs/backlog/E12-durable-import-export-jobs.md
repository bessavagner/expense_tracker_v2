---
id: E12
title: Durable import/export jobs
release: R3
status: done
depends_on: [E10]
blocks: [E13]
wedge_critical: false
---

# E12 · Durable import/export jobs

## Outcome

Importing a CSV and exporting a household's data are durable, resumable, size-bounded operations that work correctly on any number of Cloud Run instances — and a partially-bad import reports exactly which rows failed instead of dying halfway.

## Why now

Review findings **B4** and **H5**. The importer writes to local disk and stores the *path* in the session, which is a latent production failure that only stays hidden because traffic is one user on one warm instance. It also has no size cap on a RAM-backed filesystem, and it swallows database exceptions inside an atomic block.

It blocks **E13** because LGPD data portability is the same machinery in reverse. Building export as part of this epic costs a fraction of building it separately.

## Evidence in the codebase

| What | Where |
|---|---|
| Upload written to local disk, path stored in session | `finances/views/importer.py:35-60` |
| The path reopened in a later request — the cross-instance failure | `finances/views/importer.py:131` |
| Entire parsed row set serialized into the DB-backed session | `finances/views/importer.py:181, 186` |
| Session rewritten again on the preview step | `finances/views/importer.py:241-260` |
| `@transaction.atomic` wrapping the whole execution | `finances/views/importer.py:268` |
| Exceptions swallowed per row inside that atomic block | `finances/views/importer.py:363-364` |
| Per-row `Entry.objects.create` in a Python loop | `finances/views/importer.py:351` |
| Temp file cleanup that only happens on the success path | `finances/views/importer.py:367-369` |
| Deployment shape making this fail at scale | `--cpu 1 --memory 1Gi`, `docs/deploy/next-session-kickoff.md:62` |
| A working reference: the CLI importer | `finances/management/commands/import_csv.py` |

**Why H5 is a real bug, not a style issue:** if any row raises an `IntegrityError`, the Postgres transaction is already poisoned. The loop keeps issuing queries, every one raises `TransactionManagementError`, and the whole import dies while reporting a misleading `error_count`.

## Stories

### S12-1 · Durable job state

- **Given** the wizard currently keeps state in the session
- **When** an `ImportJob` model is introduced
- **Then** it holds household, creating user, storage path, status, column mapping, per-row results, and summary statistics
- **And** the wizard reads its state from the job, not the session
- **And** a job survives an instance restart and is resumable from any instance
- **And** a user can see their past imports and what each one did

### S12-2 · Object storage with an enforced size cap

- **Given** local disk is wrong on a stateless, RAM-backed runtime
- **When** storage moves to GCS
- **Then** uploads go to a bucket rather than the local filesystem
- **And** a maximum file size is enforced **before** the payload is accepted, not after
- **And** a lifecycle rule deletes uploaded files after an agreed retention period, because they contain financial data
- **And** local development uses a filesystem-backed storage fallback so the app runs without GCP
- **And** the bucket is not public, and access is via signed, expiring URLs

### S12-3 · Execute imports as a task, with per-row savepoints

- **Given** E10's task infrastructure
- **When** import execution moves to a task
- **Then** each row is processed inside its own savepoint, so one bad row cannot poison the transaction — this is the H5 fix
- **And** a failed row records **why** it failed, not just that it did
- **And** the job reports created, skipped, and failed counts that are actually accurate
- **And** the user can download a report of failed rows
- **And** re-running an import is idempotent — the existing duplicate detection (`finances/views/importer.py:162-177`) must survive the refactor
- **And** the per-row query overhead fixed in E03 S03-4 is preserved

### S12-4 · Household data export

- **Given** LGPD grants a right to portability (E13), and users leaving deserve their data
- **When** export is implemented
- **Then** a user can request a full export of their household's data
- **And** it runs as a task, writes to the same bucket, and is delivered as a signed, expiring URL
- **And** the format is machine-readable and genuinely re-importable — CSV that this product's own importer can consume, plus JSON for completeness
- **And** the export covers entries, income, categories, payment methods, budgets, installment plans, systematic expenses, and memory rules
- **And** chat history is included or deliberately excluded, with the decision recorded — E13 owns the retention policy
- **And** the export link expires and is not guessable

### S12-5 · Progress and honest failure

- **Given** an import of thousands of rows takes time
- **When** it is running
- **Then** the user sees real progress, not an indefinite spinner
- **And** a failed job says what went wrong in pt-BR and what to do next
- **And** a job that dies mid-execution is visible as failed rather than appearing to run forever

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Observable assertions:

- [x] A test proves an import survives the wizard's steps being served by different processes — the B4 fix — `test_import_job_wizard.py::TestTheWizardNeedsNoSession::test_each_step_can_be_served_by_a_different_session`
- [x] A test proves an oversized upload is rejected before storage — `test_import_storage.py::test_a_refused_upload_leaves_nothing_in_storage`
- [x] A test proves a row raising `IntegrityError` does not abort the remaining rows — the H5 fix — `test_import_runner.py::TestOneBadRowDoesNotPoisonTheRest`
- [x] A test proves re-running the same import creates no duplicates — `test_import_runner.py::TestIdempotence`, and `test_import_double_submit.py` under two real concurrent connections
- [x] Failed rows are individually reported with reasons — `test_import_progress.py::TestTheFailuresReport` (capped at 1000, with an exact count beyond it)
- [x] An export round-trips: export a household, import the result into a fresh household, and the ledger totals match — `test_export_roundtrip.py::TestRoundTrip::test_the_ledger_total_matches`, plus the per-category split
- [x] Export URLs expire, verified by test — `test_downloads.py::test_a_token_past_its_window_is_refused` and `test_export_views.py::TestDownloading::test_an_expired_link_is_a_404`
- [x] Local development works without GCP credentials — `test_storage.py::test_no_bucket_falls_back_to_the_filesystem`
- [x] `docs/runbook.md` documents the bucket, its retention rule, and how to investigate a stuck job — *Import and export jobs (E12)*

**Provisioned on 2026-08-16.** `gs://ledger-jobs-expense-tracker-482807` exists
in `southamerica-east1`, verified by `buckets describe`:
`uniform_bucket_level_access: True`, `public_access_prevention: enforced`, and
`lifecycle: {"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}`. The
Cloud Run runtime identity
(`654941182076-compute@developer.gserviceaccount.com`) holds
`roles/storage.objectAdmin` on it.

**Deployed 2026-08-16 as revision `expense-tracker-00048-lgf`.**

1. ✅ Migrations `0020_importjob`, `0021_exportjob` and `0022_importjob_queued`
   applied to Supabase over the session pooler on **port 5432**. A `pg_dump`
   was taken first and destroyed afterwards. `finances_importbatch` was
   verified **empty (0 rows)** before the rename, so nothing rode on it;
   afterwards `to_regclass` confirms the old name gone and
   `finances_importjob` + `finances_exportjob` present.
2. ✅ Redeployed with `--update-env-vars` (never `--set-env-vars`, which
   replaces the whole list and would wipe `DATABASE_URL`). Env count 18 → 20;
   `GS_BUCKET_NAME` and `MAX_CSV_UPLOAD_BYTES=2097152` present, every existing
   secret still there. No warnings or errors in the revision's logs.
3. ✅ `core.storage.job_storage()` verified against the **real bucket**:
   `GoogleCloudStorage` selected, write + read + delete round-trip under both
   `imports/` and `exports/`, and `storage.url()` carries no credentials.

4. ✅ **Signed-in round-trip against the deployed revision, 2026-08-16.** An
   import of `amostra-agosto-2.csv` — `status=done`, 2 of 2 rows created, 0
   skipped, 0 errors — and an export, `status=done`, 186 369 bytes, with
   `completed_at` set. `gcloud storage ls` shows exactly one object under each
   prefix, both under the same household:

   ```
   imports/551e80b8-…/96212e1d-….csv
   exports/551e80b8-…/9baef148-….zip
   ```

   This is the box a local probe could not stand in for: the objects were
   written by the Cloud Run service account, as the application, against the
   real bucket. **E12 is closed.**

## Out of scope

- The legal and policy side of LGPD — deletion semantics, retention periods, privacy notice → **E13**
- Importing from other apps' proprietary formats — CSV with column mapping already covers the need
- Open Finance / bank statement import — parked (INDEX §10)
- Redesigning the wizard's UI beyond what durable state requires

## Open questions — answered

All four were settled in the implementation plan
(`docs/superpowers/plans/2026-08-16-E12-durable-import-export-jobs.md`) before a
line was written, and are recorded here so the answers outlive the plan.

1. **What is the maximum import size?** → **2 MB** (`MAX_CSV_UPLOAD_BYTES`, down from 10 MB). About 20 000 rows of ledger CSV. Ten years of a family's history is ≈5 000 rows ≈ 500 KB, so this is 4× the realistic worst case and 0.2% of the instance's 1 GiB.
2. **How long are uploaded files retained?** → **7 days**, as a GCS lifecycle rule rather than as application code — a deletion that depends on our cron running is a deletion that does not happen. Shortest window that still lets a failed import reported on Monday be debugged.
3. **Is chat history part of an export?** → **Yes, in `ledger.json` only — never in the CSVs.** It is the user's data and LGPD portability covers it. Keeping it out of the re-importable CSVs means a leaked link to `entradas.csv` is not also a chat transcript. E13 ratifies; this epic implements.
4. **Does the export need encryption at rest beyond GCS's default?** → **No CMEK.** Google-managed AES-256 at rest, `--public-access-prevention`, uniform bucket-level access, and a 1-hour application-signed URL. CMEK adds a KMS key, its rotation, its IAM and its failure mode for a bucket whose contents live 7 days behind a private, expiring link. Recorded as a deliberate deferral to **E16**, not an oversight.

**A fifth decision the implementation made:** downloads are served by our own
view behind an application-signed token, never by a raw GCS signed URL. A GCS
signed URL from Cloud Run needs either a key file on disk or an IAM `SignBlob`
round-trip; a raw bucket URL cannot check `request.household`, so tenancy would
rest on URL secrecy alone; and one signing mechanism is the only way *"export
URLs expire, verified by test"* and *"local development works without GCP
credentials"* can both be true at once.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development` — the cross-instance and transaction-poisoning tests are the point of this epic
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `superpowers:verification-before-completion` — the export round-trip is the evidence
7. `superpowers:finishing-a-development-branch`
