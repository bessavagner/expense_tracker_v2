# Receipt propose→confirm→commit-once Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the photo-receipt assistant flow propose (never write) on the image turn and commit exactly once (deterministically, from the stored `ReceiptDraft` plan) on confirmation, eliminating the double-registration bug.

**Architecture:** Split today's one-shot `register_receipt` into `propose_receipt` (validate + ratear + store a committable plan in `ReceiptDraft.payload["plan"]`, no DB writes) and `commit_receipt` (create the `Entry` rows from the stored plan, mark `REGISTERED`, idempotent). A new restricted `receipt_confirm_agent` (no generic write tools) handles the image proposal and, via deterministic routing (any message while a PENDING draft exists), the confirm/edit/cancel turns.

**Tech Stack:** Django (async views) + pydantic-ai agents, pytest with `pydantic_ai.models.test.TestModel` (LLM disabled via `ALLOW_MODEL_REQUESTS=False` in `assistant/tests/conftest.py`), model_bakery.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-23-receipt-propose-confirm-design.md` — implement exactly.
- **TDD + worktree:** work in an isolated worktree; failing test first → fail → minimal impl → pass → commit. Small commits.
- **Test DB:** pgvector container on **port 5433**. Run: `POSTGRES_PORT=5433 uv run pytest <paths> -v` from repo root.
- **Test fixtures (assistant):** `user`, `logged_client`, `seeded_user`, `baker` (see `assistant/tests/conftest.py`). LLM is disabled globally; agent tests use `TestModel` via `agents_override(...)` (`assistant/agents/orchestrator.py:107`) or `<agent>.override(model=TestModel())`.
- **No migration:** the plan is stored in the existing `ReceiptDraft.payload` (JSONField) under key `"plan"`; status uses the existing `ReceiptDraftStatus {PENDING, REGISTERED, DISCARDED}`.
- **Determinism:** `commit_receipt` must NOT call the LLM and must NOT re-categorize — it only materializes `payload["plan"]["lines"]`. Store FK ids in the plan so commit never re-resolves by name.
- **Money:** `Decimal`, quantized to cents (`_CENTS = Decimal("0.01")`, `ROUND_HALF_UP`); reuse `_prorate_discount` (`tools.py:130`).
- **Scope:** photo-receipt flow only. Plain-text registration stays immediate. No draft expiration, no historical-dup sweep.
- **Lint:** `uv run ruff check src/backend` (line-length 100).

## File Structure

- Modify `src/backend/finances/../assistant/agents/tools.py` — extract `_resolve_receipt_plan(...)` core from `register_receipt`; add `propose_receipt`, `commit_receipt`, `discard_receipt`; retire `register_receipt` write body (keep removed from agents).
- Create `src/backend/assistant/agents/receipt_confirm.py` — `receipt_confirm_agent`.
- Modify `src/backend/assistant/agents/prompts.py` — add `RECEIPT_CONFIRM_PROMPT`.
- Modify `src/backend/assistant/agents/registrar.py` — remove the `register_receipt` tool.
- Modify `src/backend/assistant/agents/extraction.py` — `extraction_to_prompt` instructs `propose_receipt` (never write).
- Modify `src/backend/assistant/agents/orchestrator.py` — `agents_override` also overrides `receipt_confirm_agent`.
- Modify `src/backend/assistant/views.py` — image flow proposes; routing pending-draft→`receipt_confirm_agent`; `MUTATING_TOOLS` update; fallback retry/ask-resend.
- Tests: `src/backend/assistant/tests/test_receipt_flow.py` (new, unit) + additions to `test_views.py` (integration).

---

## Task 1: `propose_receipt` + shared plan builder (no DB writes)

**Files:**
- Modify: `src/backend/assistant/agents/tools.py`
- Test: `src/backend/assistant/tests/test_receipt_flow.py` (new)

**Interfaces:**
- Consumes: `ReceiptDraft`, `ReceiptDraftStatus`, `_resolve_by_name`, `_prorate_discount`, `list_categories`, `list_payment_methods`, `Category`, `PaymentMethod`, `_CENTS`, `Decimal`, `timezone`.
- Produces:
  - `_resolve_receipt_plan(user, draft, items_by_category, payment_method_name="", summaries=None) -> tuple[dict | None, str]` — returns `(plan, "")` on success or `(None, error_message)`. `plan` = `{"store","date","payment_method_id","payment_method_name","lines":[{"category_id","category_name","description","amount"}],"total","table"}`.
  - `propose_receipt(user, items_by_category, payment_method_name="", summaries=None) -> str` — resolves the plan for the latest PENDING draft, stores it in `draft.payload["plan"]`, returns the table preview + a confirm question. Creates **no** `Entry`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_receipt_flow.py`:

```python
from decimal import Decimal

import pytest
from model_bakery import baker

from assistant.agents.tools import propose_receipt
from assistant.models import ReceiptDraft, ReceiptDraftStatus
from finances.models import Entry

pytestmark = pytest.mark.django_db


def _draft(user, **over):
    payload = {
        "store": "MATEUS",
        "date": "2026-06-22",
        "discount": "0",
        "amount_paid": "100.00",
        "payment_hint": "Pix",
        "items": [
            {"description": "arroz", "line_total": "60.00"},
            {"description": "refri", "line_total": "40.00"},
        ],
    }
    payload.update(over)
    return ReceiptDraft.objects.create(
        user=user, payload=payload, status=ReceiptDraftStatus.PENDING
    )


def test_propose_stores_plan_and_writes_nothing(seeded_user):
    _draft(seeded_user)
    out = propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
        summaries={"Alimentação": "grãos", "Lanche": "bebida"},
    )
    assert Entry.objects.count() == 0  # nothing written
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert draft.status == ReceiptDraftStatus.PENDING
    plan = (draft.payload or {}).get("plan")
    assert plan is not None
    amounts = sorted(Decimal(l["amount"]) for l in plan["lines"])
    assert amounts == [Decimal("40.00"), Decimal("60.00")]
    assert plan["payment_method_name"] == "Pix"
    assert "Confirma" in out


def test_propose_rejects_incomplete_coverage(seeded_user):
    _draft(seeded_user)
    out = propose_receipt(seeded_user, items_by_category={"Alimentação": [0]})
    assert "exatamente UMA" in out  # item 1 missing
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert "plan" not in (draft.payload or {})


def test_propose_ambiguous_payment_asks(seeded_user):
    _draft(seeded_user, payment_hint="")
    out = propose_receipt(
        seeded_user, items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="",
    )
    assert "forma de pagamento" in out.lower()
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert "plan" not in (draft.payload or {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v`
Expected: FAIL — `ImportError: cannot import name 'propose_receipt'`.

- [ ] **Step 3: Write minimal implementation**

In `src/backend/assistant/agents/tools.py`, refactor: extract the resolution/rateio core out of `register_receipt` into `_resolve_receipt_plan`, then add `propose_receipt`. Place above `register_receipt`:

```python
def _resolve_receipt_plan(
    user, draft, items_by_category, payment_method_name="", summaries=None
):
    """Validate + resolve a committable plan from a pending receipt draft.

    Returns (plan, "") on success or (None, error_message). No DB writes.
    """
    payload = draft.payload or {}
    items = payload.get("items", [])
    n = len(items)
    if n == 0:
        return None, "Erro: o recibo pendente não tem itens."

    assigned = [i for idxs in items_by_category.values() for i in idxs]
    if sorted(assigned) != list(range(n)):
        seen: set[int] = set()
        dups = sorted({i for i in assigned if (i in seen) or seen.add(i)})
        missing = sorted(set(range(n)) - set(assigned))
        out_of_range = sorted(i for i in assigned if i < 0 or i >= n)
        problems = []
        if missing:
            problems.append(f"faltando={missing}")
        if dups:
            problems.append(f"repetidos={dups}")
        if out_of_range:
            problems.append(f"fora do intervalo 0..{n - 1}={out_of_range}")
        return None, (
            f"Erro: cada um dos {n} itens deve ser atribuído a exatamente UMA "
            f"categoria ({'; '.join(problems)})."
        )

    pm_name = (payment_method_name or "").strip() or str(
        payload.get("payment_hint") or ""
    ).strip()
    payment_method, pm_matches = _resolve_by_name(
        PaymentMethod.objects.filter(user=user, is_active=True), pm_name
    )
    if payment_method is None:
        available = ", ".join(list_payment_methods(user))
        if len(pm_matches) > 1:
            return None, (
                f"Forma de pagamento '{pm_name}' é ambígua. Qual? "
                f"{', '.join(pm_matches)}"
            )
        hint = str(payload.get("payment_hint") or "").strip()
        last4 = str(payload.get("card_last4") or "").strip()
        extra = f" O cupom indica '{hint}'." if hint else ""
        if last4:
            extra += f" Cartão final {last4}."
        return None, (
            f"Qual a forma de pagamento?{extra} Não consegui resolver "
            f"'{pm_name}'. Disponíveis: {available}"
        )

    resolved: dict[str, object] = {}
    category_sums: dict[str, Decimal] = {}
    for cat_name, idxs in items_by_category.items():
        category, cat_matches = _resolve_by_name(
            Category.objects.filter(user=user), cat_name
        )
        if category is None:
            if len(cat_matches) > 1:
                return None, (
                    f"Erro: categoria '{cat_name}' é ambígua. "
                    f"Você quis dizer: {', '.join(cat_matches)}?"
                )
            available = ", ".join(list_categories(user))
            return None, (
                f"Erro: categoria '{cat_name}' não encontrada. Disponíveis: {available}"
            )
        try:
            subtotal = sum(
                (Decimal(str(items[i].get("line_total", "0"))) for i in idxs),
                Decimal("0"),
            )
        except InvalidOperation:
            return None, f"Erro: valor inválido nos itens da categoria '{cat_name}'."
        resolved[cat_name] = category
        category_sums[cat_name] = subtotal

    try:
        discount_val = Decimal(str(payload.get("discount") or "0"))
    except InvalidOperation:
        discount_val = Decimal("0")
    discount_by_cat = _prorate_discount(category_sums, discount_val)

    store = str(payload.get("store") or "Recibo").strip()
    date_str = payload.get("date")
    try:
        entry_date = date.fromisoformat(date_str) if date_str else timezone.localdate()
    except (ValueError, TypeError):
        entry_date = timezone.localdate()

    summaries = summaries or {}
    lines = []
    for cat_name, category in resolved.items():
        net = (category_sums[cat_name] - discount_by_cat[cat_name]).quantize(_CENTS)
        summary = (summaries.get(cat_name) or "").strip() or category.name
        description = f"{store} - {summary}".replace(",", " -").strip()
        lines.append(
            {
                "category_id": str(category.id),
                "category_name": category.name,
                "description": description,
                "amount": f"{net:.2f}",
            }
        )

    total = sum((Decimal(l["amount"]) for l in lines), Decimal("0"))
    table_rows = "\n".join(
        f"| {l['category_name']} | R$ {l['amount']} |" for l in lines
    )
    table = (
        f"**{store}** — {entry_date:%d/%m/%Y} · {payment_method.name}\n\n"
        f"| Categoria | Valor |\n|---|---|\n{table_rows}\n\n"
        f"Total: R$ {total:.2f}"
    )
    plan = {
        "store": store,
        "date": entry_date.isoformat(),
        "payment_method_id": payment_method.id,
        "payment_method_name": payment_method.name,
        "lines": lines,
        "total": f"{total:.2f}",
        "table": table,
    }
    return plan, ""


def propose_receipt(user, items_by_category, payment_method_name="", summaries=None) -> str:
    """Plan (não grava) o recibo de FOTO pendente: valida, rateia e SALVA o plano
    no draft. Mostre a tabela e PEÇA confirmação; só grava no commit."""
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return "Não há recibo (foto) pendente para preparar."
    plan, err = _resolve_receipt_plan(
        user, draft, items_by_category, payment_method_name, summaries
    )
    if err:
        return err
    payload = draft.payload or {}
    payload["plan"] = plan
    draft.payload = payload
    draft.save(update_fields=["payload", "updated_at"])
    return f"{plan['table']}\n\nConfirma?"
```

Add `payment_method_id` JSON-safety note: `payment_method.id`/`category.id` may be UUID — store `str(...)`. The code above already uses `str(category.id)`; change `"payment_method_id": payment_method.id` to `"payment_method_id": str(payment_method.id)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_flow.py
git commit -m "feat(assistant): propose_receipt (validate+plan, no write)"
```

---

## Task 2: `commit_receipt` + `discard_receipt` (deterministic, idempotent)

**Files:**
- Modify: `src/backend/assistant/agents/tools.py`
- Test: `src/backend/assistant/tests/test_receipt_flow.py`

**Interfaces:**
- Consumes: `ReceiptDraft`, `ReceiptDraftStatus`, `Entry`, `transaction`, `Decimal`, `date`.
- Produces:
  - `commit_receipt(user) -> str` — materializes `payload["plan"]["lines"]` of the latest PENDING draft into `Entry` rows (one per line), marks `REGISTERED`, returns a confirmation string. Idempotent (no pending plan → "Não há recibo pendente.").
  - `discard_receipt(user) -> str` — marks latest PENDING draft `DISCARDED`.

- [ ] **Step 1: Write the failing test**

Append to `test_receipt_flow.py`:

