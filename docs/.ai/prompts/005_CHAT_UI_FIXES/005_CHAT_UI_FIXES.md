# Plano de Desenvolvimento — Correções e Features do Chat / UX de Lançamentos

**Data:** 2026-06-15
**Branch alvo:** worktree dedicada → merge em `main` só ao final, com testes passando.
**Escopo:** 9 itens reportados (chat widget + formulário de parcelamento + modal de entrada + cálculo de fatura + edição/exclusão de planos de parcelamento).

---

## Diagnóstico (verificação feita no código)

Arquivos-chave inspecionados:

- `src/backend/frontend/src/cards/ChatWidget.tsx` — componente React do chat (island).
- `src/backend/templates/base.html` — layout global (drawer + `<main>` + mounts React + modal de entrada).
- `src/backend/templates/dashboard/dashboard_page.html` — monta os cards React.
- `src/backend/templates/partials/_modal_entry_form.html` — modal de Nova Entrada (Regular / Parcelamento).
- `src/backend/finances/forms.py` — `InstallmentForm` (campos `total_amount`, `num_installments`, `installment_amount`).
- `src/backend/finances/views/entries.py` — `EntryModalView.post` (cria entrada/parcelamento).
- `src/backend/assistant/views.py` + `assistant/agents/tools.py` — chat SSE e ferramentas que mutam dados.
- `src/backend/finances/services/billing.py` — `compute_billing_month` / `resolve_closing_day` (fatura).
- Referência: `/home/bessa/Documents/trabalhos/bitgov/repositories/finai-bitgov/src/templates/ai/chat_widget.html` — padrão de chat fixável + resize.

### Achados por item

**1. Botão "Minimizar" com comportamento estranho.**
Em `ChatWidget.tsx:460-471`, o container fixo (`w-96 h-[32rem]`) é sempre renderizado; ao minimizar, só o conteúdo (`chatMessages/quickReplies/chatInput`) é ocultado por `{!isMinimized && (...)}` (linha 463). Resultado: a "caixa" de 32rem continua ocupando a tela, vazia, só com o header — exatamente o "conteúdo some mas o chat se mantém". **Fix:** ao minimizar, colapsar para um cabeçalho compacto (altura `auto`/`h-auto`, largura reduzida) ou voltar ao botão flutuante. O correto é a caixa encolher para a barra de título.

**2. Não existe modo "fixar à direita" com resize mútuo.**
Hoje o chat é sempre um overlay `fixed bottom-6 right-6` (`ChatWidget.tsx:461`). Não divide espaço com a view principal. O finai-bitgov implementa isto com: estados `pinned`/`floating`, mover o nó DOM entre `#chat-panel` (no flex `#app-layout`) e `#chat-floating-mount`, larguras em % aplicadas via JS, drag handle com `mousemove`, persistência em `localStorage` (`CHAT_PINNED_KEY`, `CHAT_WIDTH_KEY`), min/max 30–70% e auto-unpin abaixo de 768px (ver `chat_widget.html:564-906`).
**Diferença de arquitetura:** nosso chat é um island React em `base.html:61`, e o `<main>` é Django (`base.html:43`). Não há `#app-layout`/`#chat-panel`. Portanto adaptaremos o padrão: em modo *pinned*, o `ChatWidget` renderiza um painel `fixed` full-height à direita com largura `W`, e aplica `padding-right: W` no container de scroll (`.drawer-content`) para o conteúdo refluir. O drag handle ajusta `W` ao vivo (encolhe a view, cresce o chat e vice-versa).

**3. Ícones 📷 e 🎤 são emojis.**
`ChatWidget.tsx:428` (`📷`) e `:437` (`🎤`). Trocar por SVGs inline modernos (clipe de papel + microfone), no estilo dos SVGs do finai (`chat_widget.html:160-210`).

**4. Clipe de papel deve oferecer escolha (arquivo OU câmera).**
Hoje há um único `<input type="file" accept="image/*" capture="environment">` (`ChatWidget.tsx:391-397`) — `capture` força a câmera no mobile, sem opção de escolher um arquivo existente. **Fix:** o clipe abre um popover/menu com duas ações: "Arquivo" (input sem `capture`) e "Câmera" (input com `capture="environment"`).

