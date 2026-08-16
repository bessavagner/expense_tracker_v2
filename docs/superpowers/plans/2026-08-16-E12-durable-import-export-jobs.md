# E12 · Durable import/export jobs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CSV import and household export durable, resumable and size-bounded operations that work on any Cloud Run instance, where one bad row fails alone and says why.

**Architecture:** The wizard's state moves out of the Django session and off local disk into two places: an `ImportJob` row (renamed from `ImportBatch`) and an object-storage key. Parsed rows are never stored — they are re-derived from the stored CSV plus the stored column mapping, which is what removes the multi-megabyte session write entirely. Execution moves into an E10 task that wraps every row in its own savepoint. Export is the same machinery in reverse: a task builds a ZIP into the same bucket, delivered through an application-signed, expiring URL.

**Tech Stack:** Django 6, PostgreSQL (Supabase pooler), `django-storages[google]` over GCS with a `FileSystemStorage` fallback, E10's `core.tasks` (Cloud Tasks + eager local backend), HTMX polling, pytest + model-bakery + time-machine.

**Spec:** [`docs/backlog/E12-durable-import-export-jobs.md`](../../backlog/E12-durable-import-export-jobs.md)

---

## Decisions taken before this plan (E12 Open questions, resolved)

These answer the spec's four Open questions. They are settled — do not re-litigate them inside a task.

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Maximum import size | **2 MB** (`MAX_CSV_UPLOAD_BYTES`, down from 10 MB) | ~20 000 rows of ledger CSV. Ten years of a family's history is ≈5 000 rows ≈ 500 KB, so 2 MB is 4× the realistic worst case and 0.2% of the 1 GiB instance. |
| 2 | Upload retention | **7 days**, as a GCS lifecycle rule | Shortest window that still lets a failed import reported on Monday be debugged. They are financial records; E13 inherits the smaller surface. |
| 3 | Chat history in the export | **Yes, in `ledger.json` only — never in the CSVs** | It is the user's data and LGPD portability covers it. Keeping it out of the re-importable CSVs means a leaked link to `entradas.csv` is not also a chat transcript. E13 ratifies; this epic implements. |
| 4 | Encryption at rest beyond GCS default | **No CMEK.** Google-managed AES-256 at rest, `--public-access-prevention`, uniform bucket-level access, and a 1-hour application-signed URL | CMEK adds a KMS key, its rotation, its IAM and its failure mode for a bucket whose contents live 7 days behind a private, expiring link. Recorded as a deliberate deferral to E16, not an oversight. |

**A fifth decision this plan makes:** downloads are served by **our own view behind an application-signed token**, never by a raw GCS signed URL. Three reasons: a GCS signed URL from Cloud Run needs either a key file on disk or an IAM `SignBlob` round-trip; a raw bucket URL cannot check `request.household`, so tenancy would be enforced by URL secrecy alone; and one signing mechanism means the expiry test runs locally, with no GCP, which is the only way DoD box *"Export URLs expire, verified by test"* and DoD box *"Local development works without GCP credentials"* can both be true.

---

## Global Constraints

Copied verbatim from `docs/backlog/INDEX.md` §7. Every task's requirements implicitly include this section; violating any of these fails review regardless of whether the DoD passes.

1. **TDD.** Test first, always. Project convention, not a preference.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number**. No epic may move arithmetic into a prompt.
4. **Tenant scoping is centralized.** After E04, no epic may write `filter(user=...)` on a domain model. Use the household-scoped manager (`.for_household(...)` / `.for_request(...)`).
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean. Line length 100, target py312.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
8. **pt-BR in the product UI, English in code, comments, and docs.** Existing convention.
9. **Migrations are reversible** or the epic states explicitly why not.
10. **No time-bomb tests.** Any date-sensitive test freezes the clock (`time_machine`). See E02.

**Verification commands** (the DoD draws on these; local dev needs the pgvector container on :5433):

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

**One pre-existing local failure** is expected and is not yours: `email_config` disagreeing with the local `.env`. Confirm it fails on `main` before spending time on it.

---

## File Structure

### Created

| File | Responsibility |
|---|---|
| `src/backend/core/storage.py` | The one place object storage is reached. `job_storage()` returns GCS or `FileSystemStorage`; nothing else in the codebase names a bucket. |
| `src/backend/core/downloads.py` | Application-signed download tokens: `sign_download()`, `unsign_download()`. One signing mechanism, so expiry is testable without GCP. |
| `src/backend/core/tests/test_storage.py` | Backend selection, and that the app is complete with no GCP credentials. |
| `src/backend/core/tests/test_downloads.py` | Token round-trip, tamper rejection, expiry under a frozen clock. |
| `src/backend/finances/models/import_job.py` | `ImportJob` — the durable wizard state. Replaces `import_batch.py`. |
| `src/backend/finances/models/export_job.py` | `ExportJob` — one requested household export. |
| `src/backend/finances/services/import_storage.py` | `store_upload()` — the size cap, enforced while streaming, before any byte is written. |
| `src/backend/finances/services/import_rows.py` | `rows_for(job)` — re-derives parsed rows from storage + mapping, and marks duplicates. The reason no row set is ever serialised into a session or a JSONField. |
| `src/backend/finances/services/import_runner.py` | `run_import(job)` — the per-row savepoint loop. Pure function; no HTTP, no request. |
| `src/backend/finances/services/export_builder.py` | `build_export(household) -> bytes` — the ZIP. |
| `src/backend/finances/tasks.py` | The two `@task_handler`s. Module name is part of E10's autodiscover contract. |
| `src/backend/finances/views/exporter.py` | Request an export, list them, download one. |
| `src/backend/finances/management/commands/sweep_stuck_import_jobs.py` | Turns a job that died mid-run from "running forever" into "failed". |
| `src/backend/templates/importer/_step_status.html` | The progress surface, polled by HTMX. |
| `src/backend/templates/importer/_progress.html` | The polled fragment alone. |
| `src/backend/templates/importer/import_history.html` | Past imports and what each one did. |
| `src/backend/templates/exporter/export_page.html` | Request and download exports. |
| `src/backend/finances/tests/test_import_storage.py` | The size cap. |
| `src/backend/finances/tests/test_import_job_wizard.py` | The cross-instance proof — the B4 fix. |
| `src/backend/finances/tests/test_import_runner.py` | The savepoint proof — the H5 fix. |
| `src/backend/finances/tests/test_import_progress.py` | Progress, stuck jobs, pt-BR failure. |
| `src/backend/finances/tests/test_import_history.py` | The history page. |
| `src/backend/finances/tests/test_export_builder.py` | Export contents. |
| `src/backend/finances/tests/test_export_roundtrip.py` | Export → import → totals match. |
| `src/backend/finances/tests/test_export_views.py` | Request, download, expiry, cross-household refusal. |

### Modified

| File | Change |
|---|---|
| `pyproject.toml` | Add `django-storages[google]`. |
| `src/backend/config/settings.py:493` | `MAX_CSV_UPLOAD_BYTES` 10 MB → 2 MB; add the storage, retention and stuck-job settings. |
| `.env.example:130` | Same values. |
| `src/backend/finances/views/importer.py` | Rewritten against `ImportJob`. The session is not read or written. |
| `src/backend/finances/urls.py:219-222` | Job-scoped URLs plus status, history and export. |
| `src/backend/finances/models/__init__.py` | `ImportBatch` → `ImportJob`, add `ExportJob`. |
| `src/backend/finances/admin.py` | Register both jobs. |
| `src/backend/templates/importer/_step_mapping.html`, `_step_preview.html`, `_step_result.html` | Job-scoped form actions. |
| `src/backend/templates/base.html:50` | Add the "Exportar" nav item. |
| `src/backend/finances/tests/features/test_import.py` | `ImportBatch` → `ImportJob`. |
| `src/backend/finances/tests/test_views_importer.py`, `test_import_double_submit.py`, `test_import_query_count.py` | Follow the URLs. |
| `src/backend/accounts/tests/test_tenancy_bases.py:110`, `test_bake_scoping.py:33`, `test_user_column_is_on_its_way_out.py:19`, `src/backend/finances/tests/test_household_columns.py:71` | Model-label allowlists: `ImportBatch` → `ImportJob`, add `ExportJob`. |
| `docs/runbook.md` | The bucket, its retention rule, and how to investigate a stuck job. |
| `docs/backlog/E12-durable-import-export-jobs.md`, `docs/backlog/INDEX.md` | Status, and the closing note. |

### Deleted

`src/backend/finances/models/import_batch.py` — becomes `import_job.py` by rename.

---

## Known bound, accepted deliberately

`core/tasks/views.py` holds `select_for_update` on the `TaskRun` row for the whole handler. A 20 000-row import therefore holds one row lock for the duration of the run. At the 2 MB cap that is bounded and well inside Cloud Run's 300 s request timeout; chunked execution across several tasks is the fix if a real user ever hits it, and it is **out of scope here**. Write this sentence into the runbook (Task 10) rather than discovering it in an incident.

---

## Task 1: Object storage, and the size cap enforced before storage

Delivers S12-2's storage half and its size half. Nothing later can be built without `job_storage()`.

**Files:**
- Create: `src/backend/core/storage.py`
- Create: `src/backend/core/tests/test_storage.py`
- Create: `src/backend/finances/services/import_storage.py`
- Create: `src/backend/finances/tests/test_import_storage.py`
- Modify: `pyproject.toml:6-29` (dependencies)
- Modify: `src/backend/config/settings.py:493`
- Modify: `.env.example:130`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `core.storage.job_storage() -> django.core.files.storage.Storage`
  - `core.storage.JOB_UPLOAD_PREFIX: str` = `"imports"`, `core.storage.JOB_EXPORT_PREFIX: str` = `"exports"`
  - `finances.services.import_storage.UploadTooLarge(ValueError)`
  - `finances.services.import_storage.store_upload(uploaded_file, household_id) -> str` (the storage key)
  - `finances.services.import_storage.open_text(key) -> io.TextIOWrapper`
  - Settings: `GS_BUCKET_NAME: str`, `JOB_STORAGE_ROOT: Path`, `IMPORT_UPLOAD_RETENTION_DAYS: int`, `EXPORT_RETENTION_DAYS: int`, `EXPORT_URL_MAX_AGE_SECONDS: int`, `IMPORT_STUCK_AFTER_MINUTES: int`, `MAX_CSV_UPLOAD_BYTES: int` (2 MB)

- [ ] **Step 1: Add the dependency**

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
uv add "django-storages[google]>=1.14"
```

Expected: `pyproject.toml` gains `django-storages[google]>=1.14` under `[project].dependencies`, and `uv.lock` updates. Add this comment directly above the new line, matching the style of the `google-cloud-tasks` entry already there:

```toml
    # E12. GCS is production-only: with GS_BUCKET_NAME unset, core.storage falls
    # back to FileSystemStorage and the app is complete with no GCP credentials.
    "django-storages[google]>=1.14",
```

- [ ] **Step 2: Write the failing storage tests**

Create `src/backend/core/tests/test_storage.py`:

```python
"""One place names a bucket, and with no bucket the app is still complete."""

from pathlib import Path

from django.core.files.storage import FileSystemStorage
from django.test import override_settings

from core.storage import JOB_EXPORT_PREFIX, JOB_UPLOAD_PREFIX, job_storage


@override_settings(GS_BUCKET_NAME="")
def test_no_bucket_falls_back_to_the_filesystem(tmp_path):
    with override_settings(JOB_STORAGE_ROOT=tmp_path):
        storage = job_storage()
    assert isinstance(storage, FileSystemStorage)
    assert Path(storage.location) == tmp_path


@override_settings(GS_BUCKET_NAME="")
def test_the_fallback_round_trips_bytes(tmp_path):
    from django.core.files.base import ContentFile

    with override_settings(JOB_STORAGE_ROOT=tmp_path):
        storage = job_storage()
        key = storage.save("imports/x.csv", ContentFile(b"data,valor\n"))
        with storage.open(key) as handle:
            assert handle.read() == b"data,valor\n"


def test_the_prefixes_are_distinct():
    """Uploads and exports share a bucket but never a namespace: the retention
    rule and the audit story differ, and a shared prefix makes both ambiguous."""
    assert JOB_UPLOAD_PREFIX != JOB_EXPORT_PREFIX
```

- [ ] **Step 3: Run them to verify they fail**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.storage'`

- [ ] **Step 4: Write `core/storage.py`**

```python
"""Where a job's bytes live.

One function, so that the bucket name, the ACL posture and the local fallback
are decided in exactly one place. A second construction site is how a bucket
ends up public because someone copied the defaults.

Deliberately uncached. Constructing either backend is cheap, and an
``lru_cache`` here would make ``override_settings`` in a test silently
ineffective -- the worst kind of test, one that passes without exercising
anything.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage

# Uploads and exports share the bucket and never the prefix. The lifecycle
# rules differ (E12 decisions 2 and 4), and a rule cannot target a prefix that
# also holds the other kind.
JOB_UPLOAD_PREFIX = "imports"
JOB_EXPORT_PREFIX = "exports"


def job_storage() -> Storage:
    """The storage backing import uploads and export archives.

    ``GS_BUCKET_NAME`` unset is the entire local story: no credentials, no
    emulator, no network. That is the answer to the spec's "local development
    works without GCP credentials", and it is a default rather than a flag so
    that forgetting to set something fails safe.
    """
    if settings.GS_BUCKET_NAME:
        from storages.backends.gcloud import GoogleCloudStorage

        return GoogleCloudStorage(
            bucket_name=settings.GS_BUCKET_NAME,
            # Uniform bucket-level access is on (see docs/runbook.md), so a
            # per-object ACL is not merely unnecessary -- GCS rejects it.
            default_acl=None,
            # No credentials in a URL. Downloads go through
            # core.downloads + a household check, never a raw bucket link.
            querystring_auth=False,
            # Two jobs must never collide; the caller's key already carries a
            # UUID, and this makes an accidental collision a new name rather
            # than a silent overwrite of somebody's financial data.
            file_overwrite=False,
        )
    return FileSystemStorage(location=settings.JOB_STORAGE_ROOT)
```

- [ ] **Step 5: Add the settings**

In `src/backend/config/settings.py`, replace line 493 and its comment:

```python
# The CSV importer never legitimately needs more than a few MB.
MAX_CSV_UPLOAD_BYTES = int(os.environ.get("MAX_CSV_UPLOAD_BYTES", str(10 * 1024 * 1024)))
```

with:

```python
# E12 decision 1. ~20 000 rows of ledger CSV. Ten years of a family's history
# is around 5 000 rows -- roughly 500 KB -- so this is 4x the realistic worst
# case and 0.2% of the instance's 1 GiB. Enforced twice: here for a request
# that declares its length (core.middleware, core.asgi_body_limit), and again
# while streaming in finances.services.import_storage, which is the check that
# holds for a chunked upload declaring nothing.
MAX_CSV_UPLOAD_BYTES = int(os.environ.get("MAX_CSV_UPLOAD_BYTES", str(2 * 1024 * 1024)))
```

Then append a new block immediately after the `CLOUD_TASKS_TARGET_BASE_URL` line (currently `settings.py:529`):

```python
# --- Job object storage (E12) -------------------------------------------
#
# Unset in development and in CI, and that is the whole local story: with no
# bucket, core.storage returns a FileSystemStorage and the application needs no
# GCP credentials to be complete. Same shape as CLOUD_TASKS_ENABLED.
GS_BUCKET_NAME = os.environ.get("GS_BUCKET_NAME", "")
# Where the fallback writes. Under BASE_DIR rather than /tmp so that a
# developer can actually find yesterday's upload, and gitignored.
JOB_STORAGE_ROOT = BASE_DIR / ".jobstore"
# E12 decision 2. Enforced by a GCS lifecycle rule, not by application code --
# a deletion that depends on our cron running is a deletion that does not
# happen. docs/runbook.md carries the rule.
IMPORT_UPLOAD_RETENTION_DAYS = int(os.environ.get("IMPORT_UPLOAD_RETENTION_DAYS", "7"))
EXPORT_RETENTION_DAYS = int(os.environ.get("EXPORT_RETENTION_DAYS", "7"))
# How long a download link stays valid. One hour is long enough to finish a
# download on a phone on mobile data and short enough that a link pasted into
# a chat is dead before it is read.
EXPORT_URL_MAX_AGE_SECONDS = int(os.environ.get("EXPORT_URL_MAX_AGE_SECONDS", "3600"))
# A job still RUNNING after this long lost its instance. It is reported as
# failed rather than left spinning -- S12-5's "visible as failed rather than
# appearing to run forever".
IMPORT_STUCK_AFTER_MINUTES = int(os.environ.get("IMPORT_STUCK_AFTER_MINUTES", "15"))
```

Add `.jobstore/` to `.gitignore`.

- [ ] **Step 6: Update `.env.example`**

Replace line 130 and add the neighbours:

```bash
# E12. 2 MB is ~20 000 rows; ten years of history is ~500 KB.
MAX_CSV_UPLOAD_BYTES=2097152
# Leave GS_BUCKET_NAME empty locally: the app then stores job files on the
# filesystem and needs no GCP credentials at all.
GS_BUCKET_NAME=
IMPORT_UPLOAD_RETENTION_DAYS=7
EXPORT_RETENTION_DAYS=7
EXPORT_URL_MAX_AGE_SECONDS=3600
IMPORT_STUCK_AFTER_MINUTES=15
```

- [ ] **Step 7: Run the storage tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_storage.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 8: Write the failing size-cap test**

Create `src/backend/finances/tests/test_import_storage.py`:

```python
"""The cap is enforced while streaming, before a byte reaches storage.

'Before the payload is accepted, not after' is the spec's wording and it is
load-bearing: the container's filesystem is backed by its 1 GiB of RAM, so
'write it and then check the size' spends exactly the memory the cap exists to
protect.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from core.storage import job_storage
from finances.services.import_storage import UploadTooLarge, open_text, store_upload

_HOUSEHOLD_ID = "3f1e6f7c-9a1b-4c2d-8e5f-0a1b2c3d4e5f"


@pytest.fixture
def local_storage(tmp_path):
    with override_settings(GS_BUCKET_NAME="", JOB_STORAGE_ROOT=tmp_path):
        yield tmp_path


def test_a_small_upload_is_stored_and_readable(local_storage):
    upload = SimpleUploadedFile("x.csv", b"data,valor\n01/03/2026,42\n", "text/csv")
    key = store_upload(upload, _HOUSEHOLD_ID)
    assert job_storage().exists(key)
    with open_text(key) as handle:
        assert handle.readline() == "data,valor\n"


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_an_oversized_upload_is_refused(local_storage):
    upload = SimpleUploadedFile("big.csv", b"x" * 65, "text/csv")
    with pytest.raises(UploadTooLarge):
        store_upload(upload, _HOUSEHOLD_ID)


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_a_refused_upload_leaves_nothing_in_storage(local_storage):
    """The assertion that makes this a real 'before storage' test rather than a
    'delete it afterwards' one."""
    upload = SimpleUploadedFile("big.csv", b"x" * 100_000, "text/csv")
    with pytest.raises(UploadTooLarge):
        store_upload(upload, _HOUSEHOLD_ID)
    assert list(local_storage.rglob("*.csv")) == []


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_exactly_the_limit_is_accepted(local_storage):
    """Off-by-one in the wrong direction rejects a legitimate file, which is a
    support ticket rather than an incident -- but it is still a defect."""
    upload = SimpleUploadedFile("edge.csv", b"x" * 64, "text/csv")
    assert store_upload(upload, _HOUSEHOLD_ID)


def test_non_utf8_is_refused_with_a_ptbr_reason(local_storage):
    upload = SimpleUploadedFile("latin.csv", "descrição\n".encode("latin-1"), "text/csv")
    key = store_upload(upload, _HOUSEHOLD_ID)
    with pytest.raises(UnicodeDecodeError):
        with open_text(key) as handle:
            handle.read()


def test_the_key_is_namespaced_by_household(local_storage):
    key = store_upload(SimpleUploadedFile("x.csv", b"a\n", "text/csv"), _HOUSEHOLD_ID)
    assert key.startswith(f"imports/{_HOUSEHOLD_ID}/")


def test_two_uploads_of_the_same_name_do_not_collide(local_storage):
    first = store_upload(SimpleUploadedFile("x.csv", b"a\n", "text/csv"), _HOUSEHOLD_ID)
    second = store_upload(SimpleUploadedFile("x.csv", b"b\n", "text/csv"), _HOUSEHOLD_ID)
    assert first != second
    assert isinstance(io.TextIOWrapper(job_storage().open(second)), io.TextIOWrapper)
```

- [ ] **Step 9: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finances.services.import_storage'`

