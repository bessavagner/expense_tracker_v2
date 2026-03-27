# Sub-Project 5a: AI Assistant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI chat assistant with PydanticAI that creates expense entries via natural language, streams responses via SSE, and persists conversation history. React chat widget available on every page.

**Architecture:** New `assistant` Django app with ChatMessage model. PydanticAI agent with tools for listing categories/payment methods and creating entries. Async Django views return SSE streaming responses. React chat widget mounts in base.html via the existing Vite island pattern. LLM testing uses PydanticAI's TestModel.

**Tech Stack:** PydanticAI, Django 6 (async views), StreamingHttpResponse (SSE), React 18, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-03-27-ai-assistant-sp5a-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/assistant/__init__.py` | App module |
| `src/backend/assistant/apps.py` | App config |
| `src/backend/assistant/models.py` | ChatMessage model |
| `src/backend/assistant/urls.py` | URL patterns |
| `src/backend/assistant/views.py` | Chat SSE endpoint + history endpoint |
| `src/backend/assistant/agents/__init__.py` | Agents module |
| `src/backend/assistant/agents/orchestrator.py` | PydanticAI agent with system prompt |
| `src/backend/assistant/agents/tools.py` | list_categories, list_payment_methods, create_entry |
| `src/backend/assistant/migrations/__init__.py` | Migrations |
| `src/backend/assistant/tests/__init__.py` | Tests |
| `src/backend/assistant/tests/conftest.py` | Test fixtures (user with seed data) |
| `src/backend/assistant/tests/test_models.py` | ChatMessage model tests |
| `src/backend/assistant/tests/test_tools.py` | Agent tool unit tests |
| `src/backend/assistant/tests/test_views.py` | API endpoint tests |
| `src/backend/frontend/src/cards/ChatWidget.tsx` | React chat widget |

### Modified Files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `pydantic-ai` |
| `src/backend/config/settings.py` | Add `assistant` to INSTALLED_APPS, LLM config |
| `src/backend/config/urls.py` | Include `assistant.urls` |
| `src/backend/templates/base.html` | Replace chat placeholder with ChatWidget, move script tag |
| `src/backend/templates/dashboard/dashboard_page.html` | Remove mount.js script (moved to base) |
| `src/backend/frontend/src/mount.tsx` | Register ChatWidget |
| `.env.example` | Add LLM_MODEL, LLM_API_KEY |

---

## Task 1: Assistant App + ChatMessage Model + Dependencies (TDD)

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/backend/config/settings.py`
- Create: `src/backend/assistant/` (app directory)
- Create: `src/backend/assistant/tests/test_models.py`
- Create: `src/backend/assistant/tests/conftest.py`

- [ ] **Step 1: Add pydantic-ai dependency**

```bash
uv add pydantic-ai
```

- [ ] **Step 2: Create assistant app**

```bash
cd src/backend && uv run python manage.py startapp assistant && cd ../..
```

- [ ] **Step 3: Create agents directory**

```bash
mkdir -p src/backend/assistant/agents
touch src/backend/assistant/agents/__init__.py
```

- [ ] **Step 4: Set up tests directory**

```bash
rm src/backend/assistant/tests.py
mkdir -p src/backend/assistant/tests
touch src/backend/assistant/tests/__init__.py
```

- [ ] **Step 5: Update apps.py**

```python
# src/backend/assistant/apps.py
from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assistant"
    verbose_name = "Assistente IA"
```

- [ ] **Step 6: Update settings.py**

Add `"assistant"` to INSTALLED_APPS after `"finances"`. Add at bottom:

```python
# AI Assistant
LLM_MODEL = os.environ.get("LLM_MODEL", "openai:gpt-4o-mini")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
ASSISTANT_MAX_HISTORY = int(os.environ.get("ASSISTANT_MAX_HISTORY", "20"))
```

- [ ] **Step 7: Update .env.example**

