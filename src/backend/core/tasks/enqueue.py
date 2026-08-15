"""The single way application code schedules deferred work.

One function, so that the payload ceiling, the idempotency key, the
request-ID capture and the backend choice are decided in exactly one place. A
second enqueue path is how one of those four silently stops applying.
"""

import hashlib
import json
import logging

from django.conf import settings

from core.models import TaskRun
from core.request_id import get_request_id
from core.tasks.backends import backend_for_settings
from core.tasks.registry import get_task

logger = logging.getLogger(__name__)


class PayloadTooLarge(ValueError):
    """The encoded payload exceeds what a Cloud Tasks task can carry."""


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()


def default_idempotency_key(name: str, payload: dict) -> str:
    """A stable key for "this exact work".

    Content-addressed deliberately: enqueuing identical work twice — a
    double-tapped button, a retried request — must produce one row, and a
    caller should not have to remember to ask for that.

    ``sort_keys`` matters. Two dicts that differ only in insertion order are
    the same work, and hashing their raw serialisations would say otherwise.
    """
    return f"{name}:{hashlib.sha256(_encode(payload)).hexdigest()}"


def enqueue(name: str, payload: dict, *, idempotency_key: str | None = None) -> TaskRun:
    """Schedule ``name`` to run with ``payload``. Returns the durable record.

    ``idempotency_key`` overrides the content hash when the caller has a better
    notion of sameness than "these exact bytes" — for example "this rule, at
    this value", which should re-run when the value changes and not otherwise.
    """
    definition = get_task(name)  # raises UnknownTask on a typo, here, now

    body = _encode(payload)
    if len(body) > settings.TASK_PAYLOAD_MAX_BYTES:
        raise PayloadTooLarge(
            f"Task '{name}' payload is {len(body)} bytes; the ceiling is "
            f"{settings.TASK_PAYLOAD_MAX_BYTES}. Cloud Tasks caps a task at 1 MiB "
            "and that is a fixed system limit — put the bytes in object storage "
            "and pass a reference instead (E12)."
        )

    key = idempotency_key or default_idempotency_key(name, payload)
    task_run, created = TaskRun.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "name": name,
            "payload": payload,
            "max_attempts": definition.max_attempts,
            # Captured at enqueue time rather than read at dispatch time: by the
            # time the task runs, the request that wanted it is long gone.
            "request_id": get_request_id() or "",
        },
    )
    if not created:
        logger.info("Task '%s' already enqueued as %s; not scheduling again.", name, task_run.pk)
        return task_run

    backend_for_settings().dispatch(task_run)
    return task_run
