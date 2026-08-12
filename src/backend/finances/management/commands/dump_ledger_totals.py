"""Fingerprint the ledger's money, for before/after comparison across a migration.

Row counts do not prove a migration was lossless — this project has a
documented history of reconciliation issues where the counts matched and the
balances did not. This dumps the numbers that actually matter: per-user entry
and income sums, and the running acumulado per month straight out of the
projection service.

Scoped by user on purpose. E04 phase 2 changes no read path, so running this
before and after the migration must produce identical output; a diff is
corruption. Phase 4 re-points it at household.
"""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Count, Min, Sum

from finances.models import Entry, Income
from finances.services.projection import build_projection, projection_origin

# Pinned so two runs days apart still compare: the past/future split in
# build_projection depends on `today`, and a drifting clock would produce a
# spurious diff. Update the literal if the rehearsal happens much later.
FIXED_TODAY = date(2026, 8, 12)


class Command(BaseCommand):
    help = "Dump per-user ledger totals and the monthly acumulado as JSON."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")
        parser.add_argument(
            "--months", type=int, default=36, help="How many months of acumulado to include."
        )

    def handle(self, *args, **options):
        report = {}
        for user in get_user_model().objects.order_by("username"):
            entries = Entry.objects.filter(user=user).aggregate(
                n=Count("id"), total=Sum("amount"), first=Min("billing_month")
            )
            incomes = Income.objects.filter(user=user).aggregate(total=Sum("amount"))
            start = entries["first"] or projection_origin()
            start = max(start.replace(day=1), projection_origin())
            months = build_projection(user, start, options["months"], today=FIXED_TODAY)
            report[user.get_username()] = {
                "entry_count": entries["n"],
                "entry_sum": f"{entries['total'] or 0:.2f}",
                "income_sum": f"{incomes['total'] or 0:.2f}",
                "months": [
                    {
                        "month": m["month"].isoformat(),
                        "total": f"{m['total']:.2f}",
                        "income": f"{m['income']:.2f}",
                        "acumulado": f"{m['acumulado']:.2f}",
                    }
                    for m in months
                ],
            }

        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
