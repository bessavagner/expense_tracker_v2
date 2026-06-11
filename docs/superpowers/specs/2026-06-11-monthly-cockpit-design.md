# Design — Cockpit Mensal (renda, sistemáticos e vencimentos por mês)

**Data:** 2026-06-11
**Status:** aprovado para planejamento

## Contexto e problema

O app está em produção (Cloud Run + Supabase). Ao usar, o usuário (bessavagner)
identificou lacunas de UX/feature:

1. **Não há onde ver/gerir a renda por mês** — renda só existe na aba Configurações, como lista plana.
2. **Bug no Consolidado** — clicar num valor abre um dropdown de detalhe (boa UX), mas clicar de novo **não fecha**.
3. **Renda, gastos sistemáticos e vencimento precisam ser ajustáveis mês a mês**, inclusive **corrigindo meses passados** (valores mudam; lançamentos podem estar errados).

### Estado atual relevante (do código)

- `Income` já tem campo `month` (renda é por-mês). Os campos `is_recurring`/`recurrence_start`/`recurrence_end` **existem mas não são usados** na agregação (`Income.objects.filter(month=...)`).
- `SystemicExpense` é um **template** (nome/categoria/`default_amount`). O valor de cada mês é um `Entry` com `entry_type=SYSTEMIC` (FK `systemic_expense`). Há `SystemicExpense.create_monthly_entry(month, amount)` — hoje só usado em testes; nada materializa automaticamente (os dados atuais vieram do import).
- `PaymentMethodClosingDay` já faz override do dia de fechamento **por mês**; há `resolve_closing_day(month)`. **Sem UI** — só o `closing_day` base é editável em Configurações.
- **Entradas** já navega por mês (abas de mês + seletor de ano) e mostra a tabela de lançamentos + resumo.

## Decisão de arquitetura

**Cockpit Mensal**: a aba **Entradas** (que já navega por mês) vira a tela central do mês.
Em vez de espalhar a edição, tudo do mês fica num lugar só, e funciona para meses passados.
Configurações passa a guardar apenas os **templates** (nome/categoria/forma/padrão); os
**valores por-mês** vivem no cockpit.

Alternativas descartadas: aba "Rendas" dedicada + edições espalhadas (mais telas, contexto fragmentado);
tudo em Configurações com seletor de mês (edição longe da visão do mês).

## Layout (seções empilhadas, presas ao mês selecionado)

```
Entradas   [‹ 01 02 03 … 12 ›]  [ano ▾]

💰 Renda do mês          — linhas Income do mês: add/editar/excluir; Total
🧾 Lançamentos (diversos) — tabela atual de entries (inalterada)
🔁 Gastos sistemáticos    — todos os templates ATIVOS, com valor do mês
📅 Vencimentos (cartões)  — dia de fechamento do mês por cartão
```

## Comportamento por seção

### 1. Renda do mês
- Lista as `Income` com `month` = mês selecionado (nome, valor, ações editar/excluir) + Total.
- **Adicionar renda** com opção **"repetir até dezembro/<ano>"**: cria uma linha `Income` por mês,
  do mês selecionado até dezembro do mesmo ano. Marca `is_recurring=True`,
  `recurrence_start`=mês, `recurrence_end`=dezembro (aproveita os campos existentes; serve de rastro).
  Cada linha é **independente e editável** — corrigir/alterar um mês mexe só naquele mês.
- Editar/excluir opera na `Income` daquele mês (inclui meses passados → correção de erros).
- Resolve o item 1 (ver rendas) sem nova aba no topo.

### 2. Lançamentos (diversos)
- Reaproveita o `_entries_table.html` atual (entries não-sistemáticos do mês). Sem mudança funcional.

### 3. Gastos sistemáticos do mês
- Lista **todos os `SystemicExpense` ativos** do usuário (sempre visíveis, mesmo sem lançamento).
- Para cada um, procura o `Entry` SYSTEMIC do mês (match por `systemic_expense` + `billing_month` no mês):
  - **Existe** → mostra valor (editável) + ação **"não ocorreu"** (exclui o Entry do mês).
  - **Não existe** → mostra "não lançado" + botão **"lançar R$<default_amount>"** (cria via `create_monthly_entry`).
- Editar valor atualiza o `Entry` do mês. Permite ajustar mês a mês e corrigir o passado.

### 4. Vencimentos do mês (cartões)
- Lista formas de pagamento ativas do tipo `credit_card`.
- Para cada uma, mostra o dia de fechamento **efetivo do mês** via `resolve_closing_day(month)`
  (indicando se é o padrão ou override), editável.
- Salvar grava/atualiza `PaymentMethodClosingDay` (unique por método+mês). Limpar/zerar volta ao padrão (remove override).

### 5. Fix: dropdown do Consolidado (independente)
- Causa: a célula tem `hx-get` (carrega detalhe e mostra via `hx-on::after-request`) **e** um `@click` Alpine que tenta dar toggle; no 2º clique o Alpine esconde mas o htmx dispara de novo e o `after-request` reabre. O `preventDefault` do Alpine não cancela o request do htmx.
- Correção: `hx-trigger="click once"` na célula — htmx carrega **uma vez**; cliques seguintes ficam só com o toggle do Alpine (abre/fecha). Sem mudança de backend.

## Backend (alto nível)
- Novas views/partials no app `finances` para as seções renda/sistemáticos/vencimentos do mês, no padrão HTMX existente (GET parcial + POST que devolve o parcial atualizado). Endpoints com escopo de mês (`<year>/<month>`).
- Renda: reusar/estender as views de Income (criar com opção de repetir; editar/excluir por-mês).
- Sistemáticos do mês: view que cruza templates ativos × Entry SYSTEMIC do mês; ações lançar/editar/"não ocorreu".
- Vencimentos: view que lê `resolve_closing_day` e grava `PaymentMethodClosingDay`.
- Página Entradas (`entries_page.html`) passa a incluir as 4 seções, mantendo as abas de mês.

## Testes (TDD, não-negociável)
- Renda: criar com "repetir até dezembro" cria N linhas corretas; editar/excluir afeta só o mês; agregação por mês inalterada.
- Sistemáticos: template ativo sem entry aparece como "não lançado"; "lançar" cria Entry com default; editar atualiza; "não ocorreu" remove; mês passado editável.
- Vencimentos: override grava/atualiza/remove; `resolve_closing_day` reflete o override; constraint método+mês respeitada.
- Dropdown: teste de interação (Playwright) abre/fecha ao clicar duas vezes.

## Fora de escopo
- Recorrência "infinita"/multi-ano (apenas até dezembro do ano corrente).
- Materialização automática de sistemáticos sem ação do usuário.
- Mudanças no Dashboard/Consolidado além do fix do dropdown.
- Multiusuário (segue login único).

## Entregáveis (incrementais, podem virar PRs separados)
1. Fix do dropdown do Consolidado (rápido, isolado).
2. Seção Renda do mês (+ repetir até dezembro).
3. Seção Gastos sistemáticos do mês.
4. Seção Vencimentos do mês.
</content>
