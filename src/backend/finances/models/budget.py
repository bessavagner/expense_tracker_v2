import uuid

from django.conf import settings
from django.db import models

from accounts.models import AuthoredHouseholdModel


class Budget(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="budgets",
    )
    name = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Teto do orçamento (editável)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        unique_together = ("user", "name")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_budget_per_household"
            ),
        ]

    def __str__(self):
        return self.name
