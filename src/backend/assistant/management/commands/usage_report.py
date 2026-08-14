"""What each household costs, and the distribution a price has to clear.

E07 S07-5. Percentiles are computed in Python over per-household totals rather
than in SQL: the row count here is households, not records, so the simple thing
is correct and portable across the Supabase pooler.

Unpriced records are COUNTED and reported separately, never summed as zero. A
cost report that quietly treats "we don't know" as "free" is worse than no
report — it looks authoritative.
"""

import math
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum
from django.utils import timezone

from assistant.models import UsageRecord

WIDTH = 52


def percentile(values: list[Decimal], p: float) -> Decimal:
    """Nearest-rank percentile. Empty input -> 0.

    Nearest-rank rather than interpolated: these are real household bills, and
    a p99 that is an average of two houses is a number nobody actually pays.
    """
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


def _boundary(raw: str, flag: str):
    """Parse a YYYY-MM-DD argument into an aware datetime in local time."""
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CommandError(f"{flag} espera uma data YYYY-MM-DD, recebeu {raw!r}.") from exc
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


class Command(BaseCommand):
    help = "Cost per household over a period, with p50/p90/p99 and a kind breakdown."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="YYYY-MM-DD, inclusive")
        parser.add_argument("--until", help="YYYY-MM-DD, exclusive")
        parser.add_argument("--by-kind", action="store_true")

    def handle(self, *args, **opts):
        qs = UsageRecord.objects.all()
        if opts.get("since"):
            qs = qs.filter(created_at__gte=_boundary(opts["since"], "--since"))
        if opts.get("until"):
            qs = qs.filter(created_at__lt=_boundary(opts["until"], "--until"))

        rows = list(
            qs.values("household__name")
            .annotate(total=Sum("cost_usd"), calls=Count("id"))
            .order_by("-total")
        )
        totals = [r["total"] or Decimal("0") for r in rows]

        self.stdout.write("Custo por casa (USD)")
        self.stdout.write("-" * WIDTH)
        for r in rows:
            name = (r["household__name"] or "—")[:30]
            self.stdout.write(f"{name:<32}{r['total'] or Decimal('0'):>12}{r['calls']:>8}")

        self.stdout.write("")
        self.stdout.write(f"casas ativas : {len(totals)}")
        self.stdout.write(f"p50          : {percentile(totals, 50)}")
        self.stdout.write(f"p90          : {percentile(totals, 90)}")
        self.stdout.write(f"p99          : {percentile(totals, 99)}")

        unpriced = qs.filter(cost_usd__isnull=True).count()
        if unpriced:
            self.stdout.write("")
            self.stdout.write(
                f"{unpriced} chamadas sem preço (NÃO somadas acima). "
                "Transcrição é cobrada por minuto e ModelPrice só modela tokens "
                "— ver docs/runbook.md."
            )

        if opts.get("by_kind"):
            self.stdout.write("")
            self.stdout.write("Custo por tipo de chamada (USD)")
            self.stdout.write("-" * WIDTH)
            by_kind = (
                qs.values("kind")
                .annotate(total=Sum("cost_usd"), calls=Count("id"))
                .order_by("-total")
            )
            for r in by_kind:
                self.stdout.write(f"{r['kind']:<32}{r['total'] or Decimal('0'):>12}{r['calls']:>8}")
