# Projeção: médias por categoria, dashboard, what-if e análise pelo agente

**Data:** 2026-06-20
**Status:** aprovado para planejamento

## Objetivo

Quatro features conectadas que giram em torno do motor de projeção
(`finances/services/projection.py`), construídas em ordem de dependência e cada
uma com TDD + worktree (regra do projeto):

1. **Média móvel de gasto por categoria** (janela 3 meses, padrão).
2. **Projeção do mês atual no dashboard.**
3. **Simulador what-if**: adicionar lançamentos hipotéticos (sem persistir) e ver
   o efeito na projeção dos outros meses.
4. **Tool do agente de IA** para rodar essa análise what-if a pedido.

Além disso, um requisito transversal (features 1+2+3): **saldo projetado
estimado** e **acumulado estimado** — uma segunda linha da projeção em que os
meses futuros têm as "diversas" preenchidas pela média móvel por categoria, em
vez de só pelo pouco que já foi lançado (ver seção "Track estimado").

Princípio do projeto mantido: **toda a matemática vive em código (serviços
determinísticos); o LLM apenas compõe argumentos e narra** (ver
`assistant/agents/analytics.py`).

## Ordem de implementação

1. **Núcleo overlay**: `whatif.py` (`HypotheticalItem` + `expand_hypotheticals`)
   e o parâmetro `overlay` em `build_projection` (sem o track estimado ainda).
2. **Feature 1**: `category_stats.py` + integrações (detect_anomalies, comando,
   Settings, tool do agente).
3. **Track estimado**: estende `build_projection` com os campos estimados
   (depende da Feature 1).
4. **Feature 3**: what-if na tela de projeção (sessão + overlay + UI).
5. **Feature 2**: projeção + médias + sparkline no dashboard.
6. **Feature 4**: `simulate_projection_summary` + tool no Planejador.

Cada etapa entregável e testada (TDD, worktree) antes da próxima.

---

## Núcleo: overlay de hipóteses no motor de projeção

Base das features 3 e 4. Abordagem: parâmetro opcional `overlay` em
`build_projection`. **Um único caminho de código**; sem overlay = comportamento
atual byte-a-byte.

### `finances/services/whatif.py` (novo)

Modelo Pydantic compartilhado entre UI e agente (pydantic já está disponível via
pydantic_ai; o módulo NÃO importa `pydantic_ai`, só `pydantic`):

```
class HypoType(str, Enum):
    EXPENSE_ONEOFF   # despesa avulsa
    EXPENSE_RECURRING# despesa recorrente (intervalo)
    INCOME           # renda (avulsa ou recorrente)
    INSTALLMENT      # parcelamento (N parcelas)
    LOAN             # empréstimo (entra valor; saem N parcelas)

class HypotheticalItem(BaseModel):
    id: str                  # gerado (uuid4 hex curto) para remoção na UI
    type: HypoType
    label: str               # descrição livre ("carro novo")
    amount: Decimal          # valor principal (despesa/renda/parcela/empréstimo)
    month: date              # mês-base (primeiro dia); billing_month direto
    end_month: date | None   # para recorrentes (inclusive); senão None
    n_installments: int|None # parcelamento/empréstimo
    installment_amount: Decimal | None  # empréstimo: valor da parcela
```

`expand_hypotheticals(items, span_months: list[date]) -> dict[tuple[date,str], Decimal]`
converte cada item em deltas por `(billing_month, kind)`, onde `kind ∈
{"income","installment","regular"}` (espelha `EntryType`/income do motor):

- **EXPENSE_ONEOFF**: `+amount` em `("regular", month)`.
- **EXPENSE_RECURRING**: `+amount` em `regular` para cada mês de `month..end_month`.
- **INCOME**: `+amount` em `income` no mês (ou em cada mês se `end_month`).
- **INSTALLMENT**: `+amount` em `installment` para N meses a partir de `month`.
- **LOAN**: `+amount` em `income` no `month`; depois `+installment_amount` em
  `installment` para `n_installments` meses **a partir de `month` + 1**. Juros
  implícitos na parcela.

Regras: deltas para meses fora de `span_months` (antes da origem/depois do fim)
são **ignorados** com contagem retornada para aviso. Valores em `Decimal`,
quantizados a centavos.

### Mudança em `build_projection`

