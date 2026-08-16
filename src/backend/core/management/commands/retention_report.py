"""Retention by cohort, engagement, and the ratio that decides the wedge.

S14-3's repeatable command. Every number it prints is computed by
``core.metrics`` — the same functions `/metricas/` calls — so "D7 retention"
cannot mean one thing here and another in a browser. What the numbers *mean* is
decided in ``docs/architecture/product-metrics.md``.

Operator procedure: ``docs/runbook.md``, "Métricas de produto".
"""

from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from assistant.models import ChatMessage, MessageRole
from core import metrics
from core.events import EventName
from core.models import ProductEvent

#: Printed wherever a metric has no samples. Never a bare `0%`: "we do not know
#: yet" and "nobody came back" are different answers, and conflating them is how
#: a young beta reports a catastrophe.
UNKNOWN = "—"


def _pct(value):
    return UNKNOWN if value is None else f"{value * 100:.0f}%"


class Command(BaseCommand):
    help = "Retenção por coorte, engajamento e a razão IA:manual."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Só considera eventos a partir desta data (AAAA-MM-DD).",
        )

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                since = datetime.fromisoformat(options["since"]).replace(tzinfo=UTC)
            except ValueError as exc:
                raise CommandError("--since precisa ser AAAA-MM-DD.") from exc

        now = timezone.now()
        excluded = metrics.excluded_shadow_households()

        self._cohorts(since, now, excluded)
        self._engagement(since, now)
        self._wedge(since)
        self._excluded(excluded)

    # -- sections ---------------------------------------------------------

    def _cohorts(self, since, now, excluded):
        self.stdout.write("== Coortes (retenção rolante) ==")
        cohorts = metrics.signup_cohorts(since)
        if not cohorts:
            self.stdout.write("Nenhum cadastro no período.")
            self.stdout.write("")
            return

        self.stdout.write(f"{'Semana':<12}{'Casas':>7}{'D1':>8}{'D7':>8}{'D30':>8}")
        for monday in sorted(cohorts, reverse=True):
            ids = [hh for hh in cohorts[monday] if hh not in excluded]
            if not ids:
                continue
            row = f"{monday:%Y-%m-%d}".ljust(12) + f"{len(ids):>7}"
            for day in (1, 7, 30):
                row += f"{_pct(metrics.rolling_retention(ids, day=day, now=now)):>8}"
            self.stdout.write(row)
        self.stdout.write("")

    def _engagement(self, since, now):
        self.stdout.write("== Engajamento (últimos 7 dias) ==")
        window = max(since, now - timedelta(days=7)) if since else now - timedelta(days=7)

        turns = ChatMessage.objects.filter(role=MessageRole.USER, created_at__gte=window)
        active_households = set(turns.values_list("household_id", flat=True))
        turn_count = turns.count()
        per_household = turn_count / len(active_households) if active_households else None

        receipts = ProductEvent.objects.filter(
            name=EventName.ACTIVATED, created_at__gte=window
        ).count()
        entries = ProductEvent.objects.filter(
            name=EventName.ENTRY_CREATED,
            metadata__source="receipt",
            created_at__gte=window,
        ).count()

        self.stdout.write(f"Casas ativas: {len(active_households)}")
        self.stdout.write(
            "Turnos do assistente por casa ativa: "
            + (UNKNOWN if per_household is None else f"{per_household:.1f}")
            + f" (total {turn_count})"
        )
        self.stdout.write(f"Cupons confirmados: {entries}")
        self.stdout.write(f"Primeiras ativações: {receipts}")
        self.stdout.write("")

    def _wedge(self, since):
        self.stdout.write("== A cunha ==")
        ai, manual = metrics.wedge_ratio(since)
        total = ai + manual
        if total == 0:
            self.stdout.write("Sem lançamentos ainda — a razão IA:manual não tem amostras.")
            self.stdout.write("")
            return
        share = ai / total * 100
        self.stdout.write(f"IA {ai} : {manual} manual ({share:.0f}%)")
        if ai < manual:
            # The stop condition from docs/architecture/ga-criteria.md, printed
            # where it will actually be read rather than left in a document.
            self.stdout.write(
                "⚠️ Mais lançamentos digitados que capturados por IA — a cunha não está pegando."
            )
        self.stdout.write("")

    def _excluded(self, excluded):
        self.stdout.write("== Excluídos ==")
        self.stdout.write(
            f"Casas-sombra fora das coortes: {len(excluded)} "
            "(criadas no cadastro de quem trabalha na casa de outra pessoa)."
        )
        self.stdout.write("Definições: docs/architecture/product-metrics.md")
