---
source_url: https://www.cometapi.com/2026-llm-api-pricing-comparison-gpt-5-5-claude-gemini/ ; claude-api skill reference (Anthropic, cache 2026-06-04)
fetched_at: 2026-06-14
publisher: CometAPI / Anthropic (claude-api skill)
used_for: Etapa 3 — escolha de modelos por papel (orquestrador barato vs worker capaz)
---

# Seleção de modelos (junho/2026)

Preços aproximados por 1M tokens (input/output). **Reconfirmar na página do provedor antes de
fixar orçamento.** Valores de referência da skill `claude-api` (Anthropic) são autoritativos para
Claude.

| Papel | Modelo | Input / Output | Notas |
|---|---|---|---|
| Router / registro rápido / classificação | **Claude Haiku 4.5** | $1 / $5 | 200K ctx; ideal p/ classificação/alto volume |
| Minis baratos (alternativa de router) | GPT-5.4 mini (~$0.25/$2), Gemini 2.5 Flash (~$0.30/$2.50) | muito baixo | bom p/ extração de alto volume |
| Análise / planejamento (worker capaz) | **Claude Sonnet 4.6** | $3 / $15 | rotear análise/projeção complexa aqui |
| Topo (raro, deep analysis) | **Claude Opus 4.8** | $5 / $25 | reservar p/ relatórios pesados |

## Recomendação para o Expense Tracker
- **Orquestrador/registrador**: modelo leve/barato (Haiku 4.5 ou mini). Atende o requisito do
  prompt 004 ("orquestrador: modelo leve, rápido e barato").
- **Analista/planejador**: modelo capaz (Sonnet 4.6) — só acionado quando a tarefa exige.
- **Matemática/projeção/detecção de anomalia**: **código determinístico** no backend (Etapa 2),
  nunca no LLM.
- **Provider-agnóstico**: o projeto usa PydanticAI com `LLM_MODEL` via env. Introduzir
  `LLM_ORCHESTRATOR_MODEL` e `LLM_WORKER_MODEL` (defaults sensatos) preserva a flexibilidade de
  apontar para Claude, OpenAI ou Gemini sem mudar código. **Não** acoplar a um SDK específico.
