"""Deleting what we said we would delete, on the day we said we would.

Retention is the half of LGPD that has no user interface: nobody clicks
anything, and if this job silently stops running there is no error and no
complaint — just a database quietly keeping a year of somebody's conversations
after a document promised ninety days.

Two properties are therefore load-bearing:

  * every period comes from ``core.privacy.INVENTORY``, which the notice also
    renders, so the promise and the enforcement cannot disagree;
  * every run leaves a ``TaskRun`` row, so "did it run?" has an answer that is
    not "grep the logs".

The handler is registered from ``CoreConfig.ready`` rather than from a
``core/tasks.py`` module, because ``core.tasks`` is already a package here and
the two names cannot coexist.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from core.privacy.inventory import model_for, purgeable
from core.tasks import task_handler

logger = logging.getLogger(__name__)

PURGE_EXPIRED_DATA = "core.purge_expired_data"

#: Deleted per statement. One household's ninety-first day is a handful of
#: rows, so this only matters the first time the job runs against a database
#: that has never been swept — which is exactly when an unbounded DELETE would
#: hold a lock for the length of a Cloud Run request timeout.
BATCH = 5000


def purge_expired(as_of=None) -> dict[str, int]:
    """Delete everything past its retention period. Returns per-model counts.

    ``as_of`` is injected rather than read, so a test can pin the day and an
    operator can ask "what would tomorrow's run delete?" without touching a
    clock. Same rule as ``docs/testing-conventions.md`` §1.
    """
    now = as_of or timezone.now()
    counts: dict[str, int] = {}

    for record in purgeable():
        model = model_for(record)
        cutoff = now - timedelta(days=record.retention_days)
        # `_base_manager`, not `objects`: the household-scoped manager would
        # return none() outside a request, and a purge that silently deletes
        # nothing is worse than one that fails loudly.
        due = model._base_manager.filter(
            **{f"{record.timestamp_field}__lt": cutoff}, **record.purge_filter
        )
        deleted = _delete_in_batches(model, due)
        if deleted:
            counts[record.label] = deleted

    logger.info("Retention sweep for %s deleted: %s", now.date(), counts or "nothing")
    return counts


def count_expired(as_of=None) -> dict[str, int]:
    """What a run right now *would* delete. Used by ``--dry-run``.

    Counts only the rows each record names — not what cascades off them — so
    the number is the one an operator can check against the table itself.
    """
    now = as_of or timezone.now()
    counts: dict[str, int] = {}
    for record in purgeable():
        model = model_for(record)
        cutoff = now - timedelta(days=record.retention_days)
        due = model._base_manager.filter(
            **{f"{record.timestamp_field}__lt": cutoff}, **record.purge_filter
        ).count()
        if due:
            counts[record.label] = due
    return counts


def _delete_in_batches(model, queryset) -> int:
    """Delete by primary-key slices, so no single statement is unbounded.

    A queryset slice cannot be deleted directly in Django, which is why this
    collects ids first.
    """
    total = 0
    while True:
        ids = list(queryset.values_list("pk", flat=True)[:BATCH])
        if not ids:
            return total
        removed, _ = model._base_manager.filter(pk__in=ids).delete()
        total += len(ids)
        if len(ids) < BATCH:
            return total


@task_handler(PURGE_EXPIRED_DATA, max_attempts=3)
def purge_expired_task(payload: dict) -> None:
    """The scheduled sweep.

    ``payload["as_of"]`` is a date string rather than "now" so that the task's
    content hash differs per day — which is what makes ``enqueue`` idempotent
    per day rather than forever (plan decision D8).

    Raises on failure, which is the documented signal that earns a retry
    (`assistant/tasks.py:38-42`). Three attempts, because the work is
    idempotent: a partial sweep re-run deletes what is left and nothing twice.
    """
    # `datetime.UTC`, not `timezone.utc` — Django removed the latter in 5.0.
    from datetime import UTC, datetime

    raw = payload.get("as_of")
    as_of = datetime.fromisoformat(raw).replace(tzinfo=UTC) if raw else timezone.now()
    purge_expired(as_of=as_of)
