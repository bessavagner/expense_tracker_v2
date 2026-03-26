# Expense Tracker v2 — System Design Spec

## Overview

Personal/family expense tracking system migrating from Google Sheets. Replaces manual spreadsheet workflows with an AI-powered web application featuring intelligent data entry, automated categorization, and interactive financial dashboards.

**Current state:** Google Sheets with manual entry of expenses, installments, and recurring costs across 26 categories and 6 payment methods.

**Target state:** Django web application with AI assistant as the primary input/query interface, automated billing cycle logic, and real-time financial visualizations.

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| User model | Single user now, multi-tenant ready | FK on all models from the start; monetization planned long-term |
| Frontend | HTMX + React islands | Low maintenance for CRUD pages; full interactivity for dashboard/chat |
| Architecture | Monolithic Django hybrid | Single deployment on Cloud Run; HTMX for simple pages, React islands for dashboard/chat |
| LLM provider | Provider-agnostic via PydanticAI | Future users could choose their own provider/API key |
| Data migration | One-time CSV import | Historical data for trends without ongoing Sheets API complexity |
| AI memory | Hybrid (rules + vector) | Deterministic rules for known patterns, vector for fuzzy inference; pgvector on Supabase |
| Billing cycle | Closing date + manual override | Automatic 95% of cases, user override for edge cases |
| Analytics depth | Descriptive (v1) | Totals, averages, category breakdowns, budget vs. actual; deeper analytics via AI assistant |
| Language | pt-BR with i18n infrastructure | Django gettext wrapping for future English support |
| Dev environment | Hybrid Docker | Postgres + Redis in containers; Django runs natively via uv for fast iteration |
| Dashboard layout | Overview Cards grid | Modular equal-sized cards, easy to add/rearrange |

## Data Models

### Category
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | Multi-tenancy ready |
| name | str | "Alimentação", "Álcool", etc. |
| budget_ceiling | Decimal | Monthly spending ceiling ("teto") |
| historical_avg | Decimal, nullable | Computed from entries |
| quarterly_avg | Decimal, nullable | Computed from last 3 months |
| is_system | bool | True for "Custeio", "Financiamentos" (non-deletable) |
| created_at | datetime | Auto |
| updated_at | datetime | Auto |

### PaymentMethod
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| name | str | "Pix", "Crédito Santander" |
| type | enum | CASH, PIX, CREDIT_CARD |
| closing_day | int, nullable | Credit card closing day (null for immediate methods) |
| is_active | bool | Soft delete |

### Income
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| name | str | "Salário", "Bolsa PIBID" |
| amount | Decimal | Monthly amount |
| month | date | First day of the applicable month |
| is_recurring | bool | True for salary-like entries |
| recurrence_start | date, nullable | Start of recurrence period |
| recurrence_end | date, nullable | End (null = indefinite) |

### Entry (unified model)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| date | date | Actual transaction date |
| amount | Decimal | Positive = expense, negative = return/refund |
| description | str | Free text ("Supermercado Cosmos - compras diversas") |
| category | FK → Category | |
| payment_method | FK → PaymentMethod | |
| entry_type | enum | REGULAR, INSTALLMENT, SYSTEMIC |
| billing_month | date | Computed on save: month this entry counts toward |
| billing_month_override | bool | True if user manually overrode billing_month |
| installment_plan | FK → InstallmentPlan, nullable | Links installment child entries to their plan |
| systemic_expense | FK → SystemicExpense, nullable | Links systemic entries to their source |
| created_at | datetime | Auto |
| updated_at | datetime | Auto |

**Billing month computation:**
- If payment_method.type != CREDIT_CARD or closing_day is null → billing_month = entry.date's month
- If entry.date.day <= closing_day → billing_month = entry.date's month
- If entry.date.day > closing_day → billing_month = next month
- If billing_month_override is True → user's manual value is preserved

### InstallmentPlan
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| date | date | Purchase date |
| description | str | |
| category | FK → Category | |
| payment_method | FK → PaymentMethod | |
| total_amount | Decimal | Full purchase price |
| num_installments | int | Number of installments |
| installment_amount | Decimal | Per-installment value |
| created_at | datetime | Auto |