- [ ] **Step 10: Write `finances/services/import_storage.py`**

```python
"""Getting an uploaded CSV into object storage, and back out as text.

The cap is counted here rather than trusted from a header. ``Content-Length``
is what ``core.middleware`` and ``core.asgi_body_limit`` check, and both are
right to -- but a chunked request declares no length, and multipart overhead
means a legal declared length can still wrap an illegal file. Counting the
chunks as they arrive is the check that cannot be lied to.
"""

import io
import uuid

from django.conf import settings
from django.core.files.base import ContentFile

from core.storage import JOB_UPLOAD_PREFIX, job_storage


class UploadTooLarge(ValueError):
    """The upload exceeded ``MAX_CSV_UPLOAD_BYTES`` and was never stored."""

    def __init__(self, limit_bytes: int):
        self.limit_bytes = limit_bytes
        super().__init__(f"Upload exceeds {limit_bytes} bytes.")


def store_upload(uploaded_file, household_id) -> str:
    """Stream ``uploaded_file`` into object storage. Returns its key.

    Buffered in memory on purpose: the ceiling is 2 MB, which is smaller than
    the multipart body Django has already accepted, so this adds nothing to the
    peak. Streaming straight to the backend would be worse, not better -- it
    would mean a rejected upload had already written partial bytes to a bucket
    the caller then has to remember to clean up.
    """
    limit = settings.MAX_CSV_UPLOAD_BYTES
    buffer = io.BytesIO()
    total = 0
    for chunk in uploaded_file.chunks():
        total += len(chunk)
        if total > limit:
            # Nothing has been written to storage at this point, and nothing
            # will be. That is the property test_a_refused_upload_leaves_
            # nothing_in_storage asserts.
            raise UploadTooLarge(limit)
        buffer.write(chunk)

    key = f"{JOB_UPLOAD_PREFIX}/{household_id}/{uuid.uuid4()}.csv"
    return job_storage().save(key, ContentFile(buffer.getvalue()))


def open_text(key: str) -> io.TextIOWrapper:
    """The stored CSV as a UTF-8 text stream.

    ``newline=""`` because ``csv.reader`` does its own newline handling; without
    it a quoted field containing a line break is split into two rows, which in
    this product means one entry's description becoming a second, malformed
    entry.
    """
    return io.TextIOWrapper(job_storage().open(key), encoding="utf-8", newline="")
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_storage.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 12: Confirm the existing body-limit tests still hold**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_request_body_limit.py -v`
Expected: PASS. `test_request_body_limit.py:67` asserts `MAX_CSV_UPLOAD_BYTES < MAX_REQUEST_BODY_BYTES`; 2 MB < 60 MB, so lowering the cap keeps it true.

- [ ] **Step 13: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add pyproject.toml uv.lock .env.example .gitignore \
        src/backend/core/storage.py src/backend/core/tests/test_storage.py \
        src/backend/config/settings.py \
        src/backend/finances/services/import_storage.py \
        src/backend/finances/tests/test_import_storage.py
git commit -m "feat(E12): object storage for job files, with the size cap enforced before it"
```

---

## Task 2: `ImportJob` — the durable wizard state

Delivers S12-1's model half. `ImportBatch` becomes `ImportJob`: same table, same row, more columns. One concept, one model — introducing `ImportJob` alongside `ImportBatch` would leave two records of the same import and no rule for which one is true.

**Files:**
- Create: `src/backend/finances/models/import_job.py`
- Delete: `src/backend/finances/models/import_batch.py`
- Create: `src/backend/finances/migrations/0020_importjob.py`
- Modify: `src/backend/finances/models/__init__.py:1-23`
- Modify: `src/backend/finances/admin.py`
- Modify: `src/backend/finances/tests/features/test_import.py:9,135,143`
- Modify: `src/backend/accounts/tests/test_tenancy_bases.py:110`
- Modify: `src/backend/accounts/tests/test_bake_scoping.py:33`
- Modify: `src/backend/accounts/tests/test_user_column_is_on_its_way_out.py:19`
- Modify: `src/backend/finances/tests/test_household_columns.py:71`
- Test: `src/backend/finances/tests/test_import_job_model.py`

**Interfaces:**
- Consumes: `core.storage` settings from Task 1 (`IMPORT_STUCK_AFTER_MINUTES`).
- Produces:
  - `finances.models.ImportJob` with fields `id: UUID`, `household`, `created_by`, `import_type: str`, `storage_key: str`, `original_filename: str`, `status: str`, `column_mapping: dict`, `skip_lines: list[int]`, `category_resolutions: dict`, `pm_resolutions: dict`, `total_rows: int`, `processed_count: int`, `created_count: int`, `skipped_count: int`, `error_count: int`, `failures: list[dict]`, `failures_truncated: int`, `error_message: str`, `created_at`, `started_at`, `executed_at`, `updated_at`
  - `finances.models.ImportStatus` — `UPLOADED`, `MAPPED`, `RUNNING`, `DONE`, `FAILED`
  - `ImportJob.MAX_RECORDED_FAILURES: int` = 1000
  - `ImportJob.is_stuck -> bool`, `ImportJob.is_finished -> bool`, `ImportJob.progress_percent -> int`
  - `ImportJob.record_failure(line: int, reason: str) -> None`

- [ ] **Step 1: Write the failing model test**

Create `src/backend/finances/tests/test_import_job_model.py`:

```python
"""What the job promises the views and the runner."""

from datetime import timedelta

import pytest
import time_machine
from django.test import override_settings
from django.utils import timezone
from model_bakery import baker

from finances.models import ImportJob, ImportStatus


@pytest.mark.django_db
class TestImportJobState:
    def test_a_new_job_is_uploaded_and_unfinished(self, household):
        job = baker.make(ImportJob, household=household)
        assert job.status == ImportStatus.UPLOADED
        assert not job.is_finished

    @pytest.mark.parametrize("status", [ImportStatus.DONE, ImportStatus.FAILED])
    def test_done_and_failed_are_finished(self, household, status):
        job = baker.make(ImportJob, household=household, status=status)
        assert job.is_finished

    def test_progress_is_zero_when_nothing_is_known_yet(self, household):
        job = baker.make(ImportJob, household=household, total_rows=0, processed_count=0)
        assert job.progress_percent == 0

    def test_progress_is_a_whole_percentage(self, household):
        job = baker.make(ImportJob, household=household, total_rows=8, processed_count=3)
        assert job.progress_percent == 37

    def test_progress_never_exceeds_one_hundred(self, household):
        """A retry that re-counts must not render a 140% bar."""
        job = baker.make(ImportJob, household=household, total_rows=8, processed_count=99)
        assert job.progress_percent == 100


@pytest.mark.django_db
class TestStuckDetection:
    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_recently_started_job_is_not_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=14),
        )
        assert not job.is_stuck

    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_long_running_job_is_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=16),
        )
        assert job.is_stuck

    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_finished_job_is_never_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.DONE,
            started_at=timezone.now() - timedelta(days=3),
        )
        assert not job.is_stuck


@pytest.mark.django_db
class TestFailureRecording:
    def test_a_failure_is_recorded_with_its_line_and_reason(self, household):
        job = baker.make(ImportJob, household=household)
        job.record_failure(7, "Categoria não encontrada")
        assert job.failures == [{"line": 7, "reason": "Categoria não encontrada"}]
        assert job.failures_truncated == 0

    def test_recording_stops_at_the_cap_but_the_count_stays_exact(self, household):
        """Individually reported up to the cap; beyond it, honest about how many
        more there were. An unbounded JSONField on a pooled connection is the
        alternative, and a 20 000-row file that fails entirely would write
        megabytes into one row."""
        job = baker.make(ImportJob, household=household)
        for line in range(ImportJob.MAX_RECORDED_FAILURES + 5):
            job.record_failure(line, "erro")
        assert len(job.failures) == ImportJob.MAX_RECORDED_FAILURES
        assert job.failures_truncated == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_job_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ImportJob' from 'finances.models'`

- [ ] **Step 3: Write `finances/models/import_job.py`**

```python
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import AuthoredHouseholdModel


class ImportStatus(models.TextChoices):
    UPLOADED = "uploaded", "Enviado"
    MAPPED = "mapped", "Mapeado"
    RUNNING = "running", "Importando"
    DONE = "done", "Concluído"
    FAILED = "failed", "Falhou"


class ImportJob(AuthoredHouseholdModel):
    """One CSV import: where its file is, what it was told to do, and what it did.

    Was ``ImportBatch``, whose job was narrower -- it existed only so that
    ``ImportExecuteView`` could lock a committed row and refuse a double-tapped
    POST (a 4000-row CSV once produced 8000 rows while the page reported
    "Importados 4000"). That property survives here unchanged, and it is now the
    smaller half of what this row does.

    The larger half is E12's B4 fix. The wizard used to keep the uploaded file's
    *local path* in the session and the parsed row set in the session body. On a
    single warm instance that works; on any second instance the path names a
    file that does not exist, and the row set was a multi-megabyte write into a
    database-backed session on every step. Both are gone: the file is in object
    storage under ``storage_key``, and the rows are re-derived from that file
    plus ``column_mapping`` whenever they are needed. Nothing about a job lives
    in a session, so a job survives a restart and any step can be served by any
    instance.

    ``failures`` is capped rather than unbounded, and ``failures_truncated``
    keeps the count exact past the cap. A 2 MB CSV is around 20 000 rows; a file
    where every row fails would otherwise write megabytes of JSON into one row
    on a pooled connection.
    """

    MAX_RECORDED_FAILURES = 1000

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_type = models.CharField(max_length=20, default="regular")

    storage_key = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Chave do arquivo no armazenamento de objetos.",
    )
    original_filename = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=ImportStatus.choices,
        default=ImportStatus.UPLOADED,
    )
    column_mapping = models.JSONField(default=dict, blank=True)
    skip_lines = models.JSONField(default=list, blank=True)
    category_resolutions = models.JSONField(default=dict, blank=True)
    pm_resolutions = models.JSONField(default=dict, blank=True)

    total_rows = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    failures = models.JSONField(default=list, blank=True)
    failures_truncated = models.PositiveIntegerField(default=0)
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Em pt-BR: o que deu errado e o que fazer. Mostrado ao usuário.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Quando a importação terminou. Nulo = preparada ou em execução.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "importação"
        verbose_name_plural = "importações"
        ordering = ["-created_at"]
        indexes = [
            # The history page, and the stuck-job sweep.
            models.Index(fields=["household", "-created_at"], name="importjob_hh_recent_idx"),
            models.Index(fields=["status", "started_at"], name="importjob_status_started_idx"),
        ]

    def __str__(self):
        return f"Importação {self.id} ({self.get_status_display()})"

    @property
    def is_finished(self) -> bool:
        return self.status in {ImportStatus.DONE, ImportStatus.FAILED}

    @property
    def is_stuck(self) -> bool:
        """RUNNING for longer than any real import takes.

        The instance that was running it is gone -- Cloud Run recycled it, or
        the task exhausted the request timeout. Nothing will ever move this row
        again, so leaving it RUNNING shows the user an spinner that never stops.
        """
        if self.status != ImportStatus.RUNNING or self.started_at is None:
            return False
        cutoff = timezone.now() - timedelta(minutes=settings.IMPORT_STUCK_AFTER_MINUTES)
        return self.started_at < cutoff

    @property
    def progress_percent(self) -> int:
        if not self.total_rows:
            return 0
        return min(100, round(100 * self.processed_count / self.total_rows))

    def record_failure(self, line: int, reason: str) -> None:
        """Remember why one row did not land.

        Mutates in memory only; the caller decides when to write, because the
        runner batches its saves rather than paying a round trip per bad row.
        """
        if len(self.failures) < self.MAX_RECORDED_FAILURES:
            self.failures.append({"line": line, "reason": reason})
        else:
            self.failures_truncated += 1
```

Delete `src/backend/finances/models/import_batch.py`.

- [ ] **Step 4: Update `finances/models/__init__.py`**

Replace the `import_batch` line and the `__all__` entry:

```python
from finances.models.budget import Budget
from finances.models.category import Category
from finances.models.entry import Entry, EntryType
from finances.models.import_job import ImportJob, ImportStatus
from finances.models.income import Income
from finances.models.installment_plan import InstallmentPlan
from finances.models.payment_method import PaymentMethod, PaymentType
from finances.models.payment_method_closing_day import PaymentMethodClosingDay
from finances.models.systemic_expense import SystemicExpense

__all__ = [
    "Budget",
    "Category",
    "Entry",
    "EntryType",
    "ImportJob",
    "ImportStatus",
    "Income",
    "InstallmentPlan",
    "PaymentMethod",
    "PaymentMethodClosingDay",
    "PaymentType",
    "SystemicExpense",
]
```

(`ExportJob` joins this list in Task 8.)

- [ ] **Step 5: Generate the migration and make the rename explicit**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations finances --name importjob
```

Django will ask *"Did you rename the finances.ImportBatch model to ImportJob?"* — answer **yes**. Verify the generated `src/backend/finances/migrations/0020_importjob.py` begins with `migrations.RenameModel(old_name="ImportBatch", new_name="ImportJob")` followed by `AddField` operations. If it instead emitted `DeleteModel` + `CreateModel`, **delete the file and regenerate**: that pair drops the table and every production import record with it.

Add this docstring at the top of the generated file:

```python
"""ImportBatch becomes ImportJob, and gains everything E12 needs.

RenameModel, not delete-and-create: production holds real import records and
the counts on them are the only history of what landed. Reversible -- the
reverse renames the table back and drops the added columns, which is lossless
for anything that existed before this migration.
"""
```

- [ ] **Step 6: Prove the migration is reversible**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0020
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0019
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0020
```

Expected: three clean runs, no errors. Global constraint 9.

- [ ] **Step 7: Follow the rename through the allowlists**

Four test files hold literal model labels. Replace `"finances.ImportBatch"` with `"finances.ImportJob"` at `accounts/tests/test_tenancy_bases.py:110`, `accounts/tests/test_user_column_is_on_its_way_out.py:19`, `finances/tests/test_household_columns.py:71`, and `"ImportBatch"` with `"ImportJob"` at `accounts/tests/test_bake_scoping.py:33`.

In `finances/tests/features/test_import.py`, change the import at line 9 to `from finances.models import Entry, ImportJob, InstallmentPlan`, rename the test at line 134 to `test_import_job_belongs_to_the_household`, and change line 143 to `job = ImportJob.objects.latest("created_at")` with the following assertions reading `job` rather than `batch`.

- [ ] **Step 8: Register it in the admin**

In `src/backend/finances/admin.py`, add to the `from finances.models import (...)` block: `ImportJob,` and register:

```python
@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    """Read-only on purpose: this is the record of what an import did, and an
    editable count is a record that can be made to lie."""

    list_display = ("id", "household", "status", "import_type", "created_count",
                    "error_count", "created_at")
    list_filter = ("status", "import_type")
    search_fields = ("id", "original_filename")
    readonly_fields = [field.name for field in ImportJob._meta.fields]

    def has_add_permission(self, request):
        return False
```

- [ ] **Step 9: Run the model tests and the touched suites**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_job_model.py \
  src/backend/finances/tests/features/test_import.py \
  src/backend/finances/tests/test_household_columns.py \
  src/backend/accounts/tests/ -q
```
Expected: PASS. `test_import.py` still drives the old session-based views, which are untouched so far — it must stay green through this task.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add -A src/backend/finances src/backend/accounts
git commit -m "feat(E12): ImportBatch becomes ImportJob, carrying the wizard's durable state"
```

---

## Task 3: The wizard reads its state from the job, not the session — the B4 fix

Delivers the rest of S12-1. After this task no importer view touches `request.session`, and the URLs carry the job id so any instance can serve any step.

**Files:**
- Create: `src/backend/finances/services/import_rows.py`
- Create: `src/backend/finances/tests/test_import_job_wizard.py`
- Modify: `src/backend/finances/views/importer.py` (rewritten)
- Modify: `src/backend/finances/urls.py:219-222`
- Modify: `src/backend/templates/importer/_step_upload.html`, `_step_mapping.html:29`, `_step_preview.html`
- Modify: `src/backend/finances/tests/test_views_importer.py`, `test_import_double_submit.py`, `test_import_query_count.py`, `tests/features/test_import.py`

**Interfaces:**
- Consumes: `finances.services.import_storage.store_upload/open_text/UploadTooLarge` (Task 1); `finances.models.ImportJob`, `ImportStatus` (Task 2).
- Produces:
  - `finances.services.import_rows.rows_for(job) -> list[dict]` — parsed rows with `status` in `{"ok", "duplicate", "error"}`, each carrying `line: int`
  - `finances.services.import_rows.headers_for(job) -> list[str]`
  - `finances.services.import_rows.unmatched_names(job, rows) -> tuple[list[str], list[str]]`
  - `finances.services.import_rows.FIELDS_BY_TYPE: dict[str, list[str]]`
  - URL names, all under the `finances:` namespace: `import_upload` (`/import/`), `import_map` (`/import/<uuid:job_id>/mapear/`), `import_preview` (`/import/<uuid:job_id>/preview/`), `import_execute` (`/import/<uuid:job_id>/executar/`)

- [ ] **Step 1: Write the failing cross-instance test**

Create `src/backend/finances/tests/test_import_job_wizard.py`:

```python
"""The B4 fix, asserted the only way that means anything.

The old wizard wrote the uploaded file's local path into the session and
reopened it in a later request. On one warm instance that works. On Cloud Run
with more than one instance the second request lands somewhere the file does
not exist -- and the failure is invisible until traffic grows, which is exactly
when it is most expensive.

Two independent Client objects for the same user are two independent session
cookies, which is as close as the test suite gets to two processes. If any step
still depends on session state, the second client cannot complete the wizard.
"""

import io

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Entry, ImportJob, ImportStatus

_CSV = (
    b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
    b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
    b'05/03/2026,"R$ 14,00",Disk Bebida,\xc3\x81lcool,Pix\n'
)

_MAPPING = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


@pytest.fixture
def seeded(household):
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


@pytest.fixture
def second_client(user):
    """A second session for the same person -- the stand-in for a second
    instance. Must not share a cookie with `logged_client`."""
    client = Client()
    client.force_login(user)
    return client


def _upload(client):
    handle = io.BytesIO(_CSV)
    handle.name = "historico.csv"
    return client.post("/import/", data={"file": handle, "import_type": "regular"})


@pytest.mark.django_db
class TestTheWizardNeedsNoSession:
    def test_each_step_can_be_served_by_a_different_session(
        self, logged_client, second_client, seeded
    ):
        response = _upload(logged_client)
        job = ImportJob.objects.for_household(seeded).get()

        # Every subsequent step goes through the OTHER client.
        assert response.status_code == 302
        assert response.url == f"/import/{job.id}/mapear/"

        assert second_client.get(f"/import/{job.id}/mapear/").status_code == 200
        assert second_client.post(f"/import/{job.id}/mapear/", data=_MAPPING).status_code == 302
        assert second_client.get(f"/import/{job.id}/preview/").status_code == 200
        assert second_client.post(f"/import/{job.id}/executar/").status_code == 302

        assert Entry.objects.for_household(seeded).count() == 2

    def test_the_session_is_never_written(self, logged_client, seeded):
        """The narrower assertion, and the one that catches a partial fix: a
        wizard that still writes rows into the session has not stopped being
        the bug, it has only stopped reading them back."""
        _upload(logged_client)
        job = ImportJob.objects.for_household(seeded).get()
        logged_client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        logged_client.get(f"/import/{job.id}/preview/")

        assert "import_data" not in logged_client.session
        assert not any("import" in key for key in logged_client.session.keys())

    def test_a_job_survives_being_reloaded_from_scratch(self, logged_client, seeded):
        """No in-process cache: the whole state is columns and a stored file."""
        _upload(logged_client)
        job_id = ImportJob.objects.for_household(seeded).get().pk
        logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING)

        job = ImportJob.objects.get(pk=job_id)
        assert job.status == ImportStatus.MAPPED
        assert job.column_mapping == {"date": 0, "amount": 1, "description": 2,
                                      "category": 3, "payment_method": 4}
        assert job.storage_key
        assert job.total_rows == 2


@pytest.mark.django_db
class TestTenancy:
    def test_another_households_job_is_not_reachable(self, logged_client, seeded,
                                                     other_household, other_user):
        other_job = baker.make(ImportJob, household=other_household, created_by=other_user)
        for suffix in ("mapear/", "preview/"):
            assert logged_client.get(f"/import/{other_job.id}/{suffix}").status_code == 404
        assert logged_client.post(f"/import/{other_job.id}/executar/").status_code == 404

    def test_a_job_id_that_does_not_exist_is_a_404(self, logged_client, seeded):
        missing = "00000000-0000-4000-8000-000000000000"
        assert logged_client.get(f"/import/{missing}/preview/").status_code == 404


@pytest.mark.django_db
class TestUploadRejection:
    def test_an_oversized_upload_is_refused_in_ptbr_and_creates_no_job(
        self, logged_client, seeded, settings
    ):
        settings.MAX_CSV_UPLOAD_BYTES = 32
        handle = io.BytesIO(b"x" * 5000)
        handle.name = "grande.csv"
        response = logged_client.post(
            "/import/", data={"file": handle, "import_type": "regular"}
        )
        assert response.status_code == 200
        assert "grande demais" in response.content.decode()
        assert not ImportJob.objects.exists()

    def test_a_non_utf8_file_is_refused_and_the_job_is_discarded(self, logged_client, seeded):
        handle = io.BytesIO("data,valor,descrição\n01/03/2026,42,café\n".encode("latin-1"))
        handle.name = "latin.csv"
        response = logged_client.post(
            "/import/", data={"file": handle, "import_type": "regular"}
        )
        assert response.status_code == 200
        assert "UTF-8" in response.content.decode()
        assert not ImportJob.objects.exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_job_wizard.py -v`
