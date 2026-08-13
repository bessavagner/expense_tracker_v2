import uuid

from django.db import models

from accounts.models import AuthoredHouseholdModel
from finances.services.billing import compute_billing_month, resolve_closing_day


class EntryType(models.TextChoices):
    REGULAR = "regular", "Regular"
    INSTALLMENT = "installment", "Parcela"
    SYSTEMIC = "systemic", "Sistemático"


class Entry(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Overridden only to drop Django's implicit FK index. `household_id` leads
    # BOTH composites in Meta, so those already serve every household-only
    # lookup — verified: count(*) by household alone is an Index Only Scan on
    # entry_hh_billing_type_idx, touching no heap. The default index is a
    # strict prefix of them, and because it is narrower the planner costs it
    # lower and can pick it for filter(household, billing_month), then discard
    # most of what it read. E03 removed the same four indexes when the tenant
    # column was `user` (0008_drop_redundant_user_fk_indexes); E04 phase 2
    # re-created them under `household_id` by adding an ordinary FK.
    # See docs/architecture/query-performance-baseline.md.
    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
        db_index=False,
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=500)
    category = models.ForeignKey(
        "finances.Category", on_delete=models.PROTECT, related_name="entries"
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod", on_delete=models.PROTECT, related_name="entries"
    )
    entry_type = models.CharField(
        max_length=20, choices=EntryType.choices, default=EntryType.REGULAR
    )
    billing_month = models.DateField(help_text="Mês de contabilização (primeiro dia do mês)")
    billing_month_override = models.BooleanField(default=False)
    installment_plan = models.ForeignKey(
        "finances.InstallmentPlan",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entries",
    )
    systemic_expense = models.ForeignKey(
        "finances.SystemicExpense",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "entrada"
        verbose_name_plural = "entradas"
        ordering = ["-date", "-created_at"]
        indexes = [
            # The dashboard's core predicate. One composite instead of two
            # indexes: a B-tree serves any query with equality on a prefix, so
            # this answers filter(household, billing_month) and
            # filter(household, billing_month, entry_type) alike.
            models.Index(
                fields=["household", "billing_month", "entry_type"],
                name="entry_hh_billing_type_idx",
            ),
            # Matches Meta.ordering exactly, so the planner can skip the sort as
            # well as the scan on every unordered Entry queryset.
            models.Index(
                fields=["household", "-date", "-created_at"],
                name="entry_hh_date_recent_idx",
            ),
        ]

    def __str__(self):
        return f"{self.description} — R$ {self.amount}"

    def save(self, *args, **kwargs):
        if not self.billing_month_override:
            self.billing_month = compute_billing_month(
                self.date,
                self.payment_method.type,
                resolve_closing_day(self.payment_method, self.date),
            )
        super().save(*args, **kwargs)
