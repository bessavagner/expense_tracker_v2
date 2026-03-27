# Sub-Project 5c — Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic memory rule system so the AI assistant learns from user corrections and auto-fills entry fields using confidence thresholds.

**Architecture:** MemoryRule model stores trigger→field→value mappings with confidence scores. A `memory.py` module handles substring matching and confidence constants. Three new tools (lookup, create, list) are registered on the existing orchestrator agent. The system prompt instructs the LLM to check memory before proposing entries and create rules when users correct fields.

**Tech Stack:** Django 6, pytest, model_bakery, PydanticAI

**Spec:** `docs/superpowers/specs/2026-03-27-memory-system-sp5c-design.md`

---

## File Structure

```
src/backend/assistant/
├── models.py              # ADD MemorySource choices, MemoryRule model
├── agents/
│   ├── memory.py          # NEW — confidence constants, find_matching_rules()
│   ├── tools.py           # ADD lookup_memory(), create_memory_rule(), list_memory_rules()
│   └── orchestrator.py    # EDIT — extend system prompt, register 3 new tools
├── admin.py               # ADD MemoryRule admin registration
└── tests/
    ├── test_memory_models.py  # NEW — MemoryRule model tests
    ├── test_memory.py         # NEW — find_matching_rules tests
    ├── test_memory_tools.py   # NEW — tool function tests
    └── test_orchestrator.py   # EDIT — update tool count, add memory prompt check
```

---

### Task 1: MemoryRule Model

**Files:**
- Create: `src/backend/assistant/tests/test_memory_models.py`
- Modify: `src/backend/assistant/models.py`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_memory_models.py`:

```python
import pytest
from django.db import IntegrityError
from django.utils import timezone
from model_bakery import baker


