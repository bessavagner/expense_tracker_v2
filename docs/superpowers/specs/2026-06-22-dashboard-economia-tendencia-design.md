# Dashboard: Economia do mês + Tendência de gasto diário

**Data:** 2026-06-22
**Status:** Aprovado (desenho)

## Objetivo

Adicionar dois indicadores ao dashboard:

1. **Economia do mês** — quanto se gastou *a menos* com despesas diversas em
   relação ao padrão histórico habitual.
2. **Tendência de gasto diário** — série temporal do gasto diário suavizada por
   uma estatística robusta a outliers (mediana móvel + banda de variabilidade),
   com seletor de período.

## Contexto do código existente

- **"Diversas" = lançamentos `REGULAR`** (`Entry.entry_type == EntryType.REGULAR`),
  excluindo entradas de ajuste `#AJUSTE-SALDO` (categoria contendo "ajuste",
  case-insensitive). Constante: `ADJUSTMENT_CATEGORY_PATTERN` em
  `finances/services/category_stats.py`.
- Já existe `monthly_diverse_total_median(user, window=6, as_of=None)` em
  `finances/services/category_stats.py:36` — mediana robusta do total de diversas
  por mês ao longo de `window` meses completos anteriores a `as_of`, excluindo
  ajustes e meses sem gasto. **Reusar diretamente.**
- Modelo `Entry` (`finances/models/entry.py`): campos relevantes `amount`
  (Decimal), `date` (DateField, data real do lançamento), `billing_month`
  (DateField, 1º dia do mês de contabilização), `category` (FK), `entry_type`.
- Dashboard: `DashboardView` (TemplateView, `views/dashboard.py`) renderiza
  `dashboard/dashboard_page.html`, que monta uma ilha React (Recharts) consumindo
  endpoints DRF em `finances/api/views.py` (`SummaryView`, `EvolutionView`,
  `ProjectionCardView`, etc.). Seletor de mês/ano vive no template.

## Decisões de desenho

- **Economia** = `mediana_histórica_robusta(diversas) − gasto_real_diversas(mês)`.
  Base histórica robusta a outliers por construção (mediana).
- **Tendência** = linha de **mediana móvel** + **banda IQR (p25–p75)**, com
  dropdown de período **7 / 15 / 30 / 90 dias**.
- Banda = **IQR (p25–p75)**, não MAD (mais intuitivo de ler).
- Tendência **ignora o seletor de mês** do dashboard: sempre "últimos N dias até
  hoje" (tendência é inerentemente recente).
- Janela da mediana histórica = **6 meses** (default já usado no projeto).

---

## Indicador 1 — Economia do mês

### Backend: serviço

Nova função em `finances/services/category_stats.py`:

```python
def diverse_savings_for_month(user, billing_month, window=6) -> dict:
    """Economia em diversas vs o padrão histórico robusto.

    baseline = monthly_diverse_total_median(user, window, as_of=billing_month)
    actual   = Σ amount dos REGULAR (>0, exclui #AJUSTE) com billing_month dado
    economia = baseline - actual   (>0 => gastou menos que o habitual)
    """
```

Retorno:
```python
{
    "baseline": Decimal,      # mediana histórica das diversas
    "actual": Decimal,        # gasto real de diversas no mês
    "economia": Decimal,      # baseline - actual
    "has_baseline": bool,     # False quando baseline == 0 (sem histórico)
}
```

- `actual` usa `billing_month` (consistente com `SummaryView`), filtra
  `entry_type=REGULAR`, `amount__gt=0`, exclui categoria com "ajuste".
- `has_baseline = baseline > 0`.

### Backend: API

Novo `DiverseSavingsView` (APIView, `IsAuthenticated`) em `finances/api/views.py`.
Aceita `?year=&month=` (via `_get_month_params`). Resposta:
```json
{ "baseline": "1234.56", "actual": "1000.00", "economia": "234.56", "has_baseline": true }
```
Registrar rota junto às demais rotas de API.

### Frontend

Card numérico no grid do dashboard, mesmo estilo dos KPIs existentes:
- `economia > 0` → verde, "Economia R$ X" + legenda "habitual: R$ baseline".
- `economia < 0` → âmbar, "R$ |economia| acima do habitual".
- `has_baseline == false` → "sem base histórica ainda".

---

## Indicador 2 — Tendência de gasto diário

### Backend: serviço

Novo módulo `finances/services/daily_trend.py`:

```python
def daily_spend_trend(user, period=30, as_of=None) -> list[dict]:
    """Série diária de gasto suavizada por mediana móvel + banda IQR."""
```

Lógica:
1. `as_of = as_of or date.today()`. Janela do eixo X = últimos `period` dias até
   `as_of` (inclusive).
2. Gasto diário bruto = soma de `Entry.amount` (>0, exclui #AJUSTE) agrupado por
   **`date`** (data real). Dias sem gasto = `Decimal("0")`.
3. **Janela móvel adaptativa** (`rolling`):

   | period | rolling |
   |--------|---------|
   | 7      | 3       |
   | 15     | 5       |
   | 30     | 7       |
   | 90     | 15      |

   Períodos fora desse conjunto: usar o mapeamento do valor válido mais próximo
   (ou validar/clampar para {7,15,30,90}).
4. Para cada dia `d` da janela, sobre os valores diários da janela rolling
   terminando em `d` (retroativa), calcular: `median`, `p25`, `p75` (percentis
   por interpolação linear, consistentes com `_median` existente).

Retorno: lista ordenada (mais antigo primeiro) de
```python
{"date": date, "median": Decimal, "p25": Decimal, "p75": Decimal}
```

Helpers de percentil ficam neste módulo (ou reutilizar/estender o padrão de
`_median` em `category_stats.py`).

### Backend: API

Novo `DailyTrendView` (APIView, `IsAuthenticated`). Aceita `?period=7|15|30|90`
(default 30; valores inválidos → clamp para 30). **Ignora year/month.** Resposta:
```json
{
  "period": 30,
  "series": [
    { "date": "2026-05-24", "median": "45.00", "p25": "20.00", "p75": "80.00" }
  ]
}
```

### Frontend

Card com `ComposedChart` (Recharts):
- `Area` sombreada entre `p25` e `p75` (banda de variabilidade).
- `Line` da `median` (linha central).
- `<select>` de período (7/15/30/90) que dispara novo fetch ao endpoint.
- Eixo X = datas; eixo Y = R$.

---

## Testes (TDD)

`finances/tests/test_diverse_savings.py`:
- baseline robusto (mediana, não média) com mês outlier;
- economia positiva (gastou menos) e negativa (gastou mais);
- exclusão de entradas #AJUSTE do `actual` e do baseline;
- sem histórico → `has_baseline=False`, baseline=0.

`finances/tests/test_daily_trend.py`:
- agrupamento por `date` (não billing_month);
- mediana e IQR corretos numa janela conhecida;
- robustez: um único dia de pico não desloca a mediana;
- janela rolling adaptativa por período;
- dias sem gasto contam como 0;
- ordenação (mais antigo primeiro).

Testes de API (em `test_api_dashboard.py` ou novos): autenticação exigida
(401 sem login) e shape do JSON para ambos os endpoints.

## Fora de escopo

- Refatoração não relacionada do dashboard.
- Persistência/caching das séries (são computadas live, como os demais cards).
- Configurar a janela da mediana histórica pela UI (fica fixa em 6 meses).
