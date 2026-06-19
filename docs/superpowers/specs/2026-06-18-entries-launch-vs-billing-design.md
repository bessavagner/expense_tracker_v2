# Entradas: separar mês de lançamento × mês de pagamento, e redesenhar o painel de totais

Data: 2026-06-18
Status: aprovado (aguardando revisão do spec)

## Problema

Depois da última atualização, a tabela da tela **Entradas** filtra as linhas por
`Entry.billing_month` (mês em que o gasto é *pago*). Para cartão de crédito,
`billing_month` é deslocado para M+1/M+2. Consequência: uma compra de crédito
feita em junho aparece na **tabela de agosto**, não na de junho.

O comportamento esperado pelo usuário:

> O registro do mês aparece na tabela do **mesmo mês** (mês do lançamento);
> apenas o **valor** do gasto é que vai para a soma de "Total gastos" do mês
> seguinte/próximo (mês de pagamento da fatura).

Além disso, o painel de totais precisa ser redesenhado e há um bug de dados na
edição de renda.

## Decisões (confirmadas com o usuário)

1. **Total gastos inclui sistemáticos** — igual ao "total" da tela de Projeção.
2. **Saldo acumulado** acumula **desde o início dos dados** (sem reset anual).
3. **Selo de fatura** nas linhas de crédito: incluir agora.
4. **Meses futuros** usam a projeção de sistemáticos (templates ativos), igual à
   tela de Projeção — os números do painel batem 100% com a Projeção em qualquer mês.
5. **Renda restaurada** para junho/2026 (R$ 8.655) — já executado na friday.

## Modelo mental

Para um mês **M** na tela de Entradas:

| Conceito | Conjunto de dados | Critério |
|---|---|---|
| **Linhas da tabela** | `Entry` REGULAR | `date` cai em M (mês do lançamento/compra) |
| **Total lançado** | mesmas linhas da tabela | soma de `amount` das REGULAR com `date` em M |
| **Total gastos** | todas as entradas que *saem* em M | `billing_month` = M (= "total" da Projeção: regulares + parcelas + sistemáticos) |
| **Renda / Saldo projetado / Acumulado** | da Projeção | linha do mês M em `build_projection` |

Exemplo: compra de crédito em 20/jun (fatura paga em ago).
- **Linha** aparece na tabela de **junho** (`date` em junho).
- **Valor** entra em **Total gastos de agosto** (`billing_month` = agosto).
- Em junho, essa compra conta no **Total lançado** mas **não** no **Total gastos**.

`Entry.billing_month` continua existindo e governando os totais; só deixa de
governar em qual tabela a linha aparece.

## Mudanças

### 1. Tabela de Entradas por mês de lançamento
`EntryListView.get_queryset` (`src/backend/finances/views/entries.py`):
- Trocar o filtro `billing_month=date(year,month,1)` por
  `date__year=year, date__month=month` (mantém `entry_type=REGULAR`, ordenação `-date`).

### 2. Painel de totais
Reescrever `compute_entry_summary(user, year, month)`:
- **total_lancado** + **entry_count**: agregação de `Entry` REGULAR com `date` em M
  (`Sum("amount")`, `Count("id")`).
- **total_gastos / income / saldo_projetado / acumulado**: obtidos da linha de M
  em `build_projection(user, anchor, n, today)`, onde:
  - `anchor` = mês mais antigo com dado (min de `Income.month` e `Entry.billing_month`
    do usuário); se não houver dado, usar M; se `anchor > M`, usar M.
  - `n` = número de meses de `anchor` até M, inclusive.
  - `today = date.today()` (mantém o split passado/futuro do sistemático).
- Remover `total_returns` e `net`.

Remover do dict as chaves antigas (`total_expenses`, `total_returns`, `net`) e
introduzir as novas (`total_lancado`, `total_gastos`, `income`, `saldo_projetado`,
`acumulado`, `entry_count`).

Template `entries/_entries_summary.html`:
- Linhas: **Total lançado**, **Total gastos**, **Renda do mês**, **Saldo projetado**
  (verde se ≥ 0, vermelho se < 0), **Saldo acumulado** (idem), **Entradas** (contagem).
- Remover "Total retornos" e "Líquido".

### 3. Selo de fatura na linha
`entries/_entry_row.html`: a coluna que hoje mostra `billing_month|date:"M"` passa a
mostrar `mm/aa` e a destacar (badge) quando o mês de `billing_month` for diferente
do mês de `date` — deixando explícito que o valor cai numa fatura futura.

### 4. Bug da renda (corrigir na raiz)
`src/backend/finances/forms.py`:
- `IncomeForm` e `CockpitIncomeForm`: widget do campo `month` com
  `forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", ...})` para renderizar
  ISO (senão o `<input type=date>` aparece em branco em pt-BR e o usuário acaba
  gravando a data de hoje).
- `IncomeForm`: normalizar `month` para o dia 1 ao salvar
  (`clean_month`: `return self.cleaned_data["month"].replace(day=1)`), igual ao
  `CockpitIncomeForm.save_for_user` já faz.

`src/backend/finances/views/cockpit.py` — `_income_context`:
- Filtrar renda por **ano+mês** (`month__year=year, month__month=month`) em vez de
  igualdade exata com `date(year,month,1)`, para a renda aparecer no mês dela
  independentemente do dia gravado.

## Testes (TDD)

Atualizar/adicionar:
- `test_views_entries.py`, `features/test_views.py`, `test_entries_live_summary.py`:
  migrar das chaves antigas (`total_expenses/total_returns/net`) para as novas
  (`total_lancado/total_gastos/saldo_projetado/acumulado`).
- Novo: compra de crédito feita em M aparece na tabela de M (linha) mas seu valor
  entra em Total gastos do mês de `billing_month` (não em M).
- Novo: Total gastos do painel == "total" da Projeção para o mesmo mês (inclui
  sistemáticos), em mês atual/passado e em mês futuro.
- Novo: Saldo acumulado do painel == `acumulado` da Projeção ancorada no início dos dados.
- Novo: `IncomeForm` normaliza `month` para dia 1; modal de edição renderiza o
  valor do mês em ISO (campo não vem em branco).
- Novo: renda com `month` em dia ≠ 1 aparece no painel "Renda do mês" do mês correto.

## Fora de escopo
- Mudanças na tela de Projeção, no Consolidado ou no dashboard/API.
- Estrutura de parcelamentos/sistemáticos (apenas leitura para os totais).

## Nota de dados
O valor 8.655 (junho) existe só na friday. `copy-db-to-friday.sh` sobrescreve a
friday com o jarvis (onde junho = 8.000). Sem ação de código aqui — apenas registro.
