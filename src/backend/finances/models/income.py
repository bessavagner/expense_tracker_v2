import uuid

from django.conf import settings
from django.db import models

from accounts.models import AuthoredHouseholdModel


class Income(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="incomes",
        # E04 phase 4, beat one: nullable so the suite converts in one pass.
        null=True,
        blank=True,
        # Redundant with income_user_month_idx, whose leading column is user.
        # See the longer note on Entry.user for why the extra index is a cost
        # rather than a spare tyre.
        db_index=False,
    )
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    month = models.DateField(help_text="Primeiro dia do mês aplicável")
    is_recurring = models.BooleanField(default=False)
    recurrence_start = models.DateField(null=True, blank=True)
    recurrence_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "renda"
        verbose_name_plural = "rendas"
        ordering = ["-month", "name"]
        indexes = [
            models.Index(fields=["user", "month"], name="income_user_month_idx"),
            models.Index(fields=["household", "month"], name="income_hh_month_idx"),
        ]

    def __str__(self):
        return f"{self.name} — {self.month:%Y-%m}"