@pytest.mark.django_db
class TestMemoryRule:
    def test_create_memory_rule(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        assert rule.trigger == "cosmos"
        assert rule.field == "category"
        assert rule.value == "Alimentação"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert rule.id is not None
        assert rule.created_at is not None
        assert rule.last_used_at is not None

    def test_unique_constraint_user_trigger_field(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        with pytest.raises(IntegrityError):
            baker.make(
                "assistant.MemoryRule",
                user=user,
                trigger="cosmos",
                field="category",
                value="Lanche",
            )

    def test_same_trigger_different_fields_allowed(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rule2 = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="description",
            value="Supermercado Cosmos",
        )
        assert rule2.id is not None

    def test_same_trigger_different_users_allowed(self, user):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rule2 = baker.make(
            "assistant.MemoryRule",
            user=other,
            trigger="cosmos",
            field="category",
            value="Lanche",
        )
        assert rule2.id is not None

    def test_upsert_via_update_or_create(self, user):
        from assistant.models import MemoryRule

        MemoryRule.objects.create(
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=0.8,
            source="inferred",
        )
        rule, created = MemoryRule.objects.update_or_create(
            user=user,
            trigger="cosmos",
            field="category",
            defaults={"value": "Lanche", "confidence": 1.0, "source": "user_correction"},
        )
        assert not created
        assert rule.value == "Lanche"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert MemoryRule.objects.filter(user=user, trigger="cosmos", field="category").count() == 1

    def test_str_representation(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        result = str(rule)
        assert "cosmos" in result
        assert "category" in result
        assert "Alimentação" in result

    def test_default_confidence_is_one(self, user):
        from assistant.models import MemoryRule

        rule = MemoryRule.objects.create(
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source="user_correction",
        )
        assert rule.confidence == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory_models.py -v`
Expected: FAIL — `MemoryRule` model does not exist

- [ ] **Step 3: Write the MemoryRule model**

Add to `src/backend/assistant/models.py` (after the existing `ChatMessage` model):

```python
class MemorySource(models.TextChoices):
    USER_CORRECTION = "user_correction", "Correção do usuário"
    INFERRED = "inferred", "Inferido"


class MemoryRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memory_rules",
    )
    trigger = models.CharField(max_length=255)
    field = models.CharField(max_length=50)
    value = models.CharField(max_length=255)
    confidence = models.FloatField(default=1.0)
    source = models.CharField(max_length=20, choices=MemorySource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "regra de memória"
        verbose_name_plural = "regras de memória"
        unique_together = ("user", "trigger", "field")

    def __str__(self):
        return f"{self.trigger} → {self.field}={self.value}"
```

- [ ] **Step 4: Create and run migration**

Run: `cd src/backend && python manage.py makemigrations assistant && python manage.py migrate`

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory_models.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/models.py src/backend/assistant/tests/test_memory_models.py src/backend/assistant/migrations/
git commit -m "feat(assistant): add MemoryRule model with unique constraint on (user, trigger, field)"
```

---

### Task 2: Memory Matching Module

**Files:**
- Create: `src/backend/assistant/tests/test_memory.py`
- Create: `src/backend/assistant/agents/memory.py`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_memory.py`:

```python
import pytest
from django.utils import timezone
from model_bakery import baker

from assistant.agents.memory import AUTO_APPLY, CONFIRM_APPLY, find_matching_rules


@pytest.mark.django_db
class TestConfidenceConstants:
    def test_auto_apply_threshold(self):
        assert AUTO_APPLY == 0.9

    def test_confirm_apply_threshold(self):
        assert CONFIRM_APPLY == 0.7


@pytest.mark.django_db
class TestFindMatchingRules:
    def test_matches_case_insensitive(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(user, "Gastei 50 no COSMOS")
        assert len(rules) == 1
        assert rules[0].value == "Alimentação"

    def test_matches_substring(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(user, "fui no supermercado cosmos comprar coisas")
        assert len(rules) == 1

    def test_no_match_returns_empty(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(user, "almocei no restaurante")
        assert len(rules) == 0

    def test_multiple_rules_match(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="description",
            value="Supermercado Cosmos",
        )
        rules = find_matching_rules(user, "gastei 80 no cosmos")
        assert len(rules) == 2
        fields = {r.field for r in rules}
        assert fields == {"category", "description"}

    def test_updates_last_used_at(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        original_last_used = rule.last_used_at
        find_matching_rules(user, "gastei 50 no cosmos")
        rule.refresh_from_db()
        assert rule.last_used_at >= original_last_used

    def test_does_not_leak_other_users_rules(self, user):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            user=other,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(user, "gastei 50 no cosmos")
        assert len(rules) == 0

    def test_unmatched_rules_not_updated(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        original_last_used = rule.last_used_at
        find_matching_rules(user, "almocei no restaurante")
        rule.refresh_from_db()
        assert rule.last_used_at == original_last_used
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory.py -v`
Expected: FAIL — `memory` module does not exist

- [ ] **Step 3: Write the memory module**

Create `src/backend/assistant/agents/memory.py`:

```python
from django.utils import timezone

from assistant.models import MemoryRule

# Confidence thresholds
AUTO_APPLY = 0.9  # >= 0.9: apply silently
CONFIRM_APPLY = 0.7  # 0.7–0.9: apply with confirmation hint
# < 0.7: ask user before using


def find_matching_rules(user, message: str) -> list[MemoryRule]:
    """Find memory rules whose trigger appears in the message (case-insensitive substring)."""
    rules = MemoryRule.objects.filter(user=user)
    matched = []
    message_lower = message.lower()
    now = timezone.now()
    for rule in rules:
        if rule.trigger.lower() in message_lower:
            matched.append(rule)
            MemoryRule.objects.filter(pk=rule.pk).update(last_used_at=now)
    return matched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/memory.py src/backend/assistant/tests/test_memory.py
git commit -m "feat(assistant): add memory matching module with confidence constants"
```

---

### Task 3: Memory Tool Functions

**Files:**
- Create: `src/backend/assistant/tests/test_memory_tools.py`
- Modify: `src/backend/assistant/agents/tools.py`

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_memory_tools.py`:

```python
import pytest
from model_bakery import baker

from assistant.agents.tools import create_memory_rule, list_memory_rules, lookup_memory
from assistant.models import MemoryRule


@pytest.mark.django_db
class TestLookupMemory:
    def test_returns_matching_rules_formatted(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        result = lookup_memory(user, "gastei 50 no cosmos")
        assert "category" in result
        assert "Alimentação" in result
        assert "auto-aplicar" in result

    def test_returns_confirm_tier(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="posto",
            field="category",
            value="Transporte",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(user, "fui no posto")
        assert "sugerir" in result

    def test_returns_ask_tier(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="loja",
            field="category",
            value="Compras",
            confidence=0.5,
            source="inferred",
        )
        result = lookup_memory(user, "comprei na loja")
        assert "perguntar" in result

    def test_no_matches_returns_message(self, user):
        result = lookup_memory(user, "almocei no restaurante")
        assert "nenhuma" in result.lower()

    def test_multiple_rules_all_listed(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="payment_method",
            value="Pix",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(user, "gastei no cosmos")
        assert "category" in result
        assert "payment_method" in result


@pytest.mark.django_db
class TestCreateMemoryRule:
    def test_creates_new_rule(self, user):
        result = create_memory_rule(user, "cosmos", "category", "Alimentação")
        assert "criada" in result.lower() or "salva" in result.lower()
        rule = MemoryRule.objects.get(user=user, trigger="cosmos", field="category")
        assert rule.value == "Alimentação"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"

    def test_upserts_existing_rule(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=0.5,
            source="inferred",
        )
        result = create_memory_rule(user, "cosmos", "category", "Lanche")
        assert "atualizada" in result.lower()
        rule = MemoryRule.objects.get(user=user, trigger="cosmos", field="category")
        assert rule.value == "Lanche"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert MemoryRule.objects.filter(user=user, trigger="cosmos", field="category").count() == 1

    def test_invalid_field_returns_error(self, user):
        result = create_memory_rule(user, "cosmos", "invalid_field", "value")
        assert "erro" in result.lower()


@pytest.mark.django_db
class TestListMemoryRules:
    def test_lists_user_rules(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="posto",
            field="category",
            value="Transporte",
        )
        result = list_memory_rules(user)
        assert "cosmos" in result
        assert "posto" in result

    def test_empty_returns_message(self, user):
        result = list_memory_rules(user)
        assert "nenhuma" in result.lower()

    def test_excludes_other_users(self, user):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            user=other,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        result = list_memory_rules(user)
        assert "nenhuma" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory_tools.py -v`
Expected: FAIL — `lookup_memory`, `create_memory_rule`, `list_memory_rules` not importable

- [ ] **Step 3: Write the tool functions**

Add to the end of `src/backend/assistant/agents/tools.py`:

```python
from assistant.agents.memory import AUTO_APPLY, CONFIRM_APPLY, find_matching_rules
from assistant.models import MemoryRule, MemorySource

VALID_MEMORY_FIELDS = {"category", "payment_method", "description"}


def lookup_memory(user, message: str) -> str:
    """Look up memory rules matching the user's message."""
    rules = find_matching_rules(user, message)
    if not rules:
        return "Nenhuma regra de memória encontrada."

    lines = ["Regras de memória encontradas:"]
    for rule in rules:
        if rule.confidence >= AUTO_APPLY:
            tier = "auto-aplicar"
        elif rule.confidence >= CONFIRM_APPLY:
            tier = "sugerir ao usuário"
        else:
            tier = "perguntar ao usuário"
        lines.append(f"- {rule.field}='{rule.value}' (confiança: {rule.confidence}, {tier})")

    return "\n".join(lines)


def create_memory_rule(user, trigger: str, field: str, value: str) -> str:
    """Create or update a memory rule from user correction."""
    if field not in VALID_MEMORY_FIELDS:
        valid = ", ".join(sorted(VALID_MEMORY_FIELDS))
        return f"Erro: campo '{field}' inválido. Válidos: {valid}."

    rule, created = MemoryRule.objects.update_or_create(
        user=user,
        trigger=trigger.lower(),
        field=field,
        defaults={
            "value": value,
            "confidence": 1.0,
            "source": MemorySource.USER_CORRECTION,
        },
    )
    action = "criada" if created else "atualizada"
    return f"Regra de memória {action}: '{trigger}' → {field}='{value}'."


def list_memory_rules(user) -> str:
    """List all memory rules for the user."""
    rules = MemoryRule.objects.filter(user=user).order_by("trigger", "field")
    if not rules.exists():
        return "Nenhuma regra de memória cadastrada."

    lines = ["Suas regras de memória:"]
    for rule in rules:
        lines.append(f"- '{rule.trigger}' → {rule.field}='{rule.value}' (confiança: {rule.confidence})")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/backend && python -m pytest assistant/tests/test_memory_tools.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/assistant/agents/tools.py src/backend/assistant/tests/test_memory_tools.py
git commit -m "feat(assistant): add memory tools — lookup, create rule, list rules"
```

---

### Task 4: Orchestrator Integration

**Files:**
- Modify: `src/backend/assistant/agents/orchestrator.py`
- Modify: `src/backend/assistant/tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add to `src/backend/assistant/tests/test_orchestrator.py`:

```python
    def test_agent_has_memory_tools(self):
        """Verify memory tools are registered."""
        tool_names = list(assistant_agent._function_toolset.tools.keys())
        assert "check_memory" in tool_names
        assert "save_memory_rule" in tool_names
        assert "get_memory_rules" in tool_names

    def test_system_prompt_includes_memory_instructions(self):
        """Verify system prompt contains memory-related instructions."""
        prompt = assistant_agent._system_prompts[0]
        prompt_text = prompt if isinstance(prompt, str) else prompt.__doc__ or ""
        assert "check_memory" in prompt_text
```

Also update the existing `test_agent_has_tools` to reflect the new total:

Replace in `test_agent_has_tools`:
```python
        # 3 existing + 8 new = 11
        assert len(tool_names) == 11
```
with:
```python
        # 11 existing + 3 memory = 14
        assert len(tool_names) == 14
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src/backend && python -m pytest assistant/tests/test_orchestrator.py -v`
Expected: FAIL — tool count is 11 not 14, `check_memory` not found

- [ ] **Step 3: Update the orchestrator**

Modify `src/backend/assistant/agents/orchestrator.py`:

Add imports at the top (after existing tool imports):

```python
from assistant.agents.tools import (
    create_category,
    create_entry,
    create_memory_rule,
    create_payment_method,
    list_categories,
    list_memory_rules,
    list_payment_methods,
    lookup_memory,
    query_balance,
    query_budget_status,
    query_expenses,
    query_installments,
    update_category_budget,
    update_income,
)
```

Extend `SYSTEM_PROMPT` — add these lines before the closing `"""`:

```
- Antes de propor uma entrada, use check_memory para verificar se há regras memorizadas
- Se a regra tem confiança >= 0.9, use o valor diretamente ao propor a entrada (sem mencionar a memória)
- Se a confiança é entre 0.7 e 0.9, mencione a sugestão e pergunte se está certo
- Se a confiança é < 0.7, pergunte ao usuário antes de usar
- Quando o usuário corrigir um campo ("não, isso é Lanche", "use Pix"), crie uma regra com save_memory_rule
- Se o usuário perguntar o que você lembra, use get_memory_rules
```

Add three new tool registrations at the end of the file:

```python
@assistant_agent.tool
async def check_memory(ctx: RunContext[User], message: str) -> str:
    """Verifica regras de memória que correspondem à mensagem do usuário.

    Args:
        message: A mensagem original do usuário para buscar correspondências
    """
    return await sync_to_async(lookup_memory)(ctx.deps, message)


@assistant_agent.tool
async def save_memory_rule(
    ctx: RunContext[User], trigger: str, field: str, value: str
) -> str:
    """Salva uma regra de memória a partir de correção do usuário.

    Args:
        trigger: Padrão de correspondência (ex: "cosmos", "posto")
        field: Campo alvo: "category", "payment_method", ou "description"
        value: Valor correto (ex: "Alimentação", "Pix")
    """
    return await sync_to_async(create_memory_rule)(ctx.deps, trigger, field, value)


@assistant_agent.tool
async def get_memory_rules(ctx: RunContext[User]) -> str:
    """Lista todas as regras de memória do usuário."""
    return await sync_to_async(list_memory_rules)(ctx.deps)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src/backend && python -m pytest assistant/tests/test_orchestrator.py -v`
Expected: All tests PASS (including existing ones)

- [ ] **Step 5: Run full test suite**

Run: `cd src/backend && python -m pytest assistant/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/orchestrator.py src/backend/assistant/tests/test_orchestrator.py
git commit -m "feat(assistant): register memory tools on orchestrator, extend system prompt"
```

---

### Task 5: Django Admin Registration

**Files:**
- Modify: `src/backend/assistant/admin.py`

- [ ] **Step 1: Register MemoryRule in admin**

Replace the contents of `src/backend/assistant/admin.py`:

```python
from django.contrib import admin

from assistant.models import ChatMessage, MemoryRule


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "content_preview", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)

    def content_preview(self, obj):
        return obj.content[:80]

    content_preview.short_description = "Conteúdo"


@admin.register(MemoryRule)
class MemoryRuleAdmin(admin.ModelAdmin):
    list_display = ("user", "trigger", "field", "value", "confidence", "source", "last_used_at")
    list_filter = ("source", "field")
    search_fields = ("trigger", "value")
    readonly_fields = ("created_at", "last_used_at")
```

- [ ] **Step 2: Verify admin loads**

Run: `cd src/backend && python manage.py check`
Expected: System check identified no issues.

- [ ] **Step 3: Commit**

```bash
git add src/backend/assistant/admin.py
git commit -m "feat(assistant): register MemoryRule in Django Admin"
```

---

### Task 6: Lint, Full Test Suite, Quality Gates

- [ ] **Step 1: Run linter**

Run: `cd src/backend && ruff check assistant/`
Expected: No errors. Fix any issues found.

- [ ] **Step 2: Run full project test suite**

Run: `cd src/backend && python -m pytest --tb=short`
Expected: All tests PASS (existing 226 + new ~25 = ~251)

- [ ] **Step 3: Run type checker (if configured)**

Run: `cd src/backend && mypy assistant/ || true`
Fix any type errors found.

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add -u
git commit -m "fix(assistant): lint and type fixes for memory system"
```
