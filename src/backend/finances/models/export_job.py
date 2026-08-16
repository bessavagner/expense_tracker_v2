import uuid

from django.db import models

from accounts.models import AuthoredHouseholdModel


class ExportStatus(models.TextChoices):
    PENDING = "pending", "Na fila"
    RUNNING = "running", "Gerando"
    DONE = "done", "Pronta"
    FAILED = "failed", "Falhou"


class ExportJob(AuthoredHouseholdModel):
    """One requested export of a household's data.

    A row rather than a synchronous download for the same reason the import is
    a job: building it walks every table the household owns, and a request that
    holds a Cloud Run instance for the duration is a request that times out on
    the household that most needs the export.

    The archive itself lives in object storage under a 7-day lifecycle rule
    (E12 decision 2). This row is what survives it -- so a user who sees "Pronta,
    gerada em 3 de agosto" and gets a 404 learns that the file expired, rather
    than that the export never happened.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20, choices=ExportStatus.choices, default=ExportStatus.PENDING
    )
    storage_key = models.CharField(max_length=500, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "exportação"
        verbose_name_plural = "exportações"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["household", "-created_at"], name="exportjob_hh_recent_idx"),
        ]

    def __str__(self):
        return f"Exportação {self.id} ({self.get_status_display()})"

    @property
    def download_token(self) -> str:
        """A fresh, expiring token for this archive.

        A property rather than a stored column, deliberately: minting on read
        means every link the page renders starts its clock when the page is
        rendered, and there is no stale token in the database to leak.
        """
        from core.downloads import sign_download

        return sign_download("export", self.id)
