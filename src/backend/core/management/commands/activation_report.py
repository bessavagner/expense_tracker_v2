"""How many people got to the moment this product exists for, and how long it took.

E11's Definition of Done requires time-to-activation to be measurable. E14 owns
the dashboard and the rest of the funnel; this is the command that proves the
number exists, and the one the unaided walkthrough is checked against.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.events import EventName
from core.models import ProductEvent


def _percentile(sorted_values, fraction):
    """Nearest-rank, so a single sample reports itself rather than an average."""
    if not sorted_values:
        return None
    index = min(int(round(fraction * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return sorted_values[index]


class Command(BaseCommand):
    help = "Signups, activations, activation rate and time-to-activation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Only count signups from the last N days (default 90).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])

        signups = {
            row.household_id: row.created_at
            for row in ProductEvent.objects.filter(name=EventName.SIGNUP, created_at__gte=cutoff)
        }
        activations = {
            row.household_id: row.created_at
            for row in ProductEvent.objects.filter(name=EventName.ACTIVATED)
        }

        activated = [hh for hh in signups if hh in activations]
        deltas = sorted((activations[hh] - signups[hh]).total_seconds() / 60 for hh in activated)

        rate = (len(activated) / len(signups) * 100) if signups else 0.0
        self.stdout.write(f"Janela: últimos {options['days']} dia(s)")
        self.stdout.write(f"Cadastros: {len(signups)}")
        self.stdout.write(f"Ativados: {len(activated)}")
        self.stdout.write(f"Taxa de ativação: {rate:.1f}%")

        p50 = _percentile(deltas, 0.5)
        p90 = _percentile(deltas, 0.9)
        if p50 is None:
            self.stdout.write("Tempo até ativação: sem amostras ainda.")
            return
        self.stdout.write(
            f"Tempo até ativação (min): p50 {p50:.0f} · p90 {p90:.0f} (n={len(deltas)})"
        )
