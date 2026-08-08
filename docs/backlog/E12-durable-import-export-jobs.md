---
id: E12
title: Durable import/export jobs
release: R3
status: blocked
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

- [ ] A test proves an import survives the wizard's steps being served by different processes — the B4 fix
- [ ] A test proves an oversized upload is rejected before storage
- [ ] A test proves a row raising `IntegrityError` does not abort the remaining rows — the H5 fix
- [ ] A test proves re-running the same import creates no duplicates
- [ ] Failed rows are individually reported with reasons
- [ ] An export round-trips: export a household, import the result into a fresh household, and the ledger totals match
- [ ] Export URLs expire, verified by test
- [ ] Local development works without GCP credentials
- [ ] `docs/runbook.md` documents the bucket, its retention rule, and how to investigate a stuck job

## Out of scope

- The legal and policy side of LGPD — deletion semantics, retention periods, privacy notice → **E13**
- Importing from other apps' proprietary formats — CSV with column mapping already covers the need
- Open Finance / bank statement import — parked (INDEX §10)
- Redesigning the wizard's UI beyond what durable state requires

## Open questions

1. **What is the maximum import size?** Derive from the realistic case — years of history from a spreadsheet — and set it comfortably above that, but well below anything that threatens the instance.
2. **How long are uploaded files retained?** They contain financial data. Shortest period that still allows debugging a failed import.
3. **Is chat history part of an export?** It is the user's data and it is also the most sensitive content in the system. E13 decides; this epic implements.
4. **Does the export need to be encrypted at rest** beyond GCS's default, given it is a complete financial history behind a URL?

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development` — the cross-instance and transaction-poisoning tests are the point of this epic
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `superpowers:verification-before-completion` — the export round-trip is the evidence
7. `superpowers:finishing-a-development-branch`
