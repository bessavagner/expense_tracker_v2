"""Sub-agente REGISTRADOR (Etapa 3 do prompt 004).

Responsável por toda a ESCRITA: registrar/editar lançamentos, rendas, gastos
sistemáticos, e criar categorias/formas de pagamento. Roda num modelo leve/barato.
Segurança: política de confirmação no prompt; escopo por usuário; sem ferramentas
de leitura analítica (privilégio mínimo).
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents.prompts import REGISTRAR_PROMPT, build_date_instructions
from assistant.agents.tools import (
    create_category,
    create_entry,
    create_memory_rule,
    create_payment_method,
    list_categories,
    list_memory_rules,
    list_payment_methods,
    list_systemic_expenses,
    lookup_memory_async,
    update_category_budget,
    update_income,
)
from assistant.agents.tools import (
    register_receipt as _register_receipt,
)
from assistant.agents.tools import (
    set_systemic_amount as _set_systemic_amount,
)

User = get_user_model()

registrar_agent = Agent(
    settings.LLM_ORCHESTRATOR_MODEL,
    deps_type=User,
    system_prompt=REGISTRAR_PROMPT,
)

# Injeta a data de hoje a cada execução (corrige gravação com ano errado).
registrar_agent.instructions(build_date_instructions)


@registrar_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa disponíveis do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)


@registrar_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return await sync_to_async(list_payment_methods)(ctx.deps)


@registrar_agent.tool
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


@registrar_agent.tool
async def register_receipt(
    ctx: RunContext[User],
    date: str,
    store: str,
    payment_method_name: str,
    items_by_category: dict[str, list[str]],
    discount: str = "0",
) -> str:
    """Registra um recibo em N linhas (uma por categoria), rateando o desconto.

    Use isto para FOTOS de cupom com itens de categorias diferentes: o rateio do
    desconto e a soma são feitos de forma determinística (sem cálculo de cabeça),
    garantindo que a soma das linhas bata com o valor pago.

    Args:
        date: Data no formato AAAA-MM-DD
        store: Nome da loja/estabelecimento
        payment_method_name: Nome exato da forma de pagamento
        items_by_category: Mapa categoria -> lista de valores (str decimal) dos
            itens daquela categoria (ex.: {"Roupa": ["9.99"], "Lanche": ["9.99",
            "6.19"]})
        discount: Desconto total do cupom (str decimal); "0" se não houver
    """
    return await sync_to_async(_register_receipt)(
        user=ctx.deps,
        date_str=date,
        store=store,
        payment_method_name=payment_method_name,
        items_by_category=items_by_category,
        discount=discount,
    )


@registrar_agent.tool
async def add_category(ctx: RunContext[User], name: str, budget_ceiling: str) -> str:
    """Cria nova categoria de despesa com teto de orçamento."""
    return await sync_to_async(create_category)(ctx.deps, name, budget_ceiling)


@registrar_agent.tool
async def set_category_budget(ctx: RunContext[User], category_name: str, new_ceiling: str) -> str:
    """Atualiza o teto de orçamento de uma categoria existente."""
    return await sync_to_async(update_category_budget)(ctx.deps, category_name, new_ceiling)


@registrar_agent.tool
async def add_payment_method(
    ctx: RunContext[User], name: str, type: str, closing_day: str | None = None
) -> str:
    """Cria nova forma de pagamento (cash, pix, ou credit_card com dia de fechamento)."""
    return await sync_to_async(create_payment_method)(ctx.deps, name, type, closing_day)


@registrar_agent.tool
async def set_income(ctx: RunContext[User], name: str, amount: str, month: str) -> str:
    """Cria ou atualiza uma renda mensal. Mês no formato AAAA-MM-DD."""
    return await sync_to_async(update_income)(ctx.deps, name, amount, month)


@registrar_agent.tool
async def get_systemic_expenses(ctx: RunContext[User]) -> list[str]:
    """Lista os gastos sistemáticos ativos do usuário (despesas recorrentes mensais)."""
    return await sync_to_async(list_systemic_expenses)(ctx.deps)


@registrar_agent.tool
async def set_systemic_amount(ctx: RunContext[User], name: str, amount: str, month: str) -> str:
    """Define o valor de um gasto sistemático para um mês específico.

    Args:
        name: Nome exato (ou aproximado) do gasto sistemático
        amount: Valor em decimal (ex: "300.00")
        month: Mês no formato AAAA-MM-DD (use o primeiro dia do mês)
    """
    return await sync_to_async(_set_systemic_amount)(ctx.deps, name, amount, month)


@registrar_agent.tool
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem do usuário.

    Args:
        message: A mensagem original do usuário para buscar correspondências
    """
    return await lookup_memory_async(ctx.deps, message)


@registrar_agent.tool
async def save_memory_rule(ctx: RunContext[User], trigger: str, field: str, value: str) -> str:
    """Salva uma regra de memória a partir de correção do usuário.

    Args:
        trigger: Padrão de correspondência (ex: "cosmos", "posto")
        field: Campo alvo: "category", "payment_method", ou "description"
        value: Valor correto (ex: "Alimentação", "Pix")
    """
    return await sync_to_async(create_memory_rule)(ctx.deps, trigger, field, value)


@registrar_agent.tool
async def get_memory_rules(ctx: RunContext[User]) -> str:
    """Lista todas as regras de memória do usuário."""
    return await sync_to_async(list_memory_rules)(ctx.deps)
