# Receipt: Readable Descriptions + Learnable Categories — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Receipt entries get short human-readable descriptions, and item categories are corrected + remembered per user (learned category rules applied to future receipts).

**Architecture:** (1) A deterministic `_apply_category_memory` overrides each extracted item's category from the user's `MemoryRule(field="category")` (substring match on the NF item name) before the plan is built. (2) Prompt changes make the assistant generate readable per-category `summaries` (already plumbed into the saved description) and save a category rule (with an NF-matching trigger) whenever the user corrects a category.

**Tech Stack:** Django ORM, pydantic-ai agent prompts, pytest (fixtures in `assistant/tests/conftest.py`: `seeded_user` has categories Alimentação/Lanche/Álcool + PMs Pix/Crédito C6).

## Global Constraints
- **TDD non-negotiable** (RED→GREEN→commit). **Isolated git worktree.** **Verify + code review** before finishing.
- Backend from `<worktree>/src/backend`; interpreter `/home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest`; DB pgvector `:5433` (copy `.env` from main checkout into the worktree; no local venv).
- `ruff check` clean on touched files.
- `MemoryRule.trigger` is stored **lowercased** by `create_memory_rule`; the apply helper must lowercase both sides when matching.
- NF item names are abbreviated (`ENERG MONSTER`, `REFRIG LARANJA`) — category-rule triggers must be NF tokens (`energ`, `refrig`, `monster`), NOT colloquial words. This is enforced via the prompt (Task 2), matched case-insensitively.
- Category rules apply ONLY in the auto path (`items_by_category is None`); an explicit `items_by_category` (user correcting this turn) wins and is NOT overridden.
- `MemoryRule` is already imported in `tools.py`. Do not touch the discount/dedup logic.

---

### Task 1: `_apply_category_memory` + wire into `_resolve_receipt_plan`

**Files:**
- Modify: `src/backend/assistant/agents/tools.py` (add helper; call it in `_resolve_receipt_plan` auto path, ~line 398)
- Test: `src/backend/assistant/tests/test_category_memory.py` (new)

**Interfaces:**
- Produces: `_apply_category_memory(user, items) -> None` — mutates each item's `"category"` in place when a category rule's (lowercased) trigger is a substring of the item's lowercased `"description"`; longest trigger wins; no-op when the user has no category rules.

- [ ] **Step 1: Write failing tests**

Create `src/backend/assistant/tests/test_category_memory.py`:

```python
import pytest
from assistant.agents.tools import _apply_category_memory, propose_receipt
from assistant.models import MemoryRule, MemorySource, ReceiptDraft, ReceiptDraftStatus

pytestmark = pytest.mark.django_db


def _rule(user, trigger, value):
    return MemoryRule.objects.create(
        user=user, trigger=trigger, field="category", value=value,
        source=MemorySource.USER_CORRECTION,
    )


def test_apply_overrides_category_from_rule(seeded_user):
    _rule(seeded_user, "energ", "Lanche")
    _rule(seeded_user, "refrig", "Lanche")
    items = [
        {"description": "ENERG MONSTER 473ML", "category": "Alimentação"},
        {"description": "REFRIG LARANJA SJ 350ML", "category": "Alimentação"},
        {"description": "BROCOLIS ESP KG", "category": "Alimentação"},
    ]
    _apply_category_memory(seeded_user, items)
    assert items[0]["category"] == "Lanche"
    assert items[1]["category"] == "Lanche"
    assert items[2]["category"] == "Alimentação"  # no rule → unchanged


def test_apply_case_insensitive_and_uppercase_trigger(seeded_user):
    # even if a trigger were stored uppercase, matching is case-insensitive
    MemoryRule.objects.create(
        user=seeded_user, trigger="MONSTER", field="category", value="Lanche",
        source=MemorySource.USER_CORRECTION,
    )
    items = [{"description": "energ monster 473ml", "category": "Alimentação"}]
    _apply_category_memory(seeded_user, items)
    assert items[0]["category"] == "Lanche"


def test_apply_longest_trigger_wins(seeded_user):
    _rule(seeded_user, "queijo", "Alimentação")
    _rule(seeded_user, "queijo coalho", "Lanche")
    items = [{"description": "QUEIJO COALHO ZERO LACTOSE", "category": "?"}]
    _apply_category_memory(seeded_user, items)
    assert items[0]["category"] == "Lanche"


def test_apply_no_rules_is_noop(seeded_user):
    items = [{"description": "ENERG MONSTER", "category": "Alimentação"}]
    _apply_category_memory(seeded_user, items)
    assert items[0]["category"] == "Alimentação"


def test_propose_auto_path_applies_rules(seeded_user):
    _rule(seeded_user, "energ", "Lanche")
    ReceiptDraft.objects.create(
        user=seeded_user, status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos", "date": "2026-07-06", "amount_paid": "13.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "ENERG MONSTER 473ML", "line_total": "10.00", "category": "Alimentação"},
                {"description": "BROCOLIS ESP KG", "line_total": "3.00", "category": "Alimentação"},
            ],
        },
    )
    propose_receipt(seeded_user, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    cats = {ln["category_name"] for ln in plan["lines"]}
    assert cats == {"Lanche", "Alimentação"}


def test_propose_explicit_categories_not_overridden(seeded_user):
    _rule(seeded_user, "energ", "Lanche")  # would move item 0 to Lanche in auto path
    ReceiptDraft.objects.create(
        user=seeded_user, status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Cosmos", "date": "2026-07-06", "amount_paid": "13.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "ENERG MONSTER 473ML", "line_total": "10.00", "category": "Alimentação"},
                {"description": "BROCOLIS ESP KG", "line_total": "3.00", "category": "Alimentação"},
            ],
        },
    )
    # user explicitly assigns BOTH items to Alimentação this turn
    propose_receipt(seeded_user, items_by_category={"Alimentação": [0, 1]}, payment_method_name="Pix")
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    cats = {ln["category_name"] for ln in plan["lines"]}
    assert cats == {"Alimentação"}  # rule NOT applied; explicit assignment won
```