Expected: FAIL — the upload POST returns a redirect to `/import/map/`, so `response.url == f"/import/{job.id}/mapear/"` fails, and `ImportJob.objects.for_household(...).get()` raises `DoesNotExist` because nothing creates a job at upload time yet.

- [ ] **Step 3: Write `finances/services/import_rows.py`**

```python
"""The parsed rows -- derived, never stored.

The old wizard wrote the whole parsed row set into a database-backed session on
the mapping step and rewrote it on the preview step. For a 4000-row file that is
two multi-megabyte session writes per import, and it is why the row set had to
be small enough to serialise, which it was not.

Re-deriving is cheap and it is *correct*: the file and the mapping are the
inputs, parsing is deterministic, and a job's rows can therefore never disagree
with the file it was made from. The cap is 2 MB, so a re-parse is milliseconds.
"""

from decimal import Decimal

from finances.models import Entry, InstallmentPlan
from finances.services.csv_parser import detect_columns, parse_csv_rows
from finances.services.import_storage import open_text

FIELDS_BY_TYPE = {
    "regular": ["date", "amount", "description", "category", "payment_method"],
    "installment": [
        "date",
        "total_amount",
        "description",
        "category",
        "payment_method",
        "num_installments",
        "installment_amount",
    ],
}


def fields_for(import_type: str) -> list[str]:
    return FIELDS_BY_TYPE.get(import_type, FIELDS_BY_TYPE["regular"])


def headers_for(job) -> list[str]:
    """The CSV's header row, for the mapping dropdowns."""
    import csv

    with open_text(job.storage_key) as handle:
        return next(csv.reader(handle))


def detected_mapping(job) -> dict[str, int]:
    return detect_columns(headers_for(job), job.import_type)


def rows_for(job, *, mark_duplicates: bool = True) -> list[dict]:
    """Parse the stored CSV with the job's mapping, marking known duplicates.

    ``mark_duplicates`` is False for the runner: it has already been told which
    lines to skip, and re-running the duplicate query there would both cost a
    query and change the answer, since the rows created earlier in the same run
    are now themselves in the table.
    """
    mapping = {field: int(index) for field, index in job.column_mapping.items()}
    with open_text(job.storage_key) as handle:
        rows = parse_csv_rows(handle, mapping, job.import_type)
    if mark_duplicates:
        _mark_duplicates(job, rows)
    return rows


def _mark_duplicates(job, rows: list[dict]) -> None:
    """One query for the whole file, narrowed to the dates it mentions.

    Carried over verbatim from the session-based importer (E03 S03-4): a
    per-row ``.exists()`` made this step's cost linear in the file, and a
    500-row statement export is a common import. Narrowing to the file's own
    dates keeps the fetched set small however long the household's history is.
    """
    amount_field = "total_amount" if job.import_type == "installment" else "amount"
    candidates = [row for row in rows if row["status"] == "ok"]
    if not candidates:
        return
    dates = {row["date"] for row in candidates}

    model = InstallmentPlan if job.import_type == "installment" else Entry
    field = "total_amount" if job.import_type == "installment" else "amount"
    already_imported = set(
        model.objects.for_household(job.household)
        .filter(date__in=dates)
        .values_list("date", field, "description")
    )

    for row in candidates:
        key = (row["date"], Decimal(row[amount_field]), row["description"])
        if key in already_imported:
            row["status"] = "duplicate"


def unmatched_names(job, rows: list[dict]) -> tuple[list[str], list[str]]:
    """Category and payment-method names in the file that the household lacks."""
    from finances.models import Category, PaymentMethod

    existing_categories = {
        name.lower()
        for name in Category.objects.for_household(job.household).values_list("name", flat=True)
    }
    existing_pms = {
        name.lower()
        for name in PaymentMethod.objects.for_household(job.household).values_list(
            "name", flat=True
        )
    }

    categories, payment_methods = set(), set()
    for row in rows:
        if row["status"] != "ok":
            continue
        category = row.get("category", "")
        if category and category.lower() not in existing_categories:
            categories.add(category)
        payment_method = row.get("payment_method", "")
        if payment_method and payment_method.lower() not in existing_pms:
            payment_methods.add(payment_method)
    return sorted(categories), sorted(payment_methods)
```

- [ ] **Step 4: Rewrite the upload, mapping and preview views**

Replace the top of `src/backend/finances/views/importer.py` — imports through `ImportPreviewView` — with the following. `report_import_failures` moves to the runner in Task 4; leave it in place for now so the module keeps importing.

```python
import csv
import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from finances.models import Category, ImportJob, ImportStatus, PaymentMethod
from finances.services.import_rows import (
    detected_mapping,
    fields_for,
    headers_for,
    rows_for,
    unmatched_names,
)
from finances.services.import_storage import UploadTooLarge, store_upload


def get_job(request, job_id) -> ImportJob:
    """The job, or a 404 -- scoped to the request's household.

    ``for_request`` rather than a bare ``get``: global constraint 4, and it is
    what makes another household's job id a 404 instead of a data leak.
    """
    return get_object_or_404(ImportJob.objects.for_request(request), pk=job_id)


class ImportUploadView(LoginRequiredMixin, View):
    """Step 1: accept the CSV, put it in object storage, mint the job."""

    def get(self, request):
        return render(request, "importer/import_page.html", {"step": "upload"})

    def _error(self, request, message):
        return render(
            request,
            "importer/import_page.html",
            {"step": "upload", "error": message},
        )

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        import_type = request.POST.get("import_type", "regular")

        if not uploaded_file:
            return self._error(request, "Selecione um arquivo CSV.")

        household = request.household
        try:
            storage_key = store_upload(uploaded_file, household.id)
        except UploadTooLarge as exc:
            megabytes = exc.limit_bytes // (1024 * 1024)
            return self._error(
                request,
                f"Arquivo grande demais (máximo {megabytes} MB). "
                "Divida a planilha em partes e importe uma de cada vez.",
            )

        job = ImportJob.objects.create(
            household=household,
            created_by=request.user,
            import_type=import_type,
            storage_key=storage_key,
            original_filename=uploaded_file.name[:255],
            status=ImportStatus.UPLOADED,
        )

        # Read the header row now, so a file that is not UTF-8 is rejected here
        # -- on the step the user is looking at -- rather than two steps later
        # with the wizard already half committed.
        try:
            headers_for(job)
        except (UnicodeDecodeError, StopIteration):
            job.delete()
            return self._error(
                request,
                "Arquivo não está em formato UTF-8, ou está vazio. "
                "Re-exporte do Google Sheets como CSV.",
            )

        return redirect("finances:import_map", job_id=job.id)


class ImportMappingView(LoginRequiredMixin, View):
    """Step 2: review and confirm the column mapping."""

    def get(self, request, job_id):
        job = get_job(request, job_id)
        headers = headers_for(job)
        return render(
            request,
            "importer/import_page.html",
            {
                "step": "mapping",
                "job": job,
                "mapping": job.column_mapping or detected_mapping(job),
                "headers": headers,
                "headers_indexed": list(enumerate(headers)),
                "fields": fields_for(job.import_type),
                "import_type": job.import_type,
            },
        )

    def post(self, request, job_id):
        job = get_job(request, job_id)

        mapping = {}
        for field in fields_for(job.import_type):
            raw = request.POST.get(field)
            if raw is None:
                continue
            try:
                mapping[field] = int(raw)
            except ValueError:
                return redirect("finances:import_map", job_id=job.id)

        job.column_mapping = mapping
        job.status = ImportStatus.MAPPED
        # Counted once, here, so the progress bar has a denominator before the
        # runner starts rather than after its first save.
        job.total_rows = len(rows_for(job, mark_duplicates=False))
        job.save(update_fields=["column_mapping", "status", "total_rows", "updated_at"])

        return redirect("finances:import_preview", job_id=job.id)


class ImportPreviewView(LoginRequiredMixin, View):
    """Step 3: show what will happen, and let the user steer it."""

    def get(self, request, job_id):
        job = get_job(request, job_id)
        if not job.column_mapping:
            return redirect("finances:import_map", job_id=job.id)

        rows = rows_for(job)
        unmatched_categories, unmatched_pms = unmatched_names(job, rows)
        skip_lines = set(job.skip_lines)

        return render(
            request,
            "importer/import_page.html",
            {
                "step": "preview",
                "job": job,
                "rows": rows,
                "ok_count": sum(1 for row in rows if row["status"] == "ok"),
                "dup_count": sum(1 for row in rows if row["status"] == "duplicate"),
                "err_count": sum(1 for row in rows if row["status"] == "error"),
                "import_type": job.import_type,
                "unmatched_categories": unmatched_categories,
                "unmatched_pms": unmatched_pms,
                "categories": Category.objects.for_request(request).order_by("name"),
                "payment_methods": PaymentMethod.objects.for_request(request)
                .filter(is_active=True)
                .order_by("name"),
                "skip_lines": skip_lines,
            },
        )

    def post(self, request, job_id):
        """Record skips and conflict resolutions on the job.

        Keyed by CSV *line number* rather than by list index. An index only
        means anything relative to a particular parse; a line number is a fact
        about the file, and it is what a failure report has to name for the
        user to find the row in their spreadsheet.
        """
        job = get_job(request, job_id)

        skip_lines = []
        category_resolutions = {}
        pm_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("skip_") and value == "on":
                try:
                    skip_lines.append(int(key.removeprefix("skip_")))
                except ValueError:
                    continue
            elif key.startswith("cat_resolve_") and value:
                category_resolutions[key.removeprefix("cat_resolve_")] = value
            elif key.startswith("pm_resolve_") and value:
                pm_resolutions[key.removeprefix("pm_resolve_")] = value

        job.skip_lines = sorted(skip_lines)
        job.category_resolutions = category_resolutions
        job.pm_resolutions = pm_resolutions
        job.save(
            update_fields=[
                "skip_lines",
                "category_resolutions",
                "pm_resolutions",
                "updated_at",
            ]
        )
        return redirect("finances:import_preview", job_id=job.id)
```

Leave `ImportExecuteView` as it is for this step — Task 4 replaces it. Give it the `job_id` parameter and have it load the job so the URL change compiles:

```python
class ImportExecuteView(LoginRequiredMixin, View):
    """Step 4: execute the import. Replaced by the task path in Task 4."""

    def post(self, request, job_id):
        job = get_job(request, job_id)
        from finances.services.import_runner import run_import  # Task 4

        run_import(job)
        return redirect("finances:import_preview", job_id=job.id)
```

- [ ] **Step 5: Update the URLs**

In `src/backend/finances/urls.py`, replace lines 219-222:

```python
    path("import/", ImportUploadView.as_view(), name="import_upload"),
    path("import/<uuid:job_id>/mapear/", ImportMappingView.as_view(), name="import_map"),
    path("import/<uuid:job_id>/preview/", ImportPreviewView.as_view(), name="import_preview"),
    path("import/<uuid:job_id>/executar/", ImportExecuteView.as_view(), name="import_execute"),
```

`core.middleware.IMPORT_PATH_PREFIX` is `"/import/"`, so every one of these still gets the 2 MB ceiling rather than the 60 MB one. Do not move the importer off that prefix.

- [ ] **Step 6: Update the templates to carry the job id**

`_step_mapping.html:29` — the "← Voltar" link goes back to a fresh upload, which is still `{% url 'finances:import_upload' %}`; leave it. The form's action must become job-scoped. In `_step_mapping.html`, change the form's `action` to `{% url 'finances:import_map' job_id=job.id %}`.

In `_step_preview.html`, change the two resolution form actions and the execute form action:

```html
<form method="post" action="{% url 'finances:import_preview' job_id=job.id %}">
```
(both the category and the payment-method blocks) and

```html
            <a href="{% url 'finances:import_map' job_id=job.id %}" class="btn btn-ghost">← Voltar</a>
            <form method="post" action="{% url 'finances:import_execute' job_id=job.id %}">
```

Change the skip checkbox from index to line number:

```html
                        <input type="checkbox" class="checkbox checkbox-sm"
                               name="skip_{{ row.line }}"
                               {% if row.line in skip_lines %}checked{% endif %}>
```

`_step_upload.html` needs no change — the upload URL is unchanged.

- [ ] **Step 7: Update the existing importer tests to the new URLs**

In `test_views_importer.py`, `test_import_query_count.py`, `test_import_double_submit.py` and `features/test_import.py`, every `client.post("/import/map/", ...)` becomes a post to `/import/<job.id>/mapear/`, and `/import/execute/` becomes `/import/<job.id>/executar/`. Add this helper to each and use it:

```python
def _job_id(client, household):
    from finances.models import ImportJob

    return ImportJob.objects.for_household(household).latest("created_at").pk
```

Delete `test_views_importer.py::TestImportExecuteView::test_execute_clears_session` and `test_execute_skips_duplicates_marked_for_skip`'s session-mutating block — replace the latter's setup with a POST to the preview step:

```python
        job_id = _job_id(logged_client, household)
        logged_client.post(f"/import/{job_id}/preview/", data={"skip_2": "on"})
        response = logged_client.post(f"/import/{job_id}/executar/")
```