**5. Mutação feita pelo assistente não reflete na tela.**
Os cards (`SummaryCard.tsx:13-15`, e demais em `cards/*.tsx`) fazem `fetch` só uma vez no `useEffect` de montagem. As tools mutadoras (`tools.py`: `create_entry`, `create_category`, `update_category_budget`, `create_payment_method`, `update_income`, `set_systemic_amount`) alteram o banco, mas o stream SSE (`assistant/views.py:54-94`) só emite `token`/`done`/`error` — nada sinaliza "dados mudaram". **Fix:** detectar chamadas a tools mutadoras no fim do `run_stream` e incluir `data_changed: true` no evento `done`; o `ChatWidget` dispara um `CustomEvent("data-changed")` no `window`; cards React passam a ouvir e refazer o fetch; páginas HTMX (entries/consolidado) recarregam o conteúdo relevante.

**6. Valor da parcela não é calculado automaticamente.**
`InstallmentForm` (`forms.py:56-104`) expõe `total_amount`, `num_installments` e `installment_amount` como três `NumberInput` independentes; o template (`_modal_entry_form.html:36-42`) só renderiza os campos. O usuário digita os três manualmente. **Fix:** ao preencher total e nº de parcelas, calcular `installment_amount = total / num` automaticamente (mantendo edição manual possível). O modelo já trata o "resto" na última parcela (`installment_plan.py:50-53`), então basta o auto-preenchimento no front.

**7. Modal de entrada não fecha após criar parcelamento (desktop).**
`base.html:91-96` fecha o `#entry-modal` ao receber o evento `entry-saved`. Mas `EntryModalView.post` emite `entry-saved` **apenas** em `EntryEditModalView` (`entries.py:189-192`); na criação (regular **e** parcelamento) o `HX-Trigger` só tem `showToast` (`entries.py:223-234` e `:242-245`). Como o `hx-swap="innerHTML"` troca `#entry-modal-content` por resposta vazia, o `<dialog>` continua aberto e vazio. **Fix:** incluir `"entry-saved": true` no `HX-Trigger` das criações bem-sucedidas (regular e parcelamento). Vale também limpar/zerar o conteúdo. (O item 7 é, na prática, o mesmo bug para entrada regular — corrigir ambos.)

**8. Primeira parcela cai na fatura errada (data da compra × fechamento do cartão).**
A lógica existe: `installment_plan.generate_entries` (`installment_plan.py:44-48`) chama `compute_billing_month(self.date, payment_method.type, resolve_closing_day(...))` para a 1ª parcela e incrementa mês a mês. `compute_billing_month` (`billing.py:20-35`) só desloca para o mês seguinte quando `payment_type == CREDIT_CARD` **e** `entry_date.day > closing_day`. Caso reportado: compra em **12/06** caiu em **junho**. Causas possíveis:
  - (a) a forma de pagamento usada **não é** `CREDIT_CARD` → cai sempre no `first_of_month` (junho); ou
  - (b) o cartão está **sem `closing_day`** (`None`) → idem; ou
  - (c) `closing_day >= 12` (ex.: fecha dia 15) → 12 ≤ 15 → junho está **correto** pela regra atual.
**Confusão conceitual a esclarecer:** o usuário falou em "vencimento" (data de pagamento), mas o sistema modela **fechamento** (`closing_day`). São coisas diferentes; a fatura é definida pelo fechamento.
**Fixes propostos:**
  1. Investigar o dado real do cartão usado nesse parcelamento (tipo + `closing_day`/override do mês) para confirmar qual causa ocorreu.
  2. Revisar a semântica de borda em `compute_billing_month` (`>` vs `>=` no dia de fechamento) e documentar a regra escolhida.
  3. **Transparência na UI:** mostrar no modal de parcelamento (preview) em qual fatura cada parcela cairá, para o usuário ver imediatamente o efeito do fechamento (liga-se ao item 6).
  4. Garantir, via teste, o cenário 12/06 com cartão de fechamento conhecido (ex.: fecha dia 5 → 1ª parcela em julho).

