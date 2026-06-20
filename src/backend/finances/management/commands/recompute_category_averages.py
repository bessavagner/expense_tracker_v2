from datetime import date, datetime

from django.core.management.base import BaseCommand

from finances.models import Category
from finances.services.category_stats import category_moving_averages


class Command(BaseCommand):
    help = "Popula Category.quarterly_avg (3m) e historical_avg (todo histórico)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="grava (senão dry-run)")
        parser.add_argument("--as-of", default=None, help="YYYY-MM-DD (default hoje)")

    def handle(self, *args, **opts):
        as_of = (
            datetime.strptime(opts["as_of"], "%Y-%m-%d").date()
            if opts["as_of"] else date.today()
        )
        changed = 0
        for cat in Category.objects.all():
            q = category_moving_averages(cat.user, window=3, as_of=as_of).get(cat.id)
            h = category_moving_averages(cat.user, window=1200, as_of=as_of).get(cat.id)
            if opts["apply"]:
                cat.quarterly_avg = q
                cat.historical_avg = h
                cat.save(update_fields=["quarterly_avg", "historical_avg", "updated_at"])
            changed += 1
            self.stdout.write(f"{cat.user_id} {cat.name}: 3m={q} hist={h}")
        verb = "gravado" if opts["apply"] else "DRY-RUN"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {changed} categoria(s)."))
