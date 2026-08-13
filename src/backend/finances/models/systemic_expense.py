import uuid
from datetime import date as date_type

from django.db import models

from accounts.models import AuthoredHouseholdModel


class SystemicExpense(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
            # The template carries its own tenancy down. Until phase 4 this
            # relied on the write bridge filling household from user; the
            # bridge is gone and a generated entry must not be tenant-less.
            household=self.household,
            created_by=self.created_by,
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