**9. Edição/exclusão do parcelamento como um todo (plano), não parcela a parcela.**
Hoje só existe edição de **uma** parcela (Entry do mês) via `CockpitParcelamentoEditModalView` (`cockpit.py:394-449`), que declara explicitamente: "Editing the parent plan's structure (total / number of parcels) is out of scope" (`:397-398`). Não há: edição dos campos do plano, deslocamento de todas as parcelas, nem exclusão do plano inteiro no frontend. Para corrigir uma data errada o usuário precisaria editar parcela por parcela.
Fatos do modelo que ajudam:
  - `Entry.installment_plan` é `on_delete=CASCADE` (`entry.py:34-36`) → excluir o `InstallmentPlan` apaga todas as parcelas automaticamente. **Exclusão "tudo" é trivial no back.**
  - `InstallmentPlan.generate_entries()` (`installment_plan.py:38-42`) **lança** se já houver entries → para regerar é preciso apagar as parcelas antigas antes.
**Decisão do usuário (confirmada):**
  - *Rollout seguro:* a atualização do código **não pode alterar** parcelamentos já existentes no banco (sem data migration que mute registros; mudanças de schema, se houver, devem ser backward-compatible/nullable).
  - *Edição manual pode regerar tudo* (parcelas passadas e futuras) — não é preciso preservar parcelas passadas.
  - *Escopo:* (a) **deslocar todas as parcelas em N meses**, (b) **excluir o plano inteiro**, (c) **editar campos do plano** (descrição, categoria, forma de pagamento, valor total, nº de parcelas) regerando as parcelas. Manter também a edição de **valor por parcela** que já existe.

---

## Plano de execução

> Convenções do projeto (memória): **TDD obrigatório**, trabalho em **worktree**, gates de qualidade estritos (ruff + pytest no backend; build do frontend Vite). Mobile-first, pt-BR nos rótulos.

### Etapa 0 — Setup
- Criar worktree a partir de `main` (ex.: `feat/chat-ui-fixes`).
- Confirmar DB de dev/testes (pgvector na porta 5433) ativo.
- Baseline: `pytest` + build do frontend verdes antes de começar.

### Etapa 1 — Quick wins de backend/HTMX (itens 7 e base do 6)
**Item 7 — fechar modal na criação.**
- `entries.py` `EntryModalView.post`: adicionar `"entry-saved": true` ao `HX-Trigger` nos dois caminhos de sucesso (regular e installment).
- Teste: `assistant`/`finances` test que verifica o header `HX-Trigger` contém `entry-saved` após POST válido (regular e parcelamento).
- Verificação manual no desktop: criar parcelamento → modal fecha.

**Item 6 (parte modelo/back) — não requer mudança de back** (cálculo é no front). Confirmar que `installment_amount` pode ser derivado e que validação atual aceita o valor calculado.

### Etapa 2 — Item 6: auto-cálculo da parcela (frontend, sem React)
O modal é Django + Alpine (`_modal_entry_form.html` usa `x-data`). Implementar no próprio template:
- Dar `id`/`x-ref` aos inputs de `total_amount`, `num_installments`, `installment_amount` (ajustar widgets em `forms.py` ou via JS por `name=`).
- Lógica Alpine: ao mudar total ou nº de parcelas, setar `installment_amount = (total/num)` arredondado a 2 casas; permitir override manual (se o usuário editar a parcela, não sobrescrever).
- Mostrar dica do "resto na última parcela" quando `total` não divide exato (a regra real está em `installment_plan.py:50-53`).
- Teste: cobertura de unidade da função de cálculo (se extraída p/ JS testável) ou teste e2e leve; no mínimo, teste do servidor garantindo que valores calculados são aceitos pelo `InstallmentForm`.

### Etapa 3 — Itens 1, 3, 4: refator do ChatWidget (floating)
Tudo em `ChatWidget.tsx` (+ pequenos SVGs).
- **Item 1 (minimizar):** quando `isMinimized`, renderizar apenas a barra de título compacta (`h-auto`, largura menor, cantos arredondados), sem reservar 32rem. Garantir transição suave.
- **Item 3 (ícones):** substituir `📷`/`🎤` por SVGs inline (clipe de papel + microfone). Manter `title`/`aria-label` pt-BR e estados `disabled`.
- **Item 4 (clipe → escolha):** botão de clipe abre popover (daisyUI `dropdown`/`menu` ou estado React) com "Arquivo" e "Câmera". Dois inputs file: um sem `capture` (`accept="image/*"`) e um com `capture="environment"`. Reaproveitar `handleImagePick`.
- Testes: testes de componente (se houver runner) ou checklist manual; cobrir minimizar/expandir, abrir popover, selecionar arquivo vs câmera.

