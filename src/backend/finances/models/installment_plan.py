import uuid

from django.conf import settings
from django.db import models, transaction

from finances.services.billing import add_months, installment_billing_months


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

        months = installment_billing_months(
            self.date, self.payment_method, self.num_installments
        )
        entries = []
        for i, billing_month in enumerate(months):
            if i == self.num_installments - 1:
                amount = self.total_amount - (self.installment_amount * (self.num_installments - 1))
            else:
                amount = self.installment_amount
            entries.append(
                Entry(
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
            )
        Entry.objects.bulk_create(entries)
        return list(Entry.objects.filter(installment_plan=self).order_by("billing_month"))

    @transaction.atomic
    def regenerate_entries(self) -> list:
        """Delete this plan's entries and recreate them from the current fields.

        Used when the user edits the whole plan (total / number of parcels /
        category / etc.). Old generated entries are removed first so
        ``generate_entries`` can run again.
        """
        self.entries.all().delete()
        return self.generate_entries()

    @transaction.atomic
    def shift_months(self, n: int) -> None:
        """Shift every installment (and the plan's date) by ``n`` months.

        Use to correct a wrong purchase date — e.g. ``shift_months(1)`` moves
        each parcela one invoice forward. ``billing_month`` is always the first
        of the month; the plan date keeps its day (clamped to month length).
        """
        if n == 0:
            return
        from finances.models.entry import Entry

        entries = list(self.entries.all())
        for entry in entries:
            entry.billing_month = add_months(entry.billing_month, n)
        Entry.objects.bulk_update(entries, ["billing_month"])
        self.date = add_months(self.date, n)
        self.save(update_fields=["date", "updated_at"])
