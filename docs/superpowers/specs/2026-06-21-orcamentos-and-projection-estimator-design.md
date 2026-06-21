# Orçamentos (grupos de categorias) + estimador mediana/teto na projeção

**Data:** 2026-06-21
**Status:** rascunho — aguardando revisão

## Objetivo

Duas features conectadas pelo conceito de **teto**, num único spec, implementadas
em duas fases independentes:

1. **Toggle do estimador de diversas na projeção** — na tela de projeção, escolher
   se as "diversas" dos meses futuros são estimadas pela **mediana** histórica
   (comportamento atual) ou pelo **teto** planejado.
2. **Orçamentos** — agrupar categorias (granulares demais para controle) em grupos
   chamados *orçamentos*. Os avisos de furo no dashboard passam a ser **por
   orçamento** em vez de por categoria. O valor de cada orçamento é um campo
   **armazenado e editável**, semeado com a soma dos tetos das categorias membros.

As features compartilham a definição de "teto": uma vez que orçamentos existem, o
"teto" da projeção é a **soma dos orçamentos** (camada de controle nova), e não a
soma crua dos tetos de categoria.

Princípio do projeto mantido: **toda a matemática vive em serviços determinísticos
em código**; nada de estimativa manual por célula. Regra do projeto: **TDD +
worktree + gates de qualidade** em cada fase.

## Decisões travadas (brainstorming 2026-06-21)

- **Relação categoria↔orçamento:** 1 categoria pertence a no máximo 1 orçamento
  (FK `Category.budget`, nullable).
- **Toggle mediana/teto:** vive na própria tela de projeção (param GET/sessão,
  como o seletor de meses). Default = **mediana**. Sem persistência em modelo.
- **Avisos do dashboard:** passam a ser por orçamento; os avisos por-categoria
  saem do fluxo de orçamentos.
- **Categorias sem orçamento:** continuam gerando **aviso individual** pelo próprio
  `budget_ceiling` (não perder cobertura na transição).
- **Teto da projeção:** `Σ Budget.amount` + `Σ budget_ceiling` das categorias sem
  orçamento.
- **Valor do orçamento:** campo armazenado e editável; ação para recalcular pela
  soma dos tetos das categorias membros.

## Ordem de implementação

**Fase 1 — Modelo de Orçamentos** (base; a Fase 2 depende do teto consolidado):

1. Modelo `Budget` + FK `Category.budget` + migração.
2. Serviço `budget_stats.py`: soma de gastos por orçamento no mês; teto consolidado.
3. `AlertsView`: avisos por orçamento + aviso individual para categorias órfãs.
4. UI de gestão em Settings: CRUD de orçamento, atribuição de categorias, recálculo.

**Fase 2 — Toggle do estimador na projeção:**

5. `category_stats.monthly_diverse_total_ceiling(user)` (usa o teto consolidado da
   Fase 1).
6. `build_projection(..., diverse_estimator="median"|"ceiling")`.
7. `ProjectionView` lê `?estimate=`, default `median`; toggle no template.

Cada etapa entregável e testada antes da próxima.

---

## Fase 1 — Orçamentos

### Modelo de dados

Novo modelo `finances/models/budget.py`:

```python
class Budget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="budgets")
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                 help_text="Teto do orçamento (editável)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]
```

Em `Category` (`finances/models/category.py`):

```python
budget = models.ForeignKey(
    "finances.Budget", on_delete=models.SET_NULL,
    null=True, blank=True, related_name="categories",
)
```

`SET_NULL`: apagar um orçamento solta as categorias (viram órfãs → aviso
individual), sem apagar dados de gasto. Migração simples (campo nullable + modelo
novo, sem data migration).

### Serviço `finances/services/budget_stats.py`

Toda a matemática de orçamento, determinística e testável isoladamente:

- `budget_spend_for_month(user, billing_month) -> list[dict]`
  Para cada orçamento do usuário: `{budget, name, amount, spent, pct, status}`,
  onde `spent = Σ amount` das entradas (`amount > 0`, exclui `#AJUSTE-SALDO`) das
  categorias do orçamento naquele `billing_month`. `status`: `error` (≥100%),
  `warning` (≥90%), senão `success`. Reaproveita o padrão de exclusão de ajuste de
  `category_stats.ADJUSTMENT_CATEGORY_PATTERN`.

- `orphan_category_spend_for_month(user, billing_month) -> list[dict]`
  Mesma forma, mas para categorias com `budget IS NULL` e `budget_ceiling > 0`
  (replica a regra de aviso por-categoria de hoje).

- `total_diverse_ceiling(user) -> Decimal`
  `Σ Budget.amount` + `Σ budget_ceiling` das categorias sem orçamento. É o "teto
  consolidado" que a Fase 2 consome. **Simplificação conhecida:** mantém a
  semântica atual (teto é cap da categoria inteira, não dividido por tipo de
  lançamento) — espelha o `AlertsView` de hoje em vez de inventar um split
  sistêmico/diverso.

- `seed_amount_from_ceilings(budget) -> Decimal`
  `Σ budget_ceiling` das categorias membros. Usado pela ação "recalcular".

