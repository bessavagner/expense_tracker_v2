---
source_url: https://beam.ai/agentic-insights/multi-agent-orchestration-patterns-production ; https://www.anthropic.com/engineering/multi-agent-research-system ; https://github.com/lm-sys/routellm
fetched_at: 2026-06-14
publisher: Beam.ai / Anthropic Engineering / LMSYS RouteLLM (via WebSearch)
used_for: Etapa 3 — escolha do padrão (orchestrator-worker + router) e controle de custo
---

# Padrões de orquestração multi-agente (produção, 2026)

## Topologias dominantes (2026)
1. **Supervisor / hierárquico**
2. **Orchestrator-worker** — *o mais comum, ~70% das implantações em produção*: um agente líder
   coordena e delega a sub-agentes especializados (possivelmente em paralelo).
3. **Swarm** — agentes pares, sem controle central.

## Trade-offs de custo (importante!)
- Multi-agente independente: **~58% de overhead de tokens**; centralizado: **~285%**.
- Multi-agente só compensa quando a tarefa **realmente** se beneficia de especialização,
  paralelismo ou crítica. Para tarefas simples, **um agente com ferramentas** é melhor.
- **Acúmulo de contexto**: o orquestrador acumula contexto de cada worker. Com 4+ workers o
  contexto frequentemente estoura a janela. Um fluxo que custa $0,50 em teste pode chegar a
  $50.000/mês em 100K execuções.

## Router barato + verificação capaz
- Padrão prático: **modelo barato/rápido para o router** + modelo capaz para verificação/tarefa
  complexa → **40-60% menos custo** do que rodar tudo no modelo capaz.
- "Sonnet lê o protocolo de roteamento e delega tão bem quanto Opus a 1/4 do custo."
- RouteLLM: roteia queries simples para modelos menores/baratos, reservando o modelo forte para
  o que precisa.
- Em workloads multi-agente com forte uso de ferramentas/raciocínio, **modelos pequenos atingem
  92-100% de pass-rate** enquanto flagships ficam em ~88% — capacidade de raciocínio de fronteira
  é em boa parte desperdiçada em tarefas de tool-calling. → Reforça usar modelo leve no
  orquestrador/registrador.

## Aplicação ao Expense Tracker
- Adotar **orchestrator-worker** com router barato (ex.: Haiku 4.5 / gpt-4o-mini / Gemini Flash).
- Manter o nº de workers baixo (3): registrador, analista, planejador.
- Usar `UsageLimits` e prompts enxutos para conter o overhead de contexto/tokens.
- Para a maioria das mensagens (registro rápido), o caminho deve ser curto: orquestrador →
  registrador, evitando inflar contexto.