Assinatura: `build_projection(user, start_month, num_months, today=None, overlay=None)`.
Após montar `entry_totals` e `income_totals` da DB, somar os deltas de
`overlay` (já no formato `{(date, kind): Decimal}`) nesses dicts, antes do laço
`for m in all_months`. `kind=="income"` soma em `income_totals[m]`; demais somam
em `entry_totals[(m, EntryType.X)]`. Nada mais muda — `acumulado` acumula igual.
`overlay=None` ⇒ idêntico ao atual (teste de regressão).

Cada `row` ganha também os campos do **track estimado** (`diverse_estimated`,
`saldo_projetado_estimado`, `acumulado_estimado`) — ver seção dedicada. O
overlay compõe com ambos os tracks (real e estimado).

---

## Feature 1 — média móvel de gasto por categoria

### `finances/services/category_stats.py` (novo)

`category_moving_averages(user, window=3, as_of=None, entry_type=None) -> dict[UUID, Decimal]`
(`entry_type=None` ⇒ todos os tipos, para a média "geral" da Feature 1;
`entry_type="regular"` ⇒ só diversas, usado pelo track estimado da projeção)

- `as_of` default `date.today()`; a janela são os **`window` meses de
  billing completos anteriores** ao mês de `as_of` (exclui o mês corrente
  incompleto). Ex.: as_of jun/2026, window 3 ⇒ mar, abr, mai.
- Soma por categoria só de `amount > 0` (exclui reembolsos), divide pelo nº de
  meses com dado disponível (se histórico < window, usa o que há; se zero, a
  categoria fica fora do dict). Quantiza a centavos.
- Companion `category_moving_averages_named(user, ...) -> list[{id,name,avg,months_used}]`
  para templates/agente.

### Integrações

- **`detect_anomalies`** (`analytics.py`) passa a chamar `category_moving_averages`
  em vez de ler `cat.quarterly_avg`/`historical_avg` (hoje sempre vazios — bug
  latente que faz a detecção nunca disparar). Mantém o fallback de "sem média".
- **Comando** `recompute_category_averages` (`--apply`, dry-run default,
  idempotente): popula `Category.quarterly_avg` (window 3) e `historical_avg`
  (todo o histórico) por consistência. Função ao vivo continua canônica.
- **Settings → aba categorias**: exibe "média R$X/mês (3m)" ao lado do teto.
- **Dashboard**: bloco de médias por categoria (ver Feature 2).
- **Agente**: tool `category_averages(year?, month?)` no Analista, narrando o dict.

---

## Track estimado (saldo/acumulado projetado estimado)

Requisito transversal: a projeção (real) usa, para as "diversas" de cada mês,
apenas o que já foi lançado — então **meses futuros ficam subestimados** (quase
sem diversas). O track estimado preenche isso com a média móvel por categoria.

Por mês, `build_projection` calcula `diverse_estimated`:

- **Meses passados** (billing_month < mês corrente): `diverse_estimated =
  diverse` real (o mês já fechou; usa o lançado).
- **Mês corrente e futuros** (>= mês corrente): `diverse_estimated =` soma das
  médias móveis por categoria **apenas de lançamentos `regular`** (não de
  sistemático/parcela, que já são projetados à parte — evita dupla contagem).
  Usa uma variante `category_moving_averages(..., entry_type="regular")`.

Daí:
- `total_estimated = systemic + installments + diverse_estimated`
- `saldo_projetado_estimado = income - total_estimated`
- `acumulado_estimado` = soma corrida de `saldo_projetado_estimado` desde a
  origem (mesma âncora do acumulado real).

O overlay what-if soma nos dois tracks. O track real permanece como hoje; o
estimado é exibido **em paralelo** (linha/coluna adicional), nunca substitui.
Decisão: a média que alimenta o estimado é **regular-only** para não duplicar
sistemáticos/parcelas. (A média "geral" da Feature 1, exibida em Settings, pode
incluir todos os tipos; são consumos distintos da mesma engine de média —
parametrizados por `entry_type`.)

---

## Feature 2 — projeção do mês no dashboard

`DashboardView.get_context_data` injeta:

- `projection_row`: a linha de `build_projection` do **mês atual** (sistêmico,
  parcelas, diversas, total, renda, saldo_programado, saldo_projetado, acumulado)
  + os campos estimados (`saldo_projetado_estimado`, `acumulado_estimado`).