Append:
```
# AI Assistant
LLM_MODEL=openai:gpt-4o-mini
LLM_API_KEY=sk-your-key-here
ASSISTANT_MAX_HISTORY=20
```

- [ ] **Step 8: Create test fixtures**

```python
# src/backend/assistant/tests/conftest.py
import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def seeded_user(user):
    """User with categories and payment methods for agent testing."""
    baker.make("finances.Category", user=user, name="Alimentação")
    baker.make("finances.Category", user=user, name="Lanche")
    baker.make("finances.Category", user=user, name="Álcool")
    baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.PaymentMethod", user=user, name="Crédito C6",
        type="credit_card", closing_day=25,
    )
    return user
```

- [ ] **Step 9: Write failing model tests**

```python
# src/backend/assistant/tests/test_models.py
import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestChatMessage:
    def test_create_user_message(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="user",
            content="gastei 50 no cosmos",
        )
        assert msg.role == "user"
        assert msg.content == "gastei 50 no cosmos"
        assert msg.user == user
        assert msg.id is not None

    def test_create_assistant_message(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="assistant",
            content="Vou registrar...",
        )
        assert msg.role == "assistant"

    def test_str_representation(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="user",
            content="gastei 50 no cosmos pix",
        )
        result = str(msg)
        assert "user" in result
        assert "gastei 50" in result

    def test_ordering_by_created_at(self, user):
        msg1 = baker.make("assistant.ChatMessage", user=user, content="first")
        msg2 = baker.make("assistant.ChatMessage", user=user, content="second")
        from assistant.models import ChatMessage
        messages = list(ChatMessage.objects.filter(user=user))
        assert messages[0].content == "first"
        assert messages[1].content == "second"

    def test_metadata_nullable(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            metadata=None,
        )
        assert msg.metadata is None

    def test_metadata_stores_json(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            metadata={"agent": "entry", "entry_id": "abc-123"},
        )
        assert msg.metadata["agent"] == "entry"
```

- [ ] **Step 10: Implement ChatMessage model**

```python
# src/backend/assistant/models.py
import uuid

from django.conf import settings
from django.db import models


class MessageRole(models.TextChoices):
    USER = "user", "Usuário"
    ASSISTANT = "assistant", "Assistente"


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["created_at"]

    def __str__(self):
        preview = self.content[:50]
        return f"[{self.role}] {preview}"
```

- [ ] **Step 11: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations assistant
uv run pytest src/backend/assistant/tests/test_models.py -v
```

- [ ] **Step 12: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(assistant): add assistant app with ChatMessage model"
```

---

## Task 2: Agent Tools (TDD)

