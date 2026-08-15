"""The one HTTP door deferred work comes back through.

Cloud Tasks delivers a task by POSTing to a URL, so every handler shares this
view and the name in the path selects which. The response code is the whole
protocol: 5xx means "retry me", 2xx means "stop".

That is why a dead-lettered task answers 200. The application owns the attempt
ceiling — Cloud Tasks has no dead-letter queue, so if the queue kept retrying
past our own limit it would spend money re-running work we have already
recorded as abandoned, and the TaskRun row would say DEAD while the queue said
otherwise.
"""

import json
import logging
import uuid

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import TaskRun, TaskStatus
from core.tasks.auth import rejection_reason
from core.tasks.execution import run_task_run
from core.tasks.registry import UnknownTask, get_task

logger = logging.getLogger(__name__)


def _task_run_id(request) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(json.loads(request.body)["task_run_id"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None


# CSRF-exempt because Cloud Tasks is not a browser and carries no cookie or
# token. The OIDC check below is the authentication, and it is strictly
# stronger than CSRF for this caller.
@csrf_exempt
@require_POST
def task_dispatch_view(request, name):
    reason = rejection_reason(request)
    if reason is not None:
        # Logged, not returned: naming the failed check would tell an attacker
        # exactly what to fix.
        logger.warning("Refused /tasks/%s/: %s", name, reason)
        return JsonResponse({"error": "forbidden"}, status=403)

    try:
        get_task(name)
    except UnknownTask:
        logger.error("Dispatch for unregistered task '%s'.", name)
        return JsonResponse({"error": "unknown task"}, status=404)

    task_run_id = _task_run_id(request)
    if task_run_id is None:
        return JsonResponse({"error": "invalid body"}, status=400)

    # Checked before the lock so that "no such row" and "someone else holds the
    # row" stay distinguishable — they need opposite answers.
    if not TaskRun.objects.filter(pk=task_run_id, name=name).exists():
        logger.error("Dispatch for unknown task_run %s (task '%s').", task_run_id, name)
        return JsonResponse({"error": "unknown task_run"}, status=404)

    with transaction.atomic():
        task_run = (
            TaskRun.objects.select_for_update(skip_locked=True)
            .filter(pk=task_run_id, name=name)
            .first()
        )
        if task_run is None:
            # Another dispatch of the same task holds the row. At-least-once
            # delivery makes this normal rather than exceptional, and it is
            # precisely the case a second run must not duplicate. 200, because
            # the work is already being done — retrying would just race again.
            logger.info("Concurrent delivery of task_run %s ignored.", task_run_id)
            return HttpResponse(status=200)
        # The row lock is held for the duration of the handler. That bounds how
        # long a handler may run: it must be short. Long, media-shaped work
        # belongs behind object storage and its own job state (E12), which is
        # the other reason this epic does not move it.
        status = run_task_run(task_run)

    if status == TaskStatus.PENDING:
        return JsonResponse({"status": status}, status=500)
    return JsonResponse({"status": status}, status=200)
