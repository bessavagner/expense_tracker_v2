from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents.tools import (
    create_category,
    create_entry,
    create_memory_rule,
    create_payment_method,
    list_categories,
    list_memory_rules,
    list_payment_methods,
    lookup_memory,
    query_balance,
    query_budget_status,
    query_expenses,
    query_installments,
    update_category_budget,
    update_income,
)

# Type alias for dependencies — the User model instance
User = get_user_model()

SYSTEM_PROMPT = """\
Você é um assistente financeiro pessoal. O usuário registra gastos em português brasileiro.

Regras:
- Sempre confirme antes de criar uma entrada. Mostre os campos inferidos e pergunte "Confirma?"
- Use as categorias e formas de pagamento disponíveis (consulte com as ferramentas)
- Se não tiver certeza de algum campo, pergunte ao usuário
- Valores monetários em Real (R$)
- Datas no formato ISO (AAAA-MM-DD) ao chamar ferramentas, \
mas mostre no formato brasileiro (dd/mm/aaaa) ao usuário
- Se a data não for mencionada, use a data de hoje
- Se o usuário disser "sim", "ok", "confirma" após uma proposta de entrada, crie a entrada
- Você pode consultar gastos, saldos e orçamentos do usuário
- Pode criar categorias e formas de pagamento, e atualizar tetos de categorias e rendas
- Sempre confirme antes de modificar configurações (criar categoria, mudar teto, atualizar renda)
- Não exclua categorias ou formas de pagamento pelo chat — direcione ao painel de Configurações
- Quando o usuário perguntar sobre gastos sem especificar mês, use o mês atual
- Para consultas, responda de forma clara e concisa com os valores formatados em Real
- Seja conciso e direto nas respostas
- Antes de propor uma entrada, use check_memory para verificar se há regras memorizadas
- Se a regra tem confiança >= 0.9, use o valor diretamente ao propor a entrada \
(sem mencionar a memória)
- Se a confiança é entre 0.7 e 0.9, mencione a sugestão e pergunte se está certo
- Se a confiança é < 0.7, pergunte ao usuário antes de usar
- Quando o usuário corrigir um campo ("não, isso é Lanche", "use Pix"), \
crie uma regra com save_memory_rule
- Se o usuário perguntar o que você lembra, use get_memory_rules
"""

assistant_agent = Agent(
    settings.LLM_MODEL,
    deps_type=User,
    system_prompt=SYSTEM_PROMPT,
)


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
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem do usuário.

    Args:
        message: A mensagem original do usuário para buscar correspondências
    """
    return await sync_to_async(lookup_memory)(ctx.deps, message)


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