**Files:**
- Create: `src/backend/assistant/agents/tools.py`
- Create: `src/backend/assistant/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/assistant/tests/test_tools.py
import pytest
from datetime import date
from decimal import Decimal

from assistant.agents.tools import create_entry, list_categories, list_payment_methods


@pytest.mark.django_db
class TestListCategories:
    def test_returns_user_categories(self, seeded_user):
        result = list_categories(seeded_user)
        assert "Alimentação" in result
        assert "Lanche" in result
        assert "Álcool" in result

    def test_excludes_other_users(self, seeded_user, db):
        from model_bakery import baker
        other = baker.make("core.CustomUser")
        baker.make("finances.Category", user=other, name="OtherCat")
        result = list_categories(seeded_user)
        assert "OtherCat" not in result


@pytest.mark.django_db
class TestListPaymentMethods:
    def test_returns_user_pms(self, seeded_user):
        result = list_payment_methods(seeded_user)
        assert "Pix" in result
        assert "Crédito C6" in result

    def test_excludes_inactive(self, seeded_user):
        from model_bakery import baker
        baker.make(
            "finances.PaymentMethod", user=seeded_user,
            name="Inactive", type="pix", is_active=False,
        )
        result = list_payment_methods(seeded_user)
        assert "Inactive" not in result


@pytest.mark.django_db
class TestCreateEntry:
    def test_creates_entry(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Supermercado Cosmos",
            category_name="Alimentação",
            payment_method_name="Pix",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        from finances.models import Entry
        entry = Entry.objects.get(user=seeded_user, description="Supermercado Cosmos")
        assert entry.amount == Decimal("50.00")
        assert entry.category.name == "Alimentação"
        assert entry.payment_method.name == "Pix"

    def test_computes_billing_month(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="100.00",
            description="Test CC",
            category_name="Alimentação",
            payment_method_name="Crédito C6",
        )
        from finances.models import Entry
        entry = Entry.objects.get(user=seeded_user, description="Test CC")
        # March 27 with C6 closing day 25 → April billing
        assert entry.billing_month == date(2026, 4, 1)

    def test_invalid_category_returns_error(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Test",
            category_name="NonExistent",
            payment_method_name="Pix",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()
        from finances.models import Entry
        assert not Entry.objects.filter(user=seeded_user, description="Test").exists()

    def test_invalid_payment_method_returns_error(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Test",
            category_name="Alimentação",
            payment_method_name="NonExistent",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()

    def test_negative_amount_for_refund(self, seeded_user):
        create_entry(
            user=seeded_user,
            date_str="2026-03-17",
            amount_str="-150.00",
            description="Amanda - reembolso",
            category_name="Alimentação",
            payment_method_name="Pix",
        )
        from finances.models import Entry
        entry = Entry.objects.get(user=seeded_user, description="Amanda - reembolso")
        assert entry.amount == Decimal("-150.00")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/assistant/tests/test_tools.py -v
```

- [ ] **Step 3: Implement tools**

```python
# src/backend/assistant/agents/tools.py
from datetime import date
from decimal import Decimal, InvalidOperation

from finances.models import Category, Entry, PaymentMethod


def list_categories(user) -> list[str]:
    """List available category names for the user."""
    return list(
        Category.objects.filter(user=user).order_by("name").values_list("name", flat=True)
    )


def list_payment_methods(user) -> list[str]:
    """List available active payment method names for the user."""
    return list(
        PaymentMethod.objects.filter(user=user, is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )


def create_entry(
    user,
    date_str: str,
    amount_str: str,
    description: str,
    category_name: str,
    payment_method_name: str,
) -> str:
    """Create an expense entry. Returns a confirmation or error message."""
    # Validate category
    try:
        category = Category.objects.get(user=user, name=category_name)
    except Category.DoesNotExist:
        available = ", ".join(list_categories(user))
        return f"Erro: categoria '{category_name}' não encontrada. Disponíveis: {available}"

    # Validate payment method
    try:
        payment_method = PaymentMethod.objects.get(
            user=user, name=payment_method_name, is_active=True
        )
    except PaymentMethod.DoesNotExist:
        available = ", ".join(list_payment_methods(user))
        return f"Erro: forma de pagamento '{payment_method_name}' não encontrada. Disponíveis: {available}"

    # Parse date
    try:
        entry_date = date.fromisoformat(date_str)
    except ValueError:
        return f"Erro: data inválida '{date_str}'. Use formato AAAA-MM-DD."

    # Parse amount
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        return f"Erro: valor inválido '{amount_str}'."

    # Create entry
    entry = Entry.objects.create(
        user=user,
        date=entry_date,
        amount=amount,
        description=description,
        category=category,
        payment_method=payment_method,
    )

    return (
        f"Entrada criada! {entry.description} — R$ {entry.amount} "
        f"em {category.name} via {payment_method.name} "
        f"(fatura: {entry.billing_month:%m/%Y})"
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest src/backend/assistant/tests/test_tools.py -v
```

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add src/backend/assistant/agents/ src/backend/assistant/tests/test_tools.py
git commit -m "feat(assistant): add agent tools — list_categories, list_payment_methods, create_entry"
```

---

## Task 3: PydanticAI Orchestrator Agent

**Files:**
- Create: `src/backend/assistant/agents/orchestrator.py`
- Create: `src/backend/assistant/tests/test_orchestrator.py`

- [ ] **Step 1: Write tests using TestModel**

```python
# src/backend/assistant/tests/test_orchestrator.py
import pytest