```python
from assistant.agents.tools import commit_receipt, discard_receipt


def test_commit_creates_entries_once_and_is_idempotent(seeded_user):
    _draft(seeded_user)
    propose_receipt(
        seeded_user,
        items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
    )
    out = commit_receipt(seeded_user)
    assert Entry.objects.filter(user=seeded_user).count() == 2
    draft = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at")
    assert draft.status == ReceiptDraftStatus.REGISTERED
    assert "Registrado" in out
    total = sorted(e.amount for e in Entry.objects.filter(user=seeded_user))
    assert total == [Decimal("40.00"), Decimal("60.00")]
    # second confirm must NOT duplicate
    out2 = commit_receipt(seeded_user)
    assert Entry.objects.filter(user=seeded_user).count() == 2
    assert "pendente" in out2.lower()


def test_commit_without_plan_writes_nothing(seeded_user):
    _draft(seeded_user)  # pending draft but no propose() => no plan
    out = commit_receipt(seeded_user)
    assert Entry.objects.count() == 0
    assert "pendente" in out.lower()


def test_discard_blocks_commit(seeded_user):
    _draft(seeded_user)
    propose_receipt(
        seeded_user, items_by_category={"Alimentação": [0], "Lanche": [1]},
        payment_method_name="Pix",
    )
    discard_receipt(seeded_user)
    out = commit_receipt(seeded_user)
    assert Entry.objects.count() == 0
    assert "pendente" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v -k "commit or discard"`
Expected: FAIL — `ImportError: cannot import name 'commit_receipt'`.

- [ ] **Step 3: Write minimal implementation**

Add to `tools.py`:

```python
def commit_receipt(user) -> str:
    """Grava (uma vez) o recibo PENDENTE a partir do plano salvo. Determinístico."""
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    plan = (draft.payload or {}).get("plan") if draft else None
    if draft is None or not plan:
        return "Não há recibo pendente para registrar."

    try:
        entry_date = date.fromisoformat(plan["date"])
    except (ValueError, TypeError, KeyError):
        entry_date = timezone.localdate()

    created = []
    with transaction.atomic():
        for line in plan["lines"]:
            entry = Entry.objects.create(
                user=user,
                date=entry_date,
                amount=Decimal(line["amount"]),
                description=line["description"],
                category_id=line["category_id"],
                payment_method_id=plan["payment_method_id"],
            )
            created.append((line["category_name"], entry.amount))
        draft.status = ReceiptDraftStatus.REGISTERED
        draft.save(update_fields=["status", "updated_at"])

    total = sum((amt for _, amt in created), Decimal("0"))
    parts = "; ".join(f"{name} R$ {amt:.2f}" for name, amt in created)
    return (
        f"✅ Registrado de {plan['store']} em {entry_date:%d/%m/%Y} via "
        f"{plan['payment_method_name']}: {parts} (total R$ {total:.2f})"
    )


def discard_receipt(user) -> str:
    """Descarta o recibo (foto) PENDENTE mais recente sem gravar."""
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return "Não há recibo pendente para descartar."
    draft.status = ReceiptDraftStatus.DISCARDED
    draft.save(update_fields=["status", "updated_at"])
    return "Recibo descartado. Nada foi registrado."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_receipt_flow.py
git commit -m "feat(assistant): commit_receipt (deterministic, idempotent) + discard_receipt"
```

---

## Task 3: Retire `register_receipt` write path + `receipt_confirm_agent`

**Files:**
- Modify: `src/backend/assistant/agents/tools.py` (remove old `register_receipt` body)
- Modify: `src/backend/assistant/agents/registrar.py` (drop `register_receipt` tool + import)
- Create: `src/backend/assistant/agents/receipt_confirm.py`
- Modify: `src/backend/assistant/agents/prompts.py` (add `RECEIPT_CONFIRM_PROMPT`)
- Modify: `src/backend/assistant/agents/orchestrator.py` (`agents_override` overrides the new agent)
- Test: `src/backend/assistant/tests/test_receipt_flow.py`

**Interfaces:**
- Produces: `receipt_confirm_agent` (pydantic-ai `Agent`) with tools `propose_receipt`, `commit_receipt`, `discard_receipt`, `get_categories`, `get_payment_methods`, `check_memory`, `save_memory_rule`. No generic write tools.

- [ ] **Step 1: Write the failing test (agent shape + register_receipt retired)**

Append to `test_receipt_flow.py`:

```python
def test_receipt_agent_has_no_generic_write_tools():
    from assistant.agents.receipt_confirm import receipt_confirm_agent

    names = set(receipt_confirm_agent._function_toolset.tools.keys())
    assert {"propose_receipt", "commit_receipt", "discard_receipt"} <= names
    assert "register_entry" not in names
    assert "register_receipt" not in names


def test_registrar_no_longer_exposes_register_receipt():
    from assistant.agents.registrar import registrar_agent

    assert "register_receipt" not in set(
        registrar_agent._function_toolset.tools.keys()
    )
```

