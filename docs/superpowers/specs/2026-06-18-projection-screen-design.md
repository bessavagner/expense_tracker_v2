# Tela de Projeção (multi-mês)

**Data:** 2026-06-18
**Escopo:** Tela só-leitura com colunas de meses e linhas de métricas, derivada dos
dados existentes. Item 3 do pedido original. "Não Líquido/Líquido" ficam para uma
fatia futura (dependem de um modelo de saldo não-líquido ainda a definir).

## Contexto

O usuário mantém uma planilha (Sheets) com meses nas colunas e métricas nas linhas
(despesas sistêmicas, parcelamentos, gastos programados, despesas diversas, gastos
totais, renda, % da renda, saldo programado, SALDO PROJETADO, acumulado, e
não-líquido/líquido). Quer replicar isso no app. Decidido: tela **só-leitura
calculada** (sem edição de células).

## Intervalo de meses

Seletor de **mês inicial + número de meses**. Padrão = **mês atual −1, 14 meses**
(janela móvel cobrindo −1…+12). Query params: `start=YYYY-MM` e `months=N`
(clamp `months` a um intervalo são, ex. 1..24).

## Cálculo de cada linha (para o mês M, `billing_month = 1º dia de M`)

"Mês atual" = `date.today()` truncado ao 1º dia. "Futuro" = M > mês atual.

| Linha | Cálculo |
|---|---|
| **Despesas sistêmicas** | M ≤ atual: soma das entradas `SYSTEMIC` com `billing_month=M`. M futuro: soma de `SystemicExpense.default_amount` dos templates `is_active=True` |
| **Parcelamentos** | Soma das entradas `INSTALLMENT` com `billing_month=M` (já materializadas no banco, passado e futuro) |
| **Gastos programados** | sistemáticas + parcelamentos |
| **Despesas diversas** | Soma das entradas `REGULAR` com `billing_month=M` |
| **Gastos totais** | gastos programados + despesas diversas |
| **Renda** | Soma de `Income.amount` com `month=M` |
| **% da renda** | `gastos_totais / renda` (None quando renda = 0; UI mostra "—"). Marcação vermelha quando ≥ 100% |
| **Saldo programado** | renda − gastos programados |
| **SALDO PROJETADO** | renda − gastos totais |
| **Acumulado** | soma corrente (cumsum) do SALDO PROJETADO ao longo da janela exibida; começa em 0 antes da 1ª coluna |

Conferência contra a planilha: Acumulado(nov) = SALDO(nov); Acumulado(dez) =
SALDO(nov)+SALDO(dez). ✓

### Regra "passado vs futuro" para sistemáticas
A distinção evita ambiguidade de mês parcialmente lançado: meses ≤ atual usam o que
**de fato** foi lançado (entradas SYSTEMIC); meses estritamente futuros usam a
**projeção** dos templates ativos. Parcelamentos e diversas usam sempre as entradas
reais (parcelas futuras já existem; diversas futuras simplesmente costumam ser 0).

## Arquitetura

### Serviço — `finances/services/projection.py`
`build_projection(user, start_month: date, num_months: int) -> list[dict]`

- Função **pura** e determinística; recebe `start_month` (1º dia) e devolve uma
  lista de dicts por mês, cada um com: `month` (date), `systemic`, `installments`,
  `programmed`, `diverse`, `total`, `income`, `pct_income` (Decimal|None),
  `saldo_programado`, `saldo_projetado`, `acumulado`.
- **Uma passada agregada** no banco (sem N queries por mês):
  - Entradas no intervalo `[start, end]` agrupadas por `billing_month` e
    `entry_type` via `.values(...).annotate(Sum)`.
  - `Income` no intervalo somado por `month`.
  - Templates `SystemicExpense` ativos somados uma vez (constante para meses
    futuros).
- Acumulado calculado iterando a lista em ordem cronológica.

### View — `finances/views/projection.py`
`ProjectionView(HtmxLoginRequiredMixin, TemplateView)`

- Rota `/projection/` (name `projection`), adicionada em `finances/urls.py`.
- Lê `start`/`months` dos query params; default mês atual −1 / 14; valida e faz
  clamp. Passa `rows = build_projection(...)` ao contexto + meta pro seletor.
- `template_name = "projection/projection_page.html"`,
  `htmx_template_name = "projection/_projection_table.html"` (re-render ao trocar
  o seletor, padrão já usado nas outras telas via `HtmxLoginRequiredMixin`).

### Templates
- `projection/projection_page.html` — extends base, título, seletor de início + nº
  de meses, inclui o partial.
- `projection/_projection_table.html` — tabela larga: 1ª coluna fixa (rótulos das
  linhas), uma coluna por mês, scroll horizontal (mesmo padrão do Consolidado).
  Formatação monetária via filtro `money`; `%` da renda com cor; SALDO PROJETADO
  negativo em vermelho.

### Navegação
- Item "Projeção" no `templates/partials/_navbar.html` (link + drawer), com
  `active` quando `url_name == 'projection'`.

## Fora de escopo
- **Não Líquido / Líquido** — saldo de investimento não-líquido (hoje: limite
  depositado no C6). É um *estoque* (saldo que persiste e é editado), não um fluxo;
  modelo a definir (provável `SaldoNaoLiquido {mês, valor, nota}` com carry-forward).
  Próxima fatia.
- Edição de células / estimativas manuais (tela é só-leitura).

## Testes (TDD primeiro)
- **Serviço:**
  - Mês com entradas conhecidas (systemic+installment+regular+income) → cada linha
    com o valor esperado; `programmed`, `total`, saldos e `pct_income` corretos.
  - Mês **futuro** sem entradas SYSTEMIC → projeta dos templates ativos; parcelas
    futuras entram via entradas INSTALLMENT.
  - `acumulado` é cumulativo na ordem da janela.
  - renda = 0 → `pct_income is None`.
  - Escopo por usuário (entradas de outro usuário não entram).
- **View:** exige login; respeita `start`/`months`; faz clamp de `months` inválido;
  renderiza o partial em requisição htmx.

## Verificação final
- `pytest` verde, `ruff check` limpo.
- Verificação manual no navegador: valores batem com lançamentos reais de alguns
  meses; seletor muda o intervalo; coluna fixa + scroll horizontal funcionam.