from pydantic_ai.models.test import TestModel

from assistant.agents.orchestrator import assistant_agent


@pytest.mark.django_db
class TestOrchestratorAgent:
    def test_agent_has_tools(self):
        """Verify the agent is configured with the expected tools."""
        tool_names = [t.name for t in assistant_agent._function_tools.values()]
        assert "get_categories" in tool_names
        assert "get_payment_methods" in tool_names
        assert "register_entry" in tool_names

    def test_agent_has_system_prompt(self):
        """Verify system prompt is set."""
        # PydanticAI stores system prompts
        assert assistant_agent._system_prompts

    @pytest.mark.anyio
    async def test_agent_runs_with_test_model(self, seeded_user):
        """Verify agent can run without real LLM."""
        with assistant_agent.override(model=TestModel()):
            result = await assistant_agent.run(
                "gastei 50 no cosmos",
                deps=seeded_user,
            )
            assert result.output  # TestModel returns some output

    @pytest.mark.anyio
    async def test_agent_streaming_works(self, seeded_user):
        """Verify streaming mode works."""
        with assistant_agent.override(model=TestModel()):
            async with assistant_agent.run_stream(
                "gastei 50 no cosmos",
                deps=seeded_user,
            ) as stream:
                chunks = []
                async for text in stream.stream_text():
                    chunks.append(text)
                assert len(chunks) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/assistant/tests/test_orchestrator.py -v
```

- [ ] **Step 3: Implement orchestrator**

```python
# src/backend/assistant/agents/orchestrator.py
from django.conf import settings

from pydantic_ai import Agent, RunContext

from assistant.agents.tools import create_entry, list_categories, list_payment_methods

# Type alias for dependencies — the User model instance
from django.contrib.auth import get_user_model

User = get_user_model()

SYSTEM_PROMPT = """\
Você é um assistente financeiro pessoal. O usuário registra gastos em português brasileiro.

Regras:
- Sempre confirme antes de criar uma entrada. Mostre os campos inferidos e pergunte "Confirma?"
- Use as categorias e formas de pagamento disponíveis (consulte com as ferramentas)
- Se não tiver certeza de algum campo, pergunte ao usuário
- Valores monetários em Real (R$)
- Datas no formato ISO (AAAA-MM-DD) ao chamar ferramentas, mas mostre no formato brasileiro (dd/mm/aaaa) ao usuário
- Se a data não for mencionada, use a data de hoje
- Se o usuário disser "sim", "ok", "confirma" após uma proposta de entrada, crie a entrada
- Para funcionalidades não implementadas (consultas, relatórios, configurações), \
informe educadamente que será adicionado em breve
- Seja conciso e direto nas respostas
"""

assistant_agent = Agent(
    settings.LLM_MODEL,
    deps_type=User,
    system_prompt=SYSTEM_PROMPT,
)


@assistant_agent.tool
async def get_categories(ctx: RunContext[User]) -> list[str]:
    """Lista as categorias de despesa disponíveis do usuário."""
    return list_categories(ctx.deps)


@assistant_agent.tool
async def get_payment_methods(ctx: RunContext[User]) -> list[str]:
    """Lista as formas de pagamento ativas do usuário."""
    return list_payment_methods(ctx.deps)


@assistant_agent.tool
async def register_entry(
    ctx: RunContext[User],
    date: str,
    amount: str,
    description: str,
    category_name: str,
    payment_method_name: str,
) -> str:
    """Cria uma entrada de despesa no sistema.

    Args:
        date: Data no formato AAAA-MM-DD
        amount: Valor em decimal (ex: "42.00", "-150.00" para reembolso)
        description: Descrição da despesa
        category_name: Nome exato da categoria
        payment_method_name: Nome exato da forma de pagamento
    """
    return create_entry(
        user=ctx.deps,
        date_str=date,
        amount_str=amount,
        description=description,
        category_name=category_name,
        payment_method_name=payment_method_name,
    )