> NOTE: confirm the introspection path for tool names on the installed pydantic-ai version. If `_function_toolset.tools` differs, discover it once (`python -c "from assistant.agents.registrar import registrar_agent; print(dir(registrar_agent))"`) and use the correct attribute consistently in both assertions. Do not weaken the assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v -k "agent or registrar"`
Expected: FAIL — `ModuleNotFoundError: assistant.agents.receipt_confirm`.

- [ ] **Step 3: Implement**

In `prompts.py`, add:

```python
RECEIPT_CONFIRM_PROMPT = """Você confirma um RECIBO de foto já lido e pendente.

REGRAS:
- Para CATEGORIZAR/exibir a proposta: chame propose_receipt (items_by_category por
  ÍNDICE, cada item em UMA categoria; summaries opcional). Mostre a tabela LIMPA
  (Categoria | Valor) e termine com UMA pergunta "Confirma?". NUNCA exiba índices.
- Se o usuário CONFIRMAR (ex.: "sim", "pode", "isso", "ok"): chame commit_receipt.
- Se o usuário CANCELAR (ex.: "não", "cancela", "descarta"): chame discard_receipt.
- Se o usuário pedir AJUSTE (mudar categoria/itens/pagamento): chame propose_receipt
  de novo com a correção e re-exiba a tabela (não grave ainda).
- Só existe UM recibo pendente por vez. Nunca invente lançamentos.
"""
```

Create `src/backend/assistant/agents/receipt_confirm.py`:

```python
"""Agente de CONFIRMAÇÃO de recibo de foto (propor → confirmar → gravar uma vez).

Privilégio mínimo: sem ferramentas de escrita genérica. A única gravação é
commit_receipt (determinística, a partir do plano salvo no ReceiptDraft).
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic_ai import Agent, RunContext

from assistant.agents.prompts import RECEIPT_CONFIRM_PROMPT, build_date_instructions
from assistant.agents.tools import (
    commit_receipt as _commit_receipt,
)
from assistant.agents.tools import (
    create_memory_rule,
    list_categories,
    list_payment_methods,
    lookup_memory_async,
)
from assistant.agents.tools import (
    discard_receipt as _discard_receipt,
)
from assistant.agents.tools import (
    propose_receipt as _propose_receipt,
)

User = get_user_model()

receipt_confirm_agent = Agent(
    settings.LLM_ORCHESTRATOR_MODEL,
    deps_type=User,
    system_prompt=RECEIPT_CONFIRM_PROMPT,
)
receipt_confirm_agent.instructions(build_date_instructions)


@receipt_confirm_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa do usuário."""
    return await sync_to_async(list_categories)(ctx.deps)


@receipt_confirm_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return await sync_to_async(list_payment_methods)(ctx.deps)


@receipt_confirm_agent.tool
async def propose_receipt(
    ctx: RunContext[User],
    items_by_category: dict[str, list[int]],
    payment_method_name: str = "",
    summaries: dict[str, str] | None = None,
) -> str:
    """Prepara (sem gravar) o recibo pendente e mostra a tabela para confirmação."""
    return await sync_to_async(_propose_receipt)(
        ctx.deps, items_by_category, payment_method_name, summaries
    )


@receipt_confirm_agent.tool
async def commit_receipt(ctx: RunContext[User]) -> str:
    """Grava (uma vez) o recibo pendente a partir do plano confirmado."""
    return await sync_to_async(_commit_receipt)(ctx.deps)


@receipt_confirm_agent.tool
async def discard_receipt(ctx: RunContext[User]) -> str:
    """Descarta o recibo pendente sem gravar."""
    return await sync_to_async(_discard_receipt)(ctx.deps)


