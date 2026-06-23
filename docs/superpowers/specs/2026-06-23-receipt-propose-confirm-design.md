# Recibo de foto: fluxo "propor → confirmar → gravar uma vez"

**Data:** 2026-06-23
**Status:** Aprovado (desenho) — aguardando review da spec

## Problema

O fluxo de imagem do assistente **grava na hora E pergunta "Confirma?"** no mesmo
turno (caminho de alta confiança em `assistant/agents/extraction.py:extraction_to_prompt`,
ramo `needs_review=False`). O usuário lê a tabela como proposta, responde **"sim"**,
e esse "sim" cai no **orquestrador** (`assistant_agent`), que re-registra o recibo
por outro caminho (`register_entry` item a item) — **sem passar pela trava do
`ReceiptDraft`**. Resultado: o mesmo cupom é gravado **duas vezes** (observado na
friday: cupom MATEUS, 6 itens → 12 lançamentos, com valores levemente diferentes
porque foi uma 2ª passada do LLM).

Diagnóstico completo confirmado por logs + conversa: dois `POST /api/assistant/chat/`
(foto às 23:05:34 → grava Lote A 23:06:11 + "Confirma?"; "sim" às 23:06:34 → grava
Lote B 23:06:38).

## Princípio do desenho

O turno da **foto nunca grava** — ele lê, categoriza e **salva um plano**
committável no `ReceiptDraft`. A gravação acontece **uma única vez** no "sim",
**determinística** (cria os lançamentos a partir do plano salvo, sem re-chamar o
LLM para re-categorizar). Enquanto houver um recibo **PENDENTE**, as mensagens do
usuário são roteadas para um **fluxo dedicado de confirmação** — não para o
orquestrador genérico.

Decisões do usuário (todas confirmadas):
- **Commit determinístico do plano salvo** (sem re-derivar no "sim").
- **Roteamento determinístico**: existindo `ReceiptDraft` PENDENTE, a próxima
  mensagem vai para o agente de confirmação de recibo.
- **Edição antes do commit** continua suportada (ajustar categoria/pagamento/itens
  re-planeja o draft; só grava no "sim").

## Dados

`ReceiptDraft` (já existe; `payload` é `JSONField`, `status ∈ {PENDING, REGISTERED,
DISCARDED}`). **Sem migração** — adiciona-se uma chave ao payload:

```jsonc
payload["plan"] = {
  "lines": [ {"category": "Alimentação", "description": "MATEUS - grãos…", "amount": "524.86"}, … ],
  "payment_method": "Crédito Santander",   // resolvida (nome exato existente)
  "table": "| Categoria | Itens |\n|---|---|\n| Alimentação | … |"  // tabela limpa p/ exibir
}
```

`plan.lines` é a fonte de verdade do commit: rateio do desconto e soma já
calculados no propose (uma vez). `commit_receipt` só itera `lines` criando `Entry`.

## Componentes

### Ferramentas puras (em `assistant/agents/tools.py`) — unidade-testáveis
- `propose_receipt(user, items_by_category, payment_method_name="", summaries=None) -> str`
  - Valida cobertura dos índices (cada item em **exatamente uma** categoria) —
    reaproveita a validação atual de `register_receipt`.
  - Resolve a forma de pagamento (mesma lógica de `_resolve_by_name`); se ausente/
    ambígua, retorna a pergunta de esclarecimento (não salva plano).
  - Calcula as `lines` (rateio do desconto + descrições `"<loja> - <resumo>"`) —
    núcleo extraído do `register_receipt` atual.
  - **Salva** `payload["plan"]` no draft PENDENTE mais recente.
  - Retorna a tabela limpa (`Categoria | Itens`) + loja/data/pagamento/valor + a
    pergunta "Confirma?". **Não cria `Entry`.**