### Etapa 4 — Item 2: modo "fixar à direita" + resize mútuo (maior esforço)
Em `ChatWidget.tsx`, inspirado em finai (`chat_widget.html:564-906`), adaptado a React islands:
- Estado: `isPinned`, `panelWidthPx` (ou %), persistidos em `localStorage` (`chat_pinned`, `chat_width`).
- Botão "fixar/desfixar" no header (SVG seta), visível só em `>= 768px` (mobile sempre floating).
- **Pinned:** painel `fixed top-0 right-0 h-screen` com largura `W`; aplicar `padding-right: W` ao container de scroll (`.drawer-content` em `base.html:41`) via efeito React; barra de resize (`cursor-col-resize`) com handlers `mousedown`/`mousemove`/`mouseup` que atualizam `W` (clamp min/max, ex. 320px..60vw) — view encolhe, chat cresce e vice-versa.
- **Floating:** comportamento atual (overlay) — limpar o `padding-right`.
- Cleanup: remover `padding-right` ao desmontar/desfixar e ao cair abaixo de 768px (auto-unpin + listener de `resize`).
- Testes: lógica de clamp/persistência isolável em util testável; checklist manual de resize/persistência/responsividade.

### Etapa 5 — Item 5: reatividade após mutação do assistente
**Backend (`assistant/views.py`):**
- Definir conjunto `MUTATING_TOOLS` (= `create_entry`, `create_category`, `update_category_budget`, `create_payment_method`, `update_income`, `set_systemic_amount`, e a criação de parcelamento se exposta).
- Em `_sse_response`, após o `run_stream`, inspecionar as mensagens/tool-calls do resultado PydanticAI; se alguma tool mutadora foi chamada, incluir `"data_changed": true` no evento `done` (linha ~83-86).
- Teste: simular run com tool mutadora → `done.data_changed == true`; sem mutação → ausente/false.

**Frontend (`ChatWidget.tsx`):**
- No parse do stream (`done`), se `data_changed`, `window.dispatchEvent(new CustomEvent("data-changed"))`.

**Cards React (`cards/*.tsx`):**
- Extrair o fetch para função reutilizável; adicionar `useEffect` que ouve `data-changed` e refaz o fetch. Aplicar em Summary, TopCategories, Evolution, Alerts, RecentEntries, Installments.

**Páginas HTMX (entries/consolidado):**
- Ouvir `data-changed` e recarregar o trecho relevante (ex.: `htmx.trigger`/`location.reload()` como fallback simples). Decisão pragmática: recarregar a seção principal.

### Etapa 5.1 — Item 8: fatura correta do parcelamento
- **Investigar primeiro** (sem código): consultar no banco a forma de pagamento usada no parcelamento de 12/06 — `type` e `closing_day` (e overrides de `monthly_closing_days`). Isso define qual das causas (a/b/c) ocorreu.
- Se causa (a)/(b): o comportamento está "correto" pela regra (não-cartão / sem fechamento). Ação = **UX/educação**: deixar claro no formulário que só cartões com dia de fechamento configurado deslocam a fatura; oferecer configurar o fechamento.
- Se for regra de borda: ajustar `compute_billing_month` (decidir `>` vs `>=`) com teste TDD cobrindo 12/06.
- **Preview de faturas** no modal de parcelamento (Alpine/JS): listar "Parcela 1 → MM/AAAA … Parcela N → MM/AAAA" usando a mesma regra do back (replicada no front ou via endpoint leve de preview). Recomenda-se endpoint de preview para não duplicar a regra.
- Testes: unidade de `compute_billing_month` (cenários cartão fecha dia 5/15/sem fechamento) e de `generate_entries` (sequência de faturas a partir de 12/06).

### Etapa 5.2 — Item 9: gestão do plano de parcelamento (editar/deslocar/excluir)
**Restrição de rollout (obrigatória):** nenhuma data migration que altere `InstallmentPlan`/`Entry` existentes. Se precisar de schema novo, usar campos nullable e default seguro; entries já gerados permanecem como estão até o usuário editar manualmente.

