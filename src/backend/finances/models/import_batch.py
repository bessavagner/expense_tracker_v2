import uuid

from django.conf import settings
from django.db import models

from accounts.models import AuthoredHouseholdModel


class ImportBatch(AuthoredHouseholdModel):
    """One prepared CSV import, and the record that it has already run.

    Exists to make ``ImportExecuteView`` idempotent. The importer's steps are
    plain HTML forms, so nothing stops a browser from sending the execute POST
    twice — a double-tap on a slow import used to replay the whole file (a
    4000-row CSV produced 8000 rows while the page reported "Importados 4000").
    The session cannot arbitrate that: Django writes it at response time, so a
    second request that arrives mid-import still reads the rows as unimported.

    A committed database row can arbitrate it. The batch is created when the
    column mapping is confirmed, and the execute step locks it with
    ``select_for_update`` before touching anything. The loser of the race waits
    for the winner to commit, then sees ``executed_at`` set and renders the
    winner's counts instead of importing again — so the user still learns how
    many rows landed, which is what they were waiting to find out.

    Deliberately not a ``UniqueConstraint`` on ``Entry``: production holds two
    genuine R$ 20 fuel purchases on the same day with the same description, and
    a natural-key constraint would reject the family's real data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="import_batches",
        # E04 phase 4, beat one: nullable so the suite converts in one pass.
        null=True,
        blank=True,
    )
    import_type = models.CharField(max_length=20, default="regular")
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Quando a importação rodou. Nulo = preparada, ainda não executada.",
    )
    created_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "lote de importação"
        verbose_name_plural = "lotes de importação"
        ordering = ["-created_at"]

    def __str__(self):
        state = "executado" if self.executed_at else "preparado"
        return f"Importação {self.id} ({state})"
