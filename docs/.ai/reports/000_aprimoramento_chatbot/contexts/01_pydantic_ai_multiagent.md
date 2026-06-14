---
source_url: https://github.com/pydantic/pydantic-stack-demo (Context7 MCP: /pydantic/pydantic-stack-demo)
fetched_at: 2026-06-14
publisher: Pydantic (PydanticAI) — docs via Context7 MCP
used_for: Etapa 3 (sistema de agentes) — padrão de delegação agente→agente, model por agente, usage limits
---

# PydanticAI — delegação de agentes (agent-as-tool)

O codebase já usa PydanticAI (`pydantic-ai>=1.73.0`) com `Agent(settings.LLM_MODEL, deps_type=User, ...)`.
PydanticAI suporta **delegação de agentes nativamente**: um agente expõe outro agente como ferramenta.

## Padrão "agente chama agente" (delegação)

```python
@analysis_agent.tool_plain
async def extra_search(query: str) -> str:
    """Analysis agent can trigger additional searches."""
    result = await search_agent.run(query)
    return result.output
```

Com acesso a dependências (RunContext):

```python
@analysis_agent.tool
async def extra_search_with_context(ctx: RunContext[AbstractAgent], query: str) -> str:
    result = await ctx.deps.run(query)
    return result.output
```

Conclusão para o Expense Tracker: o **orquestrador** pode declarar cada sub-agente
(registrador, analista, planejador) como uma ferramenta (`@orchestrator.tool`). O orquestrador
recebe `deps_type=User`, e ao delegar, repassa `ctx.deps` (o usuário) para o sub-agente.

## Model por agente

`Agent(model_string, ...)` aceita um model string por agente. Logo, o orquestrador pode rodar
num modelo barato/rápido e cada sub-agente num modelo proporcional à complexidade da tarefa.
Como o projeto é provider-agnóstico (`LLM_MODEL` via env), basta introduzir settings adicionais:
`LLM_ORCHESTRATOR_MODEL`, `LLM_WORKER_MODEL`, etc.

## RunContext / deps compartilhadas

```python
@dataclass
class Deps:
    client: AsyncClient
    user_id: int

agent = Agent('openai:gpt-4o', deps_type=Deps)

@agent.tool
async def get_data(ctx: RunContext[Deps], query: str) -> str:
    client = ctx.deps.client
    user_id = ctx.deps.user_id
    ...

@agent.instructions
def add_instructions(ctx: RunContext[Deps]) -> str:
    return f'User ID: {ctx.deps.user_id}'
```

`@agent.instructions` permite injetar instruções dinâmicas (data atual, mês corrente, nome de
usuário) **fora** do system prompt estático — bom para cache e para evitar prompt estático
desatualizado.

## Controle de custo: UsageLimits

```python
from pydantic_ai import UsageLimits

limits = UsageLimits(request_limit=10)       # máx. 10 requisições
result = await agent.run('...', usage_limits=limits)

limits = UsageLimits(total_tokens=5000)      # teto de tokens
```

Crítico para multi-agente: o overhead de tokens cresce rápido (ver contexto 02). `UsageLimits`
no orquestrador evita loops de delegação caros.
