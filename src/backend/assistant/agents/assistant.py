"""Agente ASSISTENTE unificado (single strong agent — Task 3).

Substitui o sistema multi-agente (orquestrador + registrador + analista +
planejador + receipt_confirm) por UM agente forte que executa diretamente todas
as operações: escrita, leitura/análise, planejamento e confirmação de recibos.

Compatibilidade: ALL_AGENTS e agents_override seguem a mesma interface do
orchestrator.py para que os testes e a view de chat possam migrar sem quebrar.
"""

from contextlib import ExitStack, contextmanager
from datetime import date

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents import analytics
from assistant.agents.prompts import ASSISTANT_PROMPT, build_date_instructions
from assistant.agents.tools import (
    add_receipt_item as _add_receipt_item,
)
from assistant.agents.tools import (
    build_pending_receipt_directive,
    create_category,
    create_entry,
    create_memory_rule,
    create_payment_method,
    list_categories,
    list_memory_rules,
    list_payment_methods,
    list_systemic_expenses,
    lookup_memory_async,
    query_balance,
    query_budget_status,
    query_expenses,
    query_installments,
    update_category_budget,
    update_income,
)
from assistant.agents.tools import (
    commit_receipt as _commit_receipt,
)
from assistant.agents.tools import (
    delete_entry as _delete_entry,
)
from assistant.agents.tools import (
    discard_receipt as _discard_receipt,
)
from assistant.agents.tools import (
    list_recent_entries as _list_recent_entries,
)
from assistant.agents.tools import (
    propose_receipt as _propose_receipt,
)
from assistant.agents.tools import (
    set_systemic_amount as _set_systemic_amount,
)
from assistant.agents.tools import (
    update_entry as _update_entry,
)
from finances.services.whatif import HypotheticalItem, simulate_projection_summary

User = get_user_model()

assistant_agent = Agent(
    settings.LLM_ASSISTANT_MODEL,
    deps_type=User,
    system_prompt=ASSISTANT_PROMPT,
)

# Injeta a data de hoje a cada execução (corrige gravação com ano errado).
assistant_agent.instructions(build_date_instructions)


@assistant_agent.instructions
async def pending_receipt_instructions(ctx: RunContext[User]) -> str:
    """Avisa o assistente quando há recibo de foto pendente, forçando o uso das
    ferramentas reais de recibo (commit_receipt, propose_receipt, discard_receipt)
    em vez de responder 'registrei' sem gravar nada."""
    return await sync_to_async(build_pending_receipt_directive)(ctx.deps)


# ── Ferramentas de ESCRITA ──────────────────────────────────────────────────

@assistant_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa disponíveis do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)


@assistant_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return await sync_to_async(list_payment_methods)(ctx.deps)


@assistant_agent.tool
async def register_entry(
    ctx: RunContext[User],
    date: str,
    amount: str,
    description: str,
    category_name: str,
    payment_method_name: str,
) -> str:
    """Cria uma entrada de despesa no sistema.

    Args:
        date: Data no formato AAAA-MM-DD
        amount: Valor em decimal (ex: "42.00", "-150.00" para reembolso)
        description: Descrição da despesa
        category_name: Nome exato da categoria
        payment_method_name: Nome exato da forma de pagamento
    """
    return await sync_to_async(create_entry)(
        user=ctx.deps,
        date_str=date,
        amount_str=amount,
        description=description,
        category_name=category_name,
        payment_method_name=payment_method_name,
    )


@assistant_agent.tool
async def add_category(ctx: RunContext[User], name: str, budget_ceiling: str) -> str:
    """Cria nova categoria de despesa com teto de orçamento."""
    return await sync_to_async(create_category)(ctx.deps, name, budget_ceiling)


@assistant_agent.tool
async def set_category_budget(ctx: RunContext[User], category_name: str, new_ceiling: str) -> str:
    """Atualiza o teto de orçamento de uma categoria existente."""
    return await sync_to_async(update_category_budget)(ctx.deps, category_name, new_ceiling)


@assistant_agent.tool
async def add_payment_method(
    ctx: RunContext[User], name: str, type: str, closing_day: str | None = None
) -> str:
    """Cria nova forma de pagamento (cash, pix, ou credit_card com dia de fechamento)."""
    return await sync_to_async(create_payment_method)(ctx.deps, name, type, closing_day)


