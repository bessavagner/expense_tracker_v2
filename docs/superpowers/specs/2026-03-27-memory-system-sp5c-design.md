# Sub-Project 5c — Memory System (Design Spec)

## Overview

Add a deterministic memory system to the AI assistant so it learns from user corrections and auto-fills entry fields on future interactions. When the user corrects a field ("Não, isso é Lanche"), the assistant stores a memory rule mapping the trigger pattern to the corrected value. On subsequent messages, the assistant checks for matching rules and uses them to pre-fill fields based on confidence thresholds.

## Scope

**In scope:**
- `MemoryRule` model (deterministic pattern matching)
- Memory matching module (substring search, confidence constants)
- Memory tools (lookup, create, list)
- Orchestrator system prompt updates
- Confidence threshold logic (auto-apply / confirm / ask)
- Django Admin registration
- Full unit test coverage (TDD)

**Not in scope:**
- `MemoryEmbedding` / pgvector (deferred to SP6)
- Multi-agent refactor (future — current tools designed with clean boundaries for extraction)
- API endpoints for memory management (chat tools are the interface)
- Frontend changes

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector search | Deferred to SP6 | MemoryRule covers 90% of use cases; avoids pgvector complexity now |
| Agent architecture | Tools on existing orchestrator | Consistent with SP5a/5b; designed for future extraction to CorrectionAgent |
| Trigger matching | Case-insensitive substring | Simple, sufficient for user-created triggers; YAGNI on word-boundary logic |
| Confidence thresholds | Full logic now | Minimal code, future-proofs for inferred rules and vector search |
| Auto-apply UX | Silently pre-fill, still confirm | User sees the confirmation with fields filled; no mention of memory |
| Memory lookup hook | LLM calls lookup_memory tool | Transparent, consistent with tools architecture, no orchestrator changes |
| Service layer | Plain functions + ORM | Matches existing codebase patterns in tools.py |

## Data Model

### MemoryRule

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | Multi-tenancy ready |
| trigger | CharField(255) | Match pattern: "cosmos", "posto único" |
| field | CharField(50) | Target field: "category", "payment_method", "description" |
| value | CharField(255) | Resolved value: "Alimentação", "Pix" |
| confidence | FloatField | 1.0 for user corrections, 0.0–1.0 for inferred |
| source | CharField | USER_CORRECTION or INFERRED (enum via TextChoices) |
| created_at | DateTimeField | auto_now_add |
| last_used_at | DateTimeField | Set to now on creation; updated explicitly on each match via save() |

**Constraints:**
- `unique_together = ("user", "trigger", "field")` — one rule per trigger+field per user
- A trigger can map to multiple fields (e.g., "cosmos" → category="Alimentação" AND description="Supermercado Cosmos")

## Memory Matching Module (`agents/memory.py`)

### Confidence Constants

```
AUTO_APPLY = 0.9      # >= 0.9: use value directly, no mention of memory
CONFIRM_APPLY = 0.7   # 0.7–0.9: suggest value, ask for confirmation
                      # < 0.7: ask user before using
```

### `find_matching_rules(user, message) → list[MemoryRule]`

- Loads all MemoryRules for the user
- Case-insensitive substring match: `rule.trigger.lower() in message.lower()`
- Updates `last_used_at` on matched rules
- Returns list of matched rules (can be empty)
- Rules from other users are never returned

## Memory Tools (added to `tools.py`)

### `lookup_memory(message) → str`

Called by the LLM before proposing an entry. Runs `find_matching_rules` and returns results grouped by confidence tier:
- `>= 0.9` (auto-apply): "campo=valor (auto-aplicar)"
- `0.7–0.9` (confirm): "campo=valor (sugerir ao usuário)"
- `< 0.7` (ask): "campo=valor (perguntar ao usuário)"
- No matches: "Nenhuma regra de memória encontrada."

### `create_memory_rule(trigger, field, value) → str`

Creates or updates a memory rule:
- `confidence=1.0`, `source=USER_CORRECTION`
- Upserts on `(user, trigger, field)` — if rule exists, updates value and confidence
- Returns confirmation message

### `list_memory_rules() → str`

Lists all memory rules for the user in readable format. Returns empty message if no rules exist.

## Orchestrator Changes

### System Prompt Additions

```
- Antes de propor uma entrada, use lookup_memory para verificar se há regras memorizadas
- Se a regra tem confiança >= 0.9, use o valor diretamente ao propor a entrada (sem mencionar a memória)
- Se a confiança é entre 0.7 e 0.9, mencione a sugestão e pergunte se está certo
- Se a confiança é < 0.7, pergunte ao usuário antes de usar
- Quando o usuário corrigir um campo ("não, isso é Lanche", "use Pix"), crie uma regra de memória com create_memory_rule
- Se o usuário perguntar o que você lembra, use list_memory_rules
```

### New Tool Registrations

Three new `@assistant_agent.tool` wrappers calling the sync tool functions via `sync_to_async`.

## Correction Flow

1. User: "Gastei 50 no cosmos"
2. LLM calls `lookup_memory("Gastei 50 no cosmos")`
3. Returns matched rules (e.g., category=Alimentação, confidence=1.0)
4. LLM proposes entry with Alimentação pre-filled (no mention of memory)
5. User: "Não, isso é Lanche"
6. LLM calls `create_memory_rule(trigger="cosmos", field="category", value="Lanche")`
7. Rule updated — next time "cosmos" appears, maps to Lanche

Correction detection is handled by the LLM's natural language understanding via the system prompt instructions. No regex or intent classification needed.

## File Changes

```
src/backend/assistant/
├── models.py              # ADD MemorySource, MemoryRule
├── agents/
│   ├── memory.py          # NEW — find_matching_rules, confidence constants
│   ├── tools.py           # ADD lookup_memory, create_memory_rule, list_memory_rules
│   └── orchestrator.py    # EDIT — system prompt + register 3 new tools
├── admin.py               # ADD MemoryRule to Django Admin
├── migrations/
│   └── 000X_memoryrule.py # AUTO — generated by makemigrations
└── tests/
    ├── test_memory_models.py  # NEW
    ├── test_memory.py         # NEW
    ├── test_memory_tools.py   # NEW
    └── test_orchestrator.py   # EDIT — add tool registration tests
```

## Testing Strategy

All TDD — tests written before implementation.

### test_memory_models.py
- MemoryRule creation with all fields
- Unique constraint on (user, trigger, field) — duplicate raises IntegrityError
- Upsert via update_or_create works correctly
- last_used_at updates on save
- String representation

### test_memory.py
- Case-insensitive substring matching
- Multiple rules matching same message
- No match returns empty list
- last_used_at updated on match
- Rules from other users don't leak (multi-tenancy isolation)
- Multiple triggers with different fields for same pattern

### test_memory_tools.py
- lookup_memory returns formatted string with confidence tiers
- lookup_memory returns "nenhuma regra" when no matches
- create_memory_rule creates new rule with confidence=1.0 and source=USER_CORRECTION
- create_memory_rule upserts existing rule (updates value + confidence)
- list_memory_rules returns formatted list
- list_memory_rules returns empty message when no rules

### test_orchestrator.py (extend existing)
- New memory tools are registered on the agent
- System prompt contains memory-related instructions

### No BDD/integration tests
Memory is internal plumbing. The LLM decides when to call tools — testing the full correction flow end-to-end would require mocking LLM responses, which is brittle. Unit tests cover the deterministic parts.