(`skip_2` because the CSV's single data row is line 2 — line 1 is the header.)

Replace the deleted session test with its successor in `test_import_job_wizard.py::test_the_session_is_never_written`, which is strictly stronger.

- [ ] **Step 8: Run the wizard tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_job_wizard.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 9: Run every importer suite together**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_importer.py \
  src/backend/finances/tests/test_import_query_count.py \
  src/backend/finances/tests/test_import_double_submit.py \
  src/backend/finances/tests/features/test_import.py -q
```
Expected: PASS. `test_import_query_count.py` is E03 S03-4's gate — the spec requires it survive this refactor, so a failure here is a blocker, not a test to update.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances src/backend/templates/importer
git commit -m "feat(E12): the import wizard reads its state from the job, not the session"
```

---

## Task 4: The runner, with a savepoint per row — the H5 fix

Delivers S12-3's correctness half. This is the epic's reason to exist: today an `IntegrityError` on any row poisons the Postgres transaction, every subsequent query raises `TransactionManagementError`, and the import dies while reporting a misleading `error_count`.

**Files:**
- Create: `src/backend/finances/services/import_runner.py`
- Create: `src/backend/finances/tests/test_import_runner.py`
- Modify: `src/backend/finances/views/importer.py` (drop `report_import_failures`, it moves)

**Interfaces:**
- Consumes: `ImportJob`, `ImportStatus` (Task 2); `rows_for` (Task 3).
- Produces:
  - `finances.services.import_runner.run_import(job) -> None` — sets `status`, all four counts, `failures`, `started_at`, `executed_at`
  - `finances.services.import_runner.PROGRESS_EVERY: int` = 50
  - `finances.services.import_runner.report_import_failures(error_count: int, kinds: set[str]) -> None`

- [ ] **Step 1: Write the failing savepoint test**

Create `src/backend/finances/tests/test_import_runner.py`:

```python
"""H5: one bad row must not kill the rows after it.

The test forces a *real* database error rather than raising IntegrityError from
Python, and the difference is the whole point. A Python-level exception leaves
the Postgres transaction perfectly healthy, so a test that raises one passes
whether or not savepoints exist -- it would assert nothing. A description longer
than the column is rejected by Postgres itself, which marks the transaction
aborted; every statement after it then raises TransactionManagementError until
something rolls back to a savepoint. That is the production failure, reproduced.
"""

import io

import pytest
from model_bakery import baker

from finances.models import Entry, ImportJob, ImportStatus
from finances.services.import_runner import run_import
from finances.services.import_storage import store_upload

_TOO_LONG = "x" * 600  # Entry.description is CharField(max_length=500)


def _job(household, user, body: str, import_type="regular"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    header = "data,valor,descrição,categoria,forma\n"
    upload = SimpleUploadedFile("x.csv", (header + body).encode(), "text/csv")
    job = ImportJob.objects.create(
        household=household,
        created_by=user,
        import_type=import_type,
        storage_key=store_upload(upload, household.id),
        column_mapping={"date": 0, "amount": 1, "description": 2,
                        "category": 3, "payment_method": 4},
        status=ImportStatus.MAPPED,
    )
    from finances.services.import_rows import rows_for

    job.total_rows = len(rows_for(job, mark_duplicates=False))
    job.save(update_fields=["total_rows"])
    return job


@pytest.fixture
def local_storage(tmp_path, settings):
    settings.GS_BUCKET_NAME = ""
    settings.JOB_STORAGE_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def seeded(household):
    baker.make("finances.Category", household=household, name="Alimentação")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


@pytest.mark.django_db(transaction=True)
class TestOneBadRowDoesNotPoisonTheRest:
    def test_the_rows_after_a_database_error_still_land(self, seeded, user, local_storage):
        job = _job(
            seeded,
            user,
            f"01/03/2026,\"R$ 10,00\",Primeira,Alimentação,Pix\n"
            f"02/03/2026,\"R$ 20,00\",{_TOO_LONG},Alimentação,Pix\n"
            f"03/03/2026,\"R$ 30,00\",Terceira,Alimentação,Pix\n",
        )
        run_import(job)

        descriptions = set(
            Entry.objects.for_household(seeded).values_list("description", flat=True)
        )
        assert descriptions == {"Primeira", "Terceira"}

    def test_the_counts_are_accurate_rather_than_misleading(self, seeded, user, local_storage):
        job = _job(
            seeded,
            user,
            f"01/03/2026,\"R$ 10,00\",Primeira,Alimentação,Pix\n"
            f"02/03/2026,\"R$ 20,00\",{_TOO_LONG},Alimentação,Pix\n"
            f"03/03/2026,\"R$ 30,00\",Terceira,Alimentação,Pix\n",
        )
        run_import(job)
        job.refresh_from_db()

        assert job.created_count == 2
        assert job.error_count == 1
        assert job.skipped_count == 0
        assert job.status == ImportStatus.DONE

    def test_the_failed_row_says_which_line_and_why(self, seeded, user, local_storage):
        job = _job(
            seeded,
            user,
            f"01/03/2026,\"R$ 10,00\",Primeira,Alimentação,Pix\n"
            f"02/03/2026,\"R$ 20,00\",{_TOO_LONG},Alimentação,Pix\n",
        )
        run_import(job)
        job.refresh_from_db()

        assert len(job.failures) == 1
        assert job.failures[0]["line"] == 3  # header is line 1
        assert job.failures[0]["reason"]


@pytest.mark.django_db
class TestResolutionAndSkipping:
    def test_an_unknown_category_fails_that_row_with_a_ptbr_reason(
        self, seeded, user, local_storage
    ):
        job = _job(seeded, user, "01/03/2026,\"R$ 10,00\",Compra,Inexistente,Pix\n")
        run_import(job)
        job.refresh_from_db()

        assert job.created_count == 0
        assert job.error_count == 1
        assert "Categoria" in job.failures[0]["reason"]

    def test_a_new_category_resolution_creates_it_once(self, seeded, user, local_storage):
        from finances.models import Category

        job = _job(
            seeded,
            user,
            "01/03/2026,\"R$ 10,00\",A,Nova,Pix\n02/03/2026,\"R$ 20,00\",B,Nova,Pix\n",
        )
        job.category_resolutions = {"Nova": "__new__"}
        job.save(update_fields=["category_resolutions"])
        run_import(job)
        job.refresh_from_db()

        assert job.created_count == 2
        assert Category.objects.for_household(seeded).filter(name="Nova").count() == 1

    def test_a_skipped_line_is_counted_as_skipped_not_failed(self, seeded, user, local_storage):
        job = _job(
            seeded,
            user,
            "01/03/2026,\"R$ 10,00\",A,Alimentação,Pix\n"
            "02/03/2026,\"R$ 20,00\",B,Alimentação,Pix\n",
        )
        job.skip_lines = [3]
        job.save(update_fields=["skip_lines"])
        run_import(job)
        job.refresh_from_db()

        assert (job.created_count, job.skipped_count, job.error_count) == (1, 1, 0)


@pytest.mark.django_db
class TestIdempotence:
    def test_re_running_the_same_job_creates_nothing_new(self, seeded, user, local_storage):
        """The DoD's 'a test proves re-running the same import creates no
        duplicates'. A finished job refuses to run again; the guard is on the
        row, so it holds across processes."""
        job = _job(seeded, user, "01/03/2026,\"R$ 10,00\",A,Alimentação,Pix\n")
        run_import(job)
        run_import(job)
        job.refresh_from_db()

        assert Entry.objects.for_household(seeded).count() == 1
        assert job.created_count == 1

    def test_a_second_upload_of_the_same_file_is_flagged_duplicate_at_preview(
        self, seeded, user, local_storage
    ):
        """The other half of idempotence, and the one that survived the
        refactor: the file can be re-uploaded, and the preview marks the rows
        the household already has."""
        from finances.services.import_rows import rows_for

        first = _job(seeded, user, "01/03/2026,\"R$ 10,00\",A,Alimentação,Pix\n")
        run_import(first)

        second = _job(seeded, user, "01/03/2026,\"R$ 10,00\",A,Alimentação,Pix\n")
        assert [row["status"] for row in rows_for(second)] == ["duplicate"]


@pytest.mark.django_db
class TestQueryCost:
    def test_the_per_row_cost_stays_flat(self, seeded, user, local_storage,
                                         django_assert_num_queries):
        """E03 S03-4's property, restated against the runner: the closing-day
        prefetch must survive this refactor. Asserted as a slope, because an
        absolute bound would encode today's implementation."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def cost(rows):
            body = "".join(
                f"{1 + (i % 27):02d}/03/2026,\"R$ {10 + i},00\",c{i},Alimentação,Pix\n"
                for i in range(rows)
            )
            job = _job(seeded, user, body)
            with CaptureQueriesContext(connection) as captured:
                run_import(job)
            return len(captured.captured_queries)

        small = cost(10)
        Entry.objects.all().delete()
        large = cost(50)

        per_row = (large - small) / 40
        assert per_row <= 1.5, f"{per_row:.2f} queries per row ({small} -> {large})"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finances.services.import_runner'`

- [ ] **Step 3: Write `finances/services/import_runner.py`**

```python
"""Turn a mapped job into rows, one savepoint at a time.

The H5 fix lives in one place: the ``with transaction.atomic():`` inside the
loop. Django opens a SAVEPOINT for a nested atomic block, so a row that Postgres
rejects rolls back to the savepoint and the transaction stays usable. Without
it, the first IntegrityError aborts the transaction, every subsequent statement
raises TransactionManagementError, and the import dies -- while reporting an
error_count that counts the exceptions it caught rather than the rows it lost.

No request, no HTTP, no session. That is what makes this callable from a task,
from a management command and from a test with equal confidence.
"""

import logging
from datetime import date
from decimal import Decimal

import sentry_sdk
from django.db import transaction
from django.utils import timezone

from finances.models import (
    Category,
    Entry,
    EntryType,
    ImportStatus,
    InstallmentPlan,
    PaymentMethod,
)
from finances.services.billing import compute_billing_month, resolve_closing_day
from finances.services.import_rows import rows_for

logger = logging.getLogger(__name__)

# How often the progress counter reaches the database. Every row would be one
# UPDATE per row on a pooled connection -- the exact per-row cost E03 removed.
# Every fiftieth is under a second of staleness at any plausible row rate.
PROGRESS_EVERY = 50


def report_import_failures(error_count: int, kinds: set[str]) -> None:
    """Report row failures as ONE event carrying a count and a few kinds.

    Moved here from the view unchanged in spirit. Per-row reporting would turn a
    single 1000-row bad file into 1000 events and exhaust the free-tier quota
    ADR-005 assumed was adequate. The count is the signal.

    Types only, never the exception strings. A parse failure's message is built
    from the offending cell -- "invalid literal for int(): 'Farmácia Pague
    Menos'" -- so shipping it would be the leak the Sentry scrubber exists to
    prevent, arriving by a route the scrubber cannot see.
    """
    if not error_count:
        return
    sentry_sdk.capture_message(
        f"CSV import finished with {error_count} failed row(s) "
        f"({', '.join(sorted(kinds)) or 'unknown'})",
        level="warning",
    )


def run_import(job) -> None:
    """Execute ``job``. Never raises for a row-level problem.

    Refuses a job that has already finished. That guard is on a committed row
    rather than in memory, so it holds across instances and across a redelivered
    task -- which is the DoD's "re-running the same import creates no
    duplicates".
    """
    if job.is_finished:
        logger.info("Import job %s already finished (%s); not running again.", job.pk, job.status)
        return

    job.status = ImportStatus.RUNNING
    job.started_at = timezone.now()
    job.processed_count = 0
    job.created_count = 0
    job.skipped_count = 0
    job.error_count = 0
    job.failures = []
    job.failures_truncated = 0
    job.error_message = ""
    job.save(
        update_fields=[
            "status", "started_at", "processed_count", "created_count",
            "skipped_count", "error_count", "failures", "failures_truncated",
            "error_message", "updated_at",
        ]
    )

    try:
        _execute(job)
    except Exception as exc:
        # A whole-job failure: the file vanished from storage, the mapping is
        # nonsense, the database is gone. Distinct from a row failure, and it
        # must leave the job FAILED with something a person can act on rather
        # than RUNNING forever.
        logger.exception("Import job %s failed wholesale.", job.pk)
        sentry_sdk.capture_exception(exc)
        job.status = ImportStatus.FAILED
        job.executed_at = timezone.now()
        job.error_message = (
            "Não foi possível ler o arquivo enviado. "
            "Envie a planilha novamente; se o erro continuar, exporte de novo "
            "do Google Sheets como CSV (UTF-8)."
        )
        job.save(update_fields=["status", "executed_at", "error_message", "updated_at"])


def _execute(job) -> None:
    household = job.household
    user = job.created_by
    rows = rows_for(job, mark_duplicates=False)
    skip_lines = set(job.skip_lines)

    category_map = {c.name.lower(): c for c in Category.objects.for_household(household)}
    # Prefetched so resolve_closing_day -- called twice per row, here and again
    # inside Entry.save -- reads a cache instead of querying. This is E03
    # S03-4's fix and the spec requires it survive the refactor.
    payment_map = {
        p.name.lower(): p
        for p in PaymentMethod.objects.for_household(household).prefetch_related(
            "monthly_closing_days"
        )
    }

    _apply_resolutions(job, household, user, category_map, payment_map)

    failure_kinds: set[str] = set()

    for index, row in enumerate(rows, start=1):
        line = row.get("line", index + 1)

        if line in skip_lines:
            job.skipped_count += 1
        elif row["status"] == "error":
            job.error_count += 1
            job.record_failure(line, row.get("error") or "Linha inválida.")
            failure_kinds.add("ParseError")
        else:
            reason = _create_one(job, row, household, user, category_map, payment_map)
            if reason is None:
                job.created_count += 1
            else:
                job.error_count += 1
                job.record_failure(line, reason[0])
                failure_kinds.add(reason[1])

        job.processed_count = index
        if index % PROGRESS_EVERY == 0:
            job.save(
                update_fields=[
                    "processed_count", "created_count", "skipped_count",
                    "error_count", "failures", "failures_truncated", "updated_at",
                ]
            )

    report_import_failures(job.error_count, failure_kinds)

    job.status = ImportStatus.DONE
    job.executed_at = timezone.now()
    job.save(
        update_fields=[
            "status", "executed_at", "processed_count", "created_count",
            "skipped_count", "error_count", "failures", "failures_truncated",
            "updated_at",
        ]
    )


def _apply_resolutions(job, household, user, category_map, payment_map) -> None:
    """Create the categories and payment methods the user asked us to create."""
    for name, resolution in job.category_resolutions.items():
        if resolution == "__new__" and name.lower() not in category_map:
            category_map[name.lower()] = Category.objects.create(
                household=household, created_by=user, name=name
            )
    for name, resolution in job.pm_resolutions.items():
        if resolution == "__new__" and name.lower() not in payment_map:
            payment_map[name.lower()] = PaymentMethod.objects.create(
                household=household, created_by=user, name=name, type="pix"
            )


def _create_one(job, row, household, user, category_map, payment_map):
    """Create one row's records. Returns ``None`` on success, else (reason, kind).

    Every write is inside its own ``transaction.atomic()``. Nested inside the
    caller's transaction that is a SAVEPOINT, which is the entire H5 fix: a row
    Postgres rejects rolls back to the savepoint and leaves the transaction
    usable for the next row.
    """
    category = _resolve(
        row.get("category", ""), category_map, job.category_resolutions,
        Category.objects.for_household(household),
    )
    if category is None:
        return (f"Categoria '{row.get('category', '')}' não encontrada.", "UnknownCategory")

    payment_method = _resolve(
        row.get("payment_method", ""), payment_map, job.pm_resolutions,
        PaymentMethod.objects.for_household(household),
    )
    if payment_method is None:
        return (
            f"Forma de pagamento '{row.get('payment_method', '')}' não encontrada.",
            "UnknownPaymentMethod",
        )

    try:
        with transaction.atomic():
            if job.import_type == "installment":
                plan = InstallmentPlan.objects.create(
                    household=household,
                    created_by=user,
                    date=date.fromisoformat(row["date"]),
                    description=row["description"],
                    category=category,
                    payment_method=payment_method,
                    total_amount=Decimal(row["total_amount"]),
                    num_installments=int(row["num_installments"]),
                    installment_amount=Decimal(row["installment_amount"]),
                )
                plan.generate_entries()
            else:
                entry_date = date.fromisoformat(row["date"])
                Entry.objects.create(
                    household=household,
                    created_by=user,
                    date=entry_date,
                    amount=Decimal(row["amount"]),
                    description=row["description"],
                    category=category,
                    payment_method=payment_method,
                    entry_type=EntryType.REGULAR,
                    billing_month=compute_billing_month(
                        entry_date,
                        payment_method.type,
                        resolve_closing_day(payment_method, entry_date),
                    ),
                    billing_month_override=False,
                )
    except Exception as exc:
        # Deliberately broad, and deliberately reporting the *type* to the user
        # rather than the message: an exception string here is built from the
        # offending cell, which is the family's financial data.
        return (
            f"A linha foi recusada pelo banco de dados ({type(exc).__name__}). "
            "Verifique se a descrição não é longa demais e se o valor é válido.",
            type(exc).__name__,
        )
    return None


def _resolve(name: str, cache: dict, resolutions: dict, queryset):
    """A category or payment method by name, honouring the user's resolution."""
    found = cache.get(name.lower())
    if found is not None:
        return found
    chosen = resolutions.get(name)
    if chosen and chosen != "__new__":
        found = queryset.filter(pk=chosen).first()
        if found is not None:
            cache[name.lower()] = found
        return found
    return None
```

- [ ] **Step 4: Remove the old failure reporter from the view**

Delete `report_import_failures` and its `sentry_sdk` import from `src/backend/finances/views/importer.py:26-43` — it now lives in the runner. Grep for stragglers:

```bash
grep -rn "report_import_failures" src/backend/ --include="*.py" | grep -v __pycache__
```
Expected: only `import_runner.py` and any test that imports it.

- [ ] **Step 5: Run the runner tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_runner.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 6: Prove the savepoint is what makes it pass**

Temporarily change `with transaction.atomic():` in `_create_one` to `if True:` and re-run:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_runner.py::TestOneBadRowDoesNotPoisonTheRest -v
```
Expected: FAIL, with `TransactionManagementError` — the production bug, reproduced on demand. **Restore the line** and re-run to confirm green. A test that passes with and without the fix is not a test.

- [ ] **Step 7: Run the full importer set**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -q -k "import"
```
Expected: PASS.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances
git commit -m "fix(E12): a savepoint per row, so one bad row cannot poison the import (H5)"
```

---

## Task 5: Execute as a task, with real progress and honest failure

Delivers S12-3's off-request half and all of S12-5.

**Files:**
- Create: `src/backend/finances/tasks.py`
- Create: `src/backend/finances/management/commands/sweep_stuck_import_jobs.py`
- Create: `src/backend/templates/importer/_step_status.html`
- Create: `src/backend/templates/importer/_progress.html`
- Create: `src/backend/finances/tests/test_import_progress.py`
- Modify: `src/backend/finances/views/importer.py` (`ImportExecuteView`, new `ImportStatusView`)
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/templates/importer/import_page.html`

**Interfaces:**
- Consumes: `run_import` (Task 4); `core.tasks.enqueue`, `core.tasks.task_handler` (E10).
- Produces:
  - `finances.tasks.RUN_IMPORT: str` = `"finances.run_import"`
  - `finances.tasks.run_import_task(payload: dict) -> None` — payload `{"job_id": str}`
  - URL name `import_status` at `/import/<uuid:job_id>/status/`
  - Management command `sweep_stuck_import_jobs`

- [ ] **Step 1: Write the failing progress test**

Create `src/backend/finances/tests/test_import_progress.py`:

```python
"""S12-5: real progress, and a failure that says what to do.

The eager task backend (CLOUD_TASKS_ENABLED unset) runs the handler inside the
request that enqueues it, so these tests see a finished job immediately. That is
the point of the eager backend, not a limitation of the test -- the attempt
accounting and the dead-letter decision are the same code in both modes.
"""

import io
from datetime import timedelta

import pytest
import time_machine
from django.core.management import call_command
from django.utils import timezone
from model_bakery import baker

from core.models import TaskRun
from finances.models import Entry, ImportJob, ImportStatus

_CSV = (
    b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
    b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
)
_MAPPING = {"date": "0", "amount": "1", "description": "2",
            "category": "3", "payment_method": "4"}


@pytest.fixture
def seeded(household, settings, tmp_path):
    settings.GS_BUCKET_NAME = ""
    settings.JOB_STORAGE_ROOT = tmp_path
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


def _to_preview(client, household):
    handle = io.BytesIO(_CSV)
    handle.name = "x.csv"
    client.post("/import/", data={"file": handle, "import_type": "regular"})
    job = ImportJob.objects.for_household(household).latest("created_at")
    client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
    return job


@pytest.mark.django_db
class TestExecutionGoesThroughATask:
    def test_executing_enqueues_the_task_and_redirects_to_status(self, logged_client, seeded):
        job = _to_preview(logged_client, seeded)
        response = logged_client.post(f"/import/{job.id}/executar/")

        assert response.status_code == 302
        assert response.url == f"/import/{job.id}/status/"
        assert TaskRun.objects.filter(name="finances.run_import").count() == 1

    def test_the_eager_backend_actually_runs_it(self, logged_client, seeded):
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()

        assert job.status == ImportStatus.DONE
        assert Entry.objects.for_household(seeded).count() == 1

    def test_a_second_execute_does_not_enqueue_a_second_task(self, logged_client, seeded):
        """Idempotency by content hash: core.tasks.enqueue upserts on the key,
        so a double-tapped button is one TaskRun and one import."""
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        logged_client.post(f"/import/{job.id}/executar/")

        assert TaskRun.objects.filter(name="finances.run_import").count() == 1
        assert Entry.objects.for_household(seeded).count() == 1


@pytest.mark.django_db
class TestTheStatusPage:
    def test_it_shows_a_percentage_while_running(self, logged_client, seeded):
        job = baker.make(
            ImportJob, household=seeded, status=ImportStatus.RUNNING,
            total_rows=200, processed_count=50, started_at=timezone.now(),
        )
        response = logged_client.get(f"/import/{job.id}/status/")
        assert response.status_code == 200
        assert "25" in response.content.decode()

    def test_it_stops_polling_once_the_job_is_finished(self, logged_client, seeded):
        """The response must not carry an hx-trigger once there is nothing left
        to poll for -- a page that polls forever is a page that keeps an
        instance warm for nothing."""
        job = baker.make(ImportJob, household=seeded, status=ImportStatus.DONE,
                         total_rows=1, processed_count=1, created_count=1)
        response = logged_client.get(f"/import/{job.id}/status/")
        assert "hx-trigger" not in response.content.decode()

    def test_a_failed_job_says_what_to_do_in_ptbr(self, logged_client, seeded):
        job = baker.make(
            ImportJob, household=seeded, status=ImportStatus.FAILED,
            error_message="Não foi possível ler o arquivo enviado. Envie novamente.",
        )
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "Não foi possível ler o arquivo enviado" in body

    def test_another_households_status_is_a_404(self, logged_client, seeded, other_household):
        job = baker.make(ImportJob, household=other_household)
        assert logged_client.get(f"/import/{job.id}/status/").status_code == 404


@pytest.mark.django_db
class TestStuckJobs:
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_stuck_job_reads_as_failed_on_the_page_immediately(
        self, logged_client, seeded, settings
    ):
        """Without waiting for the sweep. The user is looking at the page now;
        telling them 'importando' about a job whose instance is gone is the
        indefinite spinner S12-5 exists to end."""
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob, household=seeded, status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "interrompida" in body

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_the_sweep_marks_it_failed_with_a_reason(self, seeded, settings):
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob, household=seeded, status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        call_command("sweep_stuck_import_jobs")
        job.refresh_from_db()

        assert job.status == ImportStatus.FAILED
        assert job.error_message
        assert job.executed_at is not None

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_the_sweep_leaves_a_healthy_running_job_alone(self, seeded, settings):
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob, household=seeded, status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=2),
        )
        call_command("sweep_stuck_import_jobs")
        job.refresh_from_db()

        assert job.status == ImportStatus.RUNNING
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_progress.py -v`
Expected: FAIL — the execute POST redirects to the preview, and `/import/<id>/status/` is a 404.

- [ ] **Step 3: Write `finances/tasks.py`**

```python
"""Deferred work the ledger schedules.

Discovered by ``core.tasks.registry.autodiscover()`` at startup, so the module
name is part of the contract: this file must stay ``finances/tasks.py``.
"""

import logging

from core.tasks import task_handler

logger = logging.getLogger(__name__)

RUN_IMPORT = "finances.run_import"


# max_attempts=1, against this registry's default of 5, and deliberately.
# ``run_import`` is not safely re-runnable from an arbitrary midpoint: it has
# already written some of the household's rows, and a blind retry would write
# the rest of them a second time. The job row is the durable record, the guard
# is ``ImportJob.is_finished``, and a genuinely failed import is retried by the
# user creating a NEW job -- which re-runs the duplicate detection first.
@task_handler(RUN_IMPORT, max_attempts=1)
def run_import_task(payload: dict) -> None:
    """Execute one ImportJob.

    Function-local imports so the module stays importable at startup --
    ``autodiscover`` runs inside ``AppConfig.ready`` -- and so a test patching
    ``finances.services.import_runner.run_import`` patches the object this
    function will actually reach.
    """
    from finances.models import ImportJob
    from finances.services.import_runner import run_import

    job = ImportJob.objects.filter(pk=payload["job_id"]).first()
    if job is None:
        # Deleted between enqueue and dispatch. Retrying will not bring it
        # back, so this is a completed task, not a failed one.
        logger.info("Import job %s is gone; nothing to run.", payload["job_id"])
        return
    run_import(job)
```

- [ ] **Step 4: Rewrite `ImportExecuteView` and add `ImportStatusView`**

In `src/backend/finances/views/importer.py`, replace `ImportExecuteView` with:

```python
class ImportExecuteView(LoginRequiredMixin, View):
    """Step 4: hand the job to a task and send the user to the status page.

    The old view did the whole import inside the request, wrapped in one
    ``@transaction.atomic`` -- which is where H5 lived, and which also meant a
    4000-row file held a request open for as long as it took. Enqueue is
    idempotent by content hash, so a double-tapped button produces one TaskRun
    and one import; the ``select_for_update`` dance the old view needed is now a
    property of ``core.tasks.enqueue`` plus ``ImportJob.is_finished``.
    """

    def post(self, request, job_id):
        job = get_job(request, job_id)
        if not job.is_finished:
            enqueue(RUN_IMPORT, {"job_id": str(job.id)})
        return redirect("finances:import_status", job_id=job.id)


class ImportStatusView(LoginRequiredMixin, View):
    """Progress while it runs; counts when it is done; a reason when it is not.

    Serves the whole page normally and the progress fragment to HTMX, from one
    place, so the two cannot drift into disagreeing about the same job.
    """

    def get(self, request, job_id):
        job = get_job(request, job_id)
        context = {"step": "status", "job": job, "import_type": job.import_type}
        if request.headers.get("HX-Request"):
            return render(request, "importer/_progress.html", context)
        return render(request, "importer/import_page.html", context)
```

Add to the imports at the top of the module:

```python
from core.tasks import enqueue
from finances.tasks import RUN_IMPORT
```

- [ ] **Step 5: Add the URL and the step**

In `src/backend/finances/urls.py`, after the execute path:

```python
    path("import/<uuid:job_id>/status/", ImportStatusView.as_view(), name="import_status"),
```

and add `ImportStatusView` to the `from finances.views.importer import (...)` block at line 36.

In `src/backend/templates/importer/import_page.html`, add the status step to the include chain and to the steps indicator (replace the `result` step's label):

```html
<ul class="steps mb-6">
    <li class="step {% if step == 'upload' %}step-primary{% endif %}">Upload</li>
    <li class="step {% if step == 'mapping' %}step-primary{% endif %}">Mapeamento</li>
    <li class="step {% if step == 'preview' %}step-primary{% endif %}">Preview</li>
    <li class="step {% if step == 'status' %}step-primary{% endif %}">Resultado</li>
</ul>

<div id="import-step">
    {% if step == "upload" %}{% include "importer/_step_upload.html" %}
    {% elif step == "mapping" %}{% include "importer/_step_mapping.html" %}
    {% elif step == "preview" %}{% include "importer/_step_preview.html" %}
    {% elif step == "status" %}{% include "importer/_step_status.html" %}
    {% endif %}
</div>
```

- [ ] **Step 6: Write the two status templates**

`src/backend/templates/importer/_step_status.html`:

```html
<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <h3 class="card-title">4. Resultado</h3>
        <div id="import-progress">
            {% include "importer/_progress.html" %}
        </div>
    </div>
</div>
```

`src/backend/templates/importer/_progress.html` — the fragment HTMX swaps. `hx-trigger` is present only while there is something to wait for, which is what stops the page polling a finished job forever:

```html
<div id="import-progress"
     {% if not job.is_finished and not job.is_stuck %}
     hx-get="{% url 'finances:import_status' job_id=job.id %}"
     hx-trigger="every 2s"
     hx-swap="outerHTML"
     {% endif %}>

    {% if job.is_stuck %}
    <div class="alert alert-error">
        <div>
            <h4 class="font-bold">Importação interrompida</h4>
            <p>A importação parou antes de terminar. {{ job.created_count }} entrada(s)
               foram criadas. Envie o arquivo de novo — as linhas já importadas
               aparecerão marcadas como duplicadas e podem ser puladas.</p>
        </div>
    </div>

    {% elif job.status == "failed" %}
    <div class="alert alert-error">
        <div>
            <h4 class="font-bold">A importação falhou</h4>
            <p>{{ job.error_message }}</p>
        </div>
    </div>

    {% elif job.is_finished %}
    <div class="stats shadow mb-6">
        <div class="stat">
            <div class="stat-title">Importados</div>
            <div class="stat-value text-success">{{ job.created_count }}</div>
        </div>
        <div class="stat">
            <div class="stat-title">Pulados</div>
            <div class="stat-value text-warning">{{ job.skipped_count }}</div>
        </div>
        <div class="stat">
            <div class="stat-title">Erros</div>
            <div class="stat-value text-error">{{ job.error_count }}</div>
        </div>
    </div>
    {% if job.error_count %}
    <a href="{% url 'finances:import_failures' job_id=job.id %}"
       class="btn btn-outline btn-sm mb-4">Baixar relatório de erros (CSV)</a>
    {% endif %}
    <div class="flex gap-2">
        <a href="{% url 'finances:entries' %}" class="btn btn-accent">Ver entradas</a>
        <a href="{% url 'finances:import_upload' %}" class="btn btn-ghost">Importar outro arquivo</a>
    </div>

    {% else %}
    <p class="mb-2">Importando {{ job.processed_count }} de {{ job.total_rows }} linha(s)…</p>
    <progress class="progress progress-accent w-full"
              value="{{ job.progress_percent }}" max="100"
              aria-label="Progresso da importação"></progress>
    <p class="text-sm opacity-70 mt-2">{{ job.progress_percent }}%</p>
    {% endif %}
</div>
```

`_step_result.html` is now unreachable — delete it and remove the `{% elif step == "result" %}` branch. The failures download link is wired in Task 6; until then the `{% url 'finances:import_failures' %}` reference will raise `NoReverseMatch`, so **add the URL stub in Task 6 before running the status tests with a failed job** — or, to keep this task self-contained, add the URL and a two-line view now and fill it in Task 6. Do the latter: in `urls.py` add

```python
    path("import/<uuid:job_id>/falhas.csv", ImportFailuresView.as_view(), name="import_failures"),
```

and in `importer.py` a placeholder that Task 6 replaces:

```python
class ImportFailuresView(LoginRequiredMixin, View):
    """Filled in by Task 6."""

    def get(self, request, job_id):
        raise Http404
```

- [ ] **Step 7: Write the sweep command**

`src/backend/finances/management/commands/sweep_stuck_import_jobs.py`:

```python
"""Turn a job whose instance vanished from 'running' into 'failed'.

Cloud Run recycles instances, and a task that outruns the request timeout is
simply gone -- there is no callback that says so. Without this, the row stays
RUNNING forever and the user watches a bar that will never move. The status
page reads ``is_stuck`` so a person looking right now sees the truth
immediately; this command is what makes the *stored* state honest, for the
history page, for the operator and for anything that queries by status.

Run it from Cloud Scheduler alongside the keepalive ping. See docs/runbook.md.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from finances.models import ImportJob, ImportStatus


class Command(BaseCommand):
    help = "Mark import jobs that died mid-execution as failed."

    def handle(self, *args, **options):
        swept = 0
        # Not a bulk update: is_stuck reads a setting and a timestamp per row,
        # and the number of RUNNING jobs at any moment is single digits.
        for job in ImportJob.objects.filter(status=ImportStatus.RUNNING):
            if not job.is_stuck:
                continue
            job.status = ImportStatus.FAILED
            job.executed_at = timezone.now()
            job.error_message = (
                "A importação foi interrompida antes de terminar. "
                f"{job.created_count} entrada(s) foram criadas. Envie o arquivo "
                "novamente — as linhas já importadas aparecerão como duplicadas."
            )
            job.save(update_fields=["status", "executed_at", "error_message", "updated_at"])
            swept += 1

        self.stdout.write(f"Importações interrompidas marcadas como falha: {swept}")
```

- [ ] **Step 8: Run the progress tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_progress.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 9: Confirm the task registered**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c \
  "from core.tasks.registry import autodiscover, registered_names; autodiscover(); print(registered_names())"
```
Expected: a list containing both `assistant.embed_memory_rule` and `finances.run_import`.

- [ ] **Step 10: Run every importer suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ src/backend/core/tests/ -q`
Expected: PASS.

- [ ] **Step 11: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances src/backend/templates/importer
git rm src/backend/templates/importer/_step_result.html
git commit -m "feat(E12): imports run as a task, with real progress and an honest failure"
```

---

## Task 6: Signed, expiring downloads, and the failed-row report

Delivers S12-3's "the user can download a report of failed rows" and S12-2's "access is via signed, expiring URLs". Built before the export so the export has a delivery mechanism to use.

**Files:**
- Create: `src/backend/core/downloads.py`
- Create: `src/backend/core/tests/test_downloads.py`
- Modify: `src/backend/finances/views/importer.py` (`ImportFailuresView`)
- Modify: `src/backend/finances/tests/test_import_progress.py` (add the failures-report cases)

**Interfaces:**
- Consumes: settings `EXPORT_URL_MAX_AGE_SECONDS` (Task 1).
- Produces:
  - `core.downloads.sign_download(kind: str, object_id) -> str`
  - `core.downloads.unsign_download(token: str, *, kind: str, max_age: int | None = None) -> str` — returns the object id, raises `DownloadLinkInvalid`
  - `core.downloads.DownloadLinkInvalid(Exception)`
  - `finances.views.importer.ImportFailuresView` at `/import/<uuid:job_id>/falhas.csv` (authenticated + household-scoped; no token — see the note below)

**Why the failures report is not tokenised, and the export is:** the failures report is reached from a page the user is already on, inside their own session, and it is scoped by `for_request`. A token would add nothing. The export archive is a complete financial history that the user may want to fetch from a different device or a download manager, so it gets a link that carries its own authority — bounded by expiry, and *still* checked against `request.household` on arrival.

- [ ] **Step 1: Write the failing download-token tests**

Create `src/backend/core/tests/test_downloads.py`:

```python
"""A link that carries its own authority, and stops carrying it on time."""

import pytest
import time_machine
from django.test import override_settings

from core.downloads import DownloadLinkInvalid, sign_download, unsign_download

_ID = "6f8a1c02-3c2e-5f7a-9b4d-2a1f0e5c7d31"


def test_a_fresh_token_round_trips():
    token = sign_download("export", _ID)
    assert unsign_download(token, kind="export") == _ID


def test_a_tampered_token_is_refused():
    token = sign_download("export", _ID)
    with pytest.raises(DownloadLinkInvalid):
        unsign_download(token[:-1] + ("a" if token[-1] != "a" else "b"), kind="export")


def test_a_token_for_another_kind_is_refused():
    """Kind is inside the signed payload, not beside it. A token minted for an
    import file must not open an export archive, whatever the URL says."""
    token = sign_download("import", _ID)
    with pytest.raises(DownloadLinkInvalid):
        unsign_download(token, kind="export")


def test_garbage_is_refused_rather_than_raising_something_else():
    with pytest.raises(DownloadLinkInvalid):
        unsign_download("not-a-token", kind="export")


@override_settings(EXPORT_URL_MAX_AGE_SECONDS=3600)
def test_a_token_inside_its_window_is_accepted():
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        token = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 12:59:00+00:00", tick=False):
        assert unsign_download(token, kind="export") == _ID


@override_settings(EXPORT_URL_MAX_AGE_SECONDS=3600)
def test_a_token_past_its_window_is_refused():
    """The DoD's 'export URLs expire, verified by test'. Frozen clock on both
    sides -- global constraint 10 -- so this cannot rot into a flake."""
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        token = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 13:00:01+00:00", tick=False):
        with pytest.raises(DownloadLinkInvalid):
            unsign_download(token, kind="export")


def test_two_tokens_for_the_same_object_are_not_guessable_from_each_other():
    """Timestamped, so the same id does not always mint the same string, and
    neither string reveals the id without the signing key."""
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        first = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 12:00:05+00:00", tick=False):
        second = sign_download("export", _ID)
    assert first != second
    assert _ID not in first
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_downloads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.downloads'`

- [ ] **Step 3: Write `core/downloads.py`**

```python
"""Links that expire, without a cloud round trip.

The alternative is a GCS signed URL, and it was rejected for three reasons.
Signing one from Cloud Run needs either a service-account key file on disk --
a secret we would then own -- or an IAM SignBlob call per download. A raw
bucket link cannot check ``request.household``, so tenancy would rest on URL
secrecy alone. And it would only work in production, which means the DoD's
"export URLs expire, verified by test" could never be asserted locally.

Django's TimestampSigner gives expiry from the SECRET_KEY we already rotate,
in-process, identically on a laptop and on Cloud Run.
"""

from django.conf import settings
from django.core import signing


class DownloadLinkInvalid(Exception):
    """The token was tampered with, minted for another kind, or has expired."""


def sign_download(kind: str, object_id) -> str:
    """A URL-safe token standing for "this object, from now".

    ``kind`` travels *inside* the signed payload rather than as a salt beside
    it, so that a token minted for one kind cannot be replayed against another
    by editing the path.
    """
    return signing.dumps({"kind": kind, "id": str(object_id)}, salt="core.downloads")


def unsign_download(token: str, *, kind: str, max_age: int | None = None) -> str:
    """The object id behind ``token``, or ``DownloadLinkInvalid``.

    One exception type for every failure mode on purpose: the caller answers
    404 either way, and distinguishing "expired" from "forged" in a response
    tells an attacker which half of the token to keep working on.
    """
    if max_age is None:
        max_age = settings.EXPORT_URL_MAX_AGE_SECONDS
    try:
        payload = signing.loads(token, salt="core.downloads", max_age=max_age)
    except signing.BadSignature as exc:
        raise DownloadLinkInvalid(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        raise DownloadLinkInvalid("token is for a different kind of object")
    return payload["id"]
```

- [ ] **Step 4: Run the token tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_downloads.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Write the failing failures-report test**

Append to `src/backend/finances/tests/test_import_progress.py`:

```python
@pytest.mark.django_db
class TestTheFailuresReport:
    def test_it_names_every_failed_line_and_why(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.DONE,
            error_count=2,
            failures=[
                {"line": 3, "reason": "Categoria 'Inexistente' não encontrada."},
                {"line": 9, "reason": "A linha foi recusada pelo banco de dados (DataError)."},
            ],
        )
        response = logged_client.get(f"/import/{job.id}/falhas.csv")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        body = response.content.decode("utf-8-sig")
        assert "linha,motivo" in body
        assert "3,Categoria 'Inexistente' não encontrada." in body
        assert "9," in body

    def test_it_says_how_many_more_there_were_when_truncated(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.DONE,
            error_count=1005,
            failures=[{"line": 2, "reason": "erro"}],
            failures_truncated=1004,
        )
        body = logged_client.get(f"/import/{job.id}/falhas.csv").content.decode("utf-8-sig")
        assert "1004" in body

    def test_a_job_with_no_failures_still_answers_a_valid_empty_report(
        self, logged_client, seeded
    ):
        job = baker.make(ImportJob, household=seeded, status=ImportStatus.DONE)
        response = logged_client.get(f"/import/{job.id}/falhas.csv")
        assert response.status_code == 200
        assert "linha,motivo" in response.content.decode("utf-8-sig")

    def test_another_households_report_is_a_404(self, logged_client, seeded, other_household):
        job = baker.make(ImportJob, household=other_household, failures=[{"line": 2, "reason": "x"}])
        assert logged_client.get(f"/import/{job.id}/falhas.csv").status_code == 404
```

- [ ] **Step 6: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_progress.py::TestTheFailuresReport -v`
Expected: FAIL with 404 — the placeholder view from Task 5 raises `Http404`.

- [ ] **Step 7: Implement `ImportFailuresView`**

Replace the placeholder in `src/backend/finances/views/importer.py`:

```python
class ImportFailuresView(LoginRequiredMixin, View):
    """The failed rows, as a CSV the user can open next to their spreadsheet.

    Generated from the job rather than stored: the failures are already on the
    row, and writing a second artefact to the bucket would give the retention
    rule a second thing to reason about for no gain.

    UTF-8 BOM because the audience opens this in Excel, which reads a
    BOM-less UTF-8 file as Latin-1 and renders every accent as mojibake --
    on a report whose whole job is to be readable.
    """

    def get(self, request, job_id):
        job = get_job(request, job_id)

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="erros-importacao-{job.id}.csv"'
        )
        response.write("﻿")

        writer = csv.writer(response)
        writer.writerow(["linha", "motivo"])
        for failure in job.failures:
            writer.writerow([failure["line"], failure["reason"]])
        if job.failures_truncated:
            writer.writerow(
                ["", f"...e mais {job.failures_truncated} linha(s) com erro não listadas."]
            )
        return response
```

Add `HttpResponse` to the `django.http` import at the top of the module.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_progress.py src/backend/core/tests/test_downloads.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/core src/backend/finances
git commit -m "feat(E12): expiring download tokens, and a failed-row report per import"
```

---

## Task 7: Past imports, and what each one did

Delivers S12-1's last clause. Small, and it is the surface that makes a durable job worth having: without it, a job that finished on an instance the user has since left is invisible.

**Files:**
- Create: `src/backend/templates/importer/import_history.html`
- Create: `src/backend/finances/tests/test_import_history.py`
- Modify: `src/backend/finances/views/importer.py` (`ImportHistoryView`)
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/templates/importer/_step_upload.html`

**Interfaces:**
- Consumes: `ImportJob` (Task 2), `import_status` and `import_failures` URLs (Tasks 5, 6).
- Produces: URL name `import_history` at `/import/historico/`.

**Ordering note:** `import/historico/` must be registered **before** `import/<uuid:job_id>/...` is irrelevant here — `historico` is not a UUID, so the converter will not match it either way. Register it anywhere in the block.

- [ ] **Step 1: Write the failing history test**

Create `src/backend/finances/tests/test_import_history.py`:

```python
"""A job the user cannot find is a job that did not survive."""

from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone
from model_bakery import baker

from finances.models import ImportJob, ImportStatus


@pytest.mark.django_db
class TestImportHistory:
    def test_it_lists_this_households_jobs_newest_first(self, logged_client, household):
        with time_machine.travel("2026-08-14 09:00:00+00:00", tick=False):
            older = baker.make(ImportJob, household=household, original_filename="antigo.csv",
                               status=ImportStatus.DONE, created_count=3)
        with time_machine.travel("2026-08-16 09:00:00+00:00", tick=False):
            newer = baker.make(ImportJob, household=household, original_filename="recente.csv",
                               status=ImportStatus.DONE, created_count=7)

        body = logged_client.get("/import/historico/").content.decode()
        assert body.index("recente.csv") < body.index("antigo.csv")
        assert str(newer.created_count) in body
        assert str(older.created_count) in body

    def test_it_shows_what_each_one_did(self, logged_client, household):
        baker.make(ImportJob, household=household, original_filename="marco.csv",
                   status=ImportStatus.DONE, created_count=41, skipped_count=2, error_count=1)
        body = logged_client.get("/import/historico/").content.decode()
        assert "marco.csv" in body
        assert "41" in body and "2" in body and "1" in body

    def test_another_households_jobs_are_not_listed(self, logged_client, household,
                                                    other_household):
        baker.make(ImportJob, household=other_household, original_filename="alheio.csv")
        body = logged_client.get("/import/historico/").content.decode()
        assert "alheio.csv" not in body

    def test_an_empty_history_says_so_in_ptbr(self, logged_client, household):
        body = logged_client.get("/import/historico/").content.decode()
        assert "Nenhuma importação" in body

    def test_a_running_job_links_to_its_status_page(self, logged_client, household):
        job = baker.make(ImportJob, household=household, status=ImportStatus.RUNNING,
                         started_at=timezone.now())
        body = logged_client.get("/import/historico/").content.decode()
        assert f"/import/{job.id}/status/" in body

    def test_a_job_with_errors_links_to_its_report(self, logged_client, household):
        job = baker.make(ImportJob, household=household, status=ImportStatus.DONE, error_count=4)
        body = logged_client.get("/import/historico/").content.decode()
        assert f"/import/{job.id}/falhas.csv" in body

    def test_it_is_capped_so_a_long_history_cannot_time_out_the_page(
        self, logged_client, household
    ):
        """50 is arbitrary but bounded, and the page says when it truncated
        rather than silently showing a prefix."""
        now = timezone.now()
        for index in range(55):
            baker.make(ImportJob, household=household,
                       original_filename=f"f{index}.csv", status=ImportStatus.DONE)
            ImportJob.objects.filter(original_filename=f"f{index}.csv").update(
                created_at=now - timedelta(minutes=index)
            )
        body = logged_client.get("/import/historico/").content.decode()
        assert "f0.csv" in body
        assert "f54.csv" not in body

    def test_unauthenticated_is_redirected(self):
        from django.test import Client

        assert Client().get("/import/historico/").status_code == 302
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_history.py -v`
Expected: FAIL, 404 — `/import/historico/` is not routed.

- [ ] **Step 3: Write `ImportHistoryView`**

Append to `src/backend/finances/views/importer.py`:

```python
# Bounded so that a household with years of imports cannot turn this page into
# a slow query. Old jobs stay in the database and in the admin; what is capped
# is the render, and the page says so.
HISTORY_LIMIT = 50


class ImportHistoryView(LoginRequiredMixin, View):
    """Past imports, and what each one did.

    The reason durable job state is worth having: before this, an import that
    finished was a page the user had to still be looking at.
    """

    def get(self, request):
        jobs = list(ImportJob.objects.for_request(request)[: HISTORY_LIMIT + 1])
        return render(
            request,
            "importer/import_history.html",
            {"jobs": jobs[:HISTORY_LIMIT], "truncated": len(jobs) > HISTORY_LIMIT},
        )
```

`ImportJob.Meta.ordering` is `["-created_at"]`, so the slice is already newest-first.

- [ ] **Step 4: Write the template**

`src/backend/templates/importer/import_history.html`:

```html
{% extends "base.html" %}

{% block title %}Importações{% endblock %}

{% block content %}
<div class="flex items-center justify-between mb-4">
    <h2 class="text-2xl font-bold">Importações</h2>
    <a href="{% url 'finances:import_upload' %}" class="btn btn-accent btn-sm">Nova importação</a>
</div>

{% if not jobs %}
<div class="card bg-base-100 shadow-sm">
    <div class="card-body text-center">
        <p>Nenhuma importação ainda.</p>
        <p class="text-sm opacity-70">
            Envie um CSV exportado do Google Sheets para trazer seu histórico.
        </p>
    </div>
</div>
{% else %}
<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <div class="overflow-x-auto">
            <table class="table table-sm">
                <thead>
                    <tr>
                        <th>Arquivo</th><th>Quando</th><th>Situação</th>
                        <th>Importados</th><th>Pulados</th><th>Erros</th><th></th>
                    </tr>
                </thead>
                <tbody>
                    {% for job in jobs %}
                    <tr>
                        <td>{{ job.original_filename|default:"—" }}</td>
                        <td>{{ job.created_at|date:"d/m/Y H:i" }}</td>
                        <td>
                            {% if job.is_stuck %}
                            <span class="badge badge-sm badge-error">Interrompida</span>
                            {% elif job.status == "done" %}
                            <span class="badge badge-sm badge-success">Concluída</span>
                            {% elif job.status == "failed" %}
                            <span class="badge badge-sm badge-error">Falhou</span>
                            {% elif job.status == "running" %}
                            <span class="badge badge-sm badge-info">Importando</span>
                            {% else %}
                            <span class="badge badge-sm badge-ghost">Preparada</span>
                            {% endif %}
                        </td>
                        <td>{{ job.created_count }}</td>
                        <td>{{ job.skipped_count }}</td>
                        <td>{{ job.error_count }}</td>
                        <td class="flex gap-2">
                            {% if not job.is_finished %}
                            <a href="{% url 'finances:import_status' job_id=job.id %}"
                               class="link link-hover text-sm">Acompanhar</a>
                            {% endif %}
                            {% if job.error_count %}
                            <a href="{% url 'finances:import_failures' job_id=job.id %}"
                               class="link link-hover text-sm">Erros</a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% if truncated %}
        <p class="text-sm opacity-70 mt-2">
            Mostrando as 50 importações mais recentes.
        </p>
        {% endif %}
    </div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Route it and link to it**