On creation, generates `num_installments` Entry rows with:
- `entry_type=INSTALLMENT`
- `installment_plan=self`
- Sequential billing months starting from computed billing_month
- `amount=installment_amount`
- **Rounding:** If `total_amount` is not evenly divisible by `num_installments`, the remainder is added to the last installment. E.g., R$ 100.00 / 3 = R$ 33.33 + R$ 33.33 + R$ 33.34.

### SystemicExpense
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| name | str | "Enel", "Unimed - Amanda" |
| category | FK → Category | |
| payment_method | FK → PaymentMethod, nullable | Default payment method; can be overridden per-entry |
| default_amount | Decimal | Typical monthly value |
| is_active | bool | |
| created_at | datetime | Auto |

Each month's actual value is stored as an Entry with `entry_type=SYSTEMIC` and `systemic_expense=self`. The default_amount is used when no specific entry exists yet.

### MemoryRule (AI memory — rule store)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| trigger | str | Match pattern: "cosmos", "posto único + café" |
| field | str | Target field: "description", "category", "payment_method" |
| value | str | Resolved value: "Supermercado Cosmos", "Alimentação" |
| confidence | float | 1.0 for explicit user rules, 0.0–1.0 for inferred |
| source | enum | USER_CORRECTION, INFERRED |
| created_at | datetime | Auto |
| last_used_at | datetime | Updated on each use |

### MemoryEmbedding (AI memory — vector store)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user | FK → User | |
| content | text | The interaction/context text |
| embedding | vector(1536) | Via pgvector |
| metadata | jsonb | Timestamps, related entry IDs, tags |
| created_at | datetime | Auto |

## Application Structure

```
src/backend/
├── config/              # Django settings, urls, wsgi, asgi
├── core/                # User model, shared utilities, base classes
├── finances/            # Entry, Category, PaymentMethod, Income, InstallmentPlan, SystemicExpense
├── dashboard/           # Dashboard views, aggregation queries, DRF endpoints for React
├── assistant/           # PydanticAI agents, WebSocket consumer, memory system
├── importer/            # CSV import tool
├── templates/           # Django templates (base, partials, HTMX fragments)
├── static/              # Compiled assets (Tailwind CSS, HTMX, Alpine.js, React build)
└── frontend/            # React islands source (Vite)
    ├── chat/            # Chat widget component
    ├── dashboard/       # Dashboard card components (Recharts)
    └── shared/          # Shared React utilities
```

## URL Structure

```
/                        → Dashboard (React island — card grid)
/entries/                → Monthly entries (HTMX, tabbed by month)
/entries/<year>/<month>/ → Specific month entries
/consolidated/           → Category consolidated views (HTMX)
/consolidated/systemics/ → Systemic expenses consolidated
/settings/               → Income, payment methods, categories, budgets (HTMX)
/import/                 → CSV import wizard (HTMX)
/api/dashboard/          → JSON endpoints for React dashboard cards
/api/assistant/          → REST endpoints (chat history, memory management)
/ws/assistant/           → WebSocket for real-time AI chat
```

## AI Assistant Architecture

### Multi-Agent Orchestrator (PydanticAI)

```
User Message
    ↓
┌─────────────┐
│ Orchestrator │ — classifies intent, routes to sub-agent
└──────┬──────┘
       ├──→ EntryAgent      — parse and create expense entries
       ├──→ QueryAgent      — answer questions, run aggregations
       ├──→ SettingsAgent   — modify categories, payment methods, income
       └──→ CorrectionAgent — handle corrections, update memory rules
```

**Orchestrator:** Receives raw input (text, image OCR, audio transcription). Classifies intent and routes. Below confidence threshold, asks user to clarify.

**EntryAgent:** Parses natural language into Entry creation. Handles single entries, bulk receipt parsing, and installment plans.

**QueryAgent:** Translates questions into ORM queries. Returns text summaries or chart data that opens visualization modals.

**SettingsAgent:** Handles configuration changes via natural language.

**CorrectionAgent:** Processes corrections ("Não, isso é Lanche"), creates/updates MemoryRules.

### Memory Flow

1. New input arrives
2. Check MemoryRule store (deterministic, fast) for matching triggers
3. If no match → vector similarity search on MemoryEmbedding
4. Apply confidence threshold:
   - **≥ 0.9** — auto-apply silently
   - **0.7–0.9** — apply with inline confirmation
   - **< 0.7** — ask user before proceeding
5. User correction → create new MemoryRule with confidence=1.0

### Chat Widget