@receipt_confirm_agent.tool
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem."""
    return await lookup_memory_async(ctx.deps, message)


@receipt_confirm_agent.tool
async def save_memory_rule(
    ctx: RunContext[User], trigger: str, field: str, value: str
) -> str:
    """Salva uma regra de memória a partir de correção do usuário."""
    return await sync_to_async(create_memory_rule)(ctx.deps, trigger, field, value)
```

In `registrar.py`: delete the `register_receipt` tool function (the `@registrar_agent.tool async def register_receipt(...)`) and its import `from assistant.agents.tools import (register_receipt as _register_receipt,)`.

In `tools.py`: delete the now-unused one-shot `register_receipt` function (its logic now lives in `_resolve_receipt_plan` + `commit_receipt`). Keep `_prorate_discount`, `_resolve_receipt_plan`, `build_receipt_context`.

In `orchestrator.py` `agents_override` (line 107): add `receipt_confirm_agent` to the set of agents it overrides. Read the function first; it currently overrides the orchestrator + sub-agents (registrar/analyst/etc.). Add an import `from assistant.agents.receipt_confirm import receipt_confirm_agent` and include `receipt_confirm_agent.override(model=model)` in the same `ExitStack`/`with` it already builds. (Match the existing structure exactly.)

- [ ] **Step 4: Run tests + grep for stale references**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_receipt_flow.py -v`
Run: `grep -rn "register_receipt" src/backend/assistant` — expected: only historical references in tests you update next / none in agents.
Expected: target tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/
git commit -m "feat(assistant): receipt_confirm_agent; retire one-shot register_receipt"
```

---

## Task 4: `extraction_to_prompt` proposes (never writes)

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py`
- Test: `src/backend/assistant/tests/test_extraction.py`

**Interfaces:**
- Consumes: `ReceiptExtraction`. Produces: updated `extraction_to_prompt(ext, caption="", needs_review=False) -> str` whose instructions tell the agent to call `propose_receipt` and ask "Confirma?", and NEVER to write/grave/`register_receipt`.

- [ ] **Step 1: Write the failing test**

Append to `test_extraction.py` (reuse its existing `ReceiptExtraction` construction helpers; inspect the file first for the builder):

```python
def test_extraction_prompt_instructs_propose_not_write():
    from assistant.agents.extraction import ReceiptExtraction, extraction_to_prompt

    ext = ReceiptExtraction(
        store="MATEUS", date="2026-06-22", items=[], amount_paid="0", discount="0",
    )
    for needs_review in (False, True):
        p = extraction_to_prompt(ext, "", needs_review=needs_review)
        assert "propose_receipt" in p
        assert "register_receipt" not in p
        assert "Confirma" in p
```

> NOTE: `ReceiptExtraction` may require more/fewer fields — construct it to match the model (inspect `extraction.py:48`). Keep the three assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_extraction.py -v -k propose_not_write`
Expected: FAIL (current prompt says `register_receipt`).

- [ ] **Step 3: Implement**

In `extraction.py` `extraction_to_prompt`, change BOTH branches so the head instructs `propose_receipt` (never write). Replace the `needs_review` head and the else head:

```python
    if needs_review:
        head = (
            "Recibo lido da foto, mas a LEITURA ESTÁ INCERTA (confiança baixa ou a "
            "soma não fechou). Categorize os itens e chame propose_receipt "
            "(items_by_category={categoria: [índices]}, cada índice em UMA só "
            "categoria; summaries={categoria: resumo curto}). Os índices são "
            "internos: NUNCA os exiba. propose_receipt NÃO grava — ele mostra a "
            "tabela. Aponte o que ficou duvidoso e termine com UMA pergunta "
            "'Confirma?'. NÃO registre nada até o usuário confirmar."
        )
    else:
        head = (
            "Recibo lido da foto. Categorize os itens NUMERADOS abaixo e chame "
            "propose_receipt (items_by_category={categoria: [índices]}, cada índice "
            "em UMA só categoria; summaries={categoria: resumo curto}). NUNCA exiba "
            "os índices. propose_receipt NÃO grava — apenas prepara e mostra a "
            "tabela LIMPA 'Categoria | Valor' com loja, data, pagamento e total. "
            "NÃO redigite valores. Termine com UMA única pergunta 'Confirma?'."
        )
```

(The numbered `item_lines` block and the rest stay unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_extraction.py -v`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/extraction.py src/backend/assistant/tests/test_extraction.py
git commit -m "feat(assistant): receipt extraction prompt proposes (never auto-writes)"
```

---

## Task 5: Views — image proposes (no write) + safe fallback

**Files:**
- Modify: `src/backend/assistant/views.py`
- Test: `src/backend/assistant/tests/test_views.py`

**Interfaces:**
- Consumes: `receipt_confirm_agent`, `extract_receipt`, `extraction_to_prompt`, `ReceiptDraft`.
- Produces: `_handle_images` runs `receipt_confirm_agent` (propose); on extraction failure, retries once with `LLM_VISION_MODEL` and, if still failing, returns a "resend" message — never the old freeform write path.

- [ ] **Step 1: Write the failing test**

Inspect `test_views.py` for the existing image test (it overrides `extraction_agent`/`registrar_agent` with `TestModel`). Add:

```python
def test_image_proposes_without_writing(self, logged_client, seeded_user):
    from io import BytesIO
    from assistant.agents.extraction import extraction_agent
    from assistant.agents.receipt_confirm import receipt_confirm_agent
    from finances.models import Entry
    from pydantic_ai.models.test import TestModel

    img = BytesIO(b"\xff\xd8\xff\xe0fakejpeg")
    img.name = "r.jpg"
    with (
        extraction_agent.override(model=TestModel()),
        receipt_confirm_agent.override(model=TestModel()),
    ):
        resp = logged_client.post(
            "/api/assistant/chat/", {"image": img}, format="multipart"
        )
        b"".join(resp.streaming_content)
    # image turn must never create entries
    assert Entry.objects.filter(user=seeded_user).count() == 0
```

> NOTE: match the existing image test's request style in `test_views.py` (content type / field names / how it drains `streaming_content`). `TestModel` calls each agent tool with dummy args; the assertion that matters is **0 entries** after the image turn (propose, not write). If `prepare_receipt_image` rejects the fake bytes, reuse whatever minimal valid image bytes the existing image test uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v -k image_proposes`
Expected: FAIL (today the image turn can write via registrar).

- [ ] **Step 3: Implement**

In `views.py`:
- Replace the `registrar_agent` import usage in `_handle_images` with `receipt_confirm_agent` (import it at top: `from assistant.agents.receipt_confirm import receipt_confirm_agent`).
- In the `extraction is not None` branch, change `_sse_response(user, registrar_agent, prompt, ...)` → `_sse_response(user, receipt_confirm_agent, prompt, ...)`.
- Replace the freeform fallback (lines ~298-314) with a single retry + ask-resend:

```python
    # Fallback: tenta UMA vez a extração com o modelo de visão; sem sucesso,
    # pede reenvio (nunca grava direto).
    try:
        extraction = await extract_receipt(prepared, model=settings.LLM_VISION_MODEL)
    except Exception:
        logger.exception("Extração do recibo falhou mesmo com o modelo de visão.")
        extraction = None

    if extraction is None:
        async def _resend():
            msg = (
                "Não consegui ler esse recibo com segurança. Pode reenviar a foto "
                "(mais nítida / completa) ou me diga os itens por texto?"
            )
            yield json.dumps({"type": "user_text", "content": user_label}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "token", "content": msg}, ensure_ascii=False) + "\n"
            assistant_msg = await ChatMessage.objects.acreate(
                user=user, role=MessageRole.ASSISTANT, content=msg
            )
            yield json.dumps(
                {"type": "done", "message_id": str(assistant_msg.id), "data_changed": False},
                ensure_ascii=False,
            ) + "\n"
        resp = StreamingHttpResponse(_resend(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    await ReceiptDraft.objects.acreate(
        user=user, chat_message=chat_msg, payload=extraction.model_dump(mode="json")
    )
    needs_review = receipt_needs_review(
        extraction, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE
    )
    prompt = extraction_to_prompt(extraction, caption, needs_review=needs_review)
    return _sse_response(
        user, receipt_confirm_agent, prompt, message_history=None, user_text=user_label
    )
```

> NOTE: `extract_receipt` currently takes only `images`. Add an optional `model=None` param to `extract_receipt` (extraction.py) that forwards to `extraction_agent.run(prompt, model=model)` so the vision-model retry works. If you prefer not to touch `extract_receipt`'s signature, wrap the retry with `extraction_agent.override(model=settings.LLM_VISION_MODEL)` instead — pick one and keep the structured-output path. Either way the fallback must produce a `ReceiptExtraction` or ask-resend; it must NOT write.

- Remove the now-unused `registrar_agent`/`BinaryContent` imports from `_handle_images` if no longer referenced.

- [ ] **Step 4: Run tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v`
Expected: PASS (existing image tests adjusted + new). If an existing test asserted the old auto-write behavior, update it to the propose behavior (note it in the report).

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/agents/extraction.py src/backend/assistant/tests/test_views.py
git commit -m "feat(assistant): image turn proposes via receipt_confirm_agent; safe fallback"
```

---

## Task 6: Views — deterministic routing for pending receipts

**Files:**
- Modify: `src/backend/assistant/views.py`
- Test: `src/backend/assistant/tests/test_views.py`

**Interfaces:**
- Consumes: `ReceiptDraft`, `ReceiptDraftStatus`, `receipt_confirm_agent`.
- Produces: when a PENDING `ReceiptDraft` exists for the user, `_handle_json` and the text branch of `_handle_multipart` route the message to `receipt_confirm_agent` instead of `assistant_agent`. `MUTATING_TOOLS` includes `commit_receipt`.

- [ ] **Step 1: Write the failing test (regression)**

Append to `test_views.py`:

```python
def test_pending_receipt_routes_confirm_and_commits_once(self, logged_client, seeded_user):
    from assistant.agents.receipt_confirm import receipt_confirm_agent
    from assistant.agents.tools import propose_receipt
    from assistant.models import ReceiptDraft, ReceiptDraftStatus
    from finances.models import Entry
    from pydantic_ai.models.test import TestModel

    draft = ReceiptDraft.objects.create(
        user=seeded_user, status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "MATEUS", "date": "2026-06-22", "discount": "0",
            "payment_hint": "Pix",
            "items": [
                {"description": "arroz", "line_total": "60.00"},
                {"description": "refri", "line_total": "40.00"},
            ],
        },
    )
    propose_receipt(seeded_user, {"Alimentação": [0], "Lanche": [1]}, "Pix")

    # A TestModel that calls only commit_receipt simulates the user's "sim".
    tm = TestModel(call_tools=["commit_receipt"])
    with receipt_confirm_agent.override(model=tm):
        resp = logged_client.post(
            "/api/assistant/chat/", {"message": "sim"},
            content_type="application/json",
        )
        b"".join(resp.streaming_content)
    assert Entry.objects.filter(user=seeded_user).count() == 2
    draft.refresh_from_db()
    assert draft.status == ReceiptDraftStatus.REGISTERED
```

> NOTE: send "sim" as JSON the same way the existing JSON chat tests do. `TestModel(call_tools=[...])` restricts which tools the fake model calls — confirm this kwarg name on the installed pydantic-ai; if different, use the equivalent (or a `FunctionModel` that emits a single `commit_receipt` call). The assertion that matters: exactly 2 entries and draft REGISTERED.

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v -k pending_receipt_routes`
Expected: FAIL (currently "sim" goes to the orchestrator, not the receipt agent).

- [ ] **Step 3: Implement**

In `views.py`:
- Add a helper:

```python
async def _pending_receipt(user):
    from assistant.models import ReceiptDraft, ReceiptDraftStatus

    return await (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .afirst()
    )
```

- In `_handle_json`, after creating the user `ChatMessage` and before returning the orchestrator response, route to the receipt agent when a draft is pending:

```python
    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=message)
    if await _pending_receipt(user):
        from assistant.agents.receipt_confirm import receipt_confirm_agent
        return _sse_response(user, receipt_confirm_agent, message, message_history=None)
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, message, message_history=history)
```

- In `_handle_multipart`'s text-only branch (the `await ChatMessage... caption` path near the end), apply the same pending-draft routing before the orchestrator call.
- Update `MUTATING_TOOLS` (top of file): add `"commit_receipt"` (so the front gets `data_changed` on commit). `propose_receipt`/`discard_receipt` are NOT mutating. You may drop `"register_receipt"` since it's retired (optional).

- [ ] **Step 4: Run tests**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/tests/test_views.py
git commit -m "feat(assistant): route pending-receipt messages to receipt_confirm_agent"
```

---

## Task 7: Full gate

- [ ] **Step 1: Full assistant + finances suite**

Run: `POSTGRES_PORT=5433 uv run pytest src/backend/assistant src/backend/finances -q`
Expected: all green. Fix any test that encoded the OLD auto-write behavior, updating it to propose→commit (note each change in the report).

- [ ] **Step 2: Lint**

Run: `uv run ruff check src/backend/assistant`
Expected: `All checks passed!`

- [ ] **Step 3: Manual/agent verification (optional but recommended)**

Per spec, the real bug is photo+"sim". A reviewer/controller may run the app on friday's data and: send a receipt photo (confirm 0 entries written, table + "Confirma?"), reply "sim" (confirm N entries written once), reply "sim" again (0 new). This is a behavior change to a daily-use bot — worth a smoke check before deploy.

---

## Self-Review (completed by plan author)

- **Spec coverage:** propose (no write) → Task 1; commit-once + idempotent + discard → Task 2; restricted agent + retire register_receipt → Task 3; extraction prompt proposes → Task 4; image turn proposes + safe fallback → Task 5; deterministic routing + MUTATING_TOOLS → Task 6; regression (photo+sim = N not 2N) → Tasks 2 & 6; gate → Task 7. All spec sections mapped.
- **Type consistency:** plan shape (`store/date/payment_method_id/payment_method_name/lines[{category_id,category_name,description,amount}]/total/table`) is produced by `_resolve_receipt_plan`/`propose_receipt` (Task 1) and consumed verbatim by `commit_receipt` (Task 2). `receipt_confirm_agent` tool names (`propose_receipt/commit_receipt/discard_receipt`) match the routing (Task 6) and the agent-shape test (Task 3). `agents_override` extended (Task 3) so view integration tests can mock the new agent (Tasks 5–6).
- **Placeholders:** none — full code for the pure tools, agent, prompt, extraction, and view edits. Four NOTE callouts flag library-introspection details (pydantic-ai tool-listing attribute, `TestModel(call_tools=...)` kwarg, image test request style, `extract_receipt` model param) to confirm against the installed versions at implementation time — not deferred work.
- **IDs as strings:** `category_id`/`payment_method_id` stored as `str(...)` in the JSON plan; `Entry.objects.create(category_id=..., payment_method_id=...)` accepts the stored value (UUID/int) — verify the pk type when implementing Task 2 and cast if the ORM rejects a str pk.
```
