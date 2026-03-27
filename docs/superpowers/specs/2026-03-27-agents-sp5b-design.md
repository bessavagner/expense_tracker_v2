# Sub-Project 5b: Query + Settings Agents — Design Spec

## Overview

Extend the existing PydanticAI orchestrator with query tools (expense aggregations, balance, budget status, installments) and settings tools (create/update categories, payment methods, income). No new agents — just new tools on the existing orchestrator.

**Builds on:** SP5a (orchestrator, chat endpoint, ChatMessage, EntryAgent tools).

**Does NOT include:** CorrectionAgent (corrections handled naturally by the LLM re-proposing entries), memory system (SP5c), chart/visualization generation via chat.

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| QueryAgent scope | Simple text aggregations | Dashboard has charts; text covers 90% of query use cases |
| SettingsAgent scope | Create + update only | No delete via chat (risky, FK protection); Settings page handles deletion |
| CorrectionAgent | Skipped in SP5b | Orchestrator already handles corrections via re-proposal; dedicated agent only needed with memory system |
| Architecture | New tools on existing agent | PydanticAI tool-based approach — no new agents, just more tools |

## New Tools

### Query Tools

| Tool | Signature | Description |
|------|-----------|-------------|
| `query_expenses` | `(year, month, category_name=None) -> str` | Total expenses for a month, optionally filtered by category. Includes budget ceiling comparison. |
| `query_balance` | `(year, month) -> str` | Monthly summary: income, expenses, returns, balance. |
| `query_budget_status` | `(year, month) -> str` | List categories that exceeded or are near their budget ceiling. |
| `query_installments` | `() -> str` | Active installment plans with current installment number and remaining. |

### Settings Tools

| Tool | Signature | Description |
|------|-----------|-------------|
| `create_category` | `(name, budget_ceiling) -> str` | Create new category. Returns confirmation or error if name exists. |
| `update_category_budget` | `(category_name, new_ceiling) -> str` | Update budget ceiling. Returns confirmation or error if not found. |
| `create_payment_method` | `(name, type, closing_day=None) -> str` | Create new payment method. Type: cash/pix/credit_card. |
| `update_income` | `(name, amount, month) -> str` | Create or update income for a specific month. |

### Response Format

All tools return formatted Portuguese text. Examples:

**query_expenses:**
"Em março/2026, você gastou R$ 1.989,29 com Alimentação (teto: R$ 1.300,00 — 153% do orçamento)."

**query_balance:**
"Saldo de março/2026:\n- Renda: R$ 9.854,23\n- Gastos: R$ 8.247,30\n- Retornos: R$ 458,21\n- Saldo: R$ 2.065,14"

**query_budget_status:**
"Categorias acima do teto em março/2026:\n🔴 Alimentação: R$ 1.989 / R$ 1.300 (153%)\n⚠️ Álcool: R$ 494 / R$ 511 (97%)\n\n20 categorias dentro do orçamento."

**create_category:**
"Categoria 'Assinatura' criada com teto de R$ 200,00."

**update_category_budget:**
"Teto de Alimentação atualizado de R$ 1.300,00 para R$ 1.500,00."

## System Prompt Extension

Add to the existing system prompt:

```
- Você também pode consultar gastos, saldos e orçamentos do usuário
- Pode criar categorias e formas de pagamento, e atualizar tetos de categorias e rendas
- Sempre confirme antes de modificar configurações (criar categoria, mudar teto, atualizar renda)
- Não exclua categorias ou formas de pagamento pelo chat — direcione ao painel de Configurações
- Quando o usuário perguntar sobre gastos sem especificar mês, use o mês atual
- Para consultas, responda de forma clara e concisa com os valores formatados em Real
```

## File Changes

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/assistant/agents/tools.py` | Add 8 new tool functions (4 query + 4 settings) |
| `src/backend/assistant/agents/orchestrator.py` | Register 8 new `@agent.tool` wrappers, extend system prompt |
| `src/backend/assistant/tests/test_tools.py` | Add tests for each new tool function |
| `src/backend/assistant/tests/test_orchestrator.py` | Verify new tools are registered |

No new files, no new models, no new URL patterns.

## Testing Strategy

### Tool Function Tests (test_tools.py)
- `query_expenses`: correct total for a month, filtered by category, empty month returns zero
- `query_balance`: correct income/expenses/returns/balance
- `query_budget_status`: identifies over-budget and warning categories, correct percentages
- `query_installments`: lists active plans with correct installment numbers
- `create_category`: creates category, duplicate name returns error
- `update_category_budget`: updates ceiling, non-existent category returns error
- `create_payment_method`: creates PM with correct type and closing_day
- `update_income`: creates new income, updates existing for same month+name

### Orchestrator Tests (test_orchestrator.py)
- Verify all 11 tools are registered (3 existing + 8 new)
- Agent runs with TestModel (smoke test)
