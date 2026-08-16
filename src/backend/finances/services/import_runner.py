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
    if not _claim(job):
        logger.info(
            "Import job %s is already running or finished (%s); not running again.",
            job.pk,
            job.status,
        )
        return

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


def _claim(job) -> bool:
    """Move the job to RUNNING, but only if nobody else already has.

    One conditional UPDATE, so the check and the act are the same statement.
    ``if job.is_finished: ...`` then ``job.save()`` is a check-then-act race: two
    requests -- a double-tapped button, a redelivered task, two Cloud Run
    instances -- both read "not finished" and both import the file. That is the
    exact defect the old ``select_for_update`` on ImportBatch existed to
    prevent, and it must survive the move off the session.

    Better than a row lock, too: this holds no lock for the run's duration and
    it works whoever the caller is -- the view, the task handler, a management
    command, a retry.
    """
    now = timezone.now()
    claimed = (
        type(job)
        .objects.filter(pk=job.pk)
        .exclude(status__in=[ImportStatus.RUNNING, ImportStatus.DONE, ImportStatus.FAILED])
        .update(
            status=ImportStatus.RUNNING,
            started_at=now,
            processed_count=0,
            created_count=0,
            skipped_count=0,
            error_count=0,
            failures=[],
            failures_truncated=0,
            error_message="",
            # auto_now does not fire for .update(), so it is set by hand.
            updated_at=now,
        )
    )
    if not claimed:
        job.refresh_from_db()
        return False
    job.refresh_from_db()
    return True


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
                    "processed_count",
                    "created_count",
                    "skipped_count",
                    "error_count",
                    "failures",
                    "failures_truncated",
                    "updated_at",
                ]
            )

    report_import_failures(job.error_count, failure_kinds)

    job.status = ImportStatus.DONE
    job.executed_at = timezone.now()
    job.save(
        update_fields=[
            "status",
            "executed_at",
            "processed_count",
            "created_count",
            "skipped_count",
            "error_count",
            "failures",
            "failures_truncated",
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
        row.get("category", ""),
        category_map,
        job.category_resolutions,
        Category.objects.for_household(household),
    )
    if category is None:
        return (f"Categoria '{row.get('category', '')}' não encontrada.", "UnknownCategory")

    payment_method = _resolve(
        row.get("payment_method", ""),
        payment_map,
        job.pm_resolutions,
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
