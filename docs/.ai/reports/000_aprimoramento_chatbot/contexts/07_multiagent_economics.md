---
source_url: https://www.anthropic.com/engineering/building-effective-agents ; https://blog.bytebytego.com/p/how-anthropic-built-a-multi-agent ; https://arxiv.org/pdf/2604.02460 ; https://www.augmentcode.com/guides/multi-agent-orchestration-architecture-guide
fetched_at: 2026-06-14
publisher: Anthropic Engineering / ByteByteGo / arXiv 2604.02460 / Augment Code (via WebSearch + subagente de pesquisa)
used_for: Etapa 3 — decidir o quão "multi-agente" o sistema deve ser; disciplina de custo
---

# Economia de sistemas multi-agente (quando vale, quando não)

- **Anthropic — "building effective agents"**: comece simples; adicione agentes só quando soluções
  mais simples não bastam. Roteamento = classificar input → prompt/modelo especializado (Q difícil
  → Sonnet; fácil → Haiku). Orchestrator-workers = LLM central decompõe tarefas imprevisíveis.
  "Sistemas agênticos trocam latência e custo por desempenho — avalie quando o trade-off compensa";
  autonomia traz "custos maiores e erros que se acumulam".
- **Custo do multi-agente**: a pesquisa multi-agente da Anthropic usa **~15x** os tokens de um chat
  normal; só compensa quando o valor do resultado é alto **e** a tarefa se divide em ramos
  paralelos independentes. É explicitamente **ruim** para tarefas fortemente interdependentes.
- **Paper 2026 (arXiv 2604.02460)**: single-agent **supera** multi-agente em raciocínio multi-hop
  a orçamento de tokens equivalente.
- **Multiplicador de custo**: um fluxo de $0,50 em teste pode chegar a $50k/mês em 100k execuções —
  o orquestrador adiciona chamadas sobre cada worker.

## Implicação direta para o Expense Tracker
- Um rastreador financeiro familiar é, na maioria, **tarefas baratas e de baixa ramificação**
  (registrar um gasto, consultar um total). → favorecer **router barato + 1 agente capaz com boas
  ferramentas**, não um "enxame".
- O prompt 004 pede explicitamente orquestrador + sub-agentes. **Reconciliação**: implementar
  orquestrador (router leve) + sub-agentes especializados, MAS:
  - caminho comum (registro/consulta simples) deve ser **curto** (orquestrador → 1 sub-agente);
  - sub-agentes de "deep analysis"/relatórios pesados só são acionados quando a tarefa justifica;
  - usar `UsageLimits` p/ conter loops de delegação;
  - empurrar toda matemática para código determinístico, mantendo prompts enxutos.
