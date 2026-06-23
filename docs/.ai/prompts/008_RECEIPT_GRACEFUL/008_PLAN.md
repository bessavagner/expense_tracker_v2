# Graceful Receipt Reading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use `- [ ]`.

**Goal:** Make photo-receipt reading robust (ChatGPT-like) by categorizing in the STRONG vision model, dropping the brittle item-index partition, and handling non-fiscal/e-commerce receipts with missing totals — all layered on the existing propose/commit architecture.

**Architecture:** `extract_receipt` (vision, `LLM_VISION_MODEL`) now also assigns a category per item (from the user's taxonomy) and a `receipt_type`, with nullable totals. `propose_receipt` derives the plan from those per-item categories (no index partition). `receipt_confirm_agent` (mini) only confirms/asks. `commit_receipt` unchanged.

**Tech Stack:** Django 6 async views, PydanticAI (vision + mini), pytest. Run tests from repo root with `POSTGRES_PORT=5433 .venv/bin/pytest …` (DB on 5433; `.env` not auto-loaded). A pre-existing `UserWarning: No directory at .../staticfiles/` on view tests is acceptable.

## Global Constraints

- Build ON propose/commit. Do NOT touch `commit_receipt`, `discard_receipt`, or the `_pending_receipt` routing in `views.py`.
- 1 lançamento por categoria (agregado) — keep current `_resolve_receipt_plan` aggregation.
- All new params are OPTIONAL/keyword → backward compatible. `test_receipt_flow.py`, `test_extraction.py`, `test_views.py` must stay green.
- `receipt_type` ∈ {`fiscal_cupom`, `ecommerce_order`, `invoice`, `other`}; default `"fiscal_cupom"`.
- Totals (`total`, `discount`, `amount_paid`) become `Decimal | None`, default `None`; `None` means "not visible" — never fabricate.
- Consistency gate (soma×pago) applies ONLY when `amount_paid is not None`.
- Heavy work (read + categorize + type) runs on the strong vision model; mini only confirms/asks.
- TDD. Branch `feat/receipt-graceful-reading` (already created). Spec: `docs/.ai/prompts/008_RECEIPT_GRACEFUL/008_DESIGN.md`.
- Async tests use `@pytest.mark.anyio` (NOT asyncio).

---

## Task 1: Extraction schema + consistency for nullable totals & per-item category

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py`
- Test: `src/backend/assistant/tests/test_extraction.py`

**Interfaces:**
- Produces: `ReceiptItem.category: str | None`; `ReceiptExtraction.receipt_type: str`; `ReceiptExtraction.total/discount/amount_paid: Decimal | None`. `receipt_is_consistent`/`receipt_needs_review` tolerate `amount_paid is None`.

- [ ] **Step 1: Write failing tests** (append to `test_extraction.py`):

```python
@pytest.mark.anyio
async def test_item_carries_category_and_receipt_type_defaults():
    from assistant.agents.extraction import ReceiptExtraction, ReceiptItem

    ext = ReceiptExtraction(items=[ReceiptItem(description="arroz", line_total=Decimal("10"), category="Alimentação")])
    assert ext.items[0].category == "Alimentação"
    assert ext.receipt_type == "fiscal_cupom"
    assert ext.amount_paid is None  # not "visible" by default now


def test_consistent_true_when_amount_paid_missing():
    from assistant.agents.extraction import ReceiptExtraction, ReceiptItem, receipt_is_consistent

    ext = ReceiptExtraction(items=[ReceiptItem(description="x", line_total=Decimal("10"))], amount_paid=None)
    assert receipt_is_consistent(ext) is True  # nothing to reconcile


def test_needs_review_false_when_amount_paid_missing_but_confident():
    from assistant.agents.extraction import ReceiptExtraction, ReceiptItem, receipt_needs_review

    ext = ReceiptExtraction(
        items=[ReceiptItem(description="x", line_total=Decimal("10"), category="Alimentação")],
        amount_paid=None, confidence=0.9,
    )
    assert receipt_needs_review(ext, min_confidence=0.6) is False


def test_needs_review_true_when_amount_paid_present_and_sum_wrong():
    from assistant.agents.extraction import ReceiptExtraction, ReceiptItem, receipt_needs_review

    ext = ReceiptExtraction(
        items=[ReceiptItem(description="x", line_total=Decimal("10"))],
        amount_paid=Decimal("99"), confidence=0.9,
    )
    assert receipt_needs_review(ext, min_confidence=0.6) is True
```

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_extraction.py -k "category_and_receipt_type or amount_paid_missing or sum_wrong" -v`
Expected: FAIL (`category`/`receipt_type` unknown; `amount_paid` defaults to 0 not None).

- [ ] **Step 3: Implement schema + consistency**

In `extraction.py`:
- `ReceiptItem`: add `category: str | None = None`.
- `ReceiptExtraction`: add `receipt_type: str = "fiscal_cupom"`; change `total`, `discount`, `amount_paid` to `Decimal | None = None`.
- `receipt_is_consistent`: guard nulls —

```python
def receipt_is_consistent(extraction, tolerance: Decimal = Decimal("0.05")) -> bool:
    if extraction.amount_paid is None:
        return True
    items_sum = sum((i.line_total for i in extraction.items), Decimal("0"))
    discount = extraction.discount or Decimal("0")
    return abs(items_sum - discount - extraction.amount_paid) <= tolerance
```

- `receipt_needs_review`: unchanged logic but it already calls `receipt_is_consistent` (now null-safe). Keep:

```python
def receipt_needs_review(extraction, min_confidence: float) -> bool:
    if not extraction.items:
        return True
    if extraction.confidence < min_confidence:
        return True
    return not receipt_is_consistent(extraction)
```

- [ ] **Step 4: Run → PASS** (the `-k` selection above) and the full file:

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_extraction.py -v`
Expected: PASS (existing tests stay green — they pass `amount_paid` explicitly or don't assert defaults).

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/extraction.py src/backend/assistant/tests/test_extraction.py
git commit -m "feat(receipt): per-item category, receipt_type, nullable totals + null-safe consistency"
```

---

## Task 2: `extract_receipt` taxonomy injection + prompts + auto-mode prompt

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py`
- Test: `src/backend/assistant/tests/test_extraction.py`

**Interfaces:**
- Consumes: schema from Task 1.
- Produces: `extract_receipt(images, categories=None, payment_methods=None, model=None)`; `extraction_to_prompt` instructs auto-mode (`propose_receipt()` without indices).

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.anyio
async def test_extract_receipt_injects_user_taxonomy(monkeypatch):
    from assistant.agents.extraction import extract_receipt, extraction_agent

    captured = {}
    real_run = extraction_agent.run

    async def spy(prompt, *a, **k):
        captured["prompt"] = prompt
        return await real_run(prompt, *a, **k)

    monkeypatch.setattr(extraction_agent, "run", spy)
    with extraction_agent.override(model=TestModel()):
        await extract_receipt(
            [(b"img", "image/jpeg")],
            categories=["Alimentação", "Limpeza"],
            payment_methods=["Pix", "Crédito Santander"],
        )
    text = captured["prompt"][0]  # instruction string is first element
    assert "Alimentação" in text and "Limpeza" in text
    assert "Crédito Santander" in text


def test_extraction_to_prompt_auto_mode_no_indices():
    from assistant.agents.extraction import ReceiptExtraction, ReceiptItem, extraction_to_prompt

    ext = ReceiptExtraction(
        items=[ReceiptItem(description="arroz", line_total=Decimal("10"), category="Alimentação")],
        amount_paid=Decimal("10"), confidence=0.9,
    )
    out = extraction_to_prompt(ext, needs_review=False)
    assert "propose_receipt()" in out  # instruct calling without items_by_category
    assert "Alimentação" in out
```

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_extraction.py -k "injects_user_taxonomy or auto_mode_no_indices" -v`
Expected: FAIL (`extract_receipt` has no `categories` kwarg; prompt lacks `propose_receipt()`).

- [ ] **Step 3: Implement**

- `extract_receipt`:

```python
async def extract_receipt(images, categories=None, payment_methods=None, model=None):
    instruction = EXTRACTION_INSTRUCTION
    if categories:
        instruction += (
            "\nCategorias do usuário (atribua a categoria de CADA item escolhendo "
            "EXATAMENTE uma desta lista; se nenhuma servir, deixe category=null): "
            + ", ".join(categories) + "."
        )
    if payment_methods:
        instruction += (
            "\nFormas de pagamento cadastradas (proponha em payment_hint a que casa, "
            "ou deixe como aparece no recibo): " + ", ".join(payment_methods) + "."
        )
    prompt = [instruction]
    prompt += [BinaryContent(data=data, media_type=mt) for data, mt in images]
    result = await extraction_agent.run(prompt, model=model)
    return result.output
```

- `EXTRACTION_PROMPT` / `EXTRACTION_INSTRUCTION`: generalize wording to "recibos/cupons/pedidos de compra (e-commerce) brasileiros"; ask for `receipt_type`; ask for per-item `category` (from the provided list, else null); leave `total/discount/amount_paid` null when not visible (never invent); keep anti-injection. (Edit the existing string constants; keep the multi-image sentence.)
- `extraction_to_prompt`: in the non-review branch, instruct the agent to **call `propose_receipt()` with NO `items_by_category`** (items already carry categories); only pass `items_by_category` when correcting a category; never show indices; when `amount_paid is None` or payment unresolved, ask first. Present each item as `descrição → categoria` (use `it.category or "?"`). Keep the review branch asking for confirmation. Remove reliance on exposing numeric indices in the happy path.

- [ ] **Step 4: Run → PASS** (focused + full file)

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_extraction.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/extraction.py src/backend/assistant/tests/test_extraction.py
git commit -m "feat(receipt): inject user taxonomy into vision extraction; prompt auto-mode (no indices)"
```

---

## Task 3: `propose_receipt` auto-mode from per-item categories (drop index partition)

**Files:**
- Modify: `src/backend/assistant/agents/tools.py`
- Modify: `src/backend/assistant/agents/receipt_confirm.py` (tool signature: optional `items_by_category`)
- Modify: `src/backend/assistant/agents/prompts.py` (`RECEIPT_CONFIRM_PROMPT`)
- Test: `src/backend/assistant/tests/test_receipt_flow.py`

**Interfaces:**
- Produces: `_items_by_category_from_items(items) -> dict[str, list[int]] | str`; `propose_receipt(user, items_by_category=None, ...)`; `_resolve_receipt_plan(user, draft, items_by_category=None, ...)`.

- [ ] **Step 1: Write failing tests** (append to `test_receipt_flow.py`; reuse `_draft` but add categories to items):

```python
def _draft_categorized(user):
    return ReceiptDraft.objects.create(
        user=user,
        payload={
            "store": "MATEUS", "date": "2026-06-22", "discount": None, "amount_paid": "100.00",
            "payment_hint": "Pix",
            "items": [
                {"description": "arroz", "line_total": "60.00", "category": "Alimentação"},
                {"description": "refri", "line_total": "40.00", "category": "Lanche"},
            ],
        },
        status=ReceiptDraftStatus.PENDING,
    )


def test_propose_auto_mode_groups_by_item_category(seeded_user):
    _draft_categorized(seeded_user)
    out = propose_receipt(seeded_user, payment_method_name="Pix")  # no items_by_category
    assert Entry.objects.count() == 0
    plan = ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload["plan"]
    amounts = sorted(Decimal(ln["amount"]) for ln in plan["lines"])
    assert amounts == [Decimal("40.00"), Decimal("60.00")]
    assert "Confirma" in out


def test_propose_auto_mode_errors_when_item_uncategorized(seeded_user):
    _draft(seeded_user)  # items have NO category
    out = propose_receipt(seeded_user, payment_method_name="Pix")
    assert "categor" in out.lower()  # asks for categorization
    assert "plan" not in (ReceiptDraft.objects.filter(user=seeded_user).latest("created_at").payload or {})
```

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_receipt_flow.py -k "auto_mode" -v`
Expected: FAIL (`propose_receipt` requires `items_by_category` today; auto-derivation absent).

- [ ] **Step 3: Implement**

In `tools.py`:
- Add helper:

```python
def _items_by_category_from_items(items):
    """Deriva {categoria: [índices]} a partir do campo category de cada item.
    Retorna string de erro se algum item não tiver categoria."""
    by_cat: dict[str, list[int]] = {}
    missing = []
    for i, it in enumerate(items):
        cat = (it.get("category") or "").strip()
        if not cat:
            missing.append(i)
            continue
        by_cat.setdefault(cat, []).append(i)
    if missing:
        return (
            "Itens sem categoria definida pela leitura — me diga a categoria de cada "
            "um (ex.: 'os 2 primeiros são Alimentação')."
        )
    return by_cat
```

- `_resolve_receipt_plan(user, draft, items_by_category=None, payment_method_name="", summaries=None)`: at the top, after loading `items`, if `items_by_category is None`, derive it:

```python
    if items_by_category is None:
        derived = _items_by_category_from_items(items)
        if isinstance(derived, str):
            return None, derived
        items_by_category = derived
```

  Also make discount null-safe: `discount_val = Decimal(str(payload.get("discount") or "0"))` already handles `None` (str(None)→"None" → InvalidOperation → except → 0); to be safe change to `payload.get("discount") or "0"`.
- `propose_receipt(user, items_by_category=None, payment_method_name="", summaries=None)`: pass through (default None).

In `receipt_confirm.py`: change the `propose_receipt` tool signature to `items_by_category: dict[str, list[int]] | None = None` and pass it through.

In `prompts.py` `RECEIPT_CONFIRM_PROMPT`: instruct — by default call `propose_receipt()` with NO `items_by_category` (the leitura já categoriza); only pass `items_by_category` to CORRECT a category the user disputes; when payment/total missing, ask; never show indices.

- [ ] **Step 4: Run → PASS** (focused + whole receipt-flow file, ensuring old index-based tests still pass)

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_receipt_flow.py -v`
Expected: PASS including `test_propose_stores_plan_and_writes_nothing`, `test_propose_rejects_incomplete_coverage` (manual mapping still validated), `test_commit_*`.

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/agents/receipt_confirm.py src/backend/assistant/agents/prompts.py src/backend/assistant/tests/test_receipt_flow.py
git commit -m "feat(receipt): propose_receipt auto-mode from per-item categories (drop index partition)"
```

---

## Task 4: Wire user taxonomy into the photo flow + e-commerce regression

**Files:**
- Modify: `src/backend/assistant/views.py` (`_handle_images`)
- Test: `src/backend/assistant/tests/test_views.py`

**Interfaces:**
- Consumes: `extract_receipt(images, categories=..., payment_methods=...)` from Task 2; `list_categories`, `list_payment_methods` from `assistant.agents.tools`.

- [ ] **Step 1: Write failing test** (append to `test_views.py` inside `TestChatEndpoint`, reuse `self._PNG`):

```python
    def test_images_pass_user_taxonomy_to_extraction(self, logged_client, user, monkeypatch):
        from assistant.agents.extraction import ReceiptExtraction

        baker.make("finances.Category", user=user, name="Alimentação")
        baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")

        captured = {}

        async def fake_extract(images, categories=None, payment_methods=None, model=None):
            captured["categories"] = categories
            captured["payment_methods"] = payment_methods
            return ReceiptExtraction(amount_paid=None)

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)
        img = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        from assistant.agents.receipt_confirm import receipt_confirm_agent

        with receipt_confirm_agent.override(model=TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"image": img})
            consume_streaming(response)

        assert "Alimentação" in (captured["categories"] or [])
        assert "Pix" in (captured["payment_methods"] or [])
