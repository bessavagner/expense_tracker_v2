import uuid

from django.conf import settings
from django.db import models

from accounts.models import AuthoredHouseholdModel
from finances.services.billing import compute_billing_month, resolve_closing_day


class EntryType(models.TextChoices):
    REGULAR = "regular", "Regular"
    INSTALLMENT = "installment", "Parcela"
    SYSTEMIC = "systemic", "Sistemático"


class Entry(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="entries",
        # No standalone index on user_id: it is the leading column of BOTH
        # indexes in Meta, so those already serve every user-only lookup (an
        # Index Only Scan, measured). Keeping Django's default FK index here is
        # not free — it is a strict prefix of entry_user_billing_type_idx, and
        # because it is the narrower index the planner costs it lower and picks
        # it for filter(user, billing_month), then discards 96% of the rows it
        # read. Measured at 5,000 entries for one user: 1.698 ms reading 5,000
        # rows with the FK index present, 0.422 ms reading 189 without it.
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
            # this answers filter(user, billing_month) and
            # filter(user, billing_month, entry_type) alike.
            models.Index(
                fields=["user", "billing_month", "entry_type"],
                name="entry_user_billing_type_idx",
            ),
            # Matches Meta.ordering exactly, so the planner can skip the sort as
            # well as the scan on every unordered Entry queryset.
            models.Index(
                fields=["user", "-date", "-created_at"],
                name="entry_user_date_recent_idx",
            ),
            # The household twins of the two indexes above. Phase 3 converts
            # the dashboard's queries onto them one surface at a time; the
            # user-leading pair stays until phase 4 drops the column.
            models.Index(
                fields=["household", "billing_month", "entry_type"],
                name="entry_hh_billing_type_idx",
            ),
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
