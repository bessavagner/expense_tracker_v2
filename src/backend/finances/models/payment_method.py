import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import AuthoredHouseholdModel


class PaymentType(models.TextChoices):
    CASH = "cash", "Dinheiro"
    PIX = "pix", "Pix"
    CREDIT_CARD = "credit_card", "Cartão de Crédito"


class PaymentMethod(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=PaymentType.choices)
    closing_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Dia de fechamento da fatura (apenas cartão de crédito)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "forma de pagamento"
        verbose_name_plural = "formas de pagamento"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_payment_method_per_household"
            ),
        ]

    def __str__(self):
        return self.name
