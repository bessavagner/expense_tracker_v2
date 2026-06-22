# Dashboard redesign — hierarquia, bento layout e cards-estrela

**Data:** 2026-06-22
**Status:** Aprovado (desenho) — aguardando review da spec
**Escopo:** C (redesign completo)

## Problema

O dashboard atual é uma grade 2-colunas (`grid-cols-1 md:grid-cols-2 gap-4`) onde
todos os 9 cards têm tamanho, borda e sombra idênticos (`card bg-base-100 border
border-base-300 shadow-sm`). Sem variação de peso visual, não há hierarquia — tudo
compete igualmente e a tela fica monótona. Referências de dashboards financeiros
(Dribbble: Fireart, Upnow, etc.) resolvem isso com **layout bento (tiles de
tamanhos diferentes) + camadas de elevação + escala tipográfica**, usando cor como
acento pontual.

## Princípio-guia

Manter a identidade visual existente — tema **"ledger"** (display Fraunces, corpo
Hanken Grotesk, numerais IBM Plex Mono tabular; bases de papel quente; teal como
marca; daisyUI light + dark). O ganho vem de **hierarquia e ritmo**, não de uma
estética nova. Nada de fontes/cores genéricas novas.

## Decisões do usuário

- **Cards-estrela:**
  - **Saldo do mês** → número-herói (maior da tela).
  - **Economia do mês** → card accent colorido (quebra o ritmo neutro).
  - **Tendência de gasto diário** → gráfico-assinatura, **largura total**.
  - **Projeção (acumulado futuro)** → destaque forward-looking.
- **Evolução** e **Top categorias** passam a visuais secundários (tamanho médio).

## Layout bento (desktop)

Grade base de **12 colunas** (`lg:grid-cols-12`), `gap-4`. Spans por tile:

```
┌───────────────────────────────────────┬───────────────────────┐
│ HERO · Saldo do mês            (col-8) │ ECONOMIA · accent (4) │  Tier 1
│ R$ 25.066,96  ▲  + mini renda/gastos   │ R$ 4.065,20           │
│ ▓▓▓▓▓▓░ orçamento 198%                  │ habitual/gasto        │
├──────────┬──────────┬──────────┬───────┴───────────────────────┤
│ KPI Renda│ KPI Gasto│ KPI Retor│ KPI Orçamento%                │  Tier 2 (cada col-3)
│ valor+▲% │ valor+▼% │ valor+%  │ valor + barra                 │  sparkline onde houver
│ sparkline│ sparkline│          │                               │
├──────────┴──────────┴──────────┴───────────────────────────────┤
│ ASSINATURA · Tendência de gasto diário          (col-12, alto) │  Tier 3
│ mediana móvel + banda IQR · dropdown 7/15/30/90                 │
├────────────────────────────────┬───────────────────────────────┤
│ Projeção (acumulado)    (col-7) │ Top categorias  (col-5, donut)│  Tier 4
├────────────────────────────────┼───────────────────────────────┤
│ Evolução renda vs gastos (col-7)│ Alertas         (col-5)       │
├──────────────────┬──────────────┴───────────────┬──────────────┤
│ Últimas entradas (col-6, quieto) │ Parcelas ativas (col-6, quieto)│ Tier 5
└──────────────────┴──────────────────────────────┴──────────────┘
```

**Breakpoints:**
- `< md`: 1 coluna, ordem por importância (Hero → Economia → KPIs → Tendência →
  Projeção → Top categorias → Evolução → Alertas → Entradas → Parcelas). (Mobile
  já validado funcionando com a grade atual.)
- `md`: 6 colunas (tiles reflowam: KPIs 2×2, etc.).
- `lg+`: 12 colunas conforme o diagrama.

A grade vira CSS grid explícito (spans por tile), substituindo o `grid-cols-2`
uniforme. O `ChatWidget` permanece como está (fora do grid principal).

## Três camadas de elevação

| Camada | Tiles | Tratamento |
|---|---|---|
| **Hero / Accent** | Saldo, Economia | leve gradiente/tint de marca, `shadow-md`, número em Fraunces grande |
| **Médio** | KPIs, Tendência, Projeção, Evolução, Top categorias | card padrão atual (`bg-base-100 border-base-300 shadow-sm`) |
| **Quieto** | Alertas, Entradas, Parcelas | sem sombra, `bg-base-200`, borda mais sutil — recuam |

## Escala tipográfica

Hoje quase tudo é `text-sm`. Nova escala:
- **Herói (Saldo):** `text-4xl`/`text-5xl`, Fraunces (classe `font-display`), numeral em `.amount` (Plex Mono) quando for valor monetário — decidir no protótipo qual lê melhor; default: valor em `.amount` grande.
- **Economia (accent):** `text-3xl`.
- **KPIs:** `text-2xl`.
- **Títulos de card:** `text-[11px] uppercase tracking-wide opacity-60` (padrão que a `ProjectionCard` já usa) — aplicar a todos.