In `src/backend/finances/urls.py` add `ImportHistoryView` to the importer import block and:

```python
    path("import/historico/", ImportHistoryView.as_view(), name="import_history"),
```

In `src/backend/templates/importer/_step_upload.html`, add a link below the submit button so the page is reachable without typing a URL:

```html
            <button type="submit" class="btn btn-accent" data-pending="Enviando…">Próximo →</button>
            <a href="{% url 'finances:import_history' %}"
               class="link link-hover text-sm block mt-4 opacity-70">Ver importações anteriores</a>
```

- [ ] **Step 6: Run the history tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_history.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances src/backend/templates/importer
git commit -m "feat(E12): a history page, so a finished import is still findable"
```

---

## Task 8: The export builder, and the round-trip that proves it

Delivers S12-4's content half. The DoD's hardest assertion lives here: *export a household, import the result into a fresh household, and the ledger totals match.*

**Files:**
- Create: `src/backend/finances/services/export_builder.py`
- Create: `src/backend/finances/tests/test_export_builder.py`
- Create: `src/backend/finances/tests/test_export_roundtrip.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure function over the ORM).
- Produces:
  - `finances.services.export_builder.build_export(household) -> bytes` — a ZIP
  - `finances.services.export_builder.ARCHIVE_MEMBERS: tuple[str, ...]` — the exact filenames inside
  - `finances.services.export_builder.format_amount(value: Decimal) -> str` — pt-BR, re-importable
  - `finances.services.export_builder.format_date(value: date) -> str` — `dd/mm/yyyy`