```

- [ ] **Step 4: Add pytest-anyio for async tests**

```bash
uv add --dev anyio pytest-anyio
```

Add to settings.py to prevent real model requests in tests:
```python
# Prevent accidental real LLM calls in tests
import pydantic_ai.models
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
```

Wait — this should only run during tests, not in production. Instead, add it to a `conftest.py`:

Add to `src/backend/assistant/tests/conftest.py`:
```python
import pydantic_ai.models
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest src/backend/assistant/tests/test_orchestrator.py -v
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(assistant): add PydanticAI orchestrator agent with entry tools"
```

---

## Task 4: Chat API Views (SSE + History)

**Files:**
- Create: `src/backend/assistant/views.py`
- Create: `src/backend/assistant/urls.py`
- Modify: `src/backend/config/urls.py`
- Create: `src/backend/assistant/tests/test_views.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/assistant/tests/test_views.py
import json

import pytest
from django.test import Client
from model_bakery import baker
from pydantic_ai.models.test import TestModel

from assistant.agents.orchestrator import assistant_agent
from assistant.models import ChatMessage


@pytest.mark.django_db
class TestChatEndpoint:
    def test_post_creates_user_message(self, logged_client, user):
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        assert ChatMessage.objects.filter(user=user, role="user").exists()

    def test_post_returns_sse_content_type(self, logged_client, user):
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response["Content-Type"] == "text/event-stream"

    def test_post_creates_assistant_message(self, logged_client, user):
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            # Consume the streaming response
            content = b"".join(response.streaming_content).decode()
        assert ChatMessage.objects.filter(user=user, role="assistant").exists()

    def test_post_unauthenticated(self):
        client = Client()
        response = client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_post_empty_message(self, logged_client, user):
        response = logged_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": ""}),
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestHistoryEndpoint:
    def test_returns_messages(self, logged_client, user):
        baker.make("assistant.ChatMessage", user=user, role="user", content="oi")
        baker.make("assistant.ChatMessage", user=user, role="assistant", content="olá!")
        response = logged_client.get("/api/assistant/history/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_filters_by_user(self, logged_client, user):
        other = baker.make("core.CustomUser")
        baker.make("assistant.ChatMessage", user=user, content="mine")
        baker.make("assistant.ChatMessage", user=other, content="theirs")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "mine"

    def test_limits_to_50(self, logged_client, user):
        for i in range(60):
            baker.make("assistant.ChatMessage", user=user, content=f"msg {i}")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 50

    def test_unauthenticated(self):
        client = Client()
        response = client.get("/api/assistant/history/")
        assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/assistant/tests/test_views.py -v
```

- [ ] **Step 3: Implement views**

```python
# src/backend/assistant/views.py
import json

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_http_methods

from assistant.agents.orchestrator import assistant_agent
from assistant.models import ChatMessage, MessageRole


def _check_auth(request):
    """Return error response if not authenticated, None if OK."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)
    return None


@require_http_methods(["POST"])
async def chat_view(request):
    """Handle chat messages. Returns SSE stream with async generator."""
    auth_error = _check_auth(request)
    if auth_error:
        return auth_error

    try:
        body = json.loads(request.body)
        message = body.get("message", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required"}, status=400)

    user = request.user

    # Save user message
    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=message)

    # Load conversation history
    history_qs = (
        ChatMessage.objects.filter(user=user)
        .order_by("-created_at")[: settings.ASSISTANT_MAX_HISTORY]
        .values("role", "content")
    )
    history_messages = [msg async for msg in history_qs]
    history_messages.reverse()

    # Build message history for PydanticAI
    from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

    pydantic_messages: list[ModelMessage] = []
    for msg in history_messages[:-1]:  # exclude current message (it's the prompt)
        if msg["role"] == "user":
            pydantic_messages.append(
                ModelRequest(parts=[UserPromptPart(content=msg["content"])])
            )
        else:
            pydantic_messages.append(
                ModelResponse(parts=[TextPart(content=msg["content"])])
            )

    async def stream_response():
        full_response = ""
        try:
            async with assistant_agent.run_stream(
                message,
                deps=user,
                message_history=pydantic_messages,
            ) as stream:
                async for text in stream.stream_text(delta=True):
                    full_response += text
                    yield json.dumps({"type": "token", "content": text}) + "\n"
        except Exception:
            error_msg = "Erro ao processar mensagem. Tente novamente."
            yield json.dumps({"type": "error", "content": error_msg}) + "\n"
            full_response = error_msg

        # Save assistant response
        assistant_msg = await ChatMessage.objects.acreate(
            user=user,
            role=MessageRole.ASSISTANT,
            content=full_response,
        )
        yield json.dumps({"type": "done", "message_id": str(assistant_msg.id)}) + "\n"

    response = StreamingHttpResponse(
        stream_response(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@require_GET
def history_view(request):
    """Return chat history for the current user."""
    auth_error = _check_auth(request)
    if auth_error:
        return auth_error

    messages = (
        ChatMessage.objects.filter(user=request.user)
        .order_by("-created_at")[:50]
        .values("id", "role", "content", "created_at")
    )
    messages_list = list(messages)
    messages_list.reverse()

    # Convert UUIDs and datetimes to strings
    result = [
        {
            "id": str(m["id"]),
            "role": m["role"],
            "content": m["content"],
            "created_at": m["created_at"].isoformat(),
        }
        for m in messages_list
    ]
    return JsonResponse(result, safe=False)
```

- [ ] **Step 4: Create URL patterns**

```python
# src/backend/assistant/urls.py
from django.urls import path

from assistant.views import chat_view, history_view

app_name = "assistant"

urlpatterns = [
    path("chat/", chat_view, name="chat"),
    path("history/", history_view, name="history"),
]
```

- [ ] **Step 5: Update config/urls.py**

```python
# Add to urlpatterns (before the finances include):
path("api/assistant/", include("assistant.urls")),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest src/backend/assistant/tests/test_views.py -v
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(assistant): add chat SSE endpoint and history API"
```

---

## Task 5: React ChatWidget Component

**Files:**
- Create: `src/backend/frontend/src/cards/ChatWidget.tsx`
- Modify: `src/backend/frontend/src/mount.tsx`
- Modify: `src/backend/templates/base.html`
- Modify: `src/backend/templates/dashboard/dashboard_page.html`

- [ ] **Step 1: Create ChatWidget.tsx**

```tsx
// src/backend/frontend/src/cards/ChatWidget.tsx
import { useEffect, useRef, useState } from "react";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

interface Props {
  apiUrl: string;
}

export default function ChatWidget({ apiUrl }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load history on expand
  useEffect(() => {
    if (isExpanded && messages.length === 0) {
      fetch(`${apiUrl}history/`, { credentials: "same-origin" })
        .then((r) => r.json())
        .then((data: Message[]) => setMessages(data))
        .catch(() => {});
    }
  }, [isExpanded, apiUrl]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (overrideMessage?: string) => {
    const text = overrideMessage ?? input;
    if (!text.trim() || isStreaming) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    // Add placeholder for assistant response
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "" },
    ]);

    try {
      const response = await fetch(`${apiUrl}chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        credentials: "same-origin",
        body: JSON.stringify({ message: userMsg.content }),
      });

      if (!response.ok || !response.body) throw new Error("Request failed");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            if (event.type === "token") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.content }
                    : m
                )
              );
            } else if (event.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: `Erro: ${event.content}` }
                    : m
                )
              );
            }
          } catch {
            // Skip unparseable lines
          }
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Erro de conexão. Tente novamente." }
            : m
        )
      );
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!isExpanded) {
    return (
      <button
        onClick={() => setIsExpanded(true)}
        className="w-12 h-12 bg-neutral text-neutral-content rounded-full flex items-center justify-center text-xl shadow-lg hover:scale-110 transition-transform cursor-pointer"
        title="Abrir chat"
      >
        💬
      </button>
    );
  }

  return (
    <div className="flex flex-col h-full bg-base-100 border-l border-base-300 w-80">
      {/* Header */}
      <div className="flex items-center justify-between p-3 bg-neutral text-neutral-content">
        <span className="font-bold text-sm">💬 Assistente</span>
        <button
          onClick={() => setIsExpanded(false)}
          className="btn btn-ghost btn-xs text-neutral-content"
        >
          ✕
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`chat ${msg.role === "user" ? "chat-end" : "chat-start"}`}
          >
            <div
              className={`chat-bubble text-sm ${
                msg.role === "user"
                  ? "chat-bubble-primary"
                  : "chat-bubble-neutral"
              }`}
            >
              {msg.content || (
                <span className="loading loading-dots loading-sm" />
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick replies */}
      {messages.length > 0 &&
        messages[messages.length - 1].role === "assistant" &&
        messages[messages.length - 1].content.includes("Confirma?") && (
          <div className="flex gap-1 px-3 pb-1">
            <button
              className="btn btn-xs btn-success"
              onClick={() => sendMessage("sim")}
              disabled={isStreaming}
            >
              Sim
            </button>
            <button
              className="btn btn-xs btn-error"
              onClick={() => sendMessage("não")}
              disabled={isStreaming}
            >
              Não
            </button>
          </div>
        )}

      {/* Input */}
      <div className="p-3 border-t border-base-300">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digite sua mensagem..."
            className="input input-bordered input-sm flex-1"
            disabled={isStreaming}
          />
          <button
            onClick={sendMessage}
            className="btn btn-sm btn-accent"
            disabled={isStreaming || !input.trim()}
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}

function getCsrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}
```

- [ ] **Step 2: Update mount.tsx — add ChatWidget**

Add import and registration:
```tsx
import ChatWidget from "./cards/ChatWidget";

// In COMPONENTS map:
ChatWidget,
```

- [ ] **Step 3: Update base.html**

Replace the chat placeholder sidebar with the ChatWidget mount point. Also move the React script tag from dashboard template to base.html:

In `base.html`, replace the chat `<aside>` section:
```html
<!-- Chat widget (React island) -->
<aside class="min-h-[calc(100vh-4rem)] flex flex-col items-center pt-4">
    <div data-react-component="ChatWidget" data-api-url="/api/assistant/"></div>
</aside>
```

Add before `</body>`:
```html
{% load static %}
<script type="module" src="{% static 'frontend/mount.js' %}"></script>
```

- [ ] **Step 4: Remove script tag from dashboard template**

Remove the `<script type="module" src="{% static 'frontend/mount.js' %}">` line from `dashboard_page.html` (it's now in base.html).

- [ ] **Step 5: Build frontend**

```bash
cd src/backend/frontend && npm run build && cd ../../..
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(assistant): add React chat widget with SSE streaming"
```

---

## Task 6: Final Validation

- [ ] **Step 1: Run full Python lint**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
```

- [ ] **Step 2: Run full test suite with coverage**

```bash
uv run coverage run -m pytest src/backend/ -v
uv run coverage report --fail-under=80
```

- [ ] **Step 3: Django checks**

```bash
uv run python src/backend/manage.py check
uv run python src/backend/manage.py makemigrations --check --dry-run
```

- [ ] **Step 4: Frontend build**

```bash
cd src/backend/frontend && npm run build && cd ../../..
test -f src/backend/static/frontend/mount.js && echo "OK"
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "chore: fix lint and formatting from final validation"
```
