import uuid

from django.db import models

from accounts.models import AuthoredHouseholdModel


class Income(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Redundant with income_hh_month_idx, whose leading column is household.
    # See the longer note on Entry.household for why the extra index is a cost
    # rather than a spare tyre.
    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
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
            models.Index(fields=["household", "month"], name="income_hh_month_idx"),
        ]

    def __str__(self):
        return f"{self.name} — {self.month:%Y-%m}"
