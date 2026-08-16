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
