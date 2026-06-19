# Gastos sistemáticos: UX, recorrência e correções de edição

**Data:** 2026-06-19
**Escopo:** tela de Entradas (cockpit mensal embutido em `entries_page.html`), modal global "+", edição de Renda.

## Contexto

As seções "cockpit" (sistemáticos, renda, parcelamentos, vencimentos) são carregadas
via HTMX dentro de `templates/entries/entries_page.html`, com contexto de
`current_year`/`current_month`. O botão flutuante "+" (`base.html`) é global, sem
contexto de mês, e abre `#entry-modal` carregando `partials/_modal_entry_form.html`
(hoje com abas **Regular** e **Parcelamento**). O fechamento do modal é disparado
pelo evento `entry-saved` (listener em `base.html`).

`SystemicExpense` é um *template*; cada mês gera uma `Entry` (`entry_type=systemic`)
via `create_monthly_entry`. `Income` é materializada como **uma linha por mês**; os
campos `is_recurring`/`recurrence_start`/`recurrence_end` existem mas **não são
consumidos** por projeção nem exibição.

## Itens

### Bug 5 — datas não preenchem nos modais de edição
**Causa:** `EntryForm.date` e `InstallmentForm.date` usam `DateInput(attrs={"type":"date"})`
sem `format="%Y-%m-%d"`. Com `LANGUAGE_CODE="pt-br"` + `USE_L10N=True`, o valor
renderiza como `dd/mm/yyyy`, que `<input type="date">` rejeita → campo vazio.
`IncomeForm`/`CockpitIncomeForm` já definem o format (por isso funcionam).

**Fix:** adicionar `format="%Y-%m-%d"` aos widgets de data de `EntryForm` e
`InstallmentForm`. Corrige o prefill em todos os modais de edição que usam essas
forms (entrada regular, sistemático, parcela).

### Bug 4 — editar sistemático: descrição não muda + modal não fecha
**Causa (descrição):** a linha do cockpit exibe `{{ row.systemic.name }}` (o nome do
template), não `entry.description`. Editar a descrição da `Entry` não tem efeito
visível.
**Causa (modal não fecha):** hipótese — com a data em branco (bug 5), o POST do
`EntryForm` fica inválido (`Entry.date` é obrigatório) → re-renderiza o form com erro
em vez de fechar. A confirmar na friday; o fix do bug 5 deve eliminar o sintoma.

**Fix (decisão do usuário "editar o template"):** o modal de edição do sistemático
passa a editar o **nome do `SystemicExpense`** (rótulo em todos os meses) **+** os
campos da `Entry` do mês (data, valor, categoria, forma de pagamento). Form dedicado
`SystemicEntryEditForm`:

- Campos: `name` (→ template), `date`, `amount`, `category`, `payment_method` (→ entry).
- `__init__(entry, systemic, user)` semeia `initial` a partir de ambos.
- `save()` atualiza `systemic.name` e os campos da `entry` numa transação.

`CockpitSystemicEditModalView` passa a usar essa form. Como a linha já exibe
`systemic.name`, a edição fica visível e o `entry-saved` fecha o modal.

### Itens 1 + 3 — aba "Sistemático" no modal "+" e remoção do form inline
- Nova aba **Sistemático** em `partials/_modal_entry_form.html` (ao lado de
  Regular/Parcelamento), com **legendas** em todos os campos (padrão das outras abas:
  `<label class="label">`).
- **Remoção** do form inline `flex flex-wrap` de `cockpit/_systemic_section.html`. O
  botão "+ novo" do cockpit passa a abrir `#entry-modal` carregando
  `entry_modal?year={{current_year}}&month={{current_month}}`.
- `EntryModalView.get` aceita `?year=&month=` (default = hoje) para semear o mês
  inicial da aba sistemático. `EntryModalView.post` ganha o modo `entry_mode=systemic`.

### Item 2 — recorrência por N meses (na criação)
A aba Sistemático terá, além de Nome/Categoria/Forma de pagamento/Valor padrão:

- checkbox **"Recorrente por N meses"**;
- (visível via Alpine quando marcado) **Nº de meses** e **Mês inicial**
  (default = mês do contexto / hoje).

Form `SystemicExpenseCreateForm` (estende a atual `SystemicExpenseForm` com campos não
ligados ao model: `is_recurring`, `months`, `start_month`) com `save_for_user(user)`:

