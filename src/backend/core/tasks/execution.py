"""Run one TaskRun and record what happened.

Shared by the eager backend and the HTTP dispatch view on purpose: "what
happens on the third failure" must not be able to differ between a laptop and
production. That divergence is how a retry bug survives until it is an
incident.
"""

import logging

import sentry_sdk

from core.models import TaskRun, TaskStatus
from core.tasks.registry import get_task

logger = logging.getLogger(__name__)

# Long enough to identify the failure, short enough that a pathological
# exception message cannot bloat the row.
MAX_ERROR_CHARS = 2000

# Both mean "this row is finished". A redelivery of either must be a no-op:
# re-running a DONE row would duplicate its effect, and re-running a DEAD one
# would spend attempts past a ceiling the application has already recorded
# itself as giving up at.
TERMINAL_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.DEAD})


def run_task_run(task_run: TaskRun) -> str:
    """Execute ``task_run`` once. Returns its status afterwards. Never raises.

    Returning rather than raising is what lets the caller choose the HTTP
    status without re-deriving the decision: PENDING means "retry me", DONE and
    DEAD both mean "stop".
    """
    if task_run.status in TERMINAL_STATUSES:
        # An at-least-once redelivery of work that already finished — either
        # successfully, or by exhausting its attempts. Normal, not an error,
        # and the case a second run must not duplicate.
        return task_run.status

    definition = get_task(task_run.name)
    task_run.attempts += 1
    try:
        definition.handler(task_run.payload)
    except Exception as exc:
        task_run.last_error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        if task_run.attempts >= task_run.max_attempts:
            task_run.status = TaskStatus.DEAD
            # The one report that matters in this module: silently dropping a
            # user's work is the exact failure this epic exists to end.
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Task '%s' dead-lettered after %d attempts (task_run=%s): %s",
                task_run.name,
                task_run.attempts,
                task_run.id,
                task_run.last_error,
            )
        else:
            task_run.status = TaskStatus.PENDING
            logger.warning(
                "Task '%s' attempt %d/%d failed (task_run=%s): %s",
                task_run.name,
                task_run.attempts,
                task_run.max_attempts,
                task_run.id,
                task_run.last_error,
            )
    else:
        task_run.status = TaskStatus.DONE
        task_run.last_error = ""
    task_run.save(update_fields=["attempts", "status", "last_error", "updated_at"])
    return task_run.status