```

(`baker` is already imported in `test_views.py`; if not, add `from model_bakery import baker`.)

- [ ] **Step 2: Run → FAIL**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_views.py -k "pass_user_taxonomy" -v`
Expected: FAIL (`fake_extract` receives `categories=None` because `_handle_images` doesn't pass it).

- [ ] **Step 3: Implement** — in `_handle_images`, before Phase 1, fetch taxonomy and pass it both at the normal call and the vision fallback:

```python
    from assistant.agents.tools import list_categories, list_payment_methods

    cats = await sync_to_async(list_categories)(user)
    pms = await sync_to_async(list_payment_methods)(user)
    ...
    extraction = await extract_receipt(prepared, categories=cats, payment_methods=pms)
    ...
    extraction = await extract_receipt(prepared, categories=cats, payment_methods=pms, model=settings.LLM_VISION_MODEL)
```

Add `from asgiref.sync import sync_to_async` at the top of `views.py` if not already imported.

- [ ] **Step 4: Run → PASS** (focused + full views file)

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant/tests/test_views.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/views.py src/backend/assistant/tests/test_views.py
git commit -m "feat(receipt): pass user categories + payment methods into vision extraction"
```

---

## Task 5: Full regression

- [ ] **Step 1: Assistant suite**

`POSTGRES_PORT=5433 .venv/bin/pytest src/backend/assistant -q`
Expected: PASS (no regressions in `test_receipt_flow`, `test_extraction`, `test_views`, `test_orchestrator`, `test_tools`).

- [ ] **Step 2: ruff**

`.venv/bin/ruff check src/backend/assistant/`
Expected: clean.

---

## Self-Review (coverage map)

- Spec §2.1 (extraction schema/consistency/extract_receipt/prompts/extraction_to_prompt) → Tasks 1, 2.
- Spec §2.2 (tools auto-mode) → Task 3.
- Spec §2.3 (receipt_confirm + prompt) → Task 3.
- Spec §2.4 (views taxonomy) → Task 4.
- Spec §3 tests → each task's TDD + Task 5 regression.
- Backward compat (optional kwargs) → enforced by keeping `test_receipt_flow`/`test_extraction`/`test_views` green in each task.
