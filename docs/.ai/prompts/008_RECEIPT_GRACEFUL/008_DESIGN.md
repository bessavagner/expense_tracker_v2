# 008 — Leitura "graciosa" de recibos (como ChatGPT/Claude)

> Data: 2026-06-23
> Por que o agente erra muito em recibos/screenshots enquanto ChatGPT/Claude acertam:
> (a) a categorização roda no modelo **mini** via um contrato frágil de "partição
> de índices"; (b) o esquema está preso a **cupom fiscal** e quebra em pedidos de
> e-commerce / prints sem total visível. Este trabalho fecha esses gaps **sobre a
> arquitetura propose/commit** já existente (não a substitui).

## 0. Estado atual (já no main — sessão paralela, NÃO refazer)

- `extract_receipt(images, model=None)` (visão forte `LLM_VISION_MODEL`) → `ReceiptExtraction`
  (itens crus, **sem categoria**; `total/discount/amount_paid` default `Decimal("0")`).
- `_handle_images` persiste `ReceiptDraft(payload=extraction)` e roteia para
  `receipt_confirm_agent`.
- `receipt_confirm_agent` (modelo **mini** `LLM_ORCHESTRATOR_MODEL`) com tools
  `propose_receipt` / `commit_receipt` / `discard_receipt` (+ memória/categorias).
- `propose_receipt(user, items_by_category: dict[str,list[int]], payment_method_name, summaries)`
  → `_resolve_receipt_plan` (exige **todos os índices** cobertos exatamente uma vez),
  salva `plan` no draft, mostra tabela + "Confirma?". **Não grava.**
- `commit_receipt(user)` → grava do `plan` salvo, idempotente, marca `REGISTERED`.
- Confirmação por texto/voz roteada a `receipt_confirm_agent` via `_pending_receipt`.

## 1. Objetivo e escopo

Fechar 4 gaps, mantendo propose/commit, ReceiptDraft, idempotência e o roteamento:

1. **Categorizar no modelo FORTE, numa passada** — a extração (visão) atribui a
   categoria de cada item; o mini deixa de categorizar.
2. **Matar o contrato dos "índices"** — `propose_receipt` passa a montar o plano a
   partir das categorias que já vêm nos itens; o mini não precisa enumerar índices.
3. **Generalizar além de cupom fiscal** — `receipt_type` + totais anuláveis; sem
   `amount_paid`/forma visível → **pergunta**, não falha o gate nem inventa.
4. **Passar a taxonomia do usuário** — categorias + formas de pagamento entram no
   prompt da extração (mapeia no real; sugere quando não houver categoria boa).

### Granularidade (decisão do usuário)
**Sempre 1 lançamento por categoria (agregado).** Mantém o comportamento atual de
`_resolve_receipt_plan` (uma linha por categoria, somando itens). Não muda.

### Fora de escopo (YAGNI)
Lançamento por item; QR/NFC-e; mudar o registro por texto; mexer em `commit_receipt`
(grava do plano e já está correto); tocar no roteamento `_pending_receipt`.

## 2. Mudanças por arquivo

### 2.1 `assistant/agents/extraction.py` (#1, #3, #4)

- `ReceiptItem`: novo campo `category: str | None = None` (categoria atribuída pelo
  modelo forte, escolhida da lista do usuário; `None` se incerto).
- `ReceiptExtraction`:
  - novo `receipt_type: str = "fiscal_cupom"` (valores: `fiscal_cupom`,
    `ecommerce_order`, `invoice`, `other`);
  - `total`, `discount`, `amount_paid` viram `Decimal | None` (default `None`);
    quando o valor não estiver visível na imagem, fica `None` (não `0`).
- `receipt_is_consistent`: só compara soma×pago quando `amount_paid is not None`
  (com `discount` tratado como `0` se `None`); retorna `True` quando `amount_paid`
  é `None` (não há o que reconciliar).
- `receipt_needs_review`: continua `True` se sem itens, confiança baixa, ou
  (havendo `amount_paid`) soma não fecha. `amount_paid is None` **não** força review
  por inconsistência — mas força se faltar forma de pagamento E não houver `payment_hint`.
- `extract_receipt(images, categories: list[str] | None = None,
  payment_methods: list[str] | None = None, model=None)`: injeta no prompt a lista de
  **categorias** e **formas** do usuário, pedindo categoria por item + `receipt_type`
  + proposta de forma de pagamento. Mantém o combine-multi-imagem.
