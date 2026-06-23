# Single Strong Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Collapse `orchestrator + registrar + analyst + planner + receipt_confirm` into ONE strong `assistant_agent` (model `gpt-5.4`) holding all tools, plus new edit/delete-entry and add-receipt-item tools — so the conversation is smart, can correct prior entries, and can add a line (frete) to a pending receipt.

**Architecture:** One `Agent(LLM_ASSISTANT_MODEL)` with the union of all current tools + 4 new ones; vision `extract_receipt` and the deterministic `propose_receipt`/`commit_receipt` stay. `views.py` routes every message to this one agent (no delegation, no pending-receipt routing trap).

**Tech Stack:** Django 6 async views, PydanticAI, pytest. Run from repo root: `POSTGRES_PORT=5433 .venv/bin/pytest …`. Async tests use `@pytest.mark.anyio`. Pre-existing staticfiles `UserWarning` on view tests is acceptable.

## Global Constraints

- Keep `extract_receipt`, `propose_receipt`/`commit_receipt`/`discard_receipt`, and all existing `tools.py` helpers UNCHANGED (only ADD helpers).
- New setting `LLM_ASSISTANT_MODEL = os.environ.get("LLM_ASSISTANT_MODEL", "openai:gpt-5.4")`.
- The single agent keeps the symbol name `assistant_agent` (imported by `views.py`); `agents_override(model)` context manager and `ALL_AGENTS` remain available (now wrapping the single agent) so tests keep working.
- `MUTATING_TOOLS` (views.py) must list the REAL write tools, not `delegate_registro`.
- Confirm-before-write discipline stays (CONFIRMATION_POLICY in the consolidated prompt; receipts via propose→commit).
- TDD. Branch `feat/single-strong-agent` (created). Spec: `docs/.ai/prompts/009_SINGLE_AGENT/009_DESIGN.md`.
- `Entry` model: `finances/models/entry.py` — UUID `id`, `date`, `amount` (Decimal), `description`, `category` FK, `payment_method` FK, `billing_month` (recomputed in `save()` when `billing_month_override` is False).

## Source map (existing tool wrappers to MOVE, deduped)
- Write (registrar.py): `register_entry, add_category, set_category_budget, add_payment_method, set_income, get_systemic_expenses, set_systemic_amount`.
- Read (analyst.py): `get_expenses, get_balance, get_budget_status, get_installments, get_category_breakdown, compare_with_previous_month, export_monthly_report, find_anomalies, get_category_averages`.
- Plan (planner.py): `project_month_end, get_proactive_alerts, get_upcoming_obligations, simulate_projection` (+ `HypotheticalItem` type used by `simulate_projection`).
- Receipt (receipt_confirm.py): `propose_receipt, commit_receipt, discard_receipt`.
- Shared (appear in several — register ONCE): `get_categories, get_payment_methods, check_memory, save_memory_rule, get_memory_rules`.

---

## Task 1: New helpers in `tools.py` (edit/delete entry, list recent, add receipt item)

**Files:**
- Modify: `src/backend/assistant/agents/tools.py`
- Test: `src/backend/assistant/tests/test_tools.py`

**Interfaces (Produces):**
- `list_recent_entries(user, limit=10) -> str`
- `update_entry(user, entry_id, date_str=None, amount_str=None, description=None, category_name=None, payment_method_name=None) -> str`
- `delete_entry(user, entry_id) -> str`
- `add_receipt_item(user, description, line_total, category="") -> str`

- [ ] **Step 1: Write failing tests** (append to `test_tools.py`; it already has `pytestmark = pytest.mark.django_db` and uses `seeded_user`/baker — confirm and reuse):

