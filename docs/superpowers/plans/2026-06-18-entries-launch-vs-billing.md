# Entradas: lançamento × pagamento + redesenho do painel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na tela Entradas, mostrar cada lançamento na tabela do mês em que foi *lançado* (data da compra) enquanto o *valor* conta no "Total gastos" do mês de pagamento; redesenhar o painel de totais; e corrigir o bug que faz a renda sumir ao ser editada.

**Architecture:** A tabela passa a filtrar por `Entry.date` (mês de lançamento) em vez de `Entry.billing_month`. O painel reusa `build_projection` (já existente) para os números que devem bater com a tela de Projeção (Total gastos, Renda, Saldo projetado, Acumulado) e calcula "Total lançado" por agregação direta. O bug da renda é corrigido renderizando o campo mês em ISO e normalizando-o para o dia 1.

**Tech Stack:** Django 5 + HTMX (server-rendered templates), pytest + model_bakery, Tailwind/daisyUI (build via Vite).

## Global Constraints

- TDD obrigatório: teste falhando antes da implementação (não-negociável neste projeto).
- Trabalhar em git worktree isolado (criado via superpowers:using-git-worktrees no início da execução).
- Testes rodam com pgvector em `localhost:5433` (não o Postgres do sistema).
- `lint = ruff check`; rodar antes de cada commit.
- `Entry.billing_month` continua sendo a fonte da verdade dos totais; só deixa de governar a tabela.
- Idioma da UI: pt-BR. Datas em `<input type="date">` exigem valor ISO `aaaa-mm-dd`.
- Caminho dos testes: `src/backend/finances/tests/`. Rodar a partir de `src/backend`.

---

### Task 1: `IncomeForm` renderiza mês em ISO e normaliza para o dia 1

Corrige a raiz do bug "renda some": o `<input type=date>` vinha em branco (valor pt-BR não-ISO) e o save gravava qualquer dia.

**Files:**
- Modify: `src/backend/finances/forms.py` (classes `IncomeForm` ~107-134 e `CockpitIncomeForm` ~137-160)
- Test: `src/backend/finances/tests/test_income_form_month.py` (Create)

**Interfaces:**
- Produces: `IncomeForm` com `clean_month()` que retorna `month.replace(day=1)`; widgets do campo `month` em `IncomeForm` e `CockpitIncomeForm` com `format="%Y-%m-%d"`.

- [ ] **Step 1: Write the failing test**

```python
# src/backend/finances/tests/test_income_form_month.py
from datetime import date
from decimal import Decimal

import pytest

from finances.forms import CockpitIncomeForm, IncomeForm


def test_income_form_normalizes_month_to_first_day():
    form = IncomeForm(
        data={"name": "Salário", "amount": "8655.00", "month": "2026-06-18", "is_recurring": False}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["month"] == date(2026, 6, 1)


def test_income_form_month_widget_renders_iso_value():
    form = IncomeForm(initial={"month": date(2026, 7, 1)})
    assert 'type="date"' in str(form["month"])
    # ISO value so <input type=date> prefills (pt-BR localizado viria como 01/07/2026)
    assert "2026-07-01" in str(form["month"])


def test_cockpit_income_form_month_widget_renders_iso_value():
    form = CockpitIncomeForm(initial={"month": date(2026, 7, 1)})
    assert "2026-07-01" in str(form["month"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_income_form_month.py -v`
Expected: FAIL — `test_income_form_normalizes_month_to_first_day` retorna `date(2026, 6, 18)`; os testes de widget não acham `2026-07-01` (render localizado).

- [ ] **Step 3: Write minimal implementation**

Em `src/backend/finances/forms.py`, no `IncomeForm`, trocar o widget de `month` para incluir `format` e adicionar `clean_month`:

