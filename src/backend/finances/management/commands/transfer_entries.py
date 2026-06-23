"""Transfer Entry rows between databases (e.g. local/friday -> production).

The dev box (friday) and production (Supabase) are SEPARATE databases with
different primary keys, so entries can't be copied by id. This command moves
them by VALUE, resolving Category/PaymentMethod by NAME on the target and
skipping anything already there (idempotent). Two modes:

    # on the SOURCE box (reads the local DB):
    python manage.py transfer_entries export --since 2026-06-23 > entries.json

    # against the TARGET DB (e.g. via /tmp/sb_manage.py, which points
    # DATABASE_URL at the prod session pooler):
    python /tmp/sb_manage.py transfer_entries import --apply < entries.json

`import` is dry-run by default — pass --apply to write. Use --file to read/write
a path instead of stdin/stdout (handy for tests).
"""

import json
import sys
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finances.models import Category, Entry, PaymentMethod

User = get_user_model()


def _resolve(queryset, name):
    """Lenient name match (exact-insensitive, then unique partial)."""
    obj = queryset.filter(name__iexact=name).first()
    if obj:
        return obj
    matches = list(queryset.filter(name__icontains=name))
    return matches[0] if len(matches) == 1 else None


class Command(BaseCommand):
    help = "Export/import Entry rows by value between databases (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["export", "import"])
        parser.add_argument("--since", help="export: only entries with date >= YYYY-MM-DD")
        parser.add_argument("--until", help="export: only entries with date <= YYYY-MM-DD")
        parser.add_argument("--user", help="export: filter to this username")
        parser.add_argument(
            "--file", help="read (import) or write (export) this path instead of stdin/stdout"
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="import: persist. Without it the import only reports (dry-run).",
        )

    def handle(self, *args, **options):
        if options["mode"] == "export":
            self._export(options)
        else:
            self._import(options)

    # -- export ---------------------------------------------------------------
    def _export(self, options):
        qs = Entry.objects.select_related("category", "payment_method", "user")
        if options["since"]:
            qs = qs.filter(date__gte=date.fromisoformat(options["since"]))
        if options["until"]:
            qs = qs.filter(date__lte=date.fromisoformat(options["until"]))
        if options["user"]:
            qs = qs.filter(user__username=options["user"])
        rows = [
            {
                "user": e.user.username,
                "date": e.date.isoformat(),
                "amount": str(e.amount),
                "category": e.category.name if e.category else None,
                "payment": e.payment_method.name if e.payment_method else None,
                "description": e.description,
            }
            for e in qs.order_by("date", "amount")
        ]
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        if options["file"]:
            with open(options["file"], "w", encoding="utf-8") as fh:
                fh.write(payload)
            self.stderr.write(
                self.style.SUCCESS(f"Exported {len(rows)} entries to {options['file']}")
            )
        else:
            self.stdout.write(payload)
            self.stderr.write(self.style.SUCCESS(f"Exported {len(rows)} entries."))

    # -- import ---------------------------------------------------------------
    def _import(self, options):
        apply = options["apply"]
        raw = (
            open(options["file"], encoding="utf-8").read()
            if options["file"]
            else sys.stdin.read()
        )
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f"invalid JSON input: {exc}") from exc

        skipped, errors = 0, []
        to_create = []
        for r in rows:
            u = User.objects.filter(username=r["user"]).first()
            if not u:
                errors.append(f"no user '{r['user']}' | {r['description'][:50]}")
                continue
            cat = _resolve(Category.objects.filter(user=u), r["category"] or "")
            pm = _resolve(
                PaymentMethod.objects.filter(user=u, is_active=True), r["payment"] or ""
            )
            if not cat:
                errors.append(f"no category '{r['category']}' | {r['description'][:50]}")
                continue
            if not pm:
                errors.append(f"no payment '{r['payment']}' | {r['description'][:50]}")
                continue
            d = date.fromisoformat(r["date"])
            amt = Decimal(r["amount"])
            if Entry.objects.filter(
                user=u, date=d, amount=amt, description=r["description"]
            ).exists():
                skipped += 1
                continue
            to_create.append((u, d, amt, r["description"], cat, pm))

        mode = "APPLY" if apply else "DRY-RUN"
        for _u, d, amt, desc, cat, pm in to_create:
            self.stdout.write(f"[{mode}] + {d} R$ {amt:>9} {cat.name}/{pm.name} | {desc[:45]}")

        if apply and to_create:
            with transaction.atomic():
                for u, d, amt, desc, cat, pm in to_create:
                    # let save() compute billing_month from date + payment_method
                    Entry.objects.create(
                        user=u, date=d, amount=amt, description=desc,
                        category=cat, payment_method=pm,
                    )

        self.stdout.write("")
        verb = "Created" if apply else "Would create"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {len(to_create)}; skipped(existing) {skipped}.")
        )
        for e in errors:
            self.stdout.write(self.style.WARNING(f"  SKIP(error): {e}"))
