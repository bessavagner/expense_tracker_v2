"""Fix year-typo dates on regular entries logged in 2025 months 1-9.

The household's records begin Oct/2025, so a REGULAR entry dated between
2025-01 and 2025-09 is an impossible date — a data-entry typo where the year
should be 2026 (the row physically belongs to a 2026 monthly table). The app
billed these to a pre-origin month, dropping them from the projection's
"Despesas diversas". Shifting the year by +1 and re-saving restores the correct
``billing_month`` via the closing-day rule.

Scope is deliberately narrow: only REGULAR entries in [2025-01, 2025-10) — never
installments/systemics, never the legitimate pre-origin Oct/2025 data.

Dry-run by default; pass ``--apply`` to persist.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from finances.models import Entry
from finances.models.entry import EntryType

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 10, 1)  # exclusive — Oct/2025 onward is real data


class Command(BaseCommand):
    help = "Shift year-typo regular entries (2025 months 1-9) to 2026."

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
            Entry.objects.filter(
                entry_type=EntryType.REGULAR,
                date__gte=WINDOW_START,
                date__lt=WINDOW_END,
            )
            .select_related("payment_method")
            .order_by("date")
        )

        changes = [(e, e.date.replace(year=e.date.year + 1)) for e in entries]
        for entry, new_date in changes:
            self.stdout.write(
                f"[{mode}] {entry.date} -> {new_date}  R$ {entry.amount:>9}  "
                f"{entry.description[:40]}"
            )

        if apply and changes:
            with transaction.atomic():
                for entry, new_date in changes:
                    entry.date = new_date
                    # Date moved: let save() recompute billing_month from the
                    # closing-day rule (override is already cleared on these).
                    entry.billing_month_override = False
                    entry.save()

        verb = "Updated" if apply else "Would update"
        noun = "entry" if len(changes) == 1 else "entries"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(changes)} {noun}."))
