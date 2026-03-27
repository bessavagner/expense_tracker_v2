# Sub-Project 5a: AI Assistant — Chat Infrastructure + Entry Agent — Design Spec

## Overview

Real-time AI chat assistant as the primary input interface for the expense tracker. Uses PydanticAI with a provider-agnostic orchestrator agent that routes to an EntryAgent for creating expenses. Chat streams responses via SSE (Server-Sent Events). React chat widget mounted on every page via the existing island pattern.

**Builds on:** Sub-Projects 1-4 (models, views, importer, dashboard).

**Does NOT include:** QueryAgent, SettingsAgent, CorrectionAgent, memory system (rule store + pgvector), confidence-based auto-apply. These are deferred to SP5b.

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport | SSE (not WebSocket) | Simpler, no Channels needed. Upgrade to WebSocket in SP5b if needed. |
| LLM config | Environment variable | Single user, `.env` is standard. `LLM_MODEL` and `LLM_API_KEY` in `.env`. |
| Default model | Cheapest available | Use cheap model in dev (haiku/gpt-4o-mini), configure production model via env var. |
| Chat history | Persisted to DB | ChatMessage model. Enables context continuity and future memory system. |
| Entry confirmation | Always confirm | No memory system yet → always show parsed entry and ask user to confirm before creating. |
| Chat widget | React island in base.html | Available on every page, expandable from sidebar placeholder. |
| Django app | Separate `assistant` app | Own models, URLs, agents. Clean dependency: assistant imports from finances. |

## Architecture

### SSE Streaming Flow

```
User types message
    ↓
POST /api/assistant/chat/  {message: "gastei 50 no cosmos pix"}
    ↓
Django view:
  1. Save user ChatMessage to DB
  2. Load last N messages as context
  3. Run PydanticAI orchestrator agent
  4. Return StreamingHttpResponse (SSE)
    ↓
SSE stream: tokens arrive as {"type":"token","content":"..."} lines
    ↓
Final event: {"type":"done","message_id":"<uuid>"}
    ↓
Django view:
  5. Save complete assistant ChatMessage to DB
    ↓
React widget: renders tokens in real-time, enables input when done
```

### PydanticAI Orchestrator

Single agent with tools. The LLM decides which tools to call based on the user message.

**System prompt:**
```
Você é um assistente financeiro pessoal. O usuário registra gastos em português brasileiro.

Regras:
- Sempre confirme antes de criar uma entrada. Mostre os campos inferidos e pergunte "Confirma?"
- Use as categorias e formas de pagamento disponíveis (consulte com as ferramentas)
- Se não tiver certeza de algum campo, pergunte ao usuário
- Valores monetários em Real (R$)
- Datas no formato brasileiro (dd/mm/aaaa)
- Se o usuário disser "sim", "ok", "confirma" após uma proposta de entrada, crie a entrada
- Para funcionalidades não implementadas (consultas, relatórios), informe que será adicionado em breve
```

**Tools:**
```python
@agent.tool
def list_categories(ctx) -> list[str]:
    """Lista as categorias disponíveis do usuário."""

@agent.tool
def list_payment_methods(ctx) -> list[str]:
    """Lista as formas de pagamento disponíveis do usuário."""

@agent.tool
def create_entry(ctx, date: str, amount: str, description: str,
                 category_name: str, payment_method_name: str) -> str:
    """Cria uma entrada de despesa. Retorna mensagem de confirmação."""
```

**Flow examples:**

User: "gastei 50 reais no cosmos com alimentação no pix"
→ LLM calls `list_categories` and `list_payment_methods` for validation
→ LLM responds: "Vou registrar:\n- Data: 27/03/2026\n- Valor: R$ 50,00\n- Descrição: Cosmos\n- Categoria: Alimentação\n- Forma: Pix\n\nConfirma?"

User: "sim"
→ LLM calls `create_entry(date="2026-03-27", amount="50.00", description="Cosmos", category_name="Alimentação", payment_method_name="Pix")`
→ LLM responds: "Entrada criada! R$ 50,00 em Alimentação via Pix."

User: "não, é Lanche"
→ LLM responds: "Corrigido:\n- Categoria: Lanche\n\nConfirma?"

## Models

### ChatMessage
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| role | enum: USER, ASSISTANT | |
| content | text | Message content |
| metadata | jsonb, nullable | Agent used, created entry ID, tool calls, etc. |
| created_at | datetime | Auto |

## API Endpoints

```
POST /api/assistant/chat/     → Send message, receive SSE stream
GET  /api/assistant/history/  → Last 50 messages for the user (JSON array)
```

### POST /api/assistant/chat/

**Request:** `{"message": "gastei 50 no cosmos pix"}`

**Response:** `StreamingHttpResponse` with `content_type="text/event-stream"`