### Avisos do dashboard (`AlertsView` em `finances/api/views.py`)

Substituir o laço por-categoria atual (linhas ~150–183) por:

1. Para cada item de `budget_spend_for_month`: emite `danger` ("{nome} ultrapassou
   teto em R$ {over}") ou `warning` ("{nome} em {pct}% do teto …"); senão conta como
   ok.
2. Para cada item de `orphan_category_spend_for_month`: mesma regra, mensagem
   referenciando o nome da categoria (cobertura preservada).
3. Mensagem de sucesso passa a "N orçamentos dentro do teto" (orçamentos +
   categorias órfãs ok).

As seções de parcelas e ordenação por severidade ficam intactas.

### UI de gestão (Settings)

Seguindo o padrão HTMX de `finances/views/settings.py` e seus templates:

- Lista de orçamentos: nome, `amount`, soma dos tetos das categorias membros (para
  comparar), nº de categorias.
- Criar/editar/excluir orçamento (form com `name`, `amount`).
- Atribuir categoria a orçamento: um `<select>` de orçamento na linha de cada
  categoria, na tabela de categorias já existente em Settings (altera
  `Category.budget` via HTMX, sem tela separada).
- Botão "recalcular pela soma dos tetos" → `amount = seed_amount_from_ceilings`.
- `Budget` registrado no admin (espelha `finances/admin.py`).

**Fora de escopo:** a tela **Consolidado** (cards por categoria) fica inalterada.
Agrupar o consolidado por orçamento é um passo futuro.

---

## Fase 2 — Toggle mediana/teto na projeção

### Estimador

Em `finances/services/category_stats.py`, ao lado de
`monthly_diverse_total_median`:

```python
def monthly_diverse_total_ceiling(user) -> Decimal:
    """Teto planejado de diversas: soma dos orçamentos + tetos órfãos."""
    from finances.services.budget_stats import total_diverse_ceiling
    return total_diverse_ceiling(user)
```

(Wrapper fino para manter a projeção desacoplada do módulo de orçamentos e o ponto
de escolha do estimador num lugar só.)

### Serviço `build_projection`

Novo parâmetro `diverse_estimator: str = "median"`:

```python
def build_projection(user, start_month, num_months, today=None,
                     overlay=None, diverse_estimator="median"):
    ...
    if diverse_estimator == "ceiling":
        est_typical_diverse = monthly_diverse_total_ceiling(user)
    else:
        est_typical_diverse = monthly_diverse_total_median(user, window=6, as_of=today)
```

Tudo o mais inalterado. A regra "não projetar abaixo do já lançado no mês corrente"
(`max(diverse, est_typical_diverse)` no mês corrente) vale nos dois modos.

### View / Template

`finances/views/projection.py`:

- `build_projection_context` lê `request.GET.get("estimate")` → `"teto"` mapeia para
  `diverse_estimator="ceiling"`, qualquer outro valor → `"median"`. Default
  `median`. Passa adiante a `build_projection`; o what-if (`_overlay_simulation`)
  ramifica do track estimado, então herda a escolha automaticamente.
- Expor `estimate` no contexto para o template marcar o toggle ativo e preservá-lo
  nos links/HTMX (como `months`/`start`).

Template (`projection/_projection_body.html`): um toggle de dois estados
(Mediana | Teto) no cabeçalho, disparando o mesmo fluxo HTMX dos outros controles.

---

## Testes (TDD em cada fase)

**Fase 1:**
- `test_budget_model`: criação, unicidade `(user, name)`, `SET_NULL` ao excluir.
- `test_budget_stats`: spend/pct/status por orçamento; exclusão de `#AJUSTE-SALDO`;
  órfãs; `total_diverse_ceiling` (orçamentos + órfãs); `seed_amount_from_ceilings`.
- `test_api_alerts` (estende o existente): avisos por orçamento substituem os por
  categoria; órfãs ainda alertam; mensagem de sucesso nova.
- `test_views_settings` (estende): CRUD de orçamento, atribuição, recálculo.

**Fase 2:**
- `test_category_stats`: `monthly_diverse_total_ceiling` = teto consolidado.
- `test_projection_service`: `diverse_estimator="ceiling"` usa o teto; `"median"`
  e default inalterados; mês corrente respeita `max(diverse, est)`.
- `test_views_projection`: `?estimate=teto` muda o track estimado; default mediana;
  toggle marcado corretamente.

## Riscos / notas

- **Semântica do teto vs. tipo de lançamento:** o teto de categoria é um cap da
  categoria inteira, não dividido entre diverso/sistêmico/parcela. A projeção usa
  esse teto só para a linha de **diversas**. Mantemos a simplificação atual do
  `AlertsView`; se virar problema, um flag de tipo na categoria resolve depois.
- **Migração:** apenas aditiva (modelo novo + FK nullable). Sem backfill. Os
  orçamentos começam vazios; o usuário cria e atribui via Settings.
- **Frontend build:** se o toggle/UX tocar Tailwind novo, rebuild + commit dos
  artefatos (`mount.js`, `tailwind.css`) conforme regra do projeto.
