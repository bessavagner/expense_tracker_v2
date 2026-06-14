# 000 — Aprimoramento do Chat Bot do Expense Tracker

## 1. Título e contexto

O usuário está migrando o uso do bot financeiro do fluxo legado **Google Sheets + Claude web**
para o **Expense Tracker** (Django + HTMX + React islands, Supabase/pgvector). O bot atual do
projeto (`app assistant`) já existe e funciona, mas é simples: **um único agente PydanticAI**
(`assistant_agent` em `assistant/agents/orchestrator.py`) com ~17 ferramentas, rodando em
`settings.LLM_MODEL` (default `openai:gpt-4o-mini`), memória por regras (`MemoryRule`) e busca
semântica (`MemoryEmbedding`/pgvector).

O prompt 004 (`docs/.ai/prompts/004_ENHANCE_BOT/`) pede um upgrade do bot para ter quatro
comportamentos robustos:

1. **Registro Prático e Rápido**
2. **Organização e Análise de Dados**
3. **Planejamento e Inteligência Financeira**
4. **Interação Proativa**

E define **três etapas obrigatórias**:

1. Aprimorar os prompts atuais para refletir o sistema legado sheets+claude.
2. Atualizar o backend com as queries faltantes para o novo comportamento.
3. Criar um **sistema de agentes** com um **orquestrador** (modelo leve, rápido e barato) e
   sub-agentes responsáveis por tarefas de complexidades diferentes, delegadas pelo orquestrador,
   com prompts robustos e seguros.