- [ ] **Step 2: Run tests, verify RED**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_category_memory.py -v`
Expected: import/attribute error or failures — `_apply_category_memory` doesn't exist yet, and `test_propose_auto_path_applies_rules` fails (auto path currently keeps both as Alimentação).

- [ ] **Step 3: Add the helper**

In `src/backend/assistant/agents/tools.py`, add ABOVE `_items_by_category_from_items` (~line 331):

```python
def _apply_category_memory(user, items) -> None:
    """Override each item's category from the user's learned category rules.

    NF item names are abbreviated (e.g. "ENERG MONSTER"), so a rule's trigger is
    matched as a case-insensitive substring of the item description. When several
    rules match one item, the longest (most specific) trigger wins. Mutates
    ``items`` in place; items with no matching rule keep the vision category.
    Rules are the user's ``MemoryRule`` rows with ``field="category"``.
    """
    rules = list(MemoryRule.objects.filter(user=user, field="category"))
    if not rules:
        return
    # Longest trigger first → most specific match wins.
    rules.sort(key=lambda r: len(r.trigger or ""), reverse=True)
    for item in items:
        desc = str(item.get("description") or "").lower()
        if not desc:
            continue
        for rule in rules:
            trig = (rule.trigger or "").lower()
            if trig and trig in desc:
                item["category"] = rule.value
                break
```

- [ ] **Step 4: Wire into `_resolve_receipt_plan`**

In `_resolve_receipt_plan`, change the auto-derive branch (currently):

```python
    if items_by_category is None:
        derived = _items_by_category_from_items(items)
```

to:

```python
    if items_by_category is None:
        _apply_category_memory(user, items)
        derived = _items_by_category_from_items(items)
```

- [ ] **Step 5: Run tests, verify GREEN**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_category_memory.py -v`
Expected: all PASS.

- [ ] **Step 6: Broader suite + lint + commit**

```bash
cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/ -q
/home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m ruff check assistant/agents/tools.py assistant/tests/test_category_memory.py
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_category_memory.py
git commit -m "feat(receipt): apply learned category rules to extracted items"
```
Expected: assistant suite PASS; ruff clean.

---

### Task 2: Prompts — readable summaries + learn-on-correction

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py` (`extraction_to_prompt` — add readable-summaries guidance to both heads)
- Modify: `src/backend/assistant/agents/tools.py` (`build_pending_receipt_directive` — replace the "não passe summaries" guidance; add save-category-rule guidance)
- Test: `src/backend/assistant/tests/test_receipt_prompts.py` (new)

**Interfaces:**
- Produces: prompt strings that (a) instruct generating a readable pt-BR `summaries={categoria: texto}` per category, and (b) instruct `save_memory_rule(trigger=<NF token>, field="category", value=...)` on a category correction.

- [ ] **Step 1: Write failing tests**

Create `src/backend/assistant/tests/test_receipt_prompts.py`:

```python
import pytest
from assistant.agents.extraction import ReceiptExtraction, extraction_to_prompt
from assistant.agents.tools import build_pending_receipt_directive
from assistant.models import ReceiptDraft, ReceiptDraftStatus

pytestmark = pytest.mark.django_db


def test_extraction_prompt_asks_for_readable_summaries():
    ext = ReceiptExtraction(
        store="Cosmos", amount_paid="13.00",
        items=[{"description": "ENERG MONSTER", "line_total": "10.00", "category": "Lanche"}],
    )
    out = extraction_to_prompt(ext)
    low = out.lower()
    assert "summaries" in out
    assert "resumo" in low or "legível" in low or "legivel" in low


def test_pending_directive_asks_summaries_and_learns_category(seeded_user):
    ReceiptDraft.objects.create(
        user=seeded_user, status=ReceiptDraftStatus.PENDING,
        payload={"store": "Cosmos", "amount_paid": "13.00",
                 "items": [{"description": "ENERG MONSTER", "line_total": "10.00"}]},
    )
    out = build_pending_receipt_directive(seeded_user)
    low = out.lower()
    # readable summaries requested
    assert "summaries" in out and ("resumo" in low or "legível" in low or "legivel" in low)
    # learn category on correction
    assert "save_memory_rule" in out
    assert "category" in out
    # trigger must be an NF token, not a colloquial word
    assert "trecho" in low or "aparece" in low or "nome do item" in low
