# Design — Prompt 003: Ajustes de Frontend

**Data:** 2026-06-14
**Branch:** `003-design-adjustments`
**Origem:** `docs/.ai/prompts/003_DESIGN_ADJUSTMENTS/003_DESIGN_ADJUSTMENTS.md`

Ajustes de UI/UX e responsividade antes de avançar para o app mobile. Quatro telas
afetadas: Dashboard, Entradas, Consolidado, Configurações — mais o shell global
(navbar + chat + FABs) que vale para todas.

## Abordagem

Manter o padrão server-rendered **HTMX + Alpine.js + DaisyUI/Tailwind v4**. React
continua só onde já existe (`ChatWidget`). Sem mover lógica nova para React. As
mudanças se concentram em templates, CSS utilitário, um ajuste no `ChatWidget.tsx`
e **uma view nova** (editar lançamento em modal). Isolamento em git worktree;
verificação visual via Playwright contra um runserver dedicado do worktree.

### Decisões (definidas com o usuário)
- **Menu:** hamburguer em **todas** as telas; "Expense Tracker" como cabeçalho dentro do menu.
- **Chat:** **só flutuante** — remover o modo *pinned*/sidebar e o `useChatPinned`.
- **Busca (Entradas):** filtro **instantâneo no cliente** (escopo = mês carregado).

## A. Shell global — `base.html`, `partials/_navbar.html`, `frontend/src/cards/ChatWidget.tsx`

- **Navbar:** um único botão hamburguer (dropdown DaisyUI) visível em todas as larguras.
  O primeiro item do menu é um cabeçalho não-clicável "Expense Tracker"; abaixo, os links
  (Dashboard, Entradas, Consolidado, Configurações, Importar). Remover o `<a>` de marca à
  esquerda, o `<ul>` horizontal `hidden lg:flex` e o botão "+ Nova Entrada". Manter à direita:
  toggle de tema, username, Sair.
- **Remover o `<aside>`** e o wrapper flex de chat em `base.html`. `<main>` vira coluna única
  centralizada (`max-w-7xl mx-auto`). Remove os handlers Alpine `chat:pin/unpin/resize`.
- **ChatWidget.tsx:** remover `isPinned`/`useChatPinned`/modo pinned e o resize handle. Restam
  dois estados: botão fechado e popup flutuante. Botão fechado: ícone **🤖**, opaco, maior no
  desktop (`w-14 h-14 md:w-16 md:h-16`), `fixed bottom-6 right-6 z-50`. Popup: `fixed`, opaco
  (`bg-base-100`), por cima do conteúdo.
- **FAB "+" nova entrada:** botão redondo em `base.html`, `fixed` no canto inferior direito,
  **à esquerda** do FAB do chat (ex.: chat em `right-6`, "+" em `right-24`; ambos `bottom-6`).
  Grande no desktop (`w-14 h-14 md:w-16 md:h-16`). `hx-get` para `finances:entry_modal` →
  `#entry-modal-content` + `showModal()`. Por ficar no `base.html`, **persiste em todas as telas**.

## B. Dashboard — `dashboard/dashboard_page.html`

- Aumentar os dois selects de mês/ano: remover `select-sm`, usar tamanho padrão + largura
  mínima legível (ex.: `min-w-[7rem]`/`min-w-[6rem]`). Manter o `onchange` de navegação.

## C. Entradas — `entries/entries_page.html`, `entries/_entries_table.html`, `cockpit/*`

- **Mês/ano:** substituir as *tabs* de mês por **dois selects iguais aos do Dashboard**
  (mês + ano), navegando para `finances:entries_month`.
- **Reordenar** o conteúdo:
  1. **Resumo** (mover do fim de `_entries_table.html` para o topo) — responsivo.
  2. **Formulário de adicionar** lançamento (`_inline_entry_form.html`) no topo — responsivo.
  3. **Lançamentos** (tabela) e depois **Parcelamentos**.
  4. Ao **final**: Sistemáticos, **Renda** e **Vencimentos** (reordenar os includes HTMX do cockpit).
- **Responsividade das tabelas:** corrigir o vazamento horizontal (contêiner `overflow-x-auto`
  + `min-w-0` nos pais flex/grid). Lançamentos e Parcelamentos passam a renderizar como
  **cards empilhados no mobile** (`block md:table` / card list visível só em `< md`).
- **Busca:** input de filtro instantâneo (Alpine) acima de Lançamentos e de Parcelamentos;
  oculta linhas/cards cujo texto (descrição/categoria/valor) não casa com o termo.

## D. Consolidado — `consolidated/consolidated_page.html`, `consolidated/_consolidated_table.html`

- Select de ano **mais estreito** (ex.: `w-24`).
- **Linha "Total" sempre visível:** `tfoot`/linha total com `position: sticky; bottom: 0`,
  fundo opaco (`bg-base-100`/`bg-base-200`), z acima do corpo. (DaisyUI `table-pin-rows` fixa
  só o `thead`; o sticky do rodapé é CSS adicional.)
- **Animação de scroll:** ao carregar, scroll horizontal **suave e lento** do contêiner
  `overflow-x-auto` para **centralizar a coluna do mês atual** (pequeno script: localizar a
  coluna do mês corrente e `scrollTo({ behavior: 'smooth' })`).

## E. Configurações — `settings/_systemics_tab.html`, `_payment_methods_tab.html`, `_categories_tab.html`, edição de lançamento

- Aplicar o **grid responsivo do form de Renda** (`grid-cols-2 md:grid-cols-4 … items-end`)
  aos forms de adicionar de Sistemáticos, Formas de Pagamento e Categorias.
- Corrigir responsividade das tabelas desses tabs (mesma base da seção C: scroll contido).
- **Editar lançamento vira modal:** o ✏️ em `_entry_row.html` passa a `hx-get` uma view nova
  `finances:entry_edit_modal` que retorna o form preenchido dentro de `#entry-modal`, e abre o
  dialog. Salvar (`hx-post`) atualiza a linha (`#entry-{{id}}` via `outerHTML` + evento de fechar
  o modal) ou re-renderiza com erros. Substitui a edição inline (`_entry_edit_row.html`).

## Testes e verificação

- **TDD (pytest)** na única peça com lógica de backend — a view `entry_edit_modal`:
  GET retorna o form preenchido do lançamento; POST válido salva e devolve a linha atualizada;
  POST inválido devolve o form com erros; respeita ownership do usuário.
- **Verificação visual (Playwright)** contra runserver dedicado do worktree (porta separada),
  em viewport **desktop e mobile**, para: navbar/hamburguer, FABs, chat flutuante, selects,
  reordenação e responsividade de tabelas, busca, sticky total e animação de scroll do Consolidado.

## Fora de escopo
- Busca server-side / multi-mês (decidido: cliente, mês atual).
- Manter o modo pinned do chat (removido).
- Redesign visual além do descrito no prompt; nenhuma mudança de modelo de dados.

## Plano de execução (fases)
1. **A** Shell global (navbar, remove aside, ChatWidget flutuante 🤖, FAB "+").
2. **B** Dashboard (selects).
3. **C** Entradas (selects, reordenação, responsividade, busca).
4. **D** Consolidado (sticky total, select estreito, scroll-para-o-mês).
5. **E** Configurações (forms responsivos, editar lançamento em modal — com TDD).

A cada fase: build do `mount.js` quando houver mudança React + verificação visual.