```python
class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = ["name", "amount", "month", "is_recurring", "recurrence_start", "recurrence_end"]
        labels = {
            "name": "Nome",
            "amount": "Valor",
            "month": "Mês",
            "is_recurring": "Recorrente",
            "recurrence_start": "Início da recorrência",
            "recurrence_end": "Fim da recorrência",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(
                attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}
            ),
            "month": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "is_recurring": forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
            "recurrence_start": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
            "recurrence_end": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
        }

    def clean_month(self):
        return self.cleaned_data["month"].replace(day=1)
```

No `CockpitIncomeForm`, trocar o widget de `month` para:

```python
            "month": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "input input-bordered input-sm w-full"},
            ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_income_form_month.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Lint e commit**

```bash
cd src/backend && ruff check finances/forms.py finances/tests/test_income_form_month.py
git add src/backend/finances/forms.py src/backend/finances/tests/test_income_form_month.py
git commit -m "fix(income): render month field as ISO and normalize to first-of-month"
```

---

### Task 2: Painel "Renda do mês" filtra por ano+mês (independe do dia)

Mesmo que algum registro legado tenha `month` num dia ≠ 1, ele deve aparecer no mês certo.

**Files:**
- Modify: `src/backend/finances/views/cockpit.py` (`_income_context`, ~26-39)
- Test: `src/backend/finances/tests/test_cockpit_income.py` (adicionar teste)

**Interfaces:**
- Consumes: `IncomeForm.clean_month` (Task 1) já normaliza novos registros; esta task cobre os antigos.
- Produces: `_income_context` consultando `month__year=year, month__month=month`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em src/backend/finances/tests/test_cockpit_income.py
from datetime import date
from decimal import Decimal

from django.urls import reverse
from model_bakery import baker


@pytest.mark.django_db
def test_income_panel_shows_income_with_non_first_day(client, user):
    client.force_login(user)
    baker.make(
        "finances.Income",
        user=user,
        name="Salário",
        amount=Decimal("8655.00"),
        month=date(2026, 6, 18),  # dia ≠ 1 (registro legado corrompido)
    )
    resp = client.get(reverse("finances:cockpit_income", args=[2026, 6]))
    body = resp.content.decode()
    assert "Salário" in body
```