```

- [ ] **Step 2: Run tests, verify RED**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_receipt_prompts.py -v`
Expected: FAIL — current prompts don't request readable summaries and the directive says "NO CASO NORMAL não passe summaries".

- [ ] **Step 3: Edit `extraction_to_prompt`**

In `src/backend/assistant/agents/extraction.py`, in the NORMAL `head` string (the `else` branch), append this sentence just before `"NÃO redigite valores."`:

```
"Para CADA categoria, gere um resumo curto e legível em pt-BR agrupando os "
"tipos de produto (ex.: 'bolachas, energéticos e refrigerantes'; 'legumes e "
"verduras, leite, flocão') e passe em summaries={categoria: resumo}; NUNCA "
"inclua o nome da loja no resumo. "
```

And in the `needs_review` `head`, append before `"NÃO registre nada até o usuário confirmar."`:

```
"Para cada categoria, gere também um resumo curto e legível (summaries={categoria: "
"resumo}) agrupando os tipos de produto. "
```

- [ ] **Step 4: Edit `build_pending_receipt_directive`**

In `src/backend/assistant/agents/tools.py`, replace the store-prefix/summaries block (currently):

```python
        "- Loja errada/ausente OU pedido de PREFIXO de loja (ex.: 'adicione "
        "Amazon - como prefixo'): isso é a LOJA → propose_receipt(store_name="
        "\"Amazon\"). A descrição de cada linha já vira 'LOJA - <nomes dos "
        "produtos>' automaticamente: NO CASO NORMAL não passe summaries e NUNCA "
        "inclua o nome da loja no summary (senão vira 'Loja - Loja - ...'). Só use "
        "summaries={categoria: \"texto\"} se o usuário pedir explicitamente outro "
        "texto. A tabela mostra a coluna 'Itens' (produtos) para conferência.\n"
```

with:

```python
        "- Loja errada/ausente OU pedido de PREFIXO de loja (ex.: 'adicione "
        "Amazon - como prefixo'): isso é a LOJA → propose_receipt(store_name="
        "\"Amazon\"). A descrição de cada linha vira 'LOJA - <summary>': SEMPRE "
        "gere um summary curto e legível por categoria agrupando os tipos de "
        "produto (ex.: 'bolachas, energéticos e refrigerantes') e passe em "
        "summaries={categoria: texto}; NUNCA inclua o nome da loja no summary "
        "(senão vira 'Loja - Loja - ...'). A tabela mostra a coluna 'Itens' "
        "(produtos) para conferência.\n"
```

And replace the category-correction bullet (currently):

```python
        "- Corrigir CATEGORIA de itens: propose_receipt(items_by_category={categoria: "
        "[índices]}).\n"
```

with:

```python
        "- Corrigir CATEGORIA de itens: propose_receipt(items_by_category={categoria: "
        "[índices]}) E, para não repetir o erro nas próximas notas, SALVE a regra "
        "com save_memory_rule(trigger=<um trecho que aparece no NOME do item na "
        "nota, ex.: 'ENERG', 'REFRIG', 'MONSTER'>, field=\"category\", "
        "value=<Categoria>). Uma regra por tipo de item corrigido.\n"
```

- [ ] **Step 5: Run tests, verify GREEN**

Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/test_receipt_prompts.py assistant/tests/test_receipt_date_and_dup.py -v`
Expected: new prompt tests PASS; existing receipt tests still PASS.

- [ ] **Step 6: Broader suite + lint + commit**

```bash
cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/tests/ -q
/home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m ruff check assistant/agents/extraction.py assistant/agents/tools.py assistant/tests/test_receipt_prompts.py
git add src/backend/assistant/agents/extraction.py src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_prompts.py
git commit -m "feat(receipt): prompt for readable summaries + learn category rules on correction"
```
Expected: assistant suite PASS; ruff clean.

---

### Task 3: Verify + deploy

**Files:** none.

- [ ] **Step 1: Full assistant + finances suites green, ruff clean.**
Run: `cd src/backend && /home/bessa/Documents/projetos/expense_tracker_v2/.venv/bin/python -m pytest assistant/ finances/ -q`

- [ ] **Step 2: Merge to main + push** (finishing-a-development-branch, merge+push).

- [ ] **Step 3: Deploy to Cloud Run** (Python-only, NO migration — new field values only, no schema change):
```bash
gcloud run deploy expense-tracker --source . --project expense-tracker-482807 --region southamerica-east1 --quiet
```
NOTE: production deploy requires explicit user authorization at run time (auto-mode gates it). Smoke: `/healthz` 200, root 302, assetlinks fingerprint intact.

- [ ] **Step 4: Tell the user** to re-send a receipt: descriptions should now be readable, and correcting a category once ("energético é lanche") teaches the bot for future receipts.