- `projection_trend`: acumulado **real e estimado** do mês atual + próximos 5
  (6 pontos cada) para as sparklines.
- `category_averages`: de `category_moving_averages_named`.

O card mostra saldo/acumulado **real e estimado** lado a lado.

Template `dashboard/dashboard_page.html`:

- Card **"Projeção do mês"** com a linha completa.
- **Sparkline SVG inline**, renderizada no servidor (polyline a partir dos 6
  pontos normalizados) — sem nova dependência JS.
- Bloco **"Médias por categoria (3m)"**.

---

## Feature 3 — what-if na tela de projeção

Estado **efêmero na sessão**: `request.session["projection_whatif"]` = lista de
`HypotheticalItem` serializados.

### Views/rotas (sob `finances/urls.py`)

- `ProjectionView` lê a sessão, desserializa em `HypotheticalItem`, chama
  `expand_hypotheticals` para o span e passa `overlay` ao `build_projection`.
- `ProjectionWhatifAddView` (POST): valida o form, anexa item à sessão, re-renderiza
  `_projection_table.html` (HTMX swap).
- `ProjectionWhatifRemoveView` (POST, id) e `ProjectionWhatifClearView` (POST):
  idem.

### UI (`projection_page.html` + parcial nova `_whatif_panel.html`)

- Painel "Simulação": seletor de tipo → campos dinâmicos (avulsa: valor+mês;
  recorrente: valor+mês início+fim; renda: igual; parcelamento: valor+nº+mês;
  empréstimo: valor+nº+valor da parcela+mês). Lista de hipóteses ativas com
  remover. Botão **"Limpar"**.
- Tabela mostra **duas linhas de acumulado: base vs simulado**, com o delta por
  mês destacado, para o efeito ficar visível. Quando não há hipóteses, só a base.
- A projeção exibe também as linhas **saldo projetado estimado** e **acumulado
  estimado** (track estimado); com simulação ativa, o estimado também recebe o
  overlay.

---

## Feature 4 — tool do agente (Planejador)

`finances/services/whatif.py` (ou `analytics.py`) ganha
`simulate_projection_summary(user, items, start, months, today=None) -> str`
(determinístico): roda projeção **base** e **simulada**, devolve resumo narrável:

- tabela mês | acumulado base | acumulado simulado | Δ;
- destaques: menor acumulado simulado e em que mês; primeiro mês que fica
  negativo (se houver); Δ total no fim do horizonte.

Exposição:

- Tool `simulate_projection` no `planner_agent` (`assistant/agents/planner.py`),
  recebendo `list[HypotheticalItem]` (o LLM extrai da linguagem natural, ex.: "e
  se eu pegar 20k em 12x de 1900?"). A tool valida e chama o serviço; o agente
  narra. Schema reutiliza `HypotheticalItem`.
- Dica de delegação do orquestrador (`delegate_planejamento`) menciona "simulação
  de cenários / what-if".

---

## Testes (TDD)

- `whatif`: `expand_hypotheticals` por primitiva (incl. empréstimo: renda no mês +
  N parcelas a partir de mês+1) e clamp fora do span.
- `build_projection`: `overlay=None` == baseline (regressão); overlay desloca
  `acumulado` corretamente; renda vs despesa entram no bucket certo.
- **track estimado**: mês passado usa `diverse` real; mês futuro usa soma das
  médias regular-only; `acumulado_estimado` acumula desde a origem; sem dupla
  contagem de sistemático/parcela; sem histórico ⇒ estimado degrada para o real.
- `category_moving_averages`: janela 3, exclui reembolso, exclui mês incompleto,
  histórico curto, categoria sem gasto, filtro `entry_type` (regular-only vs todos).
- `recompute_category_averages`: dry-run vs apply, idempotência.
- Views: contexto do dashboard (row+trend+médias); fluxo de sessão what-if
  (add/remove/clear → tabela reflete; base vs simulado).
- Agente: `simulate_projection` com modelo stubado (PydanticAI) retorna a
  narração a partir do serviço determinístico.

## Fora de escopo (YAGNI)

Cenários nomeados salvos em DB; what-if por querystring compartilhável; juros por
tabela Price (parcela é informada direto); editar hipótese in-place (remove+add).