@assistant_agent.tool
async def set_income(ctx: RunContext[User], name: str, amount: str, month: str) -> str:
    """Cria ou atualiza uma renda mensal. Mês no formato AAAA-MM-DD."""
    return await sync_to_async(update_income)(ctx.deps, name, amount, month)


@assistant_agent.tool
async def get_systemic_expenses(ctx: RunContext[User]) -> list[str]:
    """Lista os gastos sistemáticos ativos do usuário (despesas recorrentes mensais)."""
    return await sync_to_async(list_systemic_expenses)(ctx.deps)


@assistant_agent.tool
async def set_systemic_amount(ctx: RunContext[User], name: str, amount: str, month: str) -> str:
    """Define o valor de um gasto sistemático para um mês específico.

    Args:
        name: Nome exato (ou aproximado) do gasto sistemático
        amount: Valor em decimal (ex: "300.00")
        month: Mês no formato AAAA-MM-DD (use o primeiro dia do mês)
    """
    return await sync_to_async(_set_systemic_amount)(ctx.deps, name, amount, month)


@assistant_agent.tool
async def list_recent_entries(ctx: RunContext[User], limit: int = 10) -> str:
    """Lista os lançamentos recentes (com id curto) para editar/excluir."""
    return await sync_to_async(_list_recent_entries)(ctx.deps, limit)


@assistant_agent.tool
async def update_entry(
    ctx: RunContext[User], entry_id: str, date: str | None = None,
    amount: str | None = None, description: str | None = None,
    category_name: str | None = None, payment_method_name: str | None = None,
) -> str:
    """Edita um lançamento existente (ache o id com list_recent_entries)."""
    return await sync_to_async(_update_entry)(
        ctx.deps, entry_id, date, amount, description, category_name, payment_method_name
    )


@assistant_agent.tool
async def delete_entry(ctx: RunContext[User], entry_id: str) -> str:
    """Exclui um lançamento existente (id de list_recent_entries)."""
    return await sync_to_async(_delete_entry)(ctx.deps, entry_id)


# ── Ferramentas de RECIBO ───────────────────────────────────────────────────

@assistant_agent.tool
async def propose_receipt(
    ctx: RunContext[User],
    items_by_category: dict[str, list[int]] | None = None,
    payment_method_name: str = "",
    summaries: dict[str, str] | None = None,
) -> str:
    """Prepara (sem gravar) o recibo pendente e mostra a tabela para confirmação."""
    return await sync_to_async(_propose_receipt)(
        ctx.deps, items_by_category, payment_method_name, summaries
    )


@assistant_agent.tool
async def commit_receipt(ctx: RunContext[User]) -> str:
    """Grava (uma vez) o recibo pendente a partir do plano confirmado."""
    return await sync_to_async(_commit_receipt)(ctx.deps)


@assistant_agent.tool
async def discard_receipt(ctx: RunContext[User]) -> str:
    """Descarta o recibo pendente sem gravar."""
    return await sync_to_async(_discard_receipt)(ctx.deps)


@assistant_agent.tool
async def add_receipt_item(
    ctx: RunContext[User], description: str, line_total: str, category: str = ""
) -> str:
    """Adiciona um item ao recibo de foto pendente (ex.: frete). Re-proponha depois."""
    return await sync_to_async(_add_receipt_item)(ctx.deps, description, line_total, category)


# ── Ferramentas de LEITURA / ANÁLISE ───────────────────────────────────────

@assistant_agent.tool
async def get_expenses(
    ctx: RunContext[User], year: int, month: int, category_name: str | None = None
) -> str:
    """Consulta gastos por mês, opcionalmente filtrado por categoria."""
    return await sync_to_async(query_expenses)(ctx.deps, year, month, category_name)


@assistant_agent.tool
async def get_balance(ctx: RunContext[User], year: int, month: int) -> str:
    """Consulta saldo do mês (renda - gastos + retornos)."""
    return await sync_to_async(query_balance)(ctx.deps, year, month)


@assistant_agent.tool
async def get_budget_status(ctx: RunContext[User], year: int, month: int) -> str:
    """Lista categorias acima ou perto do teto de orçamento."""
    return await sync_to_async(query_budget_status)(ctx.deps, year, month)


@assistant_agent.tool
async def get_installments(ctx: RunContext[User]) -> str:
    """Lista parcelamentos ativos com parcela atual e total mensal."""
    return await sync_to_async(query_installments)(ctx.deps)


