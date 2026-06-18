# Entradas: regra de cartão, totais ao vivo e bug de excluir renda

**Data:** 2026-06-18
**Escopo:** Itens 1, 2 e 4 (a tela de projeção — item 3 — terá brainstorm/spec próprio).

## Contexto

A app de finanças (Django + HTMX + ilhas React) já modela `billing_month` em
`Entry` e computa esse mês via `services/billing.py::compute_billing_month`, que
hoje coloca compras de cartão de crédito feitas **após** o dia de fechamento no
mês seguinte e as feitas **antes/no** fechamento no mês da compra.

## Item 1 — Gasto de cartão conta no mês em que é pago

### Regra desejada
- **Dinheiro / Pix:** conta no mês da compra (inalterado).
- **Cartão de crédito:** conta no mês em que a fatura é **paga**:
  - compra **no/antes** do fechamento → mês seguinte (M+1);
  - compra **depois** do fechamento → M+2.

Exemplo do usuário: cartão fecha dia 25; compra em 26/jun (após fechamento) →
conta em **agosto**. Compra em 10/jun (antes) → conta em **julho**.

### Distinção essencial: data de lançamento × data de cobrança
- **Data de lançamento (`Entry.date`):** quando a compra foi feita. **Nunca** muda.
- **Mês de cobrança (`Entry.billing_month`):** em que mês o gasto é contabilizado.
  Para cartão, depende da data da compra + dia de fechamento.

A regra nova ("mês de cobrança = mês em que a fatura é paga") vale **apenas para
entradas novas**. Os dados históricos já foram lançados com o mês de
contabilização desejado — em especial as **parcelas**, digitadas com o mês de
cobrança, não o da compra. Reescrever meses retroativamente quebraria isso.

### Mudanças
1. **`services/billing.py::compute_billing_month`** — envolve o retorno do ramo de
   cartão em `_next_month(...)`. Flui automaticamente para entradas **novas**:
   - novos lançamentos regulares (`Entry.save`);
   - novos parcelamentos (`installment_billing_months` usa `compute_billing_month`
     na 1ª parcela e `_next_month` nas seguintes);
   - o preview do modal de parcelamento (`InstallmentPreviewView`).
   Daqui pra frente o usuário digita a **data da compra** (normal e parcelada) e o
   sistema deriva o mês de cobrança.
2. **Migração `0008_freeze_credit_card_billing_month`** — **não desloca nenhum
   mês.** Apenas marca `billing_month_override=True` nas entradas de cartão
   existentes (regulares e parcelas), congelando o `billing_month` atual para que
   `Entry.save` não recompute pela regra nova num re-save futuro. Dinheiro/Pix
   ficam intactos (mês de cobrança = mês da compra → recompor é no-op).
   Irreversível por design (reverso é no-op; os dados não mudam).

### Testes (TDD primeiro)
- `compute_billing_month`: dinheiro/pix → M; cartão ≤fechamento → M+1; cartão
  >fechamento → M+2; virada de ano (dez→jan, e nov→jan no caso M+2).
- `installment_billing_months`: 1ª parcela já vem deslocada; sequência mantém +1
  por mês.
- Migração: entrada de cartão é congelada (`override=True`) **sem** mudar o mês;
  dinheiro não é congelado; entradas já congeladas ficam intactas.

## Item 2 — Totais ao vivo no topo da tela de entradas

Hoje o bloco-resumo vive em `entries/_entries_table.html:2-8`. O form inline
adiciona a linha (`afterbegin` em `#entries-tbody`) mas **não** atualiza o resumo.

### Mudanças
1. Extrair o resumo para `entries/_entries_summary.html` com `id="entries-summary"`,
   `hx-get` para um novo endpoint e `hx-trigger="entries-changed from:body"`
   (swap `outerHTML`).
2. Novo `EntriesSummaryView` (+ rota `entries/<year>/<month>/summary/`) renderiza
   o parcial via um helper compartilhado `compute_summary(user, year, month)`,
   também usado por `EntryListView` (remove duplicação da lógica de totais).
3. Cada endpoint que muta entradas (`EntryCreateView`, `EntryUpdateView`,
   `EntryDeleteView`, `EntryModalView` regular+parcelamento, `EntryEditModalView`)
   acrescenta `"entries-changed": true` ao `HX-Trigger` existente.

O append da linha pelo form inline continua igual; os totais passam a recalcular
na hora em adicionar/editar/excluir. Nome do evento usa hífen (`entries-changed`)
para não conflitar com a sintaxe de modificadores do HTMX (`from:body`).

### Testes
- `compute_summary` retorna `total_expenses`/`total_returns`/`net`/`entry_count`
  corretos para um mês.
- `EntriesSummaryView` exige login, é escopado ao usuário e renderiza o parcial.
- Endpoints de mutação incluem `entries-changed` no header `HX-Trigger`.

## Item 4 — "Excluir renda" não funciona (tela de entradas)

A fiação parece correta (`CockpitIncomeDeleteView` + botão em
`_income_section.html:17-21`). Por isso **não** vou adivinhar a causa.

### Abordagem (systematic-debugging)
1. Reproduzir rodando a app e observando a requisição `hx-delete` (status,
   resposta, console). Hipóteses iniciais: CSRF no `hx-delete`, 405 por método,
   ou `event.stopPropagation()` impedindo o disparo do HTMX.
2. Escrever teste de regressão que falha pela mesma causa.
3. Corrigir e confirmar verde + verificação manual.

O escopo exato da correção só se fecha após a reprodução.

## Fora de escopo
- Item 3 (tela de projeção multi-mês) — brainstorm/spec dedicado. A linha
  "Não Líquido" foi descrita pelo usuário como reserva/comprometido futuro; será
  detalhada lá.
- Atualizar a tabela de entradas ao criar via modal na tela de entradas (gap
  pré-existente; este trabalho foca nos totais).

## Verificação final
- Suíte de testes verde (`pytest`), lint limpo (`ruff check`).
- Verificação manual: total no topo muda ao adicionar/excluir; compra de cartão
  cai no mês de pagamento correto; excluir renda funciona.
