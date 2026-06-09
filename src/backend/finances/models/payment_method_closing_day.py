import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PaymentMethodClosingDay(models.Model):
    """Per-month override of a payment method's invoice closing day.

    Credit cards occasionally shift their closing day for a given month. The
    base :class:`PaymentMethod.closing_day` is the default; rows here override
    it for specific months.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_method = models.ForeignKey(
        "finances.PaymentMethod",
        on_delete=models.CASCADE,
        related_name="monthly_closing_days",
    )
    month = models.DateField(help_text="Primeiro dia do mês ao qual o fechamento se aplica")
    closing_day = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dia de fechamento mensal"
        verbose_name_plural = "dias de fechamento mensais"
        ordering = ["payment_method", "month"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment_method", "month"],
                name="unique_closing_day_per_method_month",
            ),
        ]

    def __str__(self):
        return f"{self.payment_method.name} {self.month:%Y-%m}: dia {self.closing_day}"
