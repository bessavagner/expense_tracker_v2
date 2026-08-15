"""Where an enqueued task actually goes.

Two backends, one contract. ``EagerBackend`` runs the handler in-process the
moment it is enqueued; it is what makes ``CLOUD_TASKS_ENABLED=0`` a complete
local setup rather than a degraded one — no emulator, no GCP credentials — and
it keeps the same bookkeeping as production because both backends go through
``run_task_run``.

The trade it makes is honest and worth stating: eagerly-run work happens
*inside* the request that scheduled it, so locally there is no instance relief
and no real retry. What is identical is the code path, the attempt accounting
and the dead-letter decision, which are the parts that are hard to get right.
"""

from django.conf import settings

from core.models import TaskRun
from core.tasks.execution import run_task_run


class EagerBackend:
    """Run it now, in this process."""

    def dispatch(self, task_run: TaskRun) -> None:
        run_task_run(task_run)


def backend_for_settings():
    """Pick a backend from configuration.

    The Cloud Tasks backend is imported lazily so that ``google-cloud-tasks``
    is never needed to import this module — a developer with no GCP setup runs
    the whole application without it.
    """
    if settings.CLOUD_TASKS_ENABLED:
        from core.tasks.cloud import CloudTasksBackend

        return CloudTasksBackend()
    return EagerBackend()
