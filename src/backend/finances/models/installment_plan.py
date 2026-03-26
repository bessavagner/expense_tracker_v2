import uuid
from datetime import date

from django.conf import settings
from django.db import models, transaction

from finances.services.billing import compute_billing_month


class InstallmentPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="installment_plans"
    )
    date = models.DateField()
    description = models.CharField(max_length=500)
    category = models.ForeignKey(
        "finances.Category", on_delete=models.PROTECT, related_name="installment_plans"
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod", on_delete=models.PROTECT, related_name="installment_plans"
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    num_installments = models.PositiveIntegerField()
    installment_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "parcelamento"
        verbose_name_plural = "parcelamentos"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.description} ({self.num_installments}x)"

    @transaction.atomic
    def generate_entries(self) -> list:
        from finances.models.entry import Entry, EntryType

        if self.entries.exists():
            raise ValueError("Entries already generated for this installment plan.")

        billing_month = compute_billing_month(
            self.date,
            self.payment_method.type,
            self.payment_method.closing_day,
        )
        entries = []
        for i in range(self.num_installments):
            if i == self.num_installments - 1:
                amount = self.total_amount - (self.installment_amount * (self.num_installments - 1))
            else:
                amount = self.installment_amount
            entry = Entry(
                user=self.user,
                date=self.date,
                amount=amount,
                description=f"{self.description} ({i + 1}/{self.num_installments})",
                category=self.category,
                payment_method=self.payment_method,
                entry_type=EntryType.INSTALLMENT,
                billing_month=billing_month,
                billing_month_override=True,
                installment_plan=self,
            )
            entries.append(entry)
            if billing_month.month == 12:
                billing_month = date(billing_month.year + 1, 1, 1)
            else:
                billing_month = date(billing_month.year, billing_month.month + 1, 1)
        Entry.objects.bulk_create(entries)
        return list(Entry.objects.filter(installment_plan=self).order_by("billing_month"))
