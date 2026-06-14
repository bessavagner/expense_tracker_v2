"""Deterministic analytics for the assistant (Etapa 2 do prompt 004).

Design principle (ver docs/.ai/reports/000_aprimoramento_chatbot): **toda a
matemática financeira vive em código**, nunca no LLM. Os agentes (Analista,
Planejador) apenas compõem a consulta e narram o resultado destas funções, e o
motor de proatividade dispara eventos a partir de ``build_proactive_alerts``.
"""

import calendar
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from finances.models import Category, Entry, InstallmentPlan, SystemicExpense

# Limiares de proatividade (ver contexts/08_proatividade_ux.md): aviso cedo,
# urgente e estouro. Ajustáveis no futuro por categoria/usuário.
WARN_PCT = Decimal("90")
INFO_PCT = Decimal("50")

# Fator de anomalia: gasto acima de ``factor`` × média é sinalizado.
ANOMALY_FACTOR = Decimal("1.5")


def _billing_month(year: int, month: int) -> "date | None":
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def _spend_qs(user, billing_month):
    """Positive-amount (despesa) entries for a billing month — exclui reembolsos."""
    return Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)


def category_breakdown(user, year: int, month: int) -> str:
    """Quebra de gastos por categoria e por forma de pagamento no mês."""
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    by_cat = (
        _spend_qs(user, bm)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    if not by_cat:
        return f"Nenhum gasto em {month:02d}/{year}."

    by_pm = (
        _spend_qs(user, bm)
        .values("payment_method__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )

    lines = [f"Gastos de {month:02d}/{year} por categoria:"]
    lines += [f"- {r['category__name']}: R$ {r['total']:.2f}" for r in by_cat]
    lines.append("\nPor forma de pagamento:")
    lines += [f"- {r['payment_method__name']}: R$ {r['total']:.2f}" for r in by_pm]
    return "\n".join(lines)


def compare_months(user, year: int, month: int) -> str:
    """Compara o gasto total do mês com o mês anterior (delta e %)."""
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    prev = date(bm.year - 1, 12, 1) if bm.month == 1 else date(bm.year, bm.month - 1, 1)

    cur_total = _spend_qs(user, bm).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    prev_total = _spend_qs(user, prev).aggregate(t=Sum("amount"))["t"] or Decimal("0")

    if prev_total == 0:
        return (
            f"Em {month:02d}/{year} você gastou R$ {cur_total:.2f}. "
            f"Não há dados do mês anterior ({prev:%m/%Y}) para comparar (sem dados)."
        )

    delta = cur_total - prev_total
    pct = delta / prev_total * 100
    direction = "a mais" if delta >= 0 else "a menos"
    return (
        f"Em {month:02d}/{year}: R$ {cur_total:.2f} "
        f"(mês anterior {prev:%m/%Y}: R$ {prev_total:.2f}). "
        f"Diferença: R$ {abs(delta):.2f} {direction} ({pct:+.0f}%)."
    )


def monthly_report_csv(user, year: int, month: int) -> str:
    """Relatório CSV do mês (semicolon-delimited, espelha o legado sheets+claude).

    Convenções do legado: sem prefixo ``R$`` nos valores, vírgula na descrição
    vira hífen (evita conflito de CSV), data em DD/MM/AAAA, decimal com vírgula.
    """
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    entries = (
        Entry.objects.filter(user=user, billing_month=bm)
        .select_related("category", "payment_method")
        .order_by("date", "created_at")
    )
    if not entries:
        return f"Nenhum lançamento em {month:02d}/{year}."

    header = "Data;Valor;Descrição;Categoria;Forma de Pagamento"
    rows = [header]
    for e in entries:
        value = f"{e.amount:.2f}".replace(".", ",")  # decimal brasileiro
        desc = e.description.replace(",", " -")
        rows.append(
            f"{e.date:%d/%m/%Y};{value};{desc};{e.category.name};{e.payment_method.name}"
        )
    return "\n".join(rows)


def project_month_end(user, year: int, month: int, today: date | None = None) -> str:
    """Projeção de gasto até o fim do mês por *run-rate* (regra de três simples)."""
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    days_in_month = calendar.monthrange(year, month)[1]
    if today is not None and today.year == year and today.month == month:
        elapsed = today.day
    else:
        elapsed = days_in_month  # mês fechado: projeção == realizado

    spent = _spend_qs(user, bm).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    elapsed = max(elapsed, 1)
    projected = spent / elapsed * days_in_month

    return (
        f"Em {month:02d}/{year} você já gastou R$ {spent:.2f} em {elapsed} dia(s). "
        f"No ritmo atual, a projeção para o fim do mês é R$ {projected:.2f}."
    )


def detect_anomalies(user, year: int, month: int, factor: Decimal = ANOMALY_FACTOR) -> str:
    """Sinaliza categorias cujo gasto excede ``factor`` × a média (trimestral/histórica)."""
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    totals = {
        r["category__id"]: r["total"]
        for r in _spend_qs(user, bm).values("category__id").annotate(total=Sum("amount"))
    }
    flagged = []
    for cat in Category.objects.filter(user=user, id__in=totals.keys()):
        avg = cat.quarterly_avg or cat.historical_avg
        if not avg or avg <= 0:
            continue
        total = totals[cat.id]
        if total > factor * avg:
            ratio = total / avg
            flagged.append(
                f"⚠️ {cat.name}: R$ {total:.2f} ({ratio:.1f}× a média de R$ {avg:.2f})"
            )

    if not flagged:
        return f"Nenhuma anomalia de gasto detectada em {month:02d}/{year}."
    return f"Anomalias de gasto em {month:02d}/{year}:\n" + "\n".join(flagged)


def build_proactive_alerts(user, year: int, month: int) -> list[dict]:
    """Motor determinístico de gatilhos: retorna eventos priorizados de orçamento.

    Cada evento: {category, level (over|warn|info), pct, ceiling, total, priority,
    message}. ``priority`` menor = mais urgente. O LLM apenas formula a mensagem;
    a decisão de disparar é determinística (ver contexts/08).
    """
    bm = _billing_month(year, month)
    if bm is None:
        return []

    totals = {
        r["category__id"]: r["total"]
        for r in _spend_qs(user, bm).values("category__id").annotate(total=Sum("amount"))
    }
    alerts: list[dict] = []
    for cat in Category.objects.filter(user=user, budget_ceiling__gt=0, id__in=totals.keys()):
        total = totals[cat.id]
        pct = total / cat.budget_ceiling * 100
        if pct >= 100:
            level, priority, icon = "over", 1, "🔴"
        elif pct >= WARN_PCT:
            level, priority, icon = "warn", 2, "⚠️"
        elif pct >= INFO_PCT:
            level, priority, icon = "info", 3, "🔔"
        else:
            continue
        alerts.append(
            {
                "category": cat.name,
                "level": level,
                "pct": float(pct),
                "ceiling": cat.budget_ceiling,
                "total": total,
                "priority": priority,
                "message": (
                    f"{icon} {cat.name}: R$ {total:.0f} de R$ {cat.budget_ceiling:.0f} "
                    f"({pct:.0f}% do teto)"
                ),
            }
        )
    # prioridade asc (mais urgente primeiro), depois maior % primeiro
    alerts.sort(key=lambda a: (a["priority"], -a["pct"]))
    return alerts


def proactive_alerts(user, year: int, month: int) -> str:
    """Wrapper textual do motor de gatilhos para uso como ferramenta de agente."""
    alerts = build_proactive_alerts(user, year, month)
    if not alerts:
        return f"Tudo dentro do orçamento em {month:02d}/{year}. Nenhum alerta."
    return f"Alertas de orçamento em {month:02d}/{year}:\n" + "\n".join(
        a["message"] for a in alerts
    )


def upcoming_obligations(user, year: int, month: int) -> str:
    """Lista obrigações futuras conhecidas: parcelas e gastos sistemáticos do mês."""
    bm = _billing_month(year, month)
    if bm is None:
        return f"Erro: ano/mês inválido ({year}/{month})."

    lines: list[str] = []
    inst_total = (
        Entry.objects.filter(
            user=user, billing_month=bm, installment_plan__isnull=False, amount__gt=0
        ).aggregate(t=Sum("amount"))["t"]
        or Decimal("0")
    )
    if inst_total > 0:
        lines.append(f"- Parcelas no mês: R$ {inst_total:.2f}")

    sys_total = (
        Entry.objects.filter(
            user=user, billing_month=bm, systemic_expense__isnull=False, amount__gt=0
        ).aggregate(t=Sum("amount"))["t"]
        or Decimal("0")
    )
    if sys_total > 0:
        lines.append(f"- Gastos sistemáticos no mês: R$ {sys_total:.2f}")

    if not lines:
        # nenhum lançamento ainda — usa os templates/planos como referência
        active_systemic = SystemicExpense.objects.filter(user=user, is_active=True).count()
        active_plans = InstallmentPlan.objects.filter(user=user).count()
        return (
            f"Sem parcelas/sistemáticos lançados em {month:02d}/{year}. "
            f"(Cadastrados: {active_plans} parcelamento(s), {active_systemic} sistemático(s).)"
        )
    return f"Obrigações conhecidas em {month:02d}/{year}:\n" + "\n".join(lines)