```python
def test_list_recent_entries_scoped_and_formatted(seeded_user):
    from assistant.agents.tools import create_entry, list_recent_entries
    create_entry(seeded_user, "2026-06-20", "50.00", "feira", "Alimentação", "Pix")
    out = list_recent_entries(seeded_user)
    assert "feira" in out and "50.00" in out
    # short id present (8 hex chars in brackets)
    import re
    assert re.search(r"\[[0-9a-f]{8}\]", out)


def test_update_entry_changes_fields_by_id_prefix(seeded_user):
    from assistant.agents.tools import create_entry, update_entry
    from finances.models import Entry
    create_entry(seeded_user, "2026-06-20", "50.00", "feira", "Alimentação", "Pix")
    e = Entry.objects.filter(user=seeded_user).latest("created_at")
    prefix = str(e.id)[:8]
    out = update_entry(seeded_user, prefix, amount_str="65.00", category_name="Lanche")
    e.refresh_from_db()
    assert e.amount == Decimal("65.00")
    assert e.category.name == "Lanche"
    assert "Atualizado" in out or "atualiz" in out.lower()


def test_update_entry_unknown_id(seeded_user):
    from assistant.agents.tools import update_entry
    assert "não encontrado" in update_entry(seeded_user, "deadbeef", amount_str="1.00").lower()


def test_delete_entry_removes(seeded_user):
    from assistant.agents.tools import create_entry, delete_entry
    from finances.models import Entry
    create_entry(seeded_user, "2026-06-20", "50.00", "feira", "Alimentação", "Pix")
    e = Entry.objects.filter(user=seeded_user).latest("created_at")
    out = delete_entry(seeded_user, str(e.id)[:8])
    assert Entry.objects.filter(id=e.id).count() == 0
    assert "exclu" in out.lower()


def test_add_receipt_item_appends_and_clears_plan(seeded_user):
    from assistant.agents.tools import add_receipt_item
    from assistant.models import ReceiptDraft, ReceiptDraftStatus
    d = ReceiptDraft.objects.create(
        user=seeded_user,
        payload={"store": "X", "items": [{"description": "a", "line_total": "10", "category": "Alimentação"}], "plan": {"stale": True}},
        status=ReceiptDraftStatus.PENDING,
    )
    out = add_receipt_item(seeded_user, "frete", "39.97", "Serviço")
    d.refresh_from_db()
    assert len(d.payload["items"]) == 2
    assert d.payload["items"][1]["description"] == "frete"
    assert "plan" not in d.payload  # forces re-propose
    assert "frete" in out


def test_add_receipt_item_no_draft(seeded_user):
    from assistant.agents.tools import add_receipt_item
    assert "pendente" in add_receipt_item(seeded_user, "x", "1.00", "Alimentação").lower()
```