Each line is a JSON object:
```
{"type": "token", "content": "Vou"}
{"type": "token", "content": " registrar"}
{"type": "token", "content": ":"}
...
{"type": "done", "message_id": "abc-123"}
```

If an error occurs (LLM failure, tool exception):
```
{"type": "error", "content": "Erro ao processar mensagem. Tente novamente."}
```

### GET /api/assistant/history/

**Response:** JSON array of messages:
```json
[
  {"id": "...", "role": "user", "content": "gastei 50 no cosmos", "created_at": "..."},
  {"id": "...", "role": "assistant", "content": "Vou registrar:...", "created_at": "..."}
]
```

## React Chat Widget

**Component:** `ChatWidget.tsx` in the existing Vite pipeline.

**Mounted in `base.html`** — replaces the current 60px chat sidebar placeholder:
```html
<div data-react-component="ChatWidget" data-api-url="/api/assistant/"></div>
```

**States:**
- **Collapsed:** floating 💬 button in the sidebar area. Click to expand.
- **Expanded:** ~320px sidebar with message list, input field, send button.

**Behavior:**
- On mount (expanded): fetch `GET /api/assistant/history/` to load past messages
- On send: `POST /api/assistant/chat/` with message text
- Read SSE stream via `fetch()` + `ReadableStream`
- Tokens appended to current assistant message in real-time
- Auto-scroll to bottom
- Input disabled while streaming
- Quick-reply button for "Sim" when assistant asks for confirmation

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/assistant/__init__.py` | App module |
| `src/backend/assistant/apps.py` | App config |
| `src/backend/assistant/models.py` | ChatMessage model |
| `src/backend/assistant/views.py` | Chat endpoint (POST + SSE), history endpoint |
| `src/backend/assistant/urls.py` | URL patterns |
| `src/backend/assistant/agents/__init__.py` | Agents module |
| `src/backend/assistant/agents/orchestrator.py` | PydanticAI orchestrator agent with system prompt |
| `src/backend/assistant/agents/tools.py` | Agent tools: list_categories, list_payment_methods, create_entry |
| `src/backend/assistant/migrations/__init__.py` | Migrations |
| `src/backend/assistant/tests/__init__.py` | Tests |
| `src/backend/assistant/tests/test_models.py` | ChatMessage model tests |
| `src/backend/assistant/tests/test_views.py` | API endpoint tests |
| `src/backend/assistant/tests/test_tools.py` | Agent tool unit tests |
| `src/backend/assistant/tests/test_orchestrator.py` | Orchestrator tests with mocked LLM |
| `src/backend/frontend/src/cards/ChatWidget.tsx` | React chat widget component |

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/config/settings.py` | Add `assistant` to INSTALLED_APPS, add LLM config vars |
| `src/backend/config/urls.py` | Include `assistant.urls` |
| `src/backend/templates/base.html` | Replace chat placeholder with ChatWidget mount point, move React script tag here from dashboard template |
| `src/backend/templates/dashboard/dashboard_page.html` | Remove `<script>` for mount.js (moved to base.html) |
| `src/backend/frontend/src/mount.tsx` | Register ChatWidget component |
| `pyproject.toml` | Add `pydantic-ai` dependency |
| `.env.example` | Add `LLM_MODEL`, `LLM_API_KEY` vars |

## Dependencies

```
pydantic-ai>=0.1      # AI agent framework
```

LLM provider SDKs installed as needed by PydanticAI (e.g., `anthropic` or `openai` — PydanticAI handles this as optional dependencies).

## Testing Strategy

### ChatMessage Model Tests
- Create message, verify fields
- Ordering by created_at
- String representation

### Agent Tool Tests
- `list_categories`: returns user's categories
- `list_payment_methods`: returns user's active payment methods
- `create_entry`: creates Entry in DB with correct billing month, returns confirmation string
- `create_entry` with invalid category: returns error message (not exception)

### Orchestrator Tests (Mocked LLM)
- Use PydanticAI `TestModel` — no real LLM calls
- Verify agent is configured with correct tools
- Verify system prompt is set

### View Tests
- POST `/api/assistant/chat/`: creates user ChatMessage, returns streaming response
- GET `/api/assistant/history/`: returns user's messages, not other users'
- Auth required (403 for anonymous)

### SSE Stream Tests
- Verify response content type is `text/event-stream`
- Verify stream contains token events (with mocked agent)

## Configuration

```env
# .env
LLM_MODEL=openai:gpt-4o-mini       # or anthropic:claude-3-5-haiku, etc.
LLM_API_KEY=sk-...                  # Provider API key
ASSISTANT_MAX_HISTORY=20            # Number of past messages to include as context
```

PydanticAI model string format: `provider:model-name` (e.g., `openai:gpt-4o-mini`, `anthropic:claude-3-5-haiku-latest`).