Este relatório é o **plano de desenvolvimento** exigido pelo prompt 004 ("Apenas comece a executar
as tarefas após a escrita do plano de desenvolvimento"). Ele consolida a pesquisa de boas práticas
e padrões da indústria de **junho/2026** (web search + MCP/context7 + subagente de pesquisa),
salva em `contexts/`.

## 2. Resumo executivo (TL;DR)

- **Manter PydanticAI e a arquitetura provider-agnóstica.** O codebase NÃO está acoplado a um
  fornecedor; o sistema de agentes deve continuar configurável por env (`LLM_MODEL` →
  `LLM_ORCHESTRATOR_MODEL` + `LLM_WORKER_MODEL`). Não migrar para um SDK específico.
- **Etapa 1 (prompts):** reescrever o system prompt e dividi-lo em prompts por agente, incorporando
  as regras do legado (colapsar itens do mesmo estabelecimento; cigarro→Álcool; refrigerante→Lanche;
  parcelado→tabela de parcelamentos; reembolso=valor negativo; não inventar dados; perguntar só
  quando ambíguo; pular confirmação quando completo e inequívoco; vírgula→hífen em descrição).
- **Etapa 2 (backend):** adicionar **queries/serviços determinísticos** para análise (quebra por
  categoria/forma de pagamento, comparação mês a mês), relatórios (tabela/CSV), planejamento
  (projeção *run-rate* de fim de mês, status de orçamento já existe) e um **motor de gatilhos
  proativos** (limiares de teto, contas/parcelas a vencer). **Toda matemática fica em código**,
  nunca no LLM.
- **Etapa 3 (agentes):** implementar **orquestrador (router leve/barato)** que delega a sub-agentes
  especializados — **Registrador** (escrita, barato), **Analista** (read-only, capaz) e
  **Planejador** (read-only, capaz) — via delegação nativa do PydanticAI (agente-como-ferramenta),
  com `UsageLimits`, **gates de confirmação** para escritas/edições/exclusões e **privilégio mínimo**
  por sub-agente.
- **Tensão honesta:** a evidência de 2026 (Anthropic ~15x tokens em multi-agente; paper mostrando
  single-agent ≥ multi-agente a orçamento igual) recomenda *cautela* com enxames. O prompt 004 pede
  multi-agente explicitamente. **Reconciliação adotada:** implementar o sistema multi-agente pedido,
  mas com **caminho comum curto**, sub-agentes pesados acionados só quando justificado, e disciplina
  de custo (router barato + `UsageLimits` + matemática determinística).
- **Tudo em worktree** (`004-enhance-bot`), **TDD** (não-negociável), merge para a main local só
  após todas as etapas concluídas e testes/ruff verdes.

## 3. Premissas e restrições

- **Stack:** Django 6 + HTMX + React islands; DRF; PydanticAI ≥ 1.73; Supabase Postgres + pgvector;
  testes com pytest (precisa do container pgvector na :5433); ruff (line-length 100, py312).
- **Domínio:** finanças familiares pessoais, pt-BR, valores em R$. Modelos já existentes:
  `Entry` (com `billing_month`, `entry_type`, `installment_plan`, `systemic_expense`), `Category`
  (com `budget_ceiling`), `PaymentMethod` (com `closing_day` + override mensal), `Income`,
  `InstallmentPlan`, `SystemicExpense`. App `assistant`: `ChatMessage`, `MemoryRule`,
  `MemoryEmbedding`, serviço de embedding, view SSE de streaming.
- **Provider-agnóstico:** não acoplar a OpenAI nem a Anthropic; manter seleção por env.
- **TDD obrigatório + gates de qualidade** (memória do projeto: TDD e worktrees são não-negociáveis).
- **Migração de dados** sheets→Supabase ainda em andamento — fora de escopo deste trabalho.
- **Compatibilidade:** não quebrar a API/SSE atual (`assistant/views.py`, `chat_view`) nem os ~309
  testes existentes; preservar o widget React de chat.

## 4. Alternativas avaliadas

### 4.1 Arquitetura de agentes

| Alternativa | Prós | Contras | Veredito |
|---|---|---|---|
| **A. Manter agente único + mais tools** | mais barato, menos latência, menos contexto | não atende o requisito explícito do prompt 004; prompt único fica gigante | Rejeitado (não cumpre o prompt) |
| **B. Orquestrador (router barato) + sub-agentes especializados via delegação PydanticAI** | atende o prompt; separa responsabilidades/prompts/segurança; modelo por complexidade | overhead de tokens/contexto se mal feito | **Escolhido** (com disciplina de custo) |
| **C. Enxame (swarm) de agentes pares** | máxima autonomia | pior custo/latência; ruim p/ tarefas interdependentes; complexidade desnecessária | Rejeitado |

### 4.2 Onde fica a "inteligência" numérica

| Alternativa | Veredito |
|---|---|
| LLM faz aritmética/projeção/anomalia | **Rejeitado** — impreciso e caro |
| **Código determinístico faz a matemática; LLM compõe a query e narra o resultado** | **Escolhido** |

### 4.3 Proatividade

| Alternativa | Veredito |
|---|---|
| LLM decide quando alertar, a cada mensagem | **Rejeitado** — fadiga, quebra de confiança (CHI 2025) |
| **Motor de regras determinístico → gate de prioridade/dedup → LLM só formula a mensagem** | **Escolhido** |

### 4.4 Modelos (junho/2026)

- **Orquestrador/Registrador:** modelo leve/barato — **Claude Haiku 4.5** ($1/$5) ou mini
  (GPT-5.4 mini, Gemini 2.5 Flash). Atende "leve, rápido e barato".
- **Analista/Planejador:** modelo capaz — **Claude Sonnet 4.6** ($3/$15).
- Configurável por env; default mantém compatibilidade com o atual (`openai:gpt-4o-mini`) onde fizer
  sentido, com novas vars para os papéis.

## 5. Análise

### 5.1 Estado atual (o que já existe e pode ser reaproveitado)
- Delegação de agentes é **nativa no PydanticAI** (`@agent.tool` que chama `outro_agent.run()`),
  com `RunContext[deps]` compartilhado e `UsageLimits` para conter custo (ctx `01`).
- O backend já tem: `query_expenses`, `query_balance`, `query_budget_status`, `query_installments`,
  `create_entry`, `create_category`, `update_category_budget`, `create_payment_method`,
  `update_income`, `list_systemic_expenses`, `set_systemic_amount`, memória (`lookup/create/list`).
- Falta para os 4 comportamentos: comparação mês a mês, quebra detalhada por categoria/forma de
  pagamento numa só chamada, export CSV/tabela, projeção de fim de mês, detecção de anomalia simples,
  e o **motor de gatilhos proativos**.

### 5.2 Riscos e mitigações
- **Custo/contexto multi-agente** (ctx `02`,`07`): mitigado por router barato, caminho comum curto,
  `UsageLimits`, prompts enxutos e matemática em código.
- **Segurança de escrita no DB** (ctx `03`; OWASP LLM06:2025 "Excessive Agency"): mitigado por
  **privilégio mínimo** (Analista/Planejador são read-only), **gates de confirmação** para
  criar/editar/excluir/mudar teto/renda/sistemático, escopo por `user=ctx.deps`, validação de saída,
  e separação de conteúdo não-confiável. Exclusão por chat **nunca** sem confirmação explícita.
- **Proatividade irritante** (ctx `08`): mitigada por gatilhos por evento, limiares ajustáveis,
  dedup/prioridade; alinhado ao "bookkeeper silencioso" do legado.
- **Regressão**: TDD + suíte existente + ruff antes do merge.

### 5.3 Reconciliação prompt × evidência
O prompt 004 exige multi-agente; a evidência alerta sobre overhead. A solução escolhida entrega o
multi-agente pedido **e** respeita a evidência: o orquestrador é um *router* barato; o caminho mais
comum (registrar/consultar) é 1 salto; sub-agentes pesados (deep analysis) só entram quando a
mensagem realmente exige; e nenhuma aritmética roda no LLM.

## 6. Recomendação e plano de desenvolvimento

**Decisão:** Arquitetura B (orquestrador router + sub-agentes), matemática determinística, motor de
proatividade determinístico, modelos por papel via env, tudo provider-agnóstico, TDD, na worktree
`004-enhance-bot`.

### Etapa 1 — Aprimoramento dos prompts (reflete o legado sheets+claude)
Arquivos: `assistant/agents/prompts.py` (novo, centraliza prompts), `assistant/agents/orchestrator.py`.
Conteúdo a incorporar (de `contexts/05`,`09` e dos arquivos do legado):
- Persona "bookkeeper preciso e conciso"; confirmação só quando ambíguo/incompleto/valor alto/edição.
- Regras de inferência/categorização do legado: colapsar itens do mesmo estabelecimento numa linha;
  cigarro→Álcool; refrigerante→Lanche; parcelado→parcelamentos; reembolso=negativo; não inventar
  dados; preservar descrição (vírgula→hífen); data relativa ("ontem"); perguntar forma de pagamento
  se faltar.
- Glossário de entidades e regras de integridade (já parcialmente presentes) — manter e endurecer.
- Prompts **por agente** (orquestrador/registrador/analista/planejador), enxutos e seguros.
- **TDD:** testes que verificam que o(s) prompt(s) contêm as regras-chave e que o roteamento textual
  esperado acontece (ex.: mensagem de parcelamento roteia ao registrador com flag de parcelas).

### Etapa 2 — Queries de backend faltantes (matemática determinística)
Arquivos: `assistant/agents/tools.py` + possíveis serviços em `finances/services/`.
Adicionar (com testes pytest primeiro):
- `compare_months` / quebra por categoria e por forma de pagamento numa chamada;
- `monthly_report` → tabela + **export CSV** (semicolon-delimited, sem prefixo R$, vírgula→hífen,
  espelhando o legado);
- `project_month_end` (projeção *run-rate*: gasto-até-agora / dias decorridos × dias do mês), e
  projeção incluindo parcelas e gastos sistemáticos futuros;
- `detect_anomalies` simples (ex.: categoria muito acima da média dos últimos N meses);
- **motor de gatilhos proativos** `compute_proactive_alerts(user, month)` → eventos candidatos
  (% do teto 50/90/100, parcela/sistemático a vencer, anomalia) + gate de prioridade/dedup.
- **TDD:** cada função com testes de borda (mês inválido, sem dados, limiares, reembolsos negativos).

### Etapa 3 — Sistema de agentes (orquestrador + sub-agentes)
Arquivos: `assistant/agents/orchestrator.py` (vira o router), novos
`assistant/agents/registrar.py`, `analyst.py`, `planner.py`; `config/settings.py`
(`LLM_ORCHESTRATOR_MODEL`, `LLM_WORKER_MODEL`).
- **Orquestrador** (`deps_type=User`, modelo leve): classifica intenção e delega via
  `@orchestrator.tool` que chama `sub_agent.run(..., deps=ctx.deps)`. `UsageLimits` no run.
- **Registrador** (escrita; modelo leve): só ferramentas de registro/memória; **gates de
  confirmação** para criar; nunca exclui sem confirmação.
- **Analista** (read-only; modelo capaz): consultas, comparações, relatórios/CSV, anomalias.
- **Planejador** (read-only; modelo capaz): projeções, recomendações de orçamento, alertas proativos
  (formula a mensagem a partir dos eventos do motor da Etapa 2).
- **Segurança** (ctx `03`): privilégio mínimo por agente; validação de saída; escopo por usuário;
  confirmação obrigatória para escritas/edições/exclusões/mudança de teto/renda/sistemático.
- **Compatibilidade:** `assistant/views.py:chat_view` continua chamando o orquestrador via
  `run_stream`; preservar SSE e histórico.
- **TDD:** testes de roteamento (intenção→sub-agente correto), de gate de confirmação (não cria sem
  "sim"), de privilégio (analista não tem tool de escrita), e de `UsageLimits`.

### Verificação e merge
Rodar suíte completa (`uv run pytest`) + `uv run ruff check` na worktree; só então fazer merge de
`004-enhance-bot` na main local. Sem merge com qualquer etapa incompleta ou teste vermelho.

## 7. Referências

### Arquivos de `contexts/`
- `01_pydantic_ai_multiagent.md` — delegação agente→agente, model por agente, `UsageLimits` (MCP/context7).
- `02_orchestrator_worker_patterns.md` — topologias 2026, trade-offs de custo, router barato.
- `03_prompt_injection_db_tools.md` — defesa em profundidade, privilégio mínimo, gates.
- `04_finance_chatbot_proactive.md` — assistentes financeiros 2026, proatividade (Cleo, Eno).
- `05_conversational_expense_logging.md` — parsing por LLM, regras do legado.
- `06_model_selection_2026.md` — preços/modelos por papel (junho/2026).
- `07_multiagent_economics.md` — quando multi-agente (não) vale; disciplina de custo.
- `08_proatividade_ux.md` — design de proatividade que não irrita (CHI 2025, limiares).
- `09_br_parcelado_extracao_memoria.md` — contexto BR (Pix parcelado), extração estruturada, memória.

### Links externos principais
- Anthropic — Building Effective Agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic — Multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- ByteByteGo — multi-agent economics (~15x tokens): https://blog.bytebytego.com/p/how-anthropic-built-a-multi-agent
- arXiv 2604.02460 — single-agent ≥ multi-agent a orçamento igual: https://arxiv.org/pdf/2604.02460
- CometAPI — preços LLM 2026: https://www.cometapi.com/2026-llm-api-pricing-comparison-gpt-5-5-claude-gemini/
- OWASP LLM06:2025 Excessive Agency: https://www.a10networks.com/glossary/llm-excessive-agency/
- Redis — HITL / confirmation gates: https://redis.io/blog/ai-human-in-the-loop/
- arXiv 2509.08646 — plan-then-execute seguro: https://arxiv.org/pdf/2509.08646
- Witness.ai — mitigação de prompt injection: https://witness.ai/blog/prompt-injection-mitigation-strategies/
- Agenta — structured outputs/function calling: https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms
- CHI 2025 — proatividade (trade-offs/timing): https://dl.acm.org/doi/10.1145/3706598.3713357
- Infracost — limiares de alerta de orçamento: https://www.infracost.io/glossary/budget-alerts/
- PocketClear — contexto BR de expense tracking: https://pocketclear.app/blog/expense-tracker-brazil.html
- PaymentExpert — Pix Parcelado (out/2025): https://paymentexpert.com/2025/10/07/brazils-race-to-standardise-pix-parcelado-for-further-instant-payment-growth/
- Vectorize — memória de agentes: https://vectorize.io/articles/best-ai-agent-memory-systems
- PydanticAI (via Context7 MCP): /pydantic/pydantic-stack-demo
