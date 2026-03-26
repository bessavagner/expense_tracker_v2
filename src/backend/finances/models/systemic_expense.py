import uuid
from datetime import date as date_type

from django.conf import settings
from django.db import models


class SystemicExpense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="systemic_expenses"
    )
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        "finances.Category", on_delete=models.PROTECT, related_name="systemic_expenses"
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="systemic_expenses",
    )
    default_amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "gasto sistemático"
        verbose_name_plural = "gastos sistemáticos"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def create_monthly_entry(self, month: date_type, amount=None, payment_method=None):
        from finances.models.entry import Entry, EntryType

        return Entry.objects.create(
            user=self.user,
            date=month,
            amount=amount if amount is not None else self.default_amount,
            description=self.name,
            category=self.category,
            payment_method=payment_method or self.payment_method,
            entry_type=EntryType.SYSTEMIC,
            billing_month=month,
            billing_month_override=True,
            systemic_expense=self,
        )
