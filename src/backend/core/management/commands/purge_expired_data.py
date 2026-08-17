"""Delete everything past its retention period (E13 S13-3).

Named `purge_expired_data`, deliberately not `retention_*`: this repo already
has `retention_report`, which is about E14's *cohort* retention. Two meanings of
"retention" one tab-completion apart is a foot-gun.

Runs as a Cloud Run Job on a daily Cloud Scheduler trigger — see
docs/runbook.md, "Retenção de dados (E13)". It enqueues rather than sweeping
inline so the run leaves a `TaskRun` row: an operator asking "did last night's
purge happen?" gets a row with a status instead of a log search.
"""

from datetime import UTC, date, datetime, time

from django.core.management.base import BaseCommand, CommandError

from core.privacy.retention import PURGE_EXPIRED_DATA, count_expired


class Command(BaseCommand):
    help = "Apaga dados cujo prazo de retenção venceu."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só mostra o que seria apagado. Não apaga nada e não enfileira nada.",
        )
        parser.add_argument(
            "--as-of",
            type=str,
            default=None,
            help="Faz as contas como se hoje fosse esta data (AAAA-MM-DD).",
        )

    def handle(self, *args, **options):
        from django.utils import timezone

        if options["as_of"]:
            try:
                as_of = date.fromisoformat(options["as_of"])
            except ValueError as exc:
                raise CommandError("--as-of precisa ser AAAA-MM-DD.") from exc
        else:
            as_of = timezone.localdate()

        if options["dry_run"]:
            # `datetime.UTC`, not `timezone.utc` — Django removed the latter in
            # 5.0. Midnight, so `--as-of` means "at the start of that day".
            moment = datetime.combine(as_of, time.min, tzinfo=UTC)
            counts = count_expired(as_of=moment)
            self.stdout.write(f"== Venceriam em {as_of:%d/%m/%Y} ==")
            if not counts:
                self.stdout.write("Nada a apagar.")
                return
            for label, total in sorted(counts.items()):
                self.stdout.write(f"{label}: {total}")
            self.stdout.write("")
            self.stdout.write("Nada foi apagado — isto é um --dry-run.")
            return

        # Imported here so `--dry-run` never touches the queue.
        from core.tasks import enqueue

        task_run = enqueue(PURGE_EXPIRED_DATA, {"as_of": as_of.isoformat()})
        self.stdout.write(f"Varredura de {as_of:%d/%m/%Y} enfileirada: {task_run.pk}")
        self.stdout.write(f"Situação: {task_run.get_status_display()}")