**Backend:**
- Novo método no modelo `InstallmentPlan`:
  - `regenerate_entries()` — apaga as entries do plano e chama `generate_entries()` (contorna o guard de `:41-42`). Atômico (`@transaction.atomic`).
  - `shift_months(n)` — desloca todas as parcelas em `n` meses (ajusta `billing_month` de cada Entry e, se fizer sentido, `plan.date`). Atômico. Decidir: deslocar via recálculo (regerar a partir de nova `date`) vs ajuste direto de `billing_month` — **recomendado ajuste direto** para preservar valores/ordem.
- Nova view de plano (no app `finances`, estilo cockpit/HTMX) com:
  - `GET` modal de edição do **plano** (form `InstallmentPlanForm` reutilizando `InstallmentForm`), pré-carregado a partir do `plan_id`.
  - `POST` editar campos → `regenerate_entries()`; resposta re-renderiza a seção + `HX-Trigger` `showToast` + `entry-saved`.
  - Ação **deslocar ±N meses** (botão/queryparam) → `shift_months(±n)`.
  - Ação **excluir plano** (`DELETE`/POST) → `plan.delete()` (cascade apaga entries) + toast.
- URLs novas: `parcelamento/<uuid:plan_id>/edit-modal/`, `.../shift/`, `.../delete/`.
- Acessar o `plan_id` a partir da linha do cockpit (hoje a linha aponta para o `entry.id`; adicionar acesso ao `row.plan.id`).

**Frontend:**
- No modal de edição do parcelamento, oferecer abas/seções: "Esta parcela" (fluxo atual) e "Plano inteiro" (novo: editar campos, deslocar meses, excluir tudo) — com confirmação para exclusão e para deslocamento (mostra preview das novas faturas, liga-se ao item 8).
- Botão de exclusão do plano inteiro com diálogo de confirmação (daisyUI modal/confirm).

**Testes (TDD):**
- `regenerate_entries`: apaga antigas e recria com novos valores; idempotência e atomicidade.
- `shift_months(+1)`: todas as parcelas avançam um mês; `-1` recua; bordas de ano (dez→jan).
- `delete` do plano remove todas as entries (cascade).
- View: permissões (só dono), `HX-Trigger` com `entry-saved`, re-render da seção.
- **Rollout:** teste/checagem garantindo que nenhuma migration nova altera linhas existentes.

### Etapa 6 — Verificação final
- `ruff check` + `pytest` verdes; build do frontend ok.
- Revisão por `code-reviewer`/`verifier` (passe separado, sem auto-aprovação).
- Checklist manual desktop+mobile dos 7 itens.
- Merge da worktree em `main` somente após tudo verde.

---

## Sequenciamento sugerido e esforço

| Ordem | Item | Risco/Esforço | Observação |
|------|------|---------------|-----------|
| 1 | #7 fechar modal | Baixo | 2 linhas + teste; entrega imediata |
| 2 | #6 auto-parcela | Baixo | Alpine no template |
| 3 | #1 minimizar | Baixo | render condicional |
| 4 | #3 ícones | Baixo | SVGs |
| 5 | #4 clipe→menu | Médio | popover + 2 inputs |
| 6 | #8 fatura parcela | Médio | investigar dado → regra/UX/preview |
| 7 | #9 gestão do plano | Médio-Alto | modelo + views + modal; rollout-safe |
| 8 | #5 reatividade | Médio | back (SSE) + cards + HTMX |
| 9 | #2 fixar+resize | Alto | refator de layout |

Itens 1–5 e 7 isolam-se em `ChatWidget.tsx`/template; recomenda-se PRs/commits atômicos por item.

## Decisões em aberto (com recomendação)
- **#2 mobile:** abaixo de 768px manter sempre floating (auto-unpin). *Recomendado.*
- **#2 unidade de largura:** px com clamp (320px..60vw). *Recomendado* (mais previsível que %).
- **#5 páginas HTMX:** `location.reload()` simples vs refresh granular por HTMX. *Recomendado começar com reload* e refinar se incomodar.
- **#1 minimizado:** colapsar para barra de título (mantém contexto) vs voltar ao botão 🤖. *Recomendado barra de título.*
