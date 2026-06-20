"""Recompute ``billing_month`` for REGULAR entries stored at the wrong month.

A bulk seed/import froze credit-card "diversas" at the *purchase* month with
``billing_month_override=True``, bypassing the invoice closing-day rule (see
``finances.services.billing.compute_billing_month``). That makes the projection
screen's "Despesas diversas" disagree with the closing-day model: purchases land
one invoice too early. This command recomputes the correct ``billing_month`` and
clears the spurious override. Installments and systemic entries keep their
intentional overrides and are never touched.

Dry-run by default; pass ``--apply`` to write.
"""

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from finances.models import Entry
from finances.models.entry import EntryType
from finances.services.billing import compute_billing_month, resolve_closing_day


class Command(BaseCommand):
    help = "Recompute billing_month for REGULAR entries via the closing-day rule."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without it the command only reports (dry-run).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        mode = "APPLY" if apply else "DRY-RUN"

        entries = (
            Entry.objects.filter(entry_type=EntryType.REGULAR)
            .select_related("payment_method")
            .order_by("billing_month", "date")
        )

        changes = []
        for entry in entries:
            pm = entry.payment_method
            correct = compute_billing_month(
                entry.date, pm.type, resolve_closing_day(pm, entry.date)
            )
            if correct != entry.billing_month:
                changes.append((entry, correct))

        moved_per_month = defaultdict(Decimal)
        for entry, correct in changes:
            self.stdout.write(
                f"[{mode}] {entry.date} R$ {entry.amount:>10} "
                f"{entry.billing_month:%Y-%m} -> {correct:%Y-%m}  {entry.description[:40]}"
            )
            moved_per_month[entry.billing_month] -= entry.amount
            moved_per_month[correct] += entry.amount

        if apply and changes:
            with transaction.atomic():
                for entry, correct in changes:
                    entry.billing_month = correct
                    entry.billing_month_override = False
                    entry.save(update_fields=["billing_month", "billing_month_override"])

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Net change per billing_month ({mode}):"))
        for month in sorted(moved_per_month):
            delta = moved_per_month[month]
            if delta:
                self.stdout.write(f"  {month:%Y-%m}: {delta:+.2f}")

        verb = "Updated" if apply else "Would update"
        noun = "entry" if len(changes) == 1 else "entries"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(changes)} {noun}."))
