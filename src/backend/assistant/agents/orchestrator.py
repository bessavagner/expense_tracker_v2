"""Orquestrador do assistente (Etapa 3 do prompt 004).

Router leve/barato que classifica a intenção e DELEGA para um sub-agente
especializado (Registrador, Analista, Planejador) via delegação nativa do
PydanticAI (agente-como-ferramenta). Mantém o caminho comum curto (1 salto) e
controla custo com ``UsageLimits``. ``assistant_agent`` é o ponto de entrada usado
pela view de chat.

Ver docs/.ai/reports/000_aprimoramento_chatbot/000_aprimoramento_chatbot.md
"""

from contextlib import ExitStack, contextmanager

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from assistant.agents.analyst import analyst_agent
from assistant.agents.planner import planner_agent
from assistant.agents.prompts import ORCHESTRATOR_PROMPT, build_date_instructions
from assistant.agents.receipt_confirm import receipt_confirm_agent
from assistant.agents.registrar import registrar_agent
from assistant.agents.tools import (
    build_pending_receipt_directive,
    build_receipt_context,
)

User = get_user_model()

# Teto de requisições por delegação — contém loops/custo do multi-agente.
_DELEGATION_LIMITS = UsageLimits(request_limit=settings.ASSISTANT_DELEGATION_REQUEST_LIMIT)

orchestrator_agent = Agent(
    settings.LLM_ORCHESTRATOR_MODEL,
    deps_type=User,
    system_prompt=ORCHESTRATOR_PROMPT,
)

# Injeta a data de hoje a cada execução (resolução de referências relativas).
orchestrator_agent.instructions(build_date_instructions)


@orchestrator_agent.instructions
async def pending_receipt_instructions(ctx: RunContext[User]) -> str:
    """Avisa o orquestrador quando há recibo de foto pendente, forçando a
    delegação do registro na confirmação (senão ele responde "registrei" sem
    gravar — ver build_pending_receipt_directive)."""
    return await sync_to_async(build_pending_receipt_directive)(ctx.deps)


@orchestrator_agent.tool
async def delegate_registro(ctx: RunContext[User], request: str) -> str:
    """Delega ESCRITA ao Registrador: registrar/editar lançamentos, rendas, gastos
    sistemáticos, categorias e formas de pagamento.

    Args:
        request: A mensagem/instrução do usuário, repassada ao Registrador.
    """
    # Anexa o recibo pendente (extraído de foto) para o registrador não rodar
    # cego no turno de correção ("separe as categorias").
    context = await sync_to_async(build_receipt_context)(ctx.deps)
    full_request = f"{context}\n\n{request}" if context else request
    result = await registrar_agent.run(
        full_request, deps=ctx.deps, usage=ctx.usage, usage_limits=_DELEGATION_LIMITS
    )
    return result.output


@orchestrator_agent.tool
async def delegate_analise(ctx: RunContext[User], request: str) -> str:
    """Delega CONSULTA/ANÁLISE ao Analista: totais, saldo, quebra por categoria/forma
    de pagamento, comparação de meses, relatório/CSV, anomalias.

    Args:
        request: A mensagem/pergunta do usuário, repassada ao Analista.
    """
    result = await analyst_agent.run(
        request, deps=ctx.deps, usage=ctx.usage, usage_limits=_DELEGATION_LIMITS
    )
    return result.output


@orchestrator_agent.tool
async def delegate_planejamento(ctx: RunContext[User], request: str) -> str:
    """Delega PLANEJAMENTO ao Planejador: projeção de fim de mês, status de teto,
    alertas proativos, obrigações futuras, recomendações, simulação de cenários /
    what-if (empréstimo, nova renda, gasto recorrente).

    Args:
        request: A mensagem/pergunta do usuário, repassada ao Planejador.
    """
    result = await planner_agent.run(
        request, deps=ctx.deps, usage=ctx.usage, usage_limits=_DELEGATION_LIMITS
    )
    return result.output


# Ponto de entrada usado pela view de chat (mantém compatibilidade de import).
assistant_agent = orchestrator_agent

# Todos os agentes do sistema — útil para testes (stub de modelo em bloco).
ALL_AGENTS = (
    orchestrator_agent,
    registrar_agent,
    analyst_agent,
    planner_agent,
    receipt_confirm_agent,
)


@contextmanager
def agents_override(model):
    """Sobrescreve o modelo de TODOS os agentes (orquestrador + sub-agentes).

    Necessário em testes: stubar só o orquestrador deixaria as delegações
    chamando o modelo real dos sub-agentes.
    """
    with ExitStack() as stack:
        for agent in ALL_AGENTS:
            stack.enter_context(agent.override(model=model))
        yield
