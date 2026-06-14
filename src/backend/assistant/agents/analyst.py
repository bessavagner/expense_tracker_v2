"""Sub-agente ANALISTA (Etapa 3 do prompt 004).

Organização e análise de dados — SOMENTE LEITURA. Roda num modelo mais capaz
(LLM_WORKER_MODEL). Toda a matemática vem das ferramentas determinísticas
(assistant.agents.analytics e tools), nunca do LLM. Privilégio mínimo: nenhuma
ferramenta de escrita.
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents import analytics
from assistant.agents.prompts import ANALYST_PROMPT
from assistant.agents.tools import (
    list_categories,
    list_payment_methods,
    list_systemic_expenses,
    query_balance,
    query_budget_status,
    query_expenses,
    query_installments,
)

User = get_user_model()

analyst_agent = Agent(
    settings.LLM_WORKER_MODEL,
    deps_type=User,
    system_prompt=ANALYST_PROMPT,
)


@analyst_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa disponíveis do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)


@analyst_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return await sync_to_async(list_payment_methods)(ctx.deps)


@analyst_agent.tool
async def get_systemic_expenses(ctx: RunContext[User]) -> list[str]:
    """Lista os gastos sistemáticos ativos do usuário."""
    return await sync_to_async(list_systemic_expenses)(ctx.deps)


@analyst_agent.tool
async def get_expenses(
    ctx: RunContext[User], year: int, month: int, category_name: str | None = None
) -> str:
    """Consulta gastos por mês, opcionalmente filtrado por categoria."""
    return await sync_to_async(query_expenses)(ctx.deps, year, month, category_name)


@analyst_agent.tool
async def get_balance(ctx: RunContext[User], year: int, month: int) -> str:
    """Consulta saldo do mês (renda - gastos + retornos)."""
    return await sync_to_async(query_balance)(ctx.deps, year, month)


@analyst_agent.tool
async def get_budget_status(ctx: RunContext[User], year: int, month: int) -> str:
    """Lista categorias acima ou perto do teto de orçamento."""
    return await sync_to_async(query_budget_status)(ctx.deps, year, month)


@analyst_agent.tool
async def get_installments(ctx: RunContext[User]) -> str:
    """Lista parcelamentos ativos com parcela atual e total mensal."""
    return await sync_to_async(query_installments)(ctx.deps)


@analyst_agent.tool
async def get_category_breakdown(ctx: RunContext[User], year: int, month: int) -> str:
    """Quebra de gastos do mês por categoria e por forma de pagamento."""
    return await sync_to_async(analytics.category_breakdown)(ctx.deps, year, month)


@analyst_agent.tool
async def compare_with_previous_month(ctx: RunContext[User], year: int, month: int) -> str:
    """Compara o gasto total do mês com o mês anterior (delta e %)."""
    return await sync_to_async(analytics.compare_months)(ctx.deps, year, month)


@analyst_agent.tool
async def export_monthly_report(ctx: RunContext[User], year: int, month: int) -> str:
    """Gera o relatório CSV do mês (semicolon-delimited, formato do legado)."""
    return await sync_to_async(analytics.monthly_report_csv)(ctx.deps, year, month)


@analyst_agent.tool
async def find_anomalies(ctx: RunContext[User], year: int, month: int) -> str:
    """Sinaliza categorias cujo gasto excede muito a média histórica/trimestral."""
    return await sync_to_async(analytics.detect_anomalies)(ctx.deps, year, month)
