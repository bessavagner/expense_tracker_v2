"""Agente de CONFIRMAÇÃO de recibo de foto (propor → confirmar → gravar uma vez).

Privilégio mínimo: sem ferramentas de escrita genérica. A única gravação é
commit_receipt (determinística, a partir do plano salvo no ReceiptDraft).
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents.prompts import RECEIPT_CONFIRM_PROMPT, build_date_instructions
from assistant.agents.tools import (
    commit_receipt as _commit_receipt,
)
from assistant.agents.tools import (
    create_memory_rule,
    list_categories,
    list_payment_methods,
    lookup_memory_async,
)
from assistant.agents.tools import (
    discard_receipt as _discard_receipt,
)
from assistant.agents.tools import (
    propose_receipt as _propose_receipt,
)

User = get_user_model()

receipt_confirm_agent = Agent(
    settings.LLM_ORCHESTRATOR_MODEL,
    deps_type=User,
    system_prompt=RECEIPT_CONFIRM_PROMPT,
)
receipt_confirm_agent.instructions(build_date_instructions)


@receipt_confirm_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)


@receipt_confirm_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return await sync_to_async(list_payment_methods)(ctx.deps)


@receipt_confirm_agent.tool
async def propose_receipt(
    ctx: RunContext[User],
    items_by_category: dict[str, list[int]],
    payment_method_name: str = "",
    summaries: dict[str, str] | None = None,
) -> str:
    """Prepara (sem gravar) o recibo pendente e mostra a tabela para confirmação."""
    return await sync_to_async(_propose_receipt)(
        ctx.deps, items_by_category, payment_method_name, summaries
    )


@receipt_confirm_agent.tool
async def commit_receipt(ctx: RunContext[User]) -> str:
    """Grava (uma vez) o recibo pendente a partir do plano confirmado."""
    return await sync_to_async(_commit_receipt)(ctx.deps)


@receipt_confirm_agent.tool
async def discard_receipt(ctx: RunContext[User]) -> str:
    """Descarta o recibo pendente sem gravar."""
    return await sync_to_async(_discard_receipt)(ctx.deps)


@receipt_confirm_agent.tool
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem."""
    return await lookup_memory_async(ctx.deps, message)


@receipt_confirm_agent.tool
async def save_memory_rule(
    ctx: RunContext[User], trigger: str, field: str, value: str
) -> str:
    """Salva uma regra de memória a partir de correção do usuário."""
    return await sync_to_async(create_memory_rule)(ctx.deps, trigger, field, value)
