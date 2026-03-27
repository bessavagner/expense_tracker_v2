from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents.tools import create_entry, list_categories, list_payment_methods

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
- Para funcionalidades não implementadas (consultas, relatórios, configurações), \
informe educadamente que será adicionado em breve
- Seja conciso e direto nas respostas
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
