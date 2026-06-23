# 009 — Colapso para um agente forte único

> Data: 2026-06-23
> A arquitetura orquestrador→sub-agentes roda o caminho CONVERSACIONAL no modelo
> mini (`gpt-5.4-mini`) e fragmenta as ferramentas, dando a sensação de "modelo
> burro": ignora instrução composta ("sim + adiciona o frete + corrige o anterior"),
> não tem ferramenta pra editar lançamento já gravado nem adicionar item fora da foto,
> e o roteamento de recibo pendente prende qualquer pergunta no agente estreito.
> Este trabalho funde os agentes num **único agente forte** com todas as ferramentas.

## Decisões (confirmadas)
- **Modelo:** `gpt-5.4` via novo `LLM_ASSISTANT_MODEL` (default `openai:gpt-5.4`,
  override por env). Um degrau acima do mini, bem abaixo de custo proibitivo; volume é baixo.
- **Incluir ferramentas novas agora:** editar/excluir lançamento + adicionar linha ao
  recibo pendente (o caso do frete).

## O que permanece (determinístico — não muda)
- `extract_receipt` (visão, `LLM_VISION_MODEL`) → `ReceiptExtraction` estruturado.
- `propose_receipt`/`commit_receipt`/`discard_receipt` (idempotente, grava do plano).
- Helpers em `agents/tools.py` (create_entry, _resolve_by_name, leitura/análise, memória).
- Confirmar-antes-de-gravar.

## Arquitetura nova

### Um agente: `assistant_agent`
- Módulo novo `agents/assistant.py` (ou repurpose de `orchestrator.py`).
- `Agent(settings.LLM_ASSISTANT_MODEL, deps_type=User, system_prompt=ASSISTANT_PROMPT)`.
- `instructions`: `build_date_instructions` + `pending_receipt_instructions` (mantém o
  aviso de recibo pendente — agora no único agente).
- **Registra TODAS as ferramentas** (união deduplicada dos 4 agentes) + as 4 novas.
  Cada tool é um wrapper `@assistant_agent.tool` async chamando o helper sync de
  `tools.py` via `sync_to_async` (mesmo padrão atual).

#### Inventário de ferramentas do agente único
- **Escrita (lançamentos/cadastros):** `register_entry`, `add_category`,
  `set_category_budget`, `add_payment_method`, `set_income`, `set_systemic_amount`,
  **`update_entry`** (novo), **`delete_entry`** (novo).
- **Recibo (foto):** `propose_receipt`, `commit_receipt`, `discard_receipt`,
  **`add_receipt_item`** (novo).
- **Leitura/análise:** `get_categories`, `get_payment_methods`, `get_systemic_expenses`,
  `get_expenses`, `get_balance`, `get_budget_status`, `get_installments`,
  `get_category_breakdown`, `compare_with_previous_month`, `export_monthly_report`,
  `find_anomalies`, `get_category_averages`, **`list_recent_entries`** (novo).
- **Planejamento:** `project_month_end`, `get_proactive_alerts`,
  `get_upcoming_obligations`, `simulate_projection`.
- **Memória:** `check_memory`, `save_memory_rule`, `get_memory_rules`.

### Ferramentas novas (helpers em `tools.py`, seguindo o padrão de `create_entry`)
- `list_recent_entries(user, limit=10) -> str`: lista os lançamentos mais recentes do
  usuário com **id curto** (8 chars), data, valor, categoria, forma, descrição — para o
  agente referenciar "o anterior". Ordena por `created_at` desc.
- `update_entry(user, entry_id, date_str=None, amount_str=None, description=None,
  category_name=None, payment_method_name=None) -> str`: atualização parcial; resolve
  categoria/forma por nome (`_resolve_by_name`, lenient); `entry_id` aceita **prefixo**
  do UUID, casado de forma única e **escopado ao usuário** (erro em ambíguo/inexistente);
  salva (deixa `Entry.save()` recomputar `billing_month`; `billing_month_override=False`).
- `delete_entry(user, entry_id) -> str`: resolve por prefixo escopado ao usuário e exclui;
  devolve confirmação com o que foi removido.
- `add_receipt_item(user, description, line_total, category) -> str`: anexa
  `{description, line_total, category}` aos `items` do `ReceiptDraft` PENDENTE e **remove
  qualquer `plan` salvo** (força re-propor com o item novo). Erro se não houver draft
  pendente. (Resolve o caso do frete.)

