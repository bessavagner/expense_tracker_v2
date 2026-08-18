"""Fail loudly when the database is behind the code running against it.

Run after every production deploy and nightly thereafter (E16 S16-9). The
nightly part is not belt-and-braces: the 2026-08-15 window *opened* at a deploy
but stayed open for a day because nothing re-asked. Drift also arrives without a
deploy — a rollback, or a `migrate` pointed at the wrong database.

Operator procedure: `docs/runbook.md`, "Schema drift".
"""

import json

from django.core.management.base import BaseCommand, CommandError

from core.migration_drift import unapplied_migrations


class Command(BaseCommand):
    help = "Exit non-zero if the database has not applied every migration in the image."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")

    def handle(self, *args, **options):
        unapplied = unapplied_migrations()

        if options["json"]:
            self.stdout.write(json.dumps({"drift": bool(unapplied), "unapplied": unapplied}))
            if unapplied:
                raise CommandError(f"schema drift: {', '.join(unapplied)}")
            return

        if not unapplied:
            # Logged on every run, including the ones that find nothing — the
            # alert in Task 7 fires on *silence*, so a quiet success is data.
            self.stdout.write(self.style.SUCCESS("ledger_drift_check_ran: no drift"))
            return

        raise CommandError(
            "ledger_drift_check_ran: schema drift — the database has not applied "
            f"{len(unapplied)} migration(s): {', '.join(unapplied)}. "
            "Fix with: DATABASE_URL=<direct connection, port 5432> "
            "uv run python src/backend/manage.py migrate"
        )