@assistant_agent.tool
async def get_category_breakdown(ctx: RunContext[User], year: int, month: int) -> str:
    """Quebra de gastos do mês por categoria e por forma de pagamento."""
    return await sync_to_async(analytics.category_breakdown)(ctx.deps, year, month)


@assistant_agent.tool
async def compare_with_previous_month(ctx: RunContext[User], year: int, month: int) -> str:
    """Compara o gasto total do mês com o mês anterior (delta e %)."""
    return await sync_to_async(analytics.compare_months)(ctx.deps, year, month)


@assistant_agent.tool
async def export_monthly_report(ctx: RunContext[User], year: int, month: int) -> str:
    """Gera o relatório CSV do mês (semicolon-delimited, formato do legado)."""
    return await sync_to_async(analytics.monthly_report_csv)(ctx.deps, year, month)


@assistant_agent.tool
async def find_anomalies(ctx: RunContext[User], year: int, month: int) -> str:
    """Sinaliza categorias cujo gasto excede muito a média histórica/trimestral."""
    return await sync_to_async(analytics.detect_anomalies)(ctx.deps, year, month)


@assistant_agent.tool
async def get_category_averages(ctx: RunContext[User], year: int | None = None,
                                month: int | None = None) -> str:
    """Média móvel (3 meses) de gasto por categoria."""
    return await sync_to_async(analytics.category_averages)(ctx.deps, year, month)


# ── Ferramentas de PLANEJAMENTO ─────────────────────────────────────────────

@assistant_agent.tool
async def project_month_end(ctx: RunContext[User], year: int, month: int) -> str:
    """Projeta o gasto até o fim do mês pelo ritmo atual (run-rate)."""
    return await sync_to_async(analytics.project_month_end)(ctx.deps, year, month)


@assistant_agent.tool
async def get_proactive_alerts(ctx: RunContext[User], year: int, month: int) -> str:
    """Retorna alertas de orçamento priorizados (motor determinístico de gatilhos)."""
    return await sync_to_async(analytics.proactive_alerts)(ctx.deps, year, month)


@assistant_agent.tool
async def get_upcoming_obligations(ctx: RunContext[User], year: int, month: int) -> str:
    """Lista obrigações conhecidas do mês: parcelas e gastos sistemáticos."""
    return await sync_to_async(analytics.upcoming_obligations)(ctx.deps, year, month)


@assistant_agent.tool
async def simulate_projection(ctx: RunContext[User], items: list[HypotheticalItem],
                              start_year: int, start_month: int, months: int = 12) -> str:
    """Simula o efeito de lançamentos hipotéticos na projeção (what-if).

    items: lista de hipóteses (despesa avulsa/recorrente, renda, parcelamento,
    empréstimo). start_year/start_month: início do horizonte; months: nº de meses.
    """
    try:
        start = date(start_year, start_month, 1)
    except ValueError:
        return f"Erro: ano/mês inválido ({start_year}/{start_month})."
    return await sync_to_async(simulate_projection_summary)(ctx.deps, items, start, months)


# ── Ferramentas de MEMÓRIA ──────────────────────────────────────────────────

@assistant_agent.tool
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem do usuário.

    Args:
        message: A mensagem original do usuário para buscar correspondências
    """
    return await lookup_memory_async(ctx.deps, message)


@assistant_agent.tool
async def save_memory_rule(ctx: RunContext[User], trigger: str, field: str, value: str) -> str:
    """Salva uma regra de memória a partir de correção do usuário.

    Args:
        trigger: Padrão de correspondência (ex: "cosmos", "posto")
        field: Campo alvo: "category", "payment_method", ou "description"
        value: Valor correto (ex: "Alimentação", "Pix")
    """
    return await sync_to_async(create_memory_rule)(ctx.deps, trigger, field, value)


@assistant_agent.tool
async def get_memory_rules(ctx: RunContext[User]) -> str:
    """Lista todas as regras de memória do usuário."""
    return await sync_to_async(list_memory_rules)(ctx.deps)


# ── Exports ─────────────────────────────────────────────────────────────────

ALL_AGENTS = (assistant_agent,)


@contextmanager
def agents_override(model):
    """Sobrescreve o modelo do assistente (usado em testes para stubar o LLM)."""
    with ExitStack() as stack:
        stack.enter_context(assistant_agent.override(model=model))
        yield