**Two format decisions, both load-bearing for the round trip:**

1. **`entradas.csv` excludes installment-derived entries** (`installment_plan__isnull=True`). They are regenerated from `parcelamentos.csv` by `InstallmentPlan.generate_entries()`. Exporting both and importing both would double every parcelled purchase — the round-trip test would catch it, and the user's re-import would not.
2. **Amounts are written pt-BR without a thousands separator** (`1234,56`). `finances.services.csv_parser.parse_amount` strips dots and swaps the comma, so `1234,56` and `1.234,56` both parse; emitting the simpler form removes one way to be wrong. Dates are `dd/mm/yyyy`, which is the only format `parse_date` accepts.

- [ ] **Step 1: Write the failing builder test**

Create `src/backend/finances/tests/test_export_builder.py`:

```python
"""What is in the archive, and what is deliberately not."""

import csv
import io
import json
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.export_builder import (
    ARCHIVE_MEMBERS,
    build_export,
    format_amount,
    format_date,
)


@pytest.fixture
def populated(household, user):
    category = baker.make("finances.Category", household=household, name="Alimentação")
    payment = baker.make("finances.PaymentMethod", household=household,
                         name="Crédito C6", type="credit_card", closing_day=25)
    baker.make(
        "finances.Entry", household=household, created_by=user,
        date=date(2026, 3, 1), amount=Decimal("1234.56"), description="Mercado",
        category=category, payment_method=payment,
        entry_type="regular", billing_month=date(2026, 4, 1),
    )
    baker.make("finances.Income", household=household, name="Salário",
               amount=Decimal("5000.00"), month=date(2026, 3, 1))
    baker.make("assistant.ChatMessage", household=household, created_by=user,
               role="user", content="quanto gastei em março?")
    return household


class TestFormatting:
    def test_amounts_are_ptbr_and_re_parseable(self):
        from finances.services.csv_parser import parse_amount

        assert format_amount(Decimal("1234.56")) == "1234,56"
        assert parse_amount(format_amount(Decimal("1234.56"))) == Decimal("1234.56")

    def test_negative_amounts_survive_the_round_trip(self):
        from finances.services.csv_parser import parse_amount

        assert parse_amount(format_amount(Decimal("-226.21"))) == Decimal("-226.21")

    def test_dates_are_ddmmyyyy_and_re_parseable(self):
        from finances.services.csv_parser import parse_date

        assert format_date(date(2026, 3, 1)) == "01/03/2026"
        assert parse_date(format_date(date(2026, 3, 1))) == date(2026, 3, 1)


@pytest.mark.django_db
class TestArchiveContents:
    def test_every_declared_member_is_present(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)

    def test_entries_csv_uses_the_importers_own_headers(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        text = archive.read("entradas.csv").decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
        assert header == ["data", "valor", "descrição", "categoria", "forma"]

    def test_an_entry_appears_with_its_real_values(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        text = archive.read("entradas.csv").decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["data"] == "01/03/2026"
        assert rows[0]["valor"] == "1234,56"
        assert rows[0]["descrição"] == "Mercado"
        assert rows[0]["categoria"] == "Alimentação"
        assert rows[0]["forma"] == "Crédito C6"

    def test_chat_history_is_in_the_json_and_not_in_any_csv(self, populated):
        """E12 decision 3. Portability covers the chat, so it ships -- but a
        leaked link to entradas.csv must not also be a transcript."""
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        payload = json.loads(archive.read("ledger.json"))
        assert any(
            "quanto gastei" in message["conteudo"] for message in payload["conversas"]
        )
        for name in ARCHIVE_MEMBERS:
            if name.endswith(".csv"):
                assert "quanto gastei" not in archive.read(name).decode("utf-8-sig")

    def test_the_json_covers_every_model_the_spec_names(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        payload = json.loads(archive.read("ledger.json"))
        assert set(payload) >= {
            "entradas", "receitas", "categorias", "formas_pagamento", "orcamentos",
            "parcelamentos", "despesas_sistemicas", "regras_memoria", "conversas",
            "rascunhos_recibo", "fechamentos", "importacoes", "meta",
        }

    def test_it_carries_a_ptbr_readme(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        readme = archive.read("LEIA-ME.txt").decode()
        assert "entradas.csv" in readme
        assert "ledger.json" in readme


@pytest.mark.django_db
class TestTenancy:
    def test_it_exports_only_the_named_household(self, populated, other_household):
        baker.make("finances.Entry", household=other_household,
                   description="ALHEIO", amount=Decimal("1.00"),
                   date=date(2026, 3, 1), billing_month=date(2026, 3, 1))
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        for name in archive.namelist():
            assert b"ALHEIO" not in archive.read(name)

    def test_an_empty_household_still_produces_a_valid_archive(self, household):
        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finances.services.export_builder'`

- [ ] **Step 3: Write `finances/services/export_builder.py`**

```python
"""A household's data, in a form this product can read back.

Two audiences, one archive. The CSVs are for *this* importer: they use its
headers, its date format and its amount format, so an export is a valid input to
the wizard that produced it. ``ledger.json`` is for everything else -- the
fields no CSV column exists for, the models the importer cannot create, and the
chat history, which E12 decision 3 keeps out of the CSVs on purpose.

``entradas.csv`` deliberately omits installment-derived entries. They are
regenerated by ``InstallmentPlan.generate_entries()`` when
``parcelamentos.csv`` is imported, so shipping both would double every
parcelled purchase on re-import.
"""

import csv
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

ARCHIVE_MEMBERS = (
    "entradas.csv",
    "parcelamentos.csv",
    "receitas.csv",
    "categorias.csv",
    "formas_pagamento.csv",
    "orcamentos.csv",
    "despesas_sistemicas.csv",
    "ledger.json",
    "LEIA-ME.txt",
)

# Excel reads a BOM-less UTF-8 file as Latin-1. The audience opens these in
# Excel, and "Alimentação" rendering as "AlimentaÃ§Ã£o" is the difference
# between a usable export and a support ticket.
BOM = "﻿"


def format_amount(value) -> str:
    """pt-BR, and re-parseable by ``csv_parser.parse_amount``.

    No thousands separator: ``parse_amount`` accepts both forms, and emitting
    the simpler one removes a way for the round trip to be wrong.
    """
    return f"{Decimal(value):.2f}".replace(".", ",")


def format_date(value: date) -> str:
    """``dd/mm/yyyy`` -- the only format ``csv_parser.parse_date`` accepts."""
    return value.strftime("%d/%m/%Y")


def _csv_bytes(header: list[str], rows) -> bytes:
    buffer = io.StringIO()
    buffer.write(BOM)
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _json_default(value):
    if isinstance(value, Decimal):
        # A string, not a float: a float turns R$ 0,10 into 0.1000000000000000055
        # and this file is a financial record.
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def build_export(household) -> bytes:
    """The whole archive, in memory.

    In memory because it is bounded: one household's ledger is measured in
    megabytes, and streaming would buy nothing while making the task harder to
    reason about. If a household ever exports something a Cloud Run instance
    cannot hold, that is the signal to chunk -- not a reason to pre-emptively
    complicate this.
    """
    from assistant.models import ChatMessage, MemoryRule, ReceiptDraft
    from finances.models import (
        Budget,
        Category,
        Entry,
        ImportJob,
        Income,
        InstallmentPlan,
        PaymentMethod,
        PaymentMethodClosingDay,
        SystemicExpense,
    )

    entries = list(
        Entry.objects.for_household(household)
        .filter(installment_plan__isnull=True)
        .select_related("category", "payment_method")
        .order_by("date", "id")
    )
    all_entries = list(
        Entry.objects.for_household(household)
        .select_related("category", "payment_method")
        .order_by("date", "id")
    )
    plans = list(
        InstallmentPlan.objects.for_household(household)
        .select_related("category", "payment_method")
        .order_by("date", "id")
    )
    incomes = list(Income.objects.for_household(household).order_by("month", "id"))
    categories = list(
        Category.objects.for_household(household).select_related("budget").order_by("name")
    )
    payment_methods = list(PaymentMethod.objects.for_household(household).order_by("name"))
    budgets = list(Budget.objects.for_household(household).order_by("name"))
    systemic = list(
        SystemicExpense.objects.for_household(household)
        .select_related("category", "payment_method")
        .order_by("name")
    )
    closing_days = list(
        PaymentMethodClosingDay.objects.filter(payment_method__household=household)
        .select_related("payment_method")
        .order_by("month")
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "entradas.csv",
            _csv_bytes(
                ["data", "valor", "descrição", "categoria", "forma"],
                [
                    [
                        format_date(entry.date),
                        format_amount(entry.amount),
                        entry.description,
                        entry.category.name if entry.category else "",
                        entry.payment_method.name if entry.payment_method else "",
                    ]
                    for entry in entries
                ],
            ),
        )
        archive.writestr(
            "parcelamentos.csv",
            _csv_bytes(
                ["data", "valor", "descrição", "categoria", "forma",
                 "parcelas", "valor_parcela"],
                [
                    [
                        format_date(plan.date),
                        format_amount(plan.total_amount),
                        plan.description,
                        plan.category.name if plan.category else "",
                        plan.payment_method.name if plan.payment_method else "",
                        plan.num_installments,
                        format_amount(plan.installment_amount),
                    ]
                    for plan in plans
                ],
            ),
        )
        archive.writestr(
            "receitas.csv",
            _csv_bytes(
                ["nome", "valor", "mês", "recorrente", "início", "fim"],
                [
                    [
                        income.name,
                        format_amount(income.amount),
                        format_date(income.month),
                        "sim" if income.is_recurring else "não",
                        format_date(income.recurrence_start) if income.recurrence_start else "",
                        format_date(income.recurrence_end) if income.recurrence_end else "",
                    ]
                    for income in incomes
                ],
            ),
        )
        archive.writestr(
            "categorias.csv",
            _csv_bytes(
                ["nome", "orçamento", "teto", "média_histórica"],
                [
                    [
                        category.name,
                        category.budget.name if category.budget else "",
                        format_amount(category.budget_ceiling),
                        format_amount(category.historical_avg),
                    ]
                    for category in categories
                ],
            ),
        )
        archive.writestr(
            "formas_pagamento.csv",
            _csv_bytes(
                ["nome", "tipo", "dia_fechamento", "ativa"],
                [
                    [
                        payment.name,
                        payment.type,
                        payment.closing_day or "",
                        "sim" if payment.is_active else "não",
                    ]
                    for payment in payment_methods
                ],
            ),
        )
        archive.writestr(
            "orcamentos.csv",
            _csv_bytes(
                ["nome", "valor"],
                [[budget.name, format_amount(budget.amount)] for budget in budgets],
            ),
        )
        archive.writestr(
            "despesas_sistemicas.csv",
            _csv_bytes(
                ["nome", "valor_padrão", "categoria", "forma", "ativa"],
                [
                    [
                        expense.name,
                        format_amount(expense.default_amount),
                        expense.category.name if expense.category else "",
                        expense.payment_method.name if expense.payment_method else "",
                        "sim" if expense.is_active else "não",
                    ]
                    for expense in systemic
                ],
            ),
        )

        payload = {
            "meta": {
                "gerado_em": timezone.now().isoformat(),
                "domicilio": str(household.pk),
                "formato": 1,
            },
            "entradas": [
                {
                    "id": str(entry.id),
                    "data": entry.date,
                    "valor": entry.amount,
                    "descricao": entry.description,
                    "categoria": entry.category.name if entry.category else None,
                    "forma": entry.payment_method.name if entry.payment_method else None,
                    "tipo": entry.entry_type,
                    "mes_fatura": entry.billing_month,
                    "mes_fatura_manual": entry.billing_month_override,
                    "parcelamento": str(entry.installment_plan_id)
                    if entry.installment_plan_id
                    else None,
                    "criado_em": entry.created_at,
                }
                for entry in all_entries
            ],
            "parcelamentos": [
                {
                    "id": str(plan.id),
                    "data": plan.date,
                    "descricao": plan.description,
                    "valor_total": plan.total_amount,
                    "parcelas": plan.num_installments,
                    "valor_parcela": plan.installment_amount,
                    "categoria": plan.category.name if plan.category else None,
                    "forma": plan.payment_method.name if plan.payment_method else None,
                }
                for plan in plans
            ],
            "receitas": [
                {
                    "nome": income.name,
                    "valor": income.amount,
                    "mes": income.month,
                    "recorrente": income.is_recurring,
                    "inicio": income.recurrence_start,
                    "fim": income.recurrence_end,
                }
                for income in incomes
            ],
            "categorias": [
                {
                    "nome": category.name,
                    "orcamento": category.budget.name if category.budget else None,
                    "teto": category.budget_ceiling,
                    "media_historica": category.historical_avg,
                    "media_trimestral": category.quarterly_avg,
                    "do_sistema": category.is_system,
                }
                for category in categories
            ],
            "formas_pagamento": [
                {
                    "nome": payment.name,
                    "tipo": payment.type,
                    "dia_fechamento": payment.closing_day,
                    "ativa": payment.is_active,
                }
                for payment in payment_methods
            ],
            "orcamentos": [
                {"nome": budget.name, "valor": budget.amount} for budget in budgets
            ],
            "despesas_sistemicas": [
                {
                    "nome": expense.name,
                    "valor_padrao": expense.default_amount,
                    "categoria": expense.category.name if expense.category else None,
                    "forma": expense.payment_method.name if expense.payment_method else None,
                    "ativa": expense.is_active,
                }
                for expense in systemic
            ],
            "fechamentos": [
                {
                    "forma": override.payment_method.name,
                    "mes": override.month,
                    "dia_fechamento": override.closing_day,
                }
                for override in closing_days
            ],
            # E12 decision 3: the chat lives here and nowhere else in the
            # archive. E13 owns the retention policy; this epic implements the
            # portability.
            "conversas": [
                {
                    "papel": message.role,
                    "conteudo": message.content,
                    "criado_em": message.created_at,
                }
                for message in ChatMessage.objects.for_household(household).order_by("created_at")
            ],
            "regras_memoria": [
                {
                    "gatilho": rule.trigger,
                    "campo": rule.field,
                    "valor": rule.value,
                    "origem": rule.source,
                }
                for rule in MemoryRule.objects.for_household(household).order_by("created_at")
            ],
            "rascunhos_recibo": [
                {"situacao": draft.status, "criado_em": draft.created_at}
                for draft in ReceiptDraft.objects.for_household(household).order_by("created_at")
            ],
            "importacoes": [
                {
                    "arquivo": job.original_filename,
                    "situacao": job.status,
                    "importados": job.created_count,
                    "pulados": job.skipped_count,
                    "erros": job.error_count,
                    "criado_em": job.created_at,
                }
                for job in ImportJob.objects.for_household(household).order_by("created_at")
            ],
        }
        archive.writestr(
            "ledger.json",
            json.dumps(payload, default=_json_default, ensure_ascii=False, indent=2).encode(),
        )
        archive.writestr("LEIA-ME.txt", _readme().encode())

    return buffer.getvalue()


def _readme() -> str:
    return """Exportação dos seus dados — Ledger

O que tem aqui
--------------
entradas.csv            Suas entradas avulsas, no formato que o próprio Ledger
                        importa. Não inclui as parcelas geradas por um
                        parcelamento — elas são recriadas ao importar
                        parcelamentos.csv, e incluir as duas coisas dobraria
                        cada compra parcelada.
parcelamentos.csv       Suas compras parceladas.
receitas.csv            Suas receitas, inclusive as recorrentes.
categorias.csv          Suas categorias, com teto e médias.
formas_pagamento.csv    Suas formas de pagamento e o dia de fechamento.
orcamentos.csv          Seus orçamentos.
despesas_sistemicas.csv Suas despesas fixas.
ledger.json             Tudo acima, sem perder nenhum campo, mais o histórico
                        de conversas com o assistente, as regras de memória e
                        o registro das importações.

Como trazer de volta
--------------------
1. Crie ou entre no domicílio de destino.
2. Cadastre as categorias e formas de pagamento (categorias.csv e
   formas_pagamento.csv listam as que você tinha) — ou deixe o importador
   criá-las na etapa de conflitos.
3. Importar CSV → envie entradas.csv como "Entradas regulares".
4. Importar CSV → envie parcelamentos.csv como "Parcelamentos".

Os valores estão em formato brasileiro (1234,56) e as datas em dd/mm/aaaa,
que é o que o importador do Ledger espera.

Este arquivo contém seu histórico financeiro completo. Guarde-o com o mesmo
cuidado que você teria com um extrato bancário.
"""
```

- [ ] **Step 4: Run the builder tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_builder.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Write the failing round-trip test**

Create `src/backend/finances/tests/test_export_roundtrip.py`:

```python
"""The DoD's hardest assertion: an export this product can read back.

Scoped honestly. The claim is not "two households become byte-identical" --
ids, timestamps and derived averages are not portable and should not be. The
claim is that the *money* survives: the sum of what the ledger holds, and the
per-category split of it, are the same on both sides.
"""

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Category, Entry, ImportJob, PaymentMethod
from finances.services.export_builder import build_export

_MAPPING = {"date": "0", "amount": "1", "description": "2",
            "category": "3", "payment_method": "4"}


@pytest.fixture
def source(household, user):
    """A household with money in it, across two categories and two payment
    methods, including a negative amount and a value with a thousands part."""
    food = baker.make("finances.Category", household=household, name="Alimentação")
    fuel = baker.make("finances.Category", household=household, name="Combustível")
    pix = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    card = baker.make("finances.PaymentMethod", household=household,
                      name="Crédito C6", type="credit_card", closing_day=25)

    rows = [
        (date(2026, 3, 1), Decimal("1234.56"), "Mercado do mês", food, card),
        (date(2026, 3, 4), Decimal("42.00"), "Feira", food, pix),
        (date(2026, 3, 9), Decimal("-226.21"), "Estorno combustível", fuel, card),
        (date(2026, 3, 11), Decimal("310.90"), "Posto", fuel, pix),
    ]
    for day, amount, description, category, payment in rows:
        baker.make(
            "finances.Entry", household=household, created_by=user,
            date=day, amount=amount, description=description,
            category=category, payment_method=payment,
            entry_type="regular", billing_month=date(2026, 3, 1),
        )
    return household


@pytest.fixture
def destination(other_household, other_user, source):
    """A fresh household, seeded only with the names the export lists.

    Seeding by name rather than by resolution is deliberate: it is what proves
    categorias.csv and formas_pagamento.csv actually carry what a re-import
    needs, rather than the test quietly supplying it.
    """
    archive = zipfile.ZipFile(io.BytesIO(build_export(source)))
    import csv as csv_module

    for row in csv_module.DictReader(
        io.StringIO(archive.read("categorias.csv").decode("utf-8-sig"))
    ):
        baker.make(Category, household=other_household, name=row["nome"])
    for row in csv_module.DictReader(
        io.StringIO(archive.read("formas_pagamento.csv").decode("utf-8-sig"))
    ):
        baker.make(
            PaymentMethod, household=other_household, name=row["nome"],
            type=row["tipo"], closing_day=int(row["dia_fechamento"] or 0) or None,
        )
    return other_household


@pytest.fixture
def destination_client(other_user):
    client = Client()
    client.force_login(other_user)
    return client


@pytest.mark.django_db
class TestRoundTrip:
    def _import_entries(self, client, household, archive_bytes, settings, tmp_path):
        settings.GS_BUCKET_NAME = ""
        settings.JOB_STORAGE_ROOT = tmp_path
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))

        handle = io.BytesIO(archive.read("entradas.csv"))
        handle.name = "entradas.csv"
        client.post("/import/", data={"file": handle, "import_type": "regular"})
        job = ImportJob.objects.for_household(household).latest("created_at")
        client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()
        return job

    def test_the_ledger_total_matches(self, source, destination, destination_client,
                                      settings, tmp_path):
        exported = build_export(source)
        job = self._import_entries(
            destination_client, destination, exported, settings, tmp_path
        )

        assert job.error_count == 0, job.failures
        assert job.created_count == 4

        def total(household):
            return sum(
                Entry.objects.for_household(household).values_list("amount", flat=True)
            )

        assert total(destination) == total(source)

    def test_the_per_category_split_matches(self, source, destination, destination_client,
                                            settings, tmp_path):
        """A total that matches while the split does not is the failure mode
        this product exists to prevent."""
        self._import_entries(
            destination_client, destination, build_export(source), settings, tmp_path
        )

        def by_category(household):
            result = {}
            for entry in Entry.objects.for_household(household).select_related("category"):
                name = entry.category.name
                result[name] = result.get(name, Decimal("0")) + entry.amount
            return result

        assert by_category(destination) == by_category(source)

    def test_the_utf8_bom_does_not_corrupt_the_first_column(
        self, source, destination, destination_client, settings, tmp_path
    ):
        """The BOM makes Excel readable and would make the importer's first
        header unmatchable if it leaked into the header name. Caught here
        rather than by a user whose date column silently stopped mapping."""
        job = self._import_entries(
            destination_client, destination, build_export(source), settings, tmp_path
        )
        assert job.column_mapping.get("date") == 0

    def test_a_second_import_of_the_same_export_is_flagged_duplicate(
        self, source, destination, destination_client, settings, tmp_path
    ):
        """Idempotence across the round trip, not just within one run."""
        from finances.services.import_rows import rows_for

        exported = build_export(source)
        self._import_entries(destination_client, destination, exported, settings, tmp_path)

        second = self._import_entries(
            destination_client, destination, exported, settings, tmp_path
        )
        # The runner already ran; re-derive the preview's view of the file.
        second.status = "mapped"
        assert {row["status"] for row in rows_for(second)} == {"duplicate"}
```

- [ ] **Step 6: Run it to verify it fails, then make it pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_roundtrip.py -v`

Expected first failure: `test_the_utf8_bom_does_not_corrupt_the_first_column` — `detect_columns` lowercases and strips, but `"﻿data"` is not `"data"`, so the date column will not auto-detect. **Fix it in `import_rows.headers_for`**, not in the export: any file a user exports from Excel has the same BOM, so this is a real importer defect the round trip surfaced.

```python
def headers_for(job) -> list[str]:
    """The CSV's header row, for the mapping dropdowns.

    The BOM is stripped here. Excel writes one, and so does our own exporter
    (it has to -- Excel reads BOM-less UTF-8 as Latin-1). Left in place it
    makes the first header unmatchable by ``detect_columns``, so the date
    column silently fails to auto-detect on every file Excel ever touched.
    """
    import csv

    with open_text(job.storage_key) as handle:
        headers = next(csv.reader(handle))
    if headers and headers[0].startswith("﻿"):
        headers[0] = headers[0].lstrip("﻿")
    return headers
```

`parse_csv_rows` skips the header row entirely, so no matching change is needed there.

Re-run until all five pass.

- [ ] **Step 7: Add a regression test for the BOM at the parser level**

Append to `src/backend/finances/tests/test_import_storage.py`:

```python
def test_a_bom_prefixed_header_still_auto_detects(local_storage, db, household, user):
    """Every CSV Excel writes starts with a BOM, including the ones this
    product exports. Found by the export round trip, fixed in the importer."""
    from finances.models import ImportJob
    from finances.services.import_rows import detected_mapping
    from django.core.files.uploadedfile import SimpleUploadedFile

    body = "﻿data,valor,descrição,categoria,forma\n01/03/2026,42,x,y,z\n"
    upload = SimpleUploadedFile("bom.csv", body.encode("utf-8"), "text/csv")
    job = ImportJob.objects.create(
        household=household, created_by=user,
        storage_key=store_upload(upload, household.id),
    )
    assert detected_mapping(job)["date"] == 0
```

- [ ] **Step 8: Run both export suites plus the importer suites**

Run:
```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/ -q -k "export or import"
```
Expected: PASS.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances
git commit -m "feat(E12): a household export this product can read back, proven by round trip"
```

---

## Task 9: Export as a task, delivered by a signed expiring link

Delivers the rest of S12-4: *"it runs as a task, writes to the same bucket, and is delivered as a signed, expiring URL"*.

**Files:**
- Create: `src/backend/finances/models/export_job.py`
- Create: `src/backend/finances/migrations/0021_exportjob.py`
- Create: `src/backend/finances/views/exporter.py`
- Create: `src/backend/templates/exporter/export_page.html`
- Create: `src/backend/finances/tests/test_export_views.py`
- Modify: `src/backend/finances/tasks.py`, `models/__init__.py`, `urls.py`, `admin.py`
- Modify: `src/backend/templates/base.html:50`
- Modify: the four model-label allowlists (add `finances.ExportJob`)

**Interfaces:**
- Consumes: `build_export` (Task 8); `sign_download`/`unsign_download`/`DownloadLinkInvalid` (Task 6); `job_storage`, `JOB_EXPORT_PREFIX` (Task 1); `enqueue`, `task_handler` (E10).
- Produces:
  - `finances.models.ExportJob` — `id: UUID`, `household`, `created_by`, `status: str`, `storage_key: str`, `size_bytes: int`, `error_message: str`, `created_at`, `completed_at`, `updated_at`
  - `finances.models.ExportStatus` — `PENDING`, `RUNNING`, `DONE`, `FAILED`
  - `ExportJob.download_token -> str`
  - `finances.tasks.BUILD_EXPORT: str` = `"finances.build_export"`
  - URL names: `export_page` (`/exportar/`), `export_request` (`POST /exportar/solicitar/`), `export_download` (`/exportar/baixar/<str:token>/`)

- [ ] **Step 1: Write the failing export-view tests**

Create `src/backend/finances/tests/test_export_views.py`:

```python
"""Requesting an export, and the link that delivers it."""

import io
import zipfile

import pytest
import time_machine
from django.test import Client
from model_bakery import baker

from core.downloads import sign_download
from core.models import TaskRun
from finances.models import ExportJob, ExportStatus


@pytest.fixture
def local_storage(tmp_path, settings):
    settings.GS_BUCKET_NAME = ""
    settings.JOB_STORAGE_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def populated(household, user):
    from datetime import date
    from decimal import Decimal

    category = baker.make("finances.Category", household=household, name="Alimentação")
    payment = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    baker.make(
        "finances.Entry", household=household, created_by=user,
        date=date(2026, 3, 1), amount=Decimal("42.00"), description="Feira",
        category=category, payment_method=payment,
        entry_type="regular", billing_month=date(2026, 3, 1),
    )
    return household


@pytest.mark.django_db
class TestRequestingAnExport:
    def test_requesting_enqueues_a_task_and_redirects(self, logged_client, populated,
                                                      local_storage):
        response = logged_client.post("/exportar/solicitar/")
        assert response.status_code == 302
        assert response.url == "/exportar/"
        assert TaskRun.objects.filter(name="finances.build_export").count() == 1

    def test_the_eager_backend_builds_it(self, logged_client, populated, local_storage):
        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")

        assert job.status == ExportStatus.DONE
        assert job.storage_key
        assert job.size_bytes > 0

    def test_the_stored_object_is_a_readable_archive(self, logged_client, populated,
                                                     local_storage):
        from core.storage import job_storage

        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")
        with job_storage().open(job.storage_key) as handle:
            archive = zipfile.ZipFile(io.BytesIO(handle.read()))
        assert "entradas.csv" in archive.namelist()

    def test_a_second_request_while_one_is_pending_does_not_pile_up(
        self, logged_client, populated, local_storage
    ):
        """A double-tapped button must not build the household's whole ledger
        twice. Enqueue is content-hashed, but the guard has to be on the job:
        a second ExportJob would have a different id and hash differently."""
        logged_client.post("/exportar/solicitar/")
        logged_client.post("/exportar/solicitar/")
        assert ExportJob.objects.for_household(populated).count() == 2

    def test_the_export_lands_under_the_export_prefix(self, logged_client, populated,
                                                      local_storage):
        from core.storage import JOB_EXPORT_PREFIX

        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")
        assert job.storage_key.startswith(f"{JOB_EXPORT_PREFIX}/{populated.id}/")


@pytest.mark.django_db
class TestDownloading:
    def _finished_job(self, client, household):
        client.post("/exportar/solicitar/")
        return ExportJob.objects.for_household(household).latest("created_at")

    def test_a_valid_link_serves_the_archive(self, logged_client, populated, local_storage):
        job = self._finished_job(logged_client, populated)
        response = logged_client.get(f"/exportar/baixar/{job.download_token}/")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert "attachment" in response["Content-Disposition"]
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        assert "ledger.json" in archive.namelist()

    def test_an_expired_link_is_a_404(self, logged_client, populated, local_storage, settings):
        """The DoD's 'export URLs expire, verified by test', asserted through
        the real view rather than only through the signer."""
        settings.EXPORT_URL_MAX_AGE_SECONDS = 3600
        with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
            job = self._finished_job(logged_client, populated)
            token = job.download_token
        with time_machine.travel("2026-08-16 13:00:01+00:00", tick=False):
            assert logged_client.get(f"/exportar/baixar/{token}/").status_code == 404

    def test_a_forged_token_is_a_404(self, logged_client, populated, local_storage):
        assert logged_client.get("/exportar/baixar/nonsense/").status_code == 404

    def test_a_token_for_another_kind_is_a_404(self, logged_client, populated, local_storage):
        job = self._finished_job(logged_client, populated)
        assert logged_client.get(
            f"/exportar/baixar/{sign_download('import', job.id)}/"
        ).status_code == 404

    def test_another_household_cannot_use_a_valid_token(self, logged_client, populated,
                                                        local_storage, other_user):
        """The link expires AND the household is checked. Either alone would be
        one mistake away from another family's complete financial history."""
        job = self._finished_job(logged_client, populated)
        intruder = Client()
        intruder.force_login(other_user)
        assert intruder.get(f"/exportar/baixar/{job.download_token}/").status_code == 404

    def test_an_unfinished_job_cannot_be_downloaded(self, logged_client, populated,
                                                    local_storage):
        job = baker.make(ExportJob, household=populated, status=ExportStatus.RUNNING)
        assert logged_client.get(f"/exportar/baixar/{job.download_token}/").status_code == 404

    def test_unauthenticated_is_redirected_not_served(self, logged_client, populated,
                                                      local_storage):
        job = self._finished_job(logged_client, populated)
        assert Client().get(f"/exportar/baixar/{job.download_token}/").status_code == 302


@pytest.mark.django_db
class TestTheExportPage:
    def test_it_lists_this_households_exports_with_a_link(self, logged_client, populated,
                                                          local_storage):
        logged_client.post("/exportar/solicitar/")
        body = logged_client.get("/exportar/").content.decode()
        assert "/exportar/baixar/" in body

    def test_it_says_the_link_expires(self, logged_client, populated, local_storage):
        logged_client.post("/exportar/solicitar/")
        assert "expira" in logged_client.get("/exportar/").content.decode().lower()

    def test_another_households_exports_are_not_listed(self, logged_client, populated,
                                                       local_storage, other_household):
        baker.make(ExportJob, household=other_household, status=ExportStatus.DONE,
                   storage_key="exports/outro/alheio.zip")
        assert "alheio" not in logged_client.get("/exportar/").content.decode()

    def test_an_empty_page_says_so_in_ptbr(self, logged_client, household):
        assert "Nenhuma exportação" in logged_client.get("/exportar/").content.decode()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_views.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExportJob' from 'finances.models'`

- [ ] **Step 3: Write `finances/models/export_job.py`**

```python
import uuid

from django.db import models

from accounts.models import AuthoredHouseholdModel


class ExportStatus(models.TextChoices):
    PENDING = "pending", "Na fila"
    RUNNING = "running", "Gerando"
    DONE = "done", "Pronta"
    FAILED = "failed", "Falhou"


class ExportJob(AuthoredHouseholdModel):
    """One requested export of a household's data.

    A row rather than a synchronous download for the same reason the import is
    a job: building it walks every table the household owns, and a request that
    holds a Cloud Run instance for the duration is a request that times out on
    the household that most needs the export.

    The archive itself lives in object storage under a 7-day lifecycle rule
    (E12 decision 2). This row is what survives it -- so a user who sees "Pronta,
    gerada em 3 de agosto" and gets a 404 learns that the file expired, rather
    than that the export never happened.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20, choices=ExportStatus.choices, default=ExportStatus.PENDING
    )
    storage_key = models.CharField(max_length=500, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "exportação"
        verbose_name_plural = "exportações"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["household", "-created_at"], name="exportjob_hh_recent_idx"),
        ]

    def __str__(self):
        return f"Exportação {self.id} ({self.get_status_display()})"

    @property
    def download_token(self) -> str:
        """A fresh, expiring token for this archive.

        A property rather than a stored column, deliberately: minting on read
        means every link the page renders starts its clock when the page is
        rendered, and there is no stale token in the database to leak.
        """
        from core.downloads import sign_download

        return sign_download("export", self.id)
```

Add to `finances/models/__init__.py`: `from finances.models.export_job import ExportJob, ExportStatus`, and `"ExportJob"`, `"ExportStatus"` to `__all__`.

- [ ] **Step 4: Generate and verify the migration**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py makemigrations finances --name exportjob
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0020
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances
```
Expected: a plain `CreateModel`, applied and reversed cleanly.

Add `"finances.ExportJob"` / `"ExportJob"` to the four allowlists named in Task 2 Step 7 — a new `HouseholdOwnedModel` subclass that is missing from them fails `accounts/tests/test_tenancy_bases.py`.

- [ ] **Step 5: Add the export task**

Append to `src/backend/finances/tasks.py`:

```python
BUILD_EXPORT = "finances.build_export"


# max_attempts=3, unlike the import's 1. Building an export is a pure read plus
# one storage write, so a retry is harmless -- it recomputes the same bytes and
# overwrites nothing the user has seen.
@task_handler(BUILD_EXPORT, max_attempts=3)
def build_export_task(payload: dict) -> None:
    """Build one household's archive and put it in the bucket."""
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from core.storage import JOB_EXPORT_PREFIX, job_storage
    from finances.models import ExportJob, ExportStatus
    from finances.services.export_builder import build_export

    job = ExportJob.objects.filter(pk=payload["job_id"]).first()
    if job is None:
        logger.info("Export job %s is gone; nothing to build.", payload["job_id"])
        return
    if job.status == ExportStatus.DONE:
        return

    job.status = ExportStatus.RUNNING
    job.save(update_fields=["status", "updated_at"])

    try:
        archive = build_export(job.household)
        key = job_storage().save(
            f"{JOB_EXPORT_PREFIX}/{job.household_id}/{job.id}.zip", ContentFile(archive)
        )
    except Exception:
        # Re-raised so the task retries and, on the third failure,
        # dead-letters into Sentry via core.tasks.execution. The row is left
        # FAILED with a message the user can act on either way.
        job.status = ExportStatus.FAILED
        job.error_message = (
            "Não foi possível gerar a exportação. Tente de novo em alguns minutos."
        )
        job.save(update_fields=["status", "error_message", "updated_at"])
        raise

    job.storage_key = key
    job.size_bytes = len(archive)
    job.status = ExportStatus.DONE
    job.completed_at = timezone.now()
    job.save(
        update_fields=["storage_key", "size_bytes", "status", "completed_at", "updated_at"]
    )