1. sempre cria o `SystemicExpense` (template);
2. se `is_recurring`: cria as `Entry` dos `months` meses a partir de `start_month`,
   usando `create_monthly_entry`, **pulando** meses que já têm a `Entry` daquele
   sistemático (idempotente);
3. retorna `(systemic, n_lancados)`.

Não-recorrente mantém o comportamento atual (só cria o template).

### Bug 6 — recorrência de Renda não reflete nos meses seguintes
**Causa:** `is_recurring`/`recurrence_start`/`recurrence_end` não são consumidos; a
projeção lê linhas `Income` por mês. Editar uma renda marcando "Recorrente" só altera
flags numa linha → meses seguintes ficam sem renda.

**Fix (decisão "upsert na janela início→fim"):** serviço
`apply_income_recurrence(income)`:

- só age quando `income.is_recurring`;
- janela = `[recurrence_start, recurrence_end]`; se em branco:
  `start = income.month`, `end = dezembro do ano de income.month`;
- para cada mês da janela, **upsert** por `(user, name, month)`: cria a renda
  faltante ou atualiza `amount`/`is_recurring`/`recurrence_start`/`recurrence_end` da
  existente (propaga a edição pra frente).

Chamado após `form.save()` em `IncomeUpdateView` (settings) e
`CockpitIncomeEditModalView` (cockpit). Idempotente.

### Item 7 (tela de Projeção) — acumulado histórico + seletores ano/mês
**Causa (acumulado):** `build_projection` inicia `acumulado = 0` no `start_month` da
janela → o acumulado de um mês muda conforme a configuração. O esperado é que o
acumulado de um mês (ex.: junho) seja o **acumulado histórico real, fixo**,
independente da janela.

**Fix:** `build_projection` ancora o acumulado no **mês mais antigo com dado** do
usuário: soma `saldo_projetado` de `[mês_mais_antigo, start_month)` como seed e segue
acumulando na janela exibida. Apenas as linhas da janela são retornadas; o acumulado
de cada mês passa a ser fixo. (`test_acumulado_is_cumulative` já começa no mês âncora,
seed 0 → continua válido.)

**Controle:** o `<input type="month">` (que no Android/TWA cai pra digitação) é
trocado por **dois selects** — mês + ano. As opções de ano vêm do histórico de dados
(`min(Income.month, Entry.billing_month)` até o ano corrente / ano do start). View
aceita `?start_year=&start_month=` (mantém `?start=YYYY-MM` como fallback).

## Testes (TDD, pytest)

- `test_forms`: `EntryForm`/`InstallmentForm` ligadas a uma instância renderizam
  `value="YYYY-MM-DD"` no widget de data (regressão bug 5).
- `test_cockpit_systemic_edit_modal`: editar nome reflete na seção; `entry-saved`
  presente no `HX-Trigger`; data vem preenchida no GET.
- `test_modal_systemic_tab` (novo): GET do modal traz a aba; POST `systemic` cria o
  template; recorrente cria N entries; mês inicial respeitado; idempotente em meses já
  lançados.
- `test_cockpit_systemic_create` / `test_entries_page_sections`: ajustar para o form
  inline removido + botão "+ novo" abrindo o modal.
- `test_income_recurrence` (novo): editar renda como recorrente faz upsert na janela;
  edição posterior propaga valor; idempotência.
- `test_projection_service`: acumulado de um mês é histórico (independe do start).
- `test_views_projection` (novo): controle tem selects `start_year`/`start_month`;
  opções de ano cobrem o histórico; `start_year`/`start_month` definem a janela.

## Verificação na friday

Reproduzir bugs 4, 5 e 6 no serviço dev rodando (`192.168.1.7:8700`) antes do fix e
validar depois (datas preenchidas, modal fecha, nome reflete, rendas materializadas
nos meses seguintes).

## Build de frontend

Se classes Tailwind novas forem adicionadas nos templates, rebuild + commit de
`mount.js`/`tailwind.css` (Tailwind com `--force`).

## Fora de escopo

- Projeção honrar flags de recorrência de renda sem materializar (mantém-se
  materialização; projeção lê linhas por mês).
- Editar estrutura de parcelamento a partir do modal sistemático.
- Recorrência "infinita" de sistemático (sempre N explícito ou lançamento manual).
