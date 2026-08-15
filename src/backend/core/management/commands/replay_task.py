"""Re-run a task that gave up.

Cloud Tasks has no dead-letter queue and no replay: once it has exhausted a
task, the task is gone. The record that survives is the TaskRun row, so
replaying is enqueuing the same work again.

Deliberately a NEW run rather than a reset of the old one: the failure is
evidence, and an operator debugging "why did this rule never get indexed"
needs the attempt count and the last error to still be there afterwards.
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.models import TaskRun, TaskStatus
from core.tasks import enqueue


class Command(BaseCommand):
    help = "Re-enqueue a dead-lettered task by its TaskRun id."

    def add_arguments(self, parser):
        parser.add_argument("task_run_id", help="The TaskRun UUID, from admin or the logs.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replay even when the task has not been dead-lettered.",
        )

    def handle(self, *args, **options):
        raw = options["task_run_id"]
        try:
            task_run = TaskRun.objects.get(pk=raw)
        except (TaskRun.DoesNotExist, ValidationError, ValueError):
            raise CommandError(f"No TaskRun {raw}.") from None

        if task_run.status != TaskStatus.DEAD and not options["force"]:
            raise CommandError(
                f"TaskRun {task_run.pk} is '{task_run.status}', not dead-lettered. "
                "Pass --force to replay it anyway."
            )

        # A key of its own, because the original's is taken and its attempt
        # budget is spent. Including the attempt count means replaying the same
        # failure twice is deduplicated (a double-typed command), while a task
        # that failed again later replays as a genuinely new run.
        replay = enqueue(
            task_run.name,
            task_run.payload,
            idempotency_key=f"replay:{task_run.pk}:{task_run.attempts}",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Re-enqueued '{task_run.name}' from {task_run.pk} as TaskRun {replay.pk} "
                f"(status: {replay.status})."
            )
        )
