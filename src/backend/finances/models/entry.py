import uuid
from django.conf import settings
from django.db import models
from finances.services.billing import compute_billing_month


class EntryType(models.TextChoices):
    REGULAR = "regular", "Regular"
    INSTALLMENT = "installment", "Parcela"
    SYSTEMIC = "systemic", "Sistemático"


class Entry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entries")
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=500)
    category = models.ForeignKey("finances.Category", on_delete=models.PROTECT, related_name="entries")
    payment_method = models.ForeignKey("finances.PaymentMethod", on_delete=models.PROTECT, related_name="entries")
    entry_type = models.CharField(max_length=20, choices=EntryType.choices, default=EntryType.REGULAR)
    billing_month = models.DateField(help_text="Mês de contabilização (primeiro dia do mês)")
    billing_month_override = models.BooleanField(default=False)
    installment_plan = models.ForeignKey("finances.InstallmentPlan", on_delete=models.CASCADE, null=True, blank=True, related_name="entries")
    systemic_expense = models.ForeignKey("finances.SystemicExpense", on_delete=models.SET_NULL, null=True, blank=True, related_name="entries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "entrada"
        verbose_name_plural = "entradas"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.description} — R$ {self.amount}"

    def save(self, *args, **kwargs):
        if not self.billing_month_override:
            self.billing_month = compute_billing_month(
                self.date, self.payment_method.type, self.payment_method.closing_day,
            )
        super().save(*args, **kwargs)