- `commit_receipt(user) -> str`
  - Pega o `ReceiptDraft` PENDENTE mais recente que tenha `payload["plan"]`.
  - Cria as N `Entry` a partir de `plan.lines` (uma transação).
  - Marca `status=REGISTERED`. Retorna "✅ Registrado: <resumo>".
  - Se não houver pendente/sem plano → retorna mensagem amigável ("Não há recibo
    pendente."). **Idempotente**: 2º "sim" não encontra pendente → não grava.
- `discard_receipt(user) -> str` — marca o PENDENTE mais recente como `DISCARDED`.
- **Refator:** extrair o núcleo de rateio/criação de linhas hoje dentro de
  `register_receipt` para ser reusado por `propose_receipt` (planeja) e
  `commit_receipt` (grava). **Aposentar** o `register_receipt` de gravação em um
  passo (remover a tool do agente; manter helpers reusados).

### Agente dedicado: `receipt_confirm_agent` (`assistant/agents/`)
- Ferramentas: `propose_receipt`, `commit_receipt`, `discard_receipt` + leitura
  (`get_categories`, `get_payment_methods`, `check_memory`, `save_memory_rule`).
- **Não** expõe `register_entry`/`register_receipt`/escrita genérica → no pior
  caso de erro do LLM, a única gravação possível é `commit_receipt` (idempotente,
  a partir do plano salvo).
- Modelo: `LLM_ORCHESTRATOR_MODEL` (leve), como o registrador.
- Prompt: "Há um recibo pendente. Confirmar → `commit_receipt`. Cancelar →
  `discard_receipt`. Mudança de categoria/pagamento/itens → `propose_receipt`
  (re-planeja e re-exibe a tabela). Mostre a tabela limpa; termine com UMA
  pergunta 'Confirma?' enquanto pendente."

## Fluxo (em `assistant/views.py`)

1. **Foto** (`_handle_images`): prepara imagens → `extract_receipt` → cria
   `ReceiptDraft(PENDING, payload=extração)` → roda `receipt_confirm_agent` com um
   prompt de **propor** (chama `propose_receipt`) → SSE com a tabela + "Confirma?".
   **Zero gravação.** (`extraction_to_prompt` passa a instruir `propose_receipt`,
   nunca gravar — unifica os ramos `needs_review`.)
2. **Mensagem com `ReceiptDraft` PENDENTE** (`_handle_json` e o ramo texto de
   `_handle_multipart`): antes do orquestrador, checar se há draft PENDENTE do
   usuário; se sim, **rotear para `receipt_confirm_agent`** (com a mensagem do
   usuário). Ele interpreta sim/não/edição.
3. **Sem draft pendente**: segue para `assistant_agent` (orquestrador) como hoje —
   **inalterado**.

## Casos de borda / erro

- **Extração falha** (`extract_receipt` levanta): tenta **uma vez** com o
  `LLM_VISION_MODEL`; se ainda falhar, responde pedindo para reenviar a foto —
  **sem gravar**. Remove-se o fallback freeform que mandava as imagens direto ao
  registrador e gravava (era a 2ª via de duplicação).
- **"não/cancela"** → `discard_receipt`.
- **Draft pendente "esquecido"**: `propose_receipt`/`commit_receipt` sempre operam
  no PENDENTE **mais recente**; uma nova foto cria um novo PENDENTE. (Sem
  expiração nesta versão — YAGNI.)
- **Forma de pagamento ambígua/ausente**: `propose_receipt` não salva plano e
  devolve a pergunta; o usuário responde, o agente re-`propose` com a forma certa.

## Tratamento de duplicação histórica

Fora de escopo desta mudança (já corrigido manualmente o caso MATEUS na friday).
Opcional/depois: varredura de duplicatas antigas (mesma loja+data+valor em poucos
minutos).

## Testes (TDD)

Unidade (`tools.py`, sem LLM):
- `propose_receipt`: validação de cobertura de índices; rateio correto nas
  `lines`; salva `payload["plan"]`; **não cria nenhum `Entry`**; pagamento
  ambíguo → pergunta, sem plano.
- `commit_receipt`: cria exatamente N `Entry` a partir de `plan.lines`; marca
  `REGISTERED`; **2ª chamada não cria nada** (idempotente); sem pendente → mensagem.
- `discard_receipt`: marca `DISCARDED`; depois disso `commit_receipt` não grava.

Integração (agentes com `TestModel`/override, padrão dos testes do assistant):
- Foto → `propose_receipt` chamado, **0 `Entry`**, draft PENDENTE com plano.
- Mensagem "sim" com draft PENDENTE → roteia para `receipt_confirm_agent` →
  `commit_receipt` → **N `Entry`, uma vez**; draft `REGISTERED`.
- 2º "sim" → nenhum `Entry` novo.
- Sem draft pendente → vai ao orquestrador (rota inalterada).
- **Regressão do bug**: foto + "sim" = N lançamentos (não 2N).

## Fora de escopo

- Confirmação para lançamentos de **texto** simples ("gastei 50 no mercado") —
  seguem imediatos pelo registrador (o bug é específico de foto).
- Expiração de drafts pendentes; varredura de duplicatas históricas.
- Mudanças de UI no `ChatWidget` (o guard de `isStreaming` já evita double-submit).

## Riscos / notas

- O `receipt_confirm_agent` interpretar "sim/não/edição" usa LLM, mas a **escrita
  é determinística** (`commit_receipt` a partir do plano) e **idempotente** — o
  risco de duplicação fica eliminado mesmo com erro do LLM, pois não há tool de
  escrita arbitrária no agente.
- Reaproveitar o rateio existente evita regressão no cálculo de desconto/soma;
  os testes de unidade fixam esse comportamento.
- Backend é assíncrono (views `async`); as tools puras rodam via `sync_to_async`
  como hoje.