(If `test_tools.py` lacks `Decimal`/`seeded_user`, add `from decimal import Decimal`; `seeded_user` is a conftest fixture providing categories `Alimentação`/`Lanche` and methods `Pix`. If `Serviço` category is absent for the add-receipt-item test, that test only checks the DRAFT payload, not category resolution, so it's fine.)

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_tools.py -k "recent_entries or update_entry or delete_entry or add_receipt_item" -v`
Expected: FAIL (helpers undefined).

- [ ] **Step 3: Implement helpers** in `tools.py` (place near `create_entry`; reuse `_resolve_by_name`, `Entry`, `Category`, `PaymentMethod`, `ReceiptDraft`, `ReceiptDraftStatus`, `Decimal`, `InvalidOperation`, `date`, all already imported):

```python
def _resolve_entry_by_prefix(user, entry_id: str):
    raw = (entry_id or "").strip().replace("-", "").lower()
    if not raw:
        return []
    return [e for e in Entry.objects.filter(user=user) if str(e.id).replace("-", "").startswith(raw)]


def list_recent_entries(user, limit: int = 10) -> str:
    qs = (
        Entry.objects.filter(user=user)
        .select_related("category", "payment_method")
        .order_by("-created_at")[:limit]
    )
    rows = list(qs)
    if not rows:
        return "Nenhum lançamento recente."
    lines = []
    for e in rows:
        cat = e.category.name if e.category else "—"
        pm = e.payment_method.name if e.payment_method else "—"
        lines.append(
            f"[{str(e.id)[:8]}] {e.date:%d/%m} R$ {e.amount} · {cat} · {pm} · {e.description}"
        )
    return "\n".join(lines)


def update_entry(
    user, entry_id, date_str=None, amount_str=None, description=None,
    category_name=None, payment_method_name=None,
) -> str:
    matches = _resolve_entry_by_prefix(user, entry_id)
    if not matches:
        return f"Erro: lançamento '{entry_id}' não encontrado."
    if len(matches) > 1:
        return f"Erro: id '{entry_id}' é ambíguo ({len(matches)} lançamentos). Dê mais dígitos."
    entry = matches[0]
    if category_name:
        category, m = _resolve_by_name(Category.objects.filter(user=user), category_name)
        if category is None:
            avail = ", ".join(list_categories(user))
            return f"Erro: categoria '{category_name}' não encontrada. Disponíveis: {avail}"
        entry.category = category
    if payment_method_name:
        pm, m = _resolve_by_name(
            PaymentMethod.objects.filter(user=user, is_active=True), payment_method_name
        )
        if pm is None:
            avail = ", ".join(list_payment_methods(user))
            return f"Erro: forma de pagamento '{payment_method_name}' não encontrada. Disponíveis: {avail}"
        entry.payment_method = pm
    if date_str:
        try:
            entry.date = date.fromisoformat(date_str)
        except ValueError:
            return f"Erro: data inválida '{date_str}'. Use AAAA-MM-DD."
    if amount_str:
        try:
            entry.amount = Decimal(amount_str)
        except InvalidOperation:
            return f"Erro: valor inválido '{amount_str}'."
    if description:
        entry.description = description
    entry.billing_month_override = False
    entry.save()
    return (
        f"Atualizado [{str(entry.id)[:8]}]: {entry.description} — R$ {entry.amount} "
        f"em {entry.category.name} via {entry.payment_method.name}"
    )


def delete_entry(user, entry_id) -> str:
    matches = _resolve_entry_by_prefix(user, entry_id)
    if not matches:
        return f"Erro: lançamento '{entry_id}' não encontrado."
    if len(matches) > 1:
        return f"Erro: id '{entry_id}' é ambíguo ({len(matches)} lançamentos). Dê mais dígitos."
    entry = matches[0]
    desc, amt = entry.description, entry.amount
    entry.delete()
    return f"Excluído: {desc} — R$ {amt}."


def add_receipt_item(user, description, line_total, category="") -> str:
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return "Não há recibo pendente para adicionar item."
    try:
        Decimal(str(line_total))
    except InvalidOperation:
        return f"Erro: valor inválido '{line_total}'."
    payload = draft.payload or {}
    items = payload.get("items", [])
    items.append({"description": description, "line_total": str(line_total), "category": (category or None)})
    payload["items"] = items
    payload.pop("plan", None)
    draft.payload = payload
    draft.save(update_fields=["payload", "updated_at"])
    return f"Item adicionado ao recibo: {description} — R$ {line_total}. Re-proponha com propose_receipt()."
```

- [ ] **Step 4: Run → PASS** (focused + whole `test_tools.py`)

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_tools.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_tools.py
git commit -m "feat(assistant): add update_entry/delete_entry/list_recent_entries/add_receipt_item helpers"
```

---

## Task 2: Consolidated `ASSISTANT_PROMPT`

**Files:**
- Modify: `src/backend/assistant/agents/prompts.py`
- Test: `src/backend/assistant/tests/test_prompts.py`

**Interfaces (Produces):** `ASSISTANT_PROMPT: str` composing role + LEGACY_REGISTRO_RULES + CONFIRMATION_POLICY + PHOTO_POLICY + MEMORY_POLICY + analysis/planning guidance + ENTITY_GLOSSARY.

- [ ] **Step 1: Write failing test** (append to `test_prompts.py`):

```python
def test_assistant_prompt_covers_all_capabilities():
    from assistant.agents.prompts import ASSISTANT_PROMPT
    p = ASSISTANT_PROMPT.lower()
    for needle in ["registr", "analis", "planej", "recibo", "memó", "confirm"]:
        assert needle in p, needle
    # edit/correct + add-item guidance present
    assert "list_recent_entries" in ASSISTANT_PROMPT
    assert "update_entry" in ASSISTANT_PROMPT
    assert "add_receipt_item" in ASSISTANT_PROMPT
```

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_prompts.py -k assistant_prompt -v`
Expected: FAIL (`ASSISTANT_PROMPT` undefined).

- [ ] **Step 3: Implement** — add `ASSISTANT_PROMPT` in `prompts.py` after the existing prompts. Lead with the role: a single personal-finance assistant (pt-BR) that EXECUTES directly (no routing), registers/edits/deletes lançamentos, answers analysis, plans, and confirms photo receipts. Concatenate the existing blocks and add explicit guidance:

```python
ASSISTANT_PROMPT = (
    """\
Você é o ASSISTENTE financeiro pessoal (pt-BR). Você EXECUTA diretamente — não
roteia para outros agentes. Você registra, edita e exclui lançamentos; responde
consultas e análises; faz planejamento; e confirma recibos de foto. Valores em
Real (R$). Seja direto e não calcule de cabeça — use as ferramentas.

Editar/corrigir um lançamento já gravado: use list_recent_entries para achar o id
curto, depois update_entry(entry_id, campos) ou delete_entry(entry_id). NÃO crie um
novo lançamento quando o usuário pedir para corrigir um existente.

Recibo de foto: os itens já vêm lidos e categorizados; chame propose_receipt() (sem
índices) e confirme antes de commit_receipt(). Para adicionar algo que não está na
foto (ex.: frete), use add_receipt_item(descrição, valor, categoria) e re-proponha.
"""
    + "\n" + LEGACY_REGISTRO_RULES
    + "\n" + CONFIRMATION_POLICY
    + "\n" + PHOTO_POLICY
    + "\n" + MEMORY_POLICY
    + "\n" + ENTITY_GLOSSARY
)
```

(Keep existing prompts in place for now; Task 5 removes the dead ones. Do not delete blocks this task.)

- [ ] **Step 4: Run → PASS** (focused + whole `test_prompts.py`)

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/prompts.py src/backend/assistant/tests/test_prompts.py
git commit -m "feat(assistant): consolidated ASSISTANT_PROMPT for single agent"
```

---

## Task 3: The single `assistant_agent` (new module) + setting + agents_override

**Files:**
- Create: `src/backend/assistant/agents/assistant.py`
- Modify: `src/backend/config/settings.py` (add `LLM_ASSISTANT_MODEL`)
- Test: `src/backend/assistant/tests/test_assistant.py` (new)

**Interfaces (Produces):** `assistant_agent` (Agent), `agents_override(model)` ctx manager, `ALL_AGENTS`. Registers all tools from the Source map + the 4 new helpers + `simulate_projection`'s `HypotheticalItem`.

- [ ] **Step 1: Add setting** in `settings.py` near the other `LLM_*`:

```python
LLM_ASSISTANT_MODEL = os.environ.get("LLM_ASSISTANT_MODEL", "openai:gpt-5.4")
```

- [ ] **Step 2: Write failing test** (`test_assistant.py`):

```python
import pytest
from pydantic_ai.models.test import TestModel

from assistant.agents.assistant import agents_override, assistant_agent


def _tools(agent):
    return set(agent._function_toolset.tools.keys())


def test_agent_exposes_full_toolset():
    t = _tools(assistant_agent)
    expected = {
        # write
        "register_entry", "add_category", "set_category_budget", "add_payment_method",
        "set_income", "set_systemic_amount", "update_entry", "delete_entry",
        # receipt
        "propose_receipt", "commit_receipt", "discard_receipt", "add_receipt_item",
        # read
        "get_categories", "get_payment_methods", "get_systemic_expenses", "get_expenses",
        "get_balance", "get_budget_status", "get_installments", "get_category_breakdown",
        "compare_with_previous_month", "export_monthly_report", "find_anomalies",
        "get_category_averages", "list_recent_entries",
        # plan
        "project_month_end", "get_proactive_alerts", "get_upcoming_obligations",
        "simulate_projection",
        # memory
        "check_memory", "save_memory_rule", "get_memory_rules",
    }
    missing = expected - t
    assert not missing, f"missing tools: {missing}"


def test_no_delegation_tools():
    t = _tools(assistant_agent)
    assert not any(name.startswith("delegate_") for name in t)


@pytest.mark.django_db
class TestRuns:
    @pytest.mark.anyio
    async def test_runs_under_testmodel(self, seeded_user):
        with agents_override(TestModel()):
            result = await assistant_agent.run("gastei 50 no cosmos", deps=seeded_user)
            assert result.output
```

- [ ] **Step 3: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_assistant.py -v`
Expected: FAIL (module/agent absent).

- [ ] **Step 4: Implement `agents/assistant.py`**

Build the agent on `settings.LLM_ASSISTANT_MODEL` with `system_prompt=ASSISTANT_PROMPT`, `deps_type=User`. Add `.instructions(build_date_instructions)` and the `@assistant_agent.instructions async def pending_receipt_instructions(ctx)` (move the existing one from `orchestrator.py`, using `build_pending_receipt_directive`). Then register every tool wrapper by MOVING the existing `@<agent>.tool async def …` bodies VERBATIM from `registrar.py`, `analyst.py`, `planner.py`, `receipt_confirm.py` (deduping the shared ones: `get_categories, get_payment_methods, check_memory, save_memory_rule, get_memory_rules` — register ONCE; `get_balance, get_budget_status, get_installments` appear in analyst AND planner — register ONCE), re-decorated as `@assistant_agent.tool`. Add wrappers for the 4 new helpers:

```python
@assistant_agent.tool
async def list_recent_entries(ctx: RunContext[User], limit: int = 10) -> str:
    """Lista os lançamentos recentes (com id curto) para editar/excluir."""
    return await sync_to_async(_list_recent_entries)(ctx.deps, limit)


@assistant_agent.tool
async def update_entry(
    ctx: RunContext[User], entry_id: str, date: str | None = None,
    amount: str | None = None, description: str | None = None,
    category_name: str | None = None, payment_method_name: str | None = None,
) -> str:
    """Edita um lançamento existente (ache o id com list_recent_entries)."""
    return await sync_to_async(_update_entry)(
        ctx.deps, entry_id, date, amount, description, category_name, payment_method_name
    )


@assistant_agent.tool
async def delete_entry(ctx: RunContext[User], entry_id: str) -> str:
    """Exclui um lançamento existente (id de list_recent_entries)."""
    return await sync_to_async(_delete_entry)(ctx.deps, entry_id)


@assistant_agent.tool
async def add_receipt_item(
    ctx: RunContext[User], description: str, line_total: str, category: str = ""
) -> str:
    """Adiciona um item ao recibo de foto pendente (ex.: frete). Re-proponha depois."""
    return await sync_to_async(_add_receipt_item)(ctx.deps, description, line_total, category)
```

Import the helpers from `assistant.agents.tools` (alias the new ones with leading underscore in import to avoid clashing with the tool function names, e.g. `from assistant.agents.tools import update_entry as _update_entry`, etc.). Include `HypotheticalItem` (used by `simulate_projection`) from wherever planner.py imports it.

Add at the bottom:

```python
ALL_AGENTS = (assistant_agent,)

@contextmanager
def agents_override(model):
    with ExitStack() as stack:
        stack.enter_context(assistant_agent.override(model=model))
        yield
```

- [ ] **Step 5: Run → PASS**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_assistant.py -v`
Expected: PASS (full toolset present, runs under TestModel). Existing suite still green (old agents untouched this task).

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/assistant.py src/backend/config/settings.py src/backend/assistant/tests/test_assistant.py
git commit -m "feat(assistant): single strong assistant_agent with full toolset + new edit/receipt tools"
```

---

## Task 4: Route everything through the single agent + MUTATING_TOOLS

**Files:**
- Modify: `src/backend/assistant/views.py`
- Modify: `src/backend/assistant/tests/test_views.py` (import path), `test_data_changed.py`
- Test: `test_views.py`, `test_data_changed.py`

- [ ] **Step 1: Write failing test** — add to `test_data_changed.py` (it tests `_run_mutated_data`/`MUTATING_TOOLS`):

```python
def test_mutating_tools_are_real_writes():
    from assistant.views import MUTATING_TOOLS
    assert "register_entry" in MUTATING_TOOLS
    assert "commit_receipt" in MUTATING_TOOLS
    assert "update_entry" in MUTATING_TOOLS
    assert "delete_entry" in MUTATING_TOOLS
    assert "delegate_registro" not in MUTATING_TOOLS
    # non-writes excluded
    assert "propose_receipt" not in MUTATING_TOOLS
    assert "get_balance" not in MUTATING_TOOLS
```

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_data_changed.py -k mutating_tools_are_real -v`
Expected: FAIL (`delegate_registro` still in `MUTATING_TOOLS`).

- [ ] **Step 3: Implement** in `views.py`:
  - Change the import `from assistant.agents.orchestrator import assistant_agent` → `from assistant.agents.assistant import assistant_agent`. Remove the `receipt_confirm_agent` import.
  - In `_handle_json`, `_handle_multipart` (text), `_handle_audio`, `_handle_images`: replace the `if await _pending_receipt(user): _sse_response(..., receipt_confirm_agent, ...)` branches — route to `assistant_agent` in all cases (the pending-receipt directive is now an instruction on `assistant_agent`). Keep `user_text`/`message_history` args as they were. (For text: keep `message_history=_load_history` for non-receipt; the agent's instruction handles pending receipts regardless, so you can keep history always — but to match current behavior, when a receipt is pending pass `message_history=None`; simplest: keep the existing `_pending_receipt` check but point BOTH branches at `assistant_agent`, differing only in `message_history`.)
  - Update `MUTATING_TOOLS` to:

```python
MUTATING_TOOLS = frozenset({
    "register_entry", "commit_receipt", "add_category", "set_category_budget",
    "add_payment_method", "set_income", "set_systemic_amount",
    "update_entry", "delete_entry",
})
```

  - In `test_views.py` and `test_data_changed.py`: change `from assistant.agents.orchestrator import agents_override` → `from assistant.agents.assistant import agents_override`. Update `test_data_changed.py` cases that referenced `delegate_registro`/`delegate_analise` to use real tools (e.g. `register_entry` mutating, `get_balance` non-mutating); keep the `_run_mutated_data` unit tests meaningful.

- [ ] **Step 4: Run → PASS**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_views.py src/backend/assistant/tests/test_data_changed.py -v`
Expected: PASS. (`agents_override` now stubs the single agent that views actually runs.)

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/tests/test_views.py src/backend/assistant/tests/test_data_changed.py
git commit -m "feat(assistant): route all chat through single agent; MUTATING_TOOLS = real writes"
```

---

## Task 5: Delete the sub-agents + reconcile remaining tests

**Files:**
- Delete: `src/backend/assistant/agents/registrar.py`, `analyst.py`, `planner.py`, `receipt_confirm.py`, `orchestrator.py`
- Modify/Delete tests: `test_orchestrator.py` (delete — superseded by `test_assistant.py`), `test_receipt_flow.py` (agent-tool assertions)
- Grep + fix any remaining imports.

- [ ] **Step 1: Find all importers** of the doomed modules:

`grep -rn "agents.orchestrator\|agents.registrar\|agents.analyst\|agents.planner\|agents.receipt_confirm\|receipt_confirm_agent\|registrar_agent\|orchestrator_agent\|analyst_agent\|planner_agent" src/backend --include=*.py | grep -v __pycache__`

- [ ] **Step 2: Reconcile tests**
  - Delete `src/backend/assistant/tests/test_orchestrator.py` (its delegation/partitioning assertions no longer apply; `test_assistant.py` covers the agent). Move its still-valid `TestPendingReceiptDirective` tests (the `build_pending_receipt_directive` ones) into `test_assistant.py` or `test_tools.py` if not duplicated.
  - In `test_receipt_flow.py`: `test_receipt_agent_has_no_generic_write_tools` and `test_registrar_no_longer_exposes_register_receipt` import `receipt_confirm_agent`/`registrar_agent`. Replace with assertions on `assistant_agent` (it DOES now have write tools + propose/commit; assert it exposes `propose_receipt`/`commit_receipt`/`register_entry` and NOT `register_receipt`). Or remove the obsolete ones and keep the propose/commit behavior tests (which use the `tools.py` helpers directly and are unaffected).

- [ ] **Step 3: Delete the modules**

```bash
git rm src/backend/assistant/agents/registrar.py src/backend/assistant/agents/analyst.py src/backend/assistant/agents/planner.py src/backend/assistant/agents/receipt_confirm.py src/backend/assistant/agents/orchestrator.py
```

- [ ] **Step 4: Fix any remaining import errors** surfaced by collection:

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant -q` — fix every ImportError/NameError until green. Common spots: `_run_mutated_data` import in tests, `agents_override` import sites, `ASSISTANT_DELEGATION_REQUEST_LIMIT` setting now unused (leave the setting; harmless).

- [ ] **Step 5: Run full assistant suite → PASS**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant -q`

- [ ] **Step 6: Commit**

```bash
git add -A src/backend/assistant
git commit -m "refactor(assistant): remove orchestrator + sub-agents (collapsed into single agent)"
```

---

## Task 6: Full regression + lint

- [ ] **Step 1:** `POSTGRES_PORT=5433 .venv/bin/pytest src/backend -q` → PASS.
- [ ] **Step 2:** `.venv/bin/ruff check src/backend/assistant/` → clean (run `ruff format` + manual wrap for any E501).
- [ ] **Step 3:** Commit any lint fixups.

---

## Self-Review (coverage map)
- New tools (update/delete/list/add_receipt_item) → Task 1.
- Consolidated prompt → Task 2.
- Single agent + setting + agents_override → Task 3.
- Routing collapse + MUTATING_TOOLS → Task 4.
- Delete sub-agents + test reconciliation → Task 5.
- Regression/lint → Task 6.
- Spec "keep extraction/propose/commit unchanged" → enforced (only additions to tools.py; helpers untouched).
