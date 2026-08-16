import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import AuthoredHouseholdModel


class ImportStatus(models.TextChoices):
    UPLOADED = "uploaded", "Enviado"
    MAPPED = "mapped", "Mapeado"
    RUNNING = "running", "Importando"
    DONE = "done", "Concluído"
    FAILED = "failed", "Falhou"


class ImportJob(AuthoredHouseholdModel):
    """One CSV import: where its file is, what it was told to do, and what it did.

    Was ``ImportBatch``, whose job was narrower -- it existed only so that
    ``ImportExecuteView`` could lock a committed row and refuse a double-tapped
    POST (a 4000-row CSV once produced 8000 rows while the page reported
    "Importados 4000"). That property survives here unchanged, and it is now the
    smaller half of what this row does.

    The larger half is E12's B4 fix. The wizard used to keep the uploaded file's
    *local path* in the session and the parsed row set in the session body. On a
    single warm instance that works; on any second instance the path names a
    file that does not exist, and the row set was a multi-megabyte write into a
    database-backed session on every step. Both are gone: the file is in object
    storage under ``storage_key``, and the rows are re-derived from that file
    plus ``column_mapping`` whenever they are needed. Nothing about a job lives
    in a session, so a job survives a restart and any step can be served by any
    instance.

    ``failures`` is capped rather than unbounded, and ``failures_truncated``
    keeps the count exact past the cap. A 2 MB CSV is around 20 000 rows; a file
    where every row fails would otherwise write megabytes of JSON into one row
    on a pooled connection.
    """

    MAX_RECORDED_FAILURES = 1000

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_type = models.CharField(max_length=20, default="regular")

    storage_key = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Chave do arquivo no armazenamento de objetos.",
    )
    original_filename = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=ImportStatus.choices,
        default=ImportStatus.UPLOADED,
    )
    column_mapping = models.JSONField(default=dict, blank=True)
    skip_lines = models.JSONField(default=list, blank=True)
    category_resolutions = models.JSONField(default=dict, blank=True)
    pm_resolutions = models.JSONField(default=dict, blank=True)

    total_rows = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    failures = models.JSONField(default=list, blank=True)
    failures_truncated = models.PositiveIntegerField(default=0)
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Em pt-BR: o que deu errado e o que fazer. Mostrado ao usuário.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Quando a importação terminou. Nulo = preparada ou em execução.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "importação"
        verbose_name_plural = "importações"
        ordering = ["-created_at"]
        indexes = [
            # The history page, and the stuck-job sweep.
            models.Index(fields=["household", "-created_at"], name="importjob_hh_recent_idx"),
            models.Index(fields=["status", "started_at"], name="importjob_status_started_idx"),
        ]

    def __str__(self):
        return f"Importação {self.id} ({self.get_status_display()})"

    @property
    def is_finished(self) -> bool:
        return self.status in {ImportStatus.DONE, ImportStatus.FAILED}

    @property
    def is_stuck(self) -> bool:
        """RUNNING for longer than any real import takes.

        The instance that was running it is gone -- Cloud Run recycled it, or
        the task exhausted the request timeout. Nothing will ever move this row
        again, so leaving it RUNNING shows the user a spinner that never stops.
        """
        if self.status != ImportStatus.RUNNING or self.started_at is None:
            return False
        cutoff = timezone.now() - timedelta(minutes=settings.IMPORT_STUCK_AFTER_MINUTES)
        return self.started_at < cutoff

    @property
    def progress_percent(self) -> int:
        """Floor, not round. 3 of 8 rows reads as 37%, never 38%.

        Rounding up would let the bar reach 100% while rows are still being
        written, which is precisely the lie the progress bar exists to stop
        telling. (``round`` would also be half-to-even here, so 37.5 -> 38.)
        """
        if not self.total_rows:
            return 0
        return min(100, int(100 * self.processed_count / self.total_rows))

    def record_failure(self, line: int, reason: str) -> None:
        """Remember why one row did not land.

        Mutates in memory only; the caller decides when to write, because the
        runner batches its saves rather than paying a round trip per bad row.
        """
        if len(self.failures) < self.MAX_RECORDED_FAILURES:
            self.failures.append({"line": line, "reason": reason})
        else:
            self.failures_truncated += 1