## Mudanças por componente

### Novo: `HeroSummaryCard` (substitui o papel do `SummaryCard`)
- Herói = **Saldo do mês** (grande), com renda e gastos como mini-stats abaixo e a
  barra de orçamento (reaproveita a lógica de `budget_pct`/cores da `SummaryCard`).
- Delta chip ▲▼ do saldo vs mês anterior.
- O `SummaryCard` atual é desmembrado: o saldo vira herói; renda/gastos/retornos/
  orçamento% migram para a faixa de KPIs.

### Novo: faixa de KPIs (`KpiTile` reutilizável)
- 4 tiles: **Renda, Gastos, Retornos, Orçamento %**.
- Cada um: título uppercase + valor (`text-2xl`) + **delta chip** (▲▼ % vs mês
  anterior) + **sparkline** de 6 meses onde houver série (Renda, Gastos; Saldo no
  hero). Retornos e Orçamento%: sem sparkline se não houver série confiável (mostrar
  só valor/chip — registrar a ausência, sem fingir dado).

### `EconomiaCard` → tratamento accent
- Mesma lógica/estados (verde/âmbar/sem-base) já implementados; ganha o fundo accent
  (tint teal/âmbar conforme sinal) e `text-3xl`. Sem mudança de dados.

### `DailyTrendCard` → assinatura
- Largura total (`col-span-12`), altura maior do gráfico. Sem mudança de dados; só
  layout/altura e título na nova escala.

### `ProjectionCard` → destaque
- Permanece, em `col-7`, altura levemente maior. Título na nova escala.

### `TopCategoriesCard` → donut
- Converter a lista ranqueada em **donut** (Recharts `PieChart`) das top categorias +
  fatia "Outros" (resto = total de gastos − Σ top). Legenda com nome + %. Reaproveita
  `TopCategoriesView` (já retorna top 5 com amount/pct); adicionar o resto/"Outros".

### `EvolutionCard` → secundário
- Mantido, tamanho médio (`col-7`). Sem mudança de dados.

### `AlertsCard`, `RecentEntriesCard`, `InstallmentsCard` → camada quieta
- `bg-base-200`, sem sombra, densidade um pouco maior. Sem mudança de dados.

## Movimento

- **Um** momento orquestrado no load: stagger de `opacity`/`translateY` nos tiles
  (delay incremental por posição). CSS puro/`@keyframes`.
- **Respeitar `prefers-reduced-motion: reduce`** → sem animação.
- Micro-interação de hover discreta nos tiles médios (leve `translateY(-1px)` +
  sombra). Nada nos tiles quietos.

## Mudanças de dados / API (aditivas)

- **`SummaryView`**: incluir valores do **mês anterior** (renda, gastos, retornos,
  saldo) para os delta chips (`*_delta_pct` ou os valores brutos p/ o front calcular).
- **`EvolutionView`**: já retorna 6 meses de income/expenses; **adicionar `returns`
  por mês** para habilitar sparkline/saldo histórico (saldo = income − expenses +
  returns).
- **`TopCategoriesView`**: adicionar a fatia **"Outros"** (total de gastos − Σ top)
  para o donut fechar 100%.
- Nenhuma migração de banco (sem mudança de modelo).

Todas as mudanças de API são **aditivas** (campos novos), sem quebrar os contratos
existentes; tipos TS atualizados em paralelo.

## Verificação visual (obrigatória)

Igual à feature anterior: rodar a app logado, **capturar e inspecionar screenshots**
do dashboard redesenhado (via Playwright/`/run`), confirmando:
- hierarquia visível (herói domina, listas recuam), layout bento correto em **lg,
  md e mobile**;
- estados do Economia accent (verde/âmbar/sem-base);
- donut de Top categorias fecha 100% com "Outros";
- KPIs com delta chips/sparklines corretos;
- gráfico-assinatura (Tendência) em largura total;
- animação de entrada presente e **desligada** sob `prefers-reduced-motion`;
- 0 erros de console.
Registrar os screenshots como evidência antes de concluir.

## Fora de escopo

- Mudar a paleta/fontes do tema "ledger".
- Novos indicadores de negócio (só reorganização/realce dos existentes).
- Mexer no `ChatWidget` ou em páginas fora do dashboard.
- Caching/persistência das séries (continuam computadas live).

## Riscos / notas

- **Tailwind:** o bento usa novas classes utilitárias (`col-span-*`, `lg:grid-cols-12`,
  gradientes, `shadow-md`, etc.) → rebuild `tailwind.css --force` + `mount.js`.
- **Sparklines:** só onde há série real; não inventar dado para Retornos/Orçamento%.
- **Donut "Outros":** garantir que não fica negativo (clamp ≥ 0) quando top 5 já
  cobre tudo.
- Densidade/responsividade exigem checagem visual nos 3 breakpoints (parte da
  verificação obrigatória).