### Prompt consolidado: `ASSISTANT_PROMPT`
Um system prompt combinando: papel (assistente financeiro pessoal pt-BR que **executa**,
não roteia) + `LEGACY_REGISTRO_RULES` + `CONFIRMATION_POLICY` + `PHOTO_POLICY` +
`MEMORY_POLICY` + orientação de análise/planejamento (resumir de
ANALYST_PROMPT/PLANNER_PROMPT) + `ENTITY_GLOSSARY`. Inclui: como editar/excluir
(use `list_recent_entries` para achar o id, depois `update_entry`/`delete_entry`); como
adicionar item ao recibo (`add_receipt_item` antes de `propose_receipt()`); recibo de
foto continua propor→confirmar→commit. Mantém anti-injeção e "não calcule de cabeça".

### `views.py` — roteamento colapsa
- Todas as mensagens (JSON texto, multipart texto, áudio, e imagem após extração) rodam
  no **único** `assistant_agent`. Remover o ramo `if _pending_receipt → receipt_confirm_agent`
  (o agente único já sabe do recibo pendente via `pending_receipt_instructions`).
- `_handle_images`: continua extraindo + persistindo o draft; depois roda o
  `assistant_agent` com o `extraction_to_prompt` (já existente).
- **`MUTATING_TOOLS`**: trocar `delegate_registro` pelas ferramentas de escrita REAIS:
  `register_entry, commit_receipt, add_category, set_category_budget, add_payment_method,
  set_income, set_systemic_amount, update_entry, delete_entry` (sinaliza `data_changed`).
  (`propose_receipt`/`add_receipt_item` NÃO gravam → fora.)

### Remoções
- `agents/registrar.py`, `agents/analyst.py`, `agents/planner.py`,
  `agents/receipt_confirm.py`; tools de delegação e `_DELEGATION_LIMITS`.
- `agents_override`/`ALL_AGENTS`: simplificam para sobrescrever **o agente único**
  (+ `extraction_agent`). Manter o nome `agents_override` para compat dos testes.
- `assistant_agent` continua sendo o símbolo importado por `views.py`.

## Testes (TDD)
- **Novos helpers** (`test_tools.py`): `list_recent_entries` (formato + escopo por
  usuário), `update_entry` (parcial, prefixo de id, ambíguo/inexistente, recomputa
  billing), `delete_entry` (remove + escopo), `add_receipt_item` (anexa + limpa plan +
  sem-draft → erro).
- **Agente único** (novo `test_assistant.py`, substitui `test_orchestrator.py`): expõe o
  conjunto completo de ferramentas (escrita+leitura+plan+recibo+memória+novas); roda sob
  `TestModel`; recibo pendente injeta a diretiva.
- **`test_data_changed.py`**: `MUTATING_TOOLS` detecta as ferramentas de escrita reais
  (register_entry, commit_receipt, update_entry, delete_entry…), ignora leitura
  (get_balance) e `propose_receipt`.
- **`test_receipt_flow.py`**: trocar as asserções de tool-set de `receipt_confirm_agent`
  para o agente único; manter os testes de propose/commit (helpers intactos).
- **`test_views.py`**: `agents_override` segue funcionando; todas as rotas → agente único;
  fluxo de foto inalterado a não ser pelo agente.
- **`test_prompts.py`**: ajustar asserções que dependiam de prompts por-agente.
- Regressão completa + ruff.

## Compatibilidade / risco
- Helpers de `tools.py` e o fluxo propose/commit **não mudam** (só ganham 4 helpers).
- Maior risco: superfície de ~30 ferramentas num agente — `gpt-5.4` lida bem; se a
  seleção degradar, agrupar/enxugar numa 2ª passada (fora de escopo agora).
- Segurança: todas as tools (inclui escrita) num agente — mitigado por
  `CONFIRMATION_POLICY` + commit determinístico do recibo. App pessoal, aceitável.
- Custo/latência: 1 chamada forte por turno (+ round-trips de tool) — menos saltos que
  router+sub-agente.

## Sequência
1. tools.py: 4 helpers novos + testes.
2. prompts.py: `ASSISTANT_PROMPT` consolidado.
3. agents/assistant.py: agente único + todas as tools + instructions + `agents_override`.
4. views.py: rotear tudo ao agente único + `MUTATING_TOOLS`.
5. Remover sub-agentes + atualizar/reescrever testes.
6. Regressão + ruff.
