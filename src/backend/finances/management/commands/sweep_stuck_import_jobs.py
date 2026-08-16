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

from finances.models import IN_FLIGHT_STATUSES, ImportJob, ImportStatus


class Command(BaseCommand):
    help = "Mark import jobs that died mid-execution as failed."

    def handle(self, *args, **options):
        swept = 0
        # Not a bulk update: is_stuck reads a setting and a timestamp per row,
        # and the number of RUNNING jobs at any moment is single digits.
        for job in ImportJob.objects.filter(status__in=IN_FLIGHT_STATUSES):
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