(Se o arquivo já tiver imports de `pytest`/`baker`/`reverse`, não duplicar.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_cockpit_income.py::test_income_panel_shows_income_with_non_first_day -v`
Expected: FAIL — "Salário" não aparece (filtro exato `month=2026-06-01` não casa com `2026-06-18`).

- [ ] **Step 3: Write minimal implementation**

Em `_income_context` (`src/backend/finances/views/cockpit.py`), trocar o filtro:

```python
def _income_context(request, year, month):
    incomes = list(
        Income.objects.filter(
            user=request.user, month__year=year, month__month=month
        ).order_by("name")
    )
    income_month_total = sum((i.amount for i in incomes), Decimal("0"))
    return {
        "current_year": year,
        "current_month": month,
        "incomes": incomes,
        "income_month_total": income_month_total,
        "income_form": CockpitIncomeForm(initial={"month": date(year, month, 1)}),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_cockpit_income.py -v`
Expected: PASS

- [ ] **Step 5: Lint e commit**

```bash
cd src/backend && ruff check finances/views/cockpit.py finances/tests/test_cockpit_income.py
git add src/backend/finances/views/cockpit.py src/backend/finances/tests/test_cockpit_income.py
git commit -m "fix(cockpit): income panel matches by year+month regardless of stored day"
```

---

### Task 3: Tabela de Entradas filtra por mês de lançamento (`date`)

**Files:**
- Modify: `src/backend/finances/views/entries.py` (`EntryListView.get_queryset`, ~65-77)
- Test: `src/backend/finances/tests/test_views_entries.py` (ajustar fixture/testes ~63-72)

**Interfaces:**
- Produces: `EntryListView` listando `Entry` REGULAR com `date__year=year, date__month=month`.

- [ ] **Step 1: Write the failing test**

Em `src/backend/finances/tests/test_views_entries.py`, **substituir** `test_filters_by_billing_month` e `test_feb_entries_not_in_march` por:

```python
    def test_filters_by_launch_month(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert len(entries) == 3
        assert all(e.date.month == 3 for e in entries)

    def test_feb_entries_not_in_march(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert not any(e.description == "Feb entry" for e in entries)

    def test_credit_purchase_appears_in_launch_month_not_billing_month(
        self, logged_client, user
    ):
        cat = baker.make("finances.Category", user=user, name="Cartão")
        card = baker.make(
            "finances.PaymentMethod", user=user, name="Visa", type="credit_card", closing_day=10
        )
        # Compra em 20/jun → fatura paga em agosto (billing_month=2026-08-01).
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 6, 20),
            amount=Decimal("200.00"),
            description="Compra crédito",
            category=cat,
            payment_method=card,
        )
        june = logged_client.get("/entries/2026/6/").context["entries"]
        august = logged_client.get("/entries/2026/8/").context["entries"]
        assert any(e.description == "Compra crédito" for e in june)
        assert not any(e.description == "Compra crédito" for e in august)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_views_entries.py -k "launch_month or credit_purchase" -v`
Expected: FAIL — a compra de crédito aparece na tabela de agosto (filtro atual por `billing_month`).

- [ ] **Step 3: Write minimal implementation**

Em `EntryListView.get_queryset` (`src/backend/finances/views/entries.py`):

```python
    def get_queryset(self):
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])
        return (
            Entry.objects.filter(
                user=self.request.user,
                date__year=year,
                date__month=month,
                entry_type=EntryType.REGULAR,
            )
            .select_related("category", "payment_method")
            .order_by("-date", "-created_at")
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_views_entries.py -v`
Expected: PASS (os testes não relacionados ao summary continuam passando; os de summary serão atualizados na Task 4)

- [ ] **Step 5: Lint e commit**

```bash
cd src/backend && ruff check finances/views/entries.py finances/tests/test_views_entries.py
git add src/backend/finances/views/entries.py src/backend/finances/tests/test_views_entries.py
git commit -m "feat(entries): list table by launch month (date) instead of billing month"
```

---

### Task 4: `compute_entry_summary` — Total lançado, Total gastos, Renda, Saldo projetado, Acumulado

**Files:**
- Modify: `src/backend/finances/views/entries.py` (`compute_entry_summary`, ~24-45; imports no topo)
- Test: `src/backend/finances/tests/test_entries_live_summary.py` (substituir asserts ~51-74), `src/backend/finances/tests/test_views_entries.py` (`test_context_has_summary` ~89-94), `src/backend/finances/tests/features/test_views.py` (~166)

**Interfaces:**
- Consumes: `build_projection(user, start_month, num_months, today)` de `finances.services.projection` — retorna lista de dicts com chaves `total`, `income`, `saldo_projetado`, `acumulado` (uma por mês de `start_month` em diante).
- Produces: `compute_entry_summary(user, year, month)` retornando dict com chaves: `total_lancado`, `total_gastos`, `income`, `saldo_projetado`, `acumulado`, `entry_count` (todos `Decimal`, exceto `entry_count: int`).

- [ ] **Step 1: Write the failing test**

Em `src/backend/finances/tests/test_entries_live_summary.py`, substituir o corpo de `test_renders_summary_partial_with_totals` e `test_scoped_to_user`:

```python
    def test_renders_summary_partial_with_totals(self, logged_client, march_setup):
        # março: 3 pix de 50 (date em março, billing março) + estorno -20 (billing março)
        response = logged_client.get("/entries/2026/3/summary/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "entries/_entries_summary.html" in [t.name for t in response.templates]
        summary = response.context["summary"]
        # Total lançado = soma das regulares com date em março = 150 - 20 = 130
        assert summary["total_lancado"] == Decimal("130.00")
        # Total gastos = total da Projeção de março (billing_month=março) = 130
        assert summary["total_gastos"] == Decimal("130.00")
        assert summary["entry_count"] == 4
        assert "total_returns" not in summary
        assert "net" not in summary

    def test_scoped_to_user(self, logged_client, other_user):
        cat = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            amount=Decimal("999.00"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/entries/2026/3/summary/", HTTP_HX_REQUEST="true")
        assert response.context["summary"]["total_lancado"] == Decimal("0")
```

Adicionar um teste novo que prova a separação lançado × gastos para crédito:

```python
    def test_credit_value_counts_in_billing_month_not_launch_month(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        card = baker.make(
            "finances.PaymentMethod", user=user, type="credit_card", closing_day=10
        )
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 6, 20),
            amount=Decimal("200.00"),
            description="crédito",
            category=cat,
            payment_method=card,
        )  # billing_month = 2026-08-01
        june = logged_client.get("/entries/2026/6/summary/", HTTP_HX_REQUEST="true").context["summary"]
        august = logged_client.get("/entries/2026/8/summary/", HTTP_HX_REQUEST="true").context["summary"]
        # Linha lançada em junho → entra no Total lançado de junho
        assert june["total_lancado"] == Decimal("200.00")
        # Valor só sai em agosto → Total gastos de junho não inclui; agosto inclui
        assert june["total_gastos"] == Decimal("0")
        assert august["total_gastos"] == Decimal("200.00")
        assert august["total_lancado"] == Decimal("0")
```

Em `src/backend/finances/tests/test_views_entries.py`, `test_context_has_summary`:

```python
    def test_context_has_summary(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "summary" in response.context
        summary = response.context["summary"]
        assert summary["total_lancado"] == Decimal("150.00")
        assert summary["entry_count"] == 3
```

Em `src/backend/finances/tests/features/test_views.py` (~166), trocar `summary["total_expenses"] == Decimal("300")` por `summary["total_lancado"] == Decimal("300")`. (Conferir no arquivo que as entradas da fixture têm `date` no mês consultado; se a fixture usar só `billing_month`, ajustar para também setar `date` no mesmo mês.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_entries_live_summary.py finances/tests/test_views_entries.py::TestEntryListView::test_context_has_summary -v`
Expected: FAIL — `KeyError`/chaves antigas ausentes.

- [ ] **Step 3: Write minimal implementation**

No topo de `src/backend/finances/views/entries.py`, garantir imports:

```python
from django.db.models import Count, Min, Sum
from finances.models import Entry, Income, PaymentMethod
from finances.services.projection import build_projection
```

Substituir `compute_entry_summary`:

```python
def compute_entry_summary(user, year, month):
    """Totais do mês para o painel de Entradas.

    ``total_lancado`` é a soma das entradas REGULARES *lançadas* no mês (por
    ``date``) — as mesmas linhas que aparecem na tabela. ``total_gastos`` e os
    saldos vêm de :func:`build_projection`, ancorada no mês mais antigo com
    dado, para baterem 100% com a tela de Projeção (inclui sistemáticos e
    parcelas, por ``billing_month``).
    """
    target = date(year, month, 1)

    lanc = Entry.objects.filter(
        user=user, entry_type=EntryType.REGULAR, date__year=year, date__month=month
    ).aggregate(total=Sum("amount"), count=Count("id"))
    total_lancado = lanc["total"] or Decimal("0")
    entry_count = lanc["count"]

    inc_min = Income.objects.filter(user=user).aggregate(m=Min("month"))["m"]
    ent_min = Entry.objects.filter(user=user).aggregate(m=Min("billing_month"))["m"]
    candidates = [d for d in (inc_min, ent_min) if d is not None]
    anchor = min(candidates).replace(day=1) if candidates else target
    if anchor > target:
        anchor = target
    num_months = (year * 12 + month) - (anchor.year * 12 + anchor.month) + 1

    rows = build_projection(user, anchor, num_months, today=date.today())
    row = rows[-1]

    return {
        "total_lancado": total_lancado,
        "total_gastos": row["total"],
        "income": row["income"],
        "saldo_projetado": row["saldo_projetado"],
        "acumulado": row["acumulado"],
        "entry_count": entry_count,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_entries_live_summary.py finances/tests/test_views_entries.py finances/tests/features/test_views.py -v`
Expected: PASS

- [ ] **Step 5: Lint e commit**

```bash
cd src/backend && ruff check finances/views/entries.py finances/tests/test_entries_live_summary.py finances/tests/test_views_entries.py finances/tests/features/test_views.py
git add src/backend/finances/views/entries.py src/backend/finances/tests/test_entries_live_summary.py src/backend/finances/tests/test_views_entries.py src/backend/finances/tests/features/test_views.py
git commit -m "feat(entries): summary with total lançado/gastos + saldo from projection"
```

---

### Task 5: Redesenhar `_entries_summary.html`

**Files:**
- Modify: `src/backend/templates/entries/_entries_summary.html`
- Test: `src/backend/finances/tests/test_entries_live_summary.py` (adicionar teste de render)

**Interfaces:**
- Consumes: dict `summary` com `total_lancado`, `total_gastos`, `income`, `saldo_projetado`, `acumulado`, `entry_count` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# adicionar em test_entries_live_summary.py (classe TestEntriesSummaryView)
    def test_summary_labels(self, logged_client, march_setup):
        body = logged_client.get(
            "/entries/2026/3/summary/", HTTP_HX_REQUEST="true"
        ).content.decode()
        assert "Total lançado" in body
        assert "Total gastos" in body
        assert "Saldo projetado" in body
        assert "Saldo acumulado" in body
        assert "Total retornos" not in body
        assert "Líquido" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_entries_live_summary.py::TestEntriesSummaryView::test_summary_labels -v`
Expected: FAIL — template ainda tem "Total retornos"/"Líquido" e não tem "Total lançado".

- [ ] **Step 3: Write minimal implementation**

Substituir `src/backend/templates/entries/_entries_summary.html`:

```html
{% load finance_filters %}
<!-- Summary (top, responsive) — refreshes live on `entries-changed` -->
<div id="entries-summary"
     hx-get="{% url 'finances:entries_summary' current_year current_month %}"
     hx-trigger="entries-changed from:body"
     hx-swap="outerHTML"
     class="flex flex-wrap gap-x-6 gap-y-1 mb-3 text-sm opacity-70">
    <span>Total lançado: <strong class="whitespace-nowrap">{{ summary.total_lancado|money }}</strong></span>
    <span>Total gastos: <strong class="text-error whitespace-nowrap">{{ summary.total_gastos|money }}</strong></span>
    <span>Renda do mês: <strong class="whitespace-nowrap">{{ summary.income|money }}</strong></span>
    <span>Saldo projetado: <strong class="whitespace-nowrap {% if summary.saldo_projetado < 0 %}text-error{% else %}text-success{% endif %}">{{ summary.saldo_projetado|money }}</strong></span>
    <span>Saldo acumulado: <strong class="whitespace-nowrap {% if summary.acumulado < 0 %}text-error{% else %}text-success{% endif %}">{{ summary.acumulado|money }}</strong></span>
    <span>Entradas: <strong>{{ summary.entry_count }}</strong></span>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_entries_live_summary.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/templates/entries/_entries_summary.html src/backend/finances/tests/test_entries_live_summary.py
git commit -m "feat(entries): redesign summary panel (lançado/gastos/renda/saldos)"
```

---

### Task 6: Selo de fatura na linha de crédito

Deixa explícito por que a linha está num mês mas o valor cai em outro.

**Files:**
- Modify: `src/backend/templates/entries/_entry_row.html` (linha ~18)
- Test: `src/backend/finances/tests/test_views_entries.py` (adicionar teste)

**Interfaces:**
- Consumes: `entry.billing_month`, `entry.date` (mês de pagamento × mês de lançamento).

- [ ] **Step 1: Write the failing test**

```python
# adicionar em test_views_entries.py, classe TestEntryListView
    def test_credit_row_shows_future_invoice_badge(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        card = baker.make(
            "finances.PaymentMethod", user=user, type="credit_card", closing_day=10
        )
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 6, 20),
            amount=Decimal("200.00"),
            description="crédito",
            category=cat,
            payment_method=card,
        )  # billing_month = 2026-08-01
        body = logged_client.get("/entries/2026/6/").content.decode()
        assert "fatura" in body.lower()
        assert "08/26" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/backend && pytest finances/tests/test_views_entries.py::TestEntryListView::test_credit_row_shows_future_invoice_badge -v`
Expected: FAIL — a coluna mostra só `billing_month|date:"M"` (ex.: "Aug"), sem "fatura" nem "08/26".

- [ ] **Step 3: Write minimal implementation**

Em `src/backend/templates/entries/_entry_row.html`, substituir a célula da linha 18:

```html
    <td>
        {% if entry.billing_month|date:"Y-m" != entry.date|date:"Y-m" %}
        <span class="badge badge-sm badge-warning whitespace-nowrap" title="Valor cai nesta fatura">fatura {{ entry.billing_month|date:"m/y" }}</span>
        {% else %}
        <span class="opacity-60">{{ entry.billing_month|date:"m/y" }}</span>
        {% endif %}
    </td>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/backend && pytest finances/tests/test_views_entries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/templates/entries/_entry_row.html src/backend/finances/tests/test_views_entries.py
git commit -m "feat(entries): badge fatura on credit rows when billing month differs"
```

---

### Task 7: Rebuild dos artefatos de frontend e suíte completa

Tailwind escaneia os templates; as novas classes (`badge-warning`, `text-error`/`text-success` no summary) precisam entrar no CSS gerado (memória: rebuild + commit após mudanças de FE; usar `--force`).

**Files:**
- Modify (gerados): `src/backend/static/.../tailwind.css` (e `mount.js` se mudar) — caminhos exatos conforme `package.json`/config do projeto.

- [ ] **Step 1: Rodar a suíte completa**

Run: `cd src/backend && pytest -q`
Expected: PASS (sem regressões; total ≥ 309 testes anteriores + os novos)

- [ ] **Step 2: Rebuild do frontend (com --force)**

Run: o comando de build do projeto (ex.: `pnpm build` / `npm run build`) com flag de força do Tailwind, conforme `reference_frontend_build_artifacts`. Verificar que `tailwind.css` contém `badge-warning`.

Verify: `grep -c "badge-warning" <caminho do tailwind.css gerado>` → ≥ 1

- [ ] **Step 3: Commit dos artefatos**

```bash
git add -A src/backend/static
git commit -m "chore(build): rebuild tailwind/mount for entries summary + fatura badge"
```

- [ ] **Step 4: Lint final**

Run: `cd src/backend && ruff check finances`
Expected: sem erros.

---

## Self-Review

**Spec coverage:**
- Linha no mês de lançamento → Task 3 ✓
- Valor no Total gastos do mês de pagamento → Task 4 (+teste de crédito) ✓
- Total gastos (inclui sistemáticos = Projeção) → Task 4 ✓
- Total lançado → Task 4 ✓
- Remover Total retornos / Líquido → Task 5 ✓
- Renda do mês / Saldo projetado / Saldo acumulado (desde início dos dados) → Task 4 + 5 ✓
- Selo de fatura → Task 6 ✓
- Meses futuros via projeção de sistemáticos → herdado de `build_projection` (Task 4) ✓
- Bug renda: render ISO + normalizar dia 1 → Task 1 ✓; painel por ano+mês → Task 2 ✓
- Restaurar renda de junho → já executado (fora do plano de código)

**Placeholder scan:** Task 7 deixa o comando de build e o caminho do `tailwind.css` para o executor resolver via `package.json`/config — é dependente do ambiente; verificação concreta (`grep badge-warning`) está incluída.

**Type consistency:** chaves do `summary` (`total_lancado`, `total_gastos`, `income`, `saldo_projetado`, `acumulado`, `entry_count`) são idênticas entre Task 4 (produz), Task 5 (consome) e os testes. `build_projection` retorna `total`/`income`/`saldo_projetado`/`acumulado` conforme `services/projection.py`.
