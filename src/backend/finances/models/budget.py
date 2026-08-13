import uuid

from django.db import models

from accounts.models import AuthoredHouseholdModel


class Budget(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_budget_per_household"
            ),
        ]

    def __str__(self):
        return self.name
