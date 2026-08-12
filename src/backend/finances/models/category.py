import uuid

from django.conf import settings
from django.db import models

from accounts.models import AuthoredHouseholdModel


class Category(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    budget = models.ForeignKey(
        "finances.Budget",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
    )
    budget_ceiling = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    historical_avg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Média histórica (computada a partir das entradas)",
    )
    quarterly_avg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Média dos últimos 3 meses (computada a partir das entradas)",
    )
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        # Both hold during phases 2 and 3. The user constraint goes away in
        # phase 4 with the column, and this becomes the only one.
        unique_together = ("user", "name")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_category_per_household"
            ),
        ]

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise models.ProtectedError(
                "Categorias do sistema não podem ser excluídas.",
                set(),
            )
        return super().delete(*args, **kwargs)
