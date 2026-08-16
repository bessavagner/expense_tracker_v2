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
# is ``import_runner._claim``, and a genuinely failed import is retried by the
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
        job.error_message = "Não foi possível gerar a exportação. Tente de novo em alguns minutos."
        job.save(update_fields=["status", "error_message", "updated_at"])
        raise

    job.storage_key = key
    job.size_bytes = len(archive)
    job.status = ExportStatus.DONE
    job.completed_at = timezone.now()
    job.save(update_fields=["storage_key", "size_bytes", "status", "completed_at", "updated_at"])