- `EXTRACTION_PROMPT` / `EXTRACTION_INSTRUCTION`: generalizar para "recibos/cupons/
  **pedidos de compra** (e-commerce) brasileiros"; pedir `receipt_type`; pedir a
  categoria de cada item **da lista fornecida** (ou `null` se nenhuma servir); deixar
  total/forma `null` quando não visíveis (NÃO inventar); manter anti-injeção.
- `extraction_to_prompt`: apresentar os itens **já com a categoria sugerida** e
  instruir o `receipt_confirm_agent` a chamar `propose_receipt()` **sem
  `items_by_category`** (modo automático); só passar `items_by_category` ao corrigir
  uma categoria. Quando `amount_paid`/forma faltarem, instruir a **perguntar** antes
  de propor. Não exibir índices ao usuário.

### 2.2 `assistant/agents/tools.py` (#2, #3)

- Novo helper `_items_by_category_from_items(items) -> dict[str, list[int]] | str`:
  monta `{categoria: [índices]}` a partir do campo `category` de cada item; retorna
  string de erro se algum item estiver sem categoria (`None`/vazia).
- `_resolve_receipt_plan(user, draft, items_by_category=None, ...)`: se
  `items_by_category` for `None`, deriva via `_items_by_category_from_items` (itens
  já categorizados pelo modelo forte). Se algum item não tiver categoria, devolve erro
  pedindo categorização (o mini então passa um `items_by_category` manual). Resto igual.
- Desconto/total anuláveis: `payload.get("discount")` `None`→`0`; o plano usa a soma
  das linhas como `total` (já é assim) — sem depender de `amount_paid`.
- `propose_receipt(user, items_by_category=None, payment_method_name="", summaries=None)`:
  default `None` → modo automático.

### 2.3 `assistant/agents/receipt_confirm.py` + `prompts.py` (#2, #3)

- `propose_receipt` tool: `items_by_category` opcional (default `None`).
- `RECEIPT_CONFIRM_PROMPT`: por padrão chamar `propose_receipt()` sem mapping; só
  enviar `items_by_category` ao **corrigir** categorização; ao faltar forma/total,
  perguntar; nunca exibir índices.

### 2.4 `assistant/views.py` (#4)

- `_handle_images`: antes de `extract_receipt`, buscar
  `await sync_to_async(list_categories)(user)` e `list_payment_methods(user)` e passar
  a `extract_receipt(prepared, categories=..., payment_methods=...)` (nos dois pontos:
  caminho normal e fallback de visão).

## 3. Testes (TDD)

- **extraction**: `extract_receipt` injeta categorias/formas no prompt (spy no run);
  `ReceiptItem.category` e `receipt_type` no schema; `receipt_is_consistent`/
  `receipt_needs_review` com `amount_paid=None` (não falha por inconsistência);
  com `amount_paid` presente e soma errada → review.
- **tools**: `_items_by_category_from_items` (ok / item sem categoria → erro);
  `propose_receipt()` sem `items_by_category` deriva o plano dos itens categorizados;
  `propose_receipt` com mapping manual continua funcionando (não quebrar
  `test_receipt_flow.py`); desconto/total `None` não quebram o plano.
- **views**: `_handle_images` passa categorias/formas reais ao `extract_receipt`
  (monkeypatch capturando args).
- **regressão**: `test_receipt_flow.py`, `test_extraction.py`, `test_views.py`
  seguem verdes (assinaturas retrocompatíveis: novos params são opcionais/keyword).
- **fixture e-commerce**: cupom sem `amount_paid`/forma (estilo print do ML) →
  extração com `receipt_type="ecommerce_order"`, itens categorizados, `amount_paid=None`
  → não força review por inconsistência; pede forma de pagamento.

## 4. Compatibilidade

- Todos os novos parâmetros são **opcionais/keyword** → `extract_receipt`,
  `propose_receipt`, `_resolve_receipt_plan` retrocompatíveis; testes existentes valem.
- `commit_receipt`, roteamento `_pending_receipt`, `discard_receipt`: intocados.
- Tiering: o trabalho pesado (ler+categorizar+tipo) roda no **modelo forte**; o mini
  só confirma/pergunta e dispara tools determinísticas.

## 5. Sequência sugerida

1. extraction.py (schema + consistência + extract_receipt + prompts) + testes.
2. tools.py (`_items_by_category_from_items` + `_resolve_receipt_plan`/`propose_receipt`
   auto-mode) + testes.
3. receipt_confirm.py + RECEIPT_CONFIRM_PROMPT (opcional mapping, perguntar) + testes.
4. views.py (passar taxonomia à extração) + testes.
5. Regressão completa + fixture e-commerce.
