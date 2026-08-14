"""Emit yesterday's assistant usage as one structured log line.

E06 shipped a four-tile golden-signals dashboard because two of its five
signals — assistant turns/day and LLM spend/day — could not be built: a
successful request emits no application log line, and turn counts lived only in
Postgres, which Cloud Monitoring cannot read. E07 created the tables; this
command bridges them to Cloud Logging, where a log-based metric can count them.

A log line rather than the Monitoring API because E06 already established
structured JSON on stdout as how this service talks to Cloud Logging
(`core/log_formatting.py`): no new IAM role, no new client library, and no new
failure mode in the request path.

A quiet day emits ZEROES rather than nothing: a missing line is
indistinguishable from a broken job, and a dashboard that silently flatlines is
worse than one that reads zero.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone

from assistant.models import UsageInteraction, UsageRecord

METRIC = "assistant_usage_daily"


class Command(BaseCommand):
    help = "Emit yesterday's assistant turns and LLM spend as a structured log line."

    def add_arguments(self, parser):
        parser.add_argument("--day", help="YYYY-MM-DD (default: yesterday)")

    def handle(self, *args, **opts):
        # Yesterday, not today: a partial day would make the newest point on
        # the dashboard always dip, which reads as a drop in usage rather than
        # as a day still in progress.
        if opts.get("day"):
            try:
                day = date.fromisoformat(opts["day"])
            except ValueError as exc:
                raise CommandError(
                    f"--day espera uma data YYYY-MM-DD, recebeu {opts['day']!r}."
                ) from exc
        else:
            day = (timezone.localtime() - timedelta(days=1)).date()

        start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        end = start + timedelta(days=1)

        turns = UsageInteraction.objects.filter(created_at__gte=start, created_at__lt=end).count()
        # `Sum` skips NULLs, so unpriced calls (transcription is billed per
        # minute and has no ModelPrice row) neither crash this nor count as
        # zero-cost real spend. `usage_report` is where that gap is surfaced.
        cost = UsageRecord.objects.filter(created_at__gte=start, created_at__lt=end).aggregate(
            total=Sum("cost_usd")
        )["total"] or Decimal("0")

        self.stdout.write(
            json.dumps(
                {
                    "metric": METRIC,
                    "day": day.isoformat(),
                    "turns": turns,
                    "cost_usd": str(cost),
                }
            )
        )