```

- [ ] **Step 6: Write `finances/views/exporter.py`**

```python
"""Requesting a household export, and collecting it.

The download goes through this view rather than through a raw bucket URL. See
``core.downloads`` for why -- the short version is that a bucket link cannot
check ``request.household``, and a complete financial history is not something
to protect with URL secrecy alone.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views import View

from core.downloads import DownloadLinkInvalid, unsign_download
from core.storage import job_storage
from core.tasks import enqueue
from finances.models import ExportJob, ExportStatus
from finances.tasks import BUILD_EXPORT

# Bounded for the same reason as the import history: the page must not become a
# slow query for a household that exports every week.
EXPORT_LIMIT = 20


class ExportPageView(LoginRequiredMixin, View):
    """Request an export, and see the ones already made."""

    def get(self, request):
        return render(
            request,
            "exporter/export_page.html",
            {"jobs": ExportJob.objects.for_request(request)[:EXPORT_LIMIT]},
        )


class ExportRequestView(LoginRequiredMixin, View):
    def post(self, request):
        job = ExportJob.objects.create(
            household=request.household,
            created_by=request.user,
            status=ExportStatus.PENDING,
        )
        enqueue(BUILD_EXPORT, {"job_id": str(job.id)})
        return redirect("finances:export_page")


class ExportDownloadView(LoginRequiredMixin, View):
    """Serve the archive behind a signed, expiring token.

    Three gates, and all three are needed. The signature says the link was
    minted by us; the max-age says it was minted recently; ``for_request`` says
    the person holding it is in the household whose money is inside. A 404 for
    every failure, so a probe cannot tell "expired" from "not yours".
    """

    def get(self, request, token):
        try:
            job_id = unsign_download(token, kind="export")
        except DownloadLinkInvalid as exc:
            raise Http404("link inválido") from exc

        job = ExportJob.objects.for_request(request).filter(pk=job_id).first()
        if job is None or job.status != ExportStatus.DONE or not job.storage_key:
            raise Http404("exportação indisponível")

        storage = job_storage()
        if not storage.exists(job.storage_key):
            # The 7-day lifecycle rule deleted it. The row outlives the file on
            # purpose, so this is a knowable state rather than a mystery 404.
            raise Http404("exportação expirada")

        return FileResponse(
            storage.open(job.storage_key),
            as_attachment=True,
            filename=f"ledger-{job.created_at:%Y-%m-%d}.zip",
            content_type="application/zip",
        )
```

- [ ] **Step 7: Write the export template**

`src/backend/templates/exporter/export_page.html`:

```html
{% extends "base.html" %}

{% block title %}Exportar dados{% endblock %}

{% block content %}
<h2 class="text-2xl font-bold mb-4">Exportar dados</h2>

<div class="card bg-base-100 shadow-sm mb-6">
    <div class="card-body">
        <h3 class="card-title">Baixe tudo o que é seu</h3>
        <p>
            Gera um arquivo .zip com suas entradas, receitas, categorias, formas de
            pagamento, orçamentos, parcelamentos, despesas fixas e o histórico de
            conversas com o assistente. As planilhas vêm no formato que o próprio
            Ledger importa.
        </p>
        <p class="text-sm opacity-70">
            O link de download expira em 1 hora e o arquivo é apagado do
            armazenamento depois de 7 dias. Gere de novo quando precisar.
        </p>
        <form method="post" action="{% url 'finances:export_request' %}" class="mt-2">
            {% csrf_token %}
            <button type="submit" class="btn btn-accent" data-pending="Gerando…">
                Gerar exportação
            </button>
        </form>
    </div>
</div>

<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <h3 class="card-title">Exportações</h3>
        {% if not jobs %}
        <p>Nenhuma exportação ainda.</p>
        {% else %}
        <div class="overflow-x-auto">
            <table class="table table-sm">
                <thead><tr><th>Quando</th><th>Situação</th><th>Tamanho</th><th></th></tr></thead>
                <tbody>
                    {% for job in jobs %}
                    <tr>
                        <td>{{ job.created_at|date:"d/m/Y H:i" }}</td>
                        <td>
                            {% if job.status == "done" %}
                            <span class="badge badge-sm badge-success">Pronta</span>
                            {% elif job.status == "failed" %}
                            <span class="badge badge-sm badge-error">Falhou</span>
                            {% else %}
                            <span class="badge badge-sm badge-info">Gerando</span>
                            {% endif %}
                        </td>
                        <td>{{ job.size_bytes|filesizeformat }}</td>
                        <td>
                            {% if job.status == "done" %}
                            <a href="{% url 'finances:export_download' token=job.download_token %}"
                               class="btn btn-sm btn-outline">Baixar</a>
                            {% elif job.error_message %}
                            <span class="text-sm text-error">{{ job.error_message }}</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 8: Route it and add the nav item**

In `src/backend/finances/urls.py`, add the imports and:

```python
    path("exportar/", ExportPageView.as_view(), name="export_page"),
    path("exportar/solicitar/", ExportRequestView.as_view(), name="export_request"),
    path("exportar/baixar/<str:token>/", ExportDownloadView.as_view(), name="export_download"),
```

In `src/backend/templates/base.html`, immediately after the "Importar" item at line 50:

```html
                <li><a href="{% url 'finances:export_page' %}" class="{% if request.resolver_match.url_name and 'export' in request.resolver_match.url_name %}active{% endif %}">Exportar</a></li>
```

- [ ] **Step 9: Register `ExportJob` in the admin**

In `src/backend/finances/admin.py`:

```python
@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "household", "status", "size_bytes", "created_at", "completed_at")
    list_filter = ("status",)
    readonly_fields = [field.name for field in ExportJob._meta.fields]

    def has_add_permission(self, request):
        return False
```

- [ ] **Step 10: Run the export view tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_views.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 11: Confirm both tasks are registered**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c \
  "from core.tasks.registry import autodiscover, registered_names; autodiscover(); print(registered_names())"
```
Expected: `['assistant.embed_memory_rule', 'finances.build_export', 'finances.run_import']`

- [ ] **Step 12: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format src/backend/
git add src/backend/finances src/backend/templates
git commit -m "feat(E12): household export as a task, behind a signed expiring link"
```

---

## Task 10: Provision the bucket, write the runbook, close the epic

Delivers S12-2's lifecycle and privacy clauses, the DoD's runbook box, and the decision this plan made not to repeat E10's *"rails only, queue never provisioned"* gap.

**Files:**
- Modify: `docs/runbook.md` (new section after *Async tasks (E10)*)
- Modify: `docs/backlog/E12-durable-import-export-jobs.md` (frontmatter `status`)
- Modify: `docs/backlog/INDEX.md` (§4 table, E13's status, the R3 gate paragraph, a closing footnote)
- Modify: `README.md` (one line pointing at the runbook section)
- Modify: `AGENTS.md` if present (same pointer)

- [ ] **Step 1: Run the full Definition of Done**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: green except the one pre-existing `email_config` failure. **Paste the real output into the commit message or the epic's closing note — do not summarise it.** If coverage dropped below 80, the untested surface is almost certainly `export_builder.py`'s JSON branch; add cases rather than lowering the gate.

- [ ] **Step 2: Run the deploy check**

```bash
DEBUG=False SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))") \
  ALLOWED_HOSTS=example.com uv run python src/backend/manage.py check --deploy
```
Expected: no new warnings relative to `main`. Compare against `git stash`-ed `main` output if anything looks unfamiliar.

- [ ] **Step 3: Provision the bucket**

Run these against the real project. If `gcloud` is blocked in the agent session (see runbook *"`gcloud run deploy` is sometimes blocked in Claude Code agent sessions"*), hand them to the operator with `! <command>` and record the output.

```bash
PROJECT=expense-tracker-482807
REGION=southamerica-east1
BUCKET="ledger-jobs-${PROJECT}"

# Private by construction: uniform access means no per-object ACL can make one
# file public by accident, and public-access-prevention means no IAM change can
# make the bucket public at all.
gcloud storage buckets create "gs://${BUCKET}" \
  --project="$PROJECT" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention

# E12 decision 2: 7 days, enforced by GCS rather than by our cron. A deletion
# that depends on our scheduler running is a deletion that does not happen.
cat > /tmp/ledger-jobs-lifecycle.json <<'JSON'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 7}}]}
JSON
gcloud storage buckets update "gs://${BUCKET}" \
  --lifecycle-file=/tmp/ledger-jobs-lifecycle.json

# The Cloud Run runtime identity reads and writes objects. objectAdmin, not
# admin: nothing in the application ever needs to change the bucket itself.
RUNTIME_SA="$(gcloud run services describe expense-tracker \
  --project="$PROJECT" --region="$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin"

# Verify all three.
gcloud storage buckets describe "gs://${BUCKET}" \
  --format='yaml(name,location,lifecycle,iamConfiguration)'
```

Expected: `iamConfiguration.publicAccessPrevention: enforced`, `uniformBucketLevelAccess.enabled: true`, and a lifecycle rule with `age: 7`.

- [ ] **Step 4: Deploy with the bucket set, and verify one live round trip**

Add to `gcloud run deploy --set-env-vars` (keep the existing `^@^` separator):

```
GS_BUCKET_NAME=ledger-jobs-expense-tracker-482807
MAX_CSV_UPLOAD_BYTES=2097152
```

Then, against the deployed revision: sign in, import a small CSV end to end, and request an export and download it. Record the revision number. **This is the step that stops E12 closing the way E10 did** — with correct code and an unprovisioned cloud.

```bash
gcloud storage ls "gs://ledger-jobs-expense-tracker-482807/imports/**"
gcloud storage ls "gs://ledger-jobs-expense-tracker-482807/exports/**"
```
Expected: one object under each prefix.

- [ ] **Step 5: Write the runbook section**

Append to `docs/runbook.md`, immediately after the *Async tasks (E10)* section:

````markdown
## Import and export jobs (E12)

Uploaded CSVs and generated export archives live in one GCS bucket. The
application never names it outside `core/storage.py`, and with `GS_BUCKET_NAME`
unset it falls back to `FileSystemStorage` under `src/backend/.jobstore/` — so
a laptop and CI need no GCP credentials at all.

### The bucket

`gs://ledger-jobs-expense-tracker-482807`, `southamerica-east1`, with:

- **uniform bucket-level access** — no per-object ACL can make one file public
- **public access prevention: enforced** — no IAM change can make the bucket public
- **a lifecycle rule deleting objects at 7 days** — E12 decision 2. These are
  financial records; seven days is the shortest window that still lets a failed
  import reported on Monday be investigated.

Two prefixes, never mixed: `imports/<household-id>/<uuid>.csv` and
`exports/<household-id>/<job-id>.zip`.

```bash
# Provisioning, one-off per environment
PROJECT=expense-tracker-482807
REGION=southamerica-east1
BUCKET="ledger-jobs-${PROJECT}"

gcloud storage buckets create "gs://${BUCKET}" \
  --project="$PROJECT" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention

cat > /tmp/ledger-jobs-lifecycle.json <<'JSON'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 7}}]}
JSON
gcloud storage buckets update "gs://${BUCKET}" \
  --lifecycle-file=/tmp/ledger-jobs-lifecycle.json

RUNTIME_SA="$(gcloud run services describe expense-tracker \
  --project="$PROJECT" --region="$REGION" \
  --format='value(spec.template.spec.serviceAccountName)')"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/storage.objectAdmin"
```

Check the rule is still there — a bucket without it is a growing pile of other
people's bank statements:

```bash
gcloud storage buckets describe "gs://ledger-jobs-expense-tracker-482807" \
  --format='yaml(lifecycle,iamConfiguration)'
```

### Deploy variables

```
GS_BUCKET_NAME=ledger-jobs-expense-tracker-482807
MAX_CSV_UPLOAD_BYTES=2097152
```

`MAX_CSV_UPLOAD_BYTES` is 2 MB (E12 decision 1) and is enforced three times:
at the ASGI layer (`core/asgi_body_limit.py`), at the Django middleware layer
(`core/middleware.py`, which applies the CSV ceiling to anything under
`/import/`), and while streaming the file into storage
(`finances/services/import_storage.py`) — the only one of the three that a
chunked request declaring no `Content-Length` cannot walk past.

**Do not move the importer off the `/import/` URL prefix.**
`core.middleware.IMPORT_PATH_PREFIX` is a literal, so a renamed path silently
gets the 60 MB chat ceiling instead of the 2 MB one.

### Why downloads go through the app and not through a GCS signed URL

`core/downloads.py` mints a Django `TimestampSigner` token; `ExportDownloadView`
verifies the signature, the age *and* `request.household` before streaming.
A raw GCS signed URL would need either a key file on disk or a `SignBlob` call
per download, and — the real objection — it cannot check which household is
asking. A complete financial history is not protected by URL secrecy alone.

Link lifetime is `EXPORT_URL_MAX_AGE_SECONDS` (1 hour). The `ExportJob` row
outlives the file deliberately, so a user whose 8-day-old export 404s learns it
expired rather than that it never existed.

### Investigating a stuck import

A job is stuck when it is `running` and `started_at` is older than
`IMPORT_STUCK_AFTER_MINUTES` (15). That means the instance running it is gone —
Cloud Run recycled it, or the task outran the request timeout. Nothing will ever
move the row again.

```bash
# What the user sees is already honest: the status page reads `is_stuck` live.
# This makes the STORED state honest, for the history page and for queries.
gcloud run jobs execute ... # or, locally:
POSTGRES_PORT=5433 uv run python src/backend/manage.py sweep_stuck_import_jobs
```

Expected output: `Importações interrompidas marcadas como falha: N`.

Schedule it next to the keepalive ping (see *Cold starts: the keepalive job*).
Once every 15 minutes is plenty.

To see what a job actually did, without the UI:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from finances.models import ImportJob
job = ImportJob.objects.get(pk='<uuid>')
print(job.status, job.created_count, job.skipped_count, job.error_count)
print(job.storage_key)
for failure in job.failures[:10]:
    print(failure)
"
```

The `TaskRun` that carried it is findable by payload:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import TaskRun
print(list(TaskRun.objects.filter(name='finances.run_import',
      payload__job_id='<uuid>').values('status','attempts','last_error','request_id')))
"
```

`request_id` joins straight to Cloud Logging — see *Start from the request ID*.

### A bound worth knowing before it is an incident

`core/tasks/views.py` holds `select_for_update` on the `TaskRun` row for the
whole handler, so one import holds one row lock for its whole run. At the 2 MB
cap that is bounded and well inside Cloud Run's 300 s request timeout. If a
real user ever hits the timeout, the fix is chunked execution across several
tasks — deliberately not built in E12, because at this scale it would be
complexity with no evidence behind it.

### `finances.run_import` retries once, on purpose

`max_attempts=1`, against the registry's default of 5. A half-finished import
has already written some of the household's rows, and a blind retry writes the
rest of them twice. The durable record is the `ImportJob`; the guard is
`ImportJob.is_finished`; a genuinely failed import is retried by the user
uploading again, which re-runs duplicate detection first. `finances.build_export`
retries three times because it is a pure read plus one write.
````

- [ ] **Step 6: Add the README and AGENTS pointers**

In `README.md`'s quickstart, one line:

```markdown
Import and export jobs (bucket, retention, stuck-job investigation) are documented in
[`docs/runbook.md` → *Import and export jobs (E12)*](docs/runbook.md).
```

Add the same line to `AGENTS.md` if that file exists.

- [ ] **Step 7: Update the backlog**

In `docs/backlog/E12-durable-import-export-jobs.md`, set `status: done` in the frontmatter and tick the Observable assertions that now hold, naming the test for each:

```markdown
- [x] A test proves an import survives the wizard's steps being served by different processes — the B4 fix — `test_import_job_wizard.py::TestTheWizardNeedsNoSession::test_each_step_can_be_served_by_a_different_session`
- [x] A test proves an oversized upload is rejected before storage — `test_import_storage.py::test_a_refused_upload_leaves_nothing_in_storage`
- [x] A test proves a row raising `IntegrityError` does not abort the remaining rows — the H5 fix — `test_import_runner.py::TestOneBadRowDoesNotPoisonTheRest`
- [x] A test proves re-running the same import creates no duplicates — `test_import_runner.py::TestIdempotence`
- [x] Failed rows are individually reported with reasons — `test_import_progress.py::TestTheFailuresReport` (capped at 1000, with an exact count beyond it)
- [x] An export round-trips — `test_export_roundtrip.py::TestRoundTrip::test_the_ledger_total_matches`
- [x] Export URLs expire, verified by test — `test_downloads.py::test_a_token_past_its_window_is_refused` and `test_export_views.py::TestDownloading::test_an_expired_link_is_a_404`
- [x] Local development works without GCP credentials — `test_storage.py::test_no_bucket_falls_back_to_the_filesystem`
- [x] `docs/runbook.md` documents the bucket, its retention rule, and how to investigate a stuck job
```

Also record the four Open questions as answered, quoting this plan's decisions table.

In `docs/backlog/INDEX.md`:
- §4 table: E12 → `**done** (2026-08-16)` with a new footnote marker; E13 → `ready` (its only unmet dependency was E12; E18 is already `ready`, so check whether E13's `depends_on: [E12, E18]` is now satisfied — if E18 is still open, E13 stays `blocked` and say so).
- The R3 gate paragraph: three of four conditions now hold; only E13's data-subject request remains.
- A closing footnote in the same voice as the others, covering: what shipped, the BOM defect the round trip found in the *importer* (not the exporter), the `select_for_update` bound, and anything that did not land.

- [ ] **Step 8: Commit the documentation**

```bash
git add docs README.md AGENTS.md
git commit -m "docs(E12): the bucket, its retention rule, and how to investigate a stuck job"
```

- [ ] **Step 9: Request a review, then finish the branch**

Run `superpowers:requesting-code-review` — a separate pass, never self-approval in this context (project convention, and the epic's own skill pipeline step 5).

Then `superpowers:verification-before-completion` with the DoD output from Step 1 pasted verbatim, and `superpowers:finishing-a-development-branch` for the merge decision.

**Feed the reviewer these four questions specifically**, because they are the places this plan chose one defensible option over another:

1. `ImportBatch` → `ImportJob` is a `RenameModel` against a table holding production rows. Is the migration genuinely reversible, and was `RenameModel` (not `DeleteModel` + `CreateModel`) actually generated?
2. `failures` is capped at 1000 with an exact overflow count. Does "individually reported with reasons" survive that cap?
3. `run_import` is `max_attempts=1`. Is refusing to retry a half-written import the right trade against E10's dead-letter story?
4. The export ships chat history in `ledger.json`. Is E13 content to inherit that, or should it be opt-in?

---

## Self-Review

Run against the spec after the plan was complete.

**1. Spec coverage** — every story and every DoD assertion maps to a task:

| Spec item | Task |
|---|---|
| S12-1 durable job state | 2 (model), 3 (wizard), 7 (history) |
| S12-2 object storage + size cap + lifecycle + local fallback + signed URLs | 1 (storage, cap, fallback), 6 (signing), 10 (lifecycle, non-public bucket) |
| S12-3 task + savepoints + reasons + accurate counts + failure report + idempotence + E03 query cost | 4 (savepoints, counts, reasons, idempotence, query cost), 5 (task), 6 (report) |
| S12-4 export: task, same bucket, signed expiring URL, re-importable CSV + JSON, model coverage, chat decision recorded | 8 (builder, round trip, coverage, chat), 9 (task, bucket, link) |
| S12-5 progress, pt-BR failure, no forever-running job | 5 |
| DoD: cross-instance test | 3 |
| DoD: oversized rejected before storage | 1 |
| DoD: `IntegrityError` does not abort | 4 |
| DoD: re-run creates no duplicates | 4 |
| DoD: failed rows individually reported | 6 |
| DoD: export round-trips, totals match | 8 |
| DoD: export URLs expire | 6, 9 |
| DoD: local dev works without GCP | 1 |
| DoD: runbook documents bucket, retention, stuck job | 10 |
| Open questions 1–4 | Decisions table above |

**Two gaps found and closed while reviewing.** The spec's *"the bucket is not public"* had no task — it is now Task 10 Step 3's `--public-access-prevention` and `--uniform-bucket-level-access`, verified by `buckets describe`. And S12-3's *"the per-row query overhead fixed in E03 S03-4 is preserved"* was implicit; it is now an explicit assertion in Task 4 (`TestQueryCost`) *and* a blocking check in Task 3 Step 9.

**One spec assumption corrected rather than followed.** The spec's evidence table describes state kept in the session and a row set serialised into it. This plan does not move that row set into the `ImportJob` — it stops storing it at all, re-deriving from the stored file plus the mapping. Doing what the spec's wording implies would have replaced a multi-megabyte session write with a multi-megabyte `JSONField` write on a pooled Supabase connection, which is the same defect wearing a different hat.

**2. Placeholder scan** — clean. Every code step carries the code. No "add appropriate error handling", no "similar to Task N", no "write tests for the above". The only forward references are the two explicitly staged ones: Task 5 creates an `ImportFailuresView` placeholder that Task 6 fills, and Task 5's `_progress.html` reverses `finances:import_failures`, which is why the URL is registered in Task 5 rather than Task 6. Both are called out in the steps that create them.

**3. Type consistency** — checked across tasks:
- `job_storage()` (Task 1) is used unchanged in Tasks 4, 8, 9.
- `store_upload(uploaded_file, household_id) -> str` (Task 1) — call sites in Tasks 3, 4, 8 all pass `household.id`.
- `rows_for(job, *, mark_duplicates=True)` (Task 3) — Task 4 calls it with `mark_duplicates=False`; the keyword exists.
- `sign_download(kind, object_id)` / `unsign_download(token, *, kind, max_age=None)` (Task 6) — `ExportJob.download_token` (Task 9) and `ExportDownloadView` (Task 9) both match.
- `ImportJob.record_failure(line, reason)` (Task 2) — the runner (Task 4) calls exactly that; `MAX_RECORDED_FAILURES` is read in Task 2's test and enforced in Task 2's method.
- `get_job(request, job_id)` (Task 3) is used by every importer view added in Tasks 5, 6, 7.
- URL names are consistent throughout: `import_upload`, `import_map`, `import_preview`, `import_execute`, `import_status`, `import_failures`, `import_history`, `export_page`, `export_request`, `export_download`.
- Status values are string literals in templates (`"done"`, `"failed"`, `"running"`) and enum members in Python (`ImportStatus.DONE`); `TextChoices` compares equal to its value, so both are correct.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-E12-durable-import-export-jobs.md`.

Before Task 1, create the worktree — global constraint 2, and the epic's own skill pipeline step 2:

```
superpowers:using-git-worktrees   →   branch e12-durable-import-export
```

Then two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
**2. Inline Execution** — `superpowers:executing-plans`, batch execution with checkpoints.