React island mounted in `base.html` on every page. Features:
- Pinnable to right side (default), collapsible to floating button
- All pages responsive to chat open/closed state via CSS grid
- WebSocket connection via Django Channels (Redis channel layer)
- Streaming token display (real-time LLM output)
- Message history with conversation context

## Dashboard Layout

**Overview Cards** grid layout:
- Equal-sized modular cards in a responsive CSS grid
- Each card is a self-contained React component
- Chat widget pinned on the right

**Initial cards:**
1. **Resumo Mensal** — income, expenses, balance for current month
2. **Top Categorias** — horizontal bar chart of top spending categories
3. **Evolução** — line chart of spending vs. income over past 6 months
4. **Alertas** — budget warnings, upcoming installments, anomalies
5. **Últimas Entradas** — most recent expense entries
6. **Parcelas Ativas** — active installment plans with remaining payments

Cards are React components consuming DRF JSON endpoints. New cards can be added without changing layout infrastructure.

## Technology Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | Django 6 |
| API | Django REST Framework |
| WebSocket | Django Channels + Redis |
| Background tasks | django-huey + Redis |
| AI agents | PydanticAI (provider-agnostic) |
| Vector store | pgvector (Supabase) |
| Package manager | uv |
| Linting | Ruff (strict) |
| Type checking | mypy |
| Testing | pytest + pytest-django + pytest-cov + pytest-bdd |
| Pre-commit | ruff + mypy + coverage gate |

### Frontend
| Component | Technology |
|-----------|-----------|
| CSS | TailwindCSS v4 + DaisyUI |
| Simple pages | HTMX + Alpine.js |
| React islands | React 18 + Vite |
| Charts | Recharts |
| Build | Vite → Django static directory |

### Infrastructure
| Environment | Stack |
|-------------|-------|
| Dev | Docker Compose (Postgres 16 + Redis 7), Django native via `uv run` |
| Prod | Google Cloud Run + Supabase (Postgres + pgvector) + Upstash Redis |
| Static files | WhiteNoise (prod), Django dev server (local) |
| CI/CD | GitHub Actions: lint → test → build → deploy |

## Sub-Project Decomposition

### Sub-Project 1: Foundation
Scaffold + core data models + basic CRUD + Django Admin
- Generate project from project generator template
- Extend with `finances` app
- All data models with full test coverage
- Billing month computation logic
- Docker Compose (Postgres + Redis)
- Pre-commit hooks, CI skeleton
- pytest-bdd feature files for core behaviors

### Sub-Project 2: HTMX Views
Server-rendered pages for data management
- Monthly entries view (tabbed by month/year)
- Consolidated views by category
- Settings page (income, payment methods, categories, budgets)
- Manual entry creation/edit forms
- Navigation + base layout with chat placeholder

### Sub-Project 3: CSV Importer
One-time migration from Google Sheets
- CSV upload with format detection
- Column mapping UI
- Preview + validation before bulk import
- Handles regular entries and installments (systemics managed via Settings tab)

### Sub-Project 4: Dashboard
React islands + interactive visualizations
- Vite build pipeline integration with Django
- Dashboard card components (Recharts)
- DRF JSON endpoints
- All 6 initial cards
- Responsive layout with chat area reserved

### Sub-Project 5: AI Assistant
Multi-agent orchestrator + chat widget
- Django Channels + WebSocket setup
- React chat widget island
- PydanticAI orchestrator + 4 sub-agents
- Memory system (MemoryRule + MemoryEmbedding with pgvector)
- Confidence threshold logic
- Text input (image/audio deferred to later)

### Sub-Project 6: Polish & Deploy
Production readiness
- Supabase configuration
- Cloud Run deployment pipeline
- i18n infrastructure (gettext wrapping)
- Performance optimization
- End-to-end BDD test suite

Each sub-project is independently shippable and builds on the previous one.

## Principles

- **TDD:** Every feature starts with failing tests. No code merges without full coverage.
- **BDD:** Behavioral specs in Gherkin (pytest-bdd) drive the acceptance criteria.
- **Worktrees:** Every sub-project/feature developed in an isolated git worktree. Merge to main only after all tests pass.
- **Code quality:** Ruff + mypy + coverage gates enforced via pre-commit hooks. Code quality blocks merges.
- **YAGNI:** Build only what's needed now. Analytics depth, multi-tenancy, and multimodal input are deferred.
