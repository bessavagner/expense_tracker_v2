"""Sub-agente PLANEJADOR (Etapa 3 do prompt 004).

Planejamento e inteligência financeira + interação proativa — SOMENTE LEITURA.
Roda num modelo mais capaz (LLM_WORKER_MODEL). A decisão de alertar é
determinística (analytics.build_proactive_alerts); o LLM apenas formula a mensagem.
"""

from datetime import date

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents import analytics
from assistant.agents.prompts import PLANNER_PROMPT, build_date_instructions
from assistant.agents.tools import query_balance, query_budget_status, query_installments
from finances.services.whatif import HypotheticalItem, simulate_projection_summary

User = get_user_model()

planner_agent = Agent(
    settings.LLM_WORKER_MODEL,
    deps_type=User,
    system_prompt=PLANNER_PROMPT,
)

# Injeta a data de hoje (projeções e referências relativas).
planner_agent.instructions(build_date_instructions)


@planner_agent.tool
async def get_balance(ctx: RunContext[User], year: int, month: int) -> str:
    """Consulta saldo do mês (renda - gastos + retornos)."""
    return await sync_to_async(query_balance)(ctx.deps, year, month)


@planner_agent.tool
async def get_budget_status(ctx: RunContext[User], year: int, month: int) -> str:
    """Lista categorias acima ou perto do teto de orçamento."""
    return await sync_to_async(query_budget_status)(ctx.deps, year, month)


@planner_agent.tool
async def get_installments(ctx: RunContext[User]) -> str:
    """Lista parcelamentos ativos com parcela atual e total mensal."""
    return await sync_to_async(query_installments)(ctx.deps)


@planner_agent.tool
async def project_month_end(ctx: RunContext[User], year: int, month: int) -> str:
    """Projeta o gasto até o fim do mês pelo ritmo atual (run-rate)."""
    return await sync_to_async(analytics.project_month_end)(ctx.deps, year, month)


@planner_agent.tool
async def get_proactive_alerts(ctx: RunContext[User], year: int, month: int) -> str:
    """Retorna alertas de orçamento priorizados (motor determinístico de gatilhos)."""
    return await sync_to_async(analytics.proactive_alerts)(ctx.deps, year, month)


@planner_agent.tool
async def get_upcoming_obligations(ctx: RunContext[User], year: int, month: int) -> str:
    """Lista obrigações conhecidas do mês: parcelas e gastos sistemáticos."""
    return await sync_to_async(analytics.upcoming_obligations)(ctx.deps, year, month)


@planner_agent.tool
async def simulate_projection(ctx: RunContext[User], items: list[HypotheticalItem],
                              start_year: int, start_month: int, months: int = 12) -> str:
    """Simula o efeito de lançamentos hipotéticos na projeção (what-if).

    items: lista de hipóteses (despesa avulsa/recorrente, renda, parcelamento,
    empréstimo). start_year/start_month: início do horizonte; months: nº de meses.
    """
    start = date(start_year, start_month, 1)
    return await sync_to_async(simulate_projection_summary)(ctx.deps, items, start, months)
