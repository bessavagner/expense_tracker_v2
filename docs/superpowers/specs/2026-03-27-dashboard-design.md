# Sub-Project 4: Dashboard — Design Spec

## Overview

Interactive dashboard with 6 React island card components rendered via Vite, consuming Django REST Framework JSON endpoints. Uses Recharts for visualizations. Mounted into a Django template via a thin island hydration layer.

**Builds on:** Sub-Projects 1-3 (models, HTMX views, CSV importer).

**Does NOT include:** AI Chat widget (Sub-Project 5), advanced analytics/econometrics (deferred to AI assistant).

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data refresh | On page load only | Single user, summary view — no need for auto-refresh |
| Time period | Month selector (defaults to current) | Reuses month selector pattern from entries page |
| Chart library | Recharts | React-native, composable, standard for React dashboards (~200KB) |
| React testing | Deferred | Cards are thin presentation; logic tested via DRF endpoint tests |

## Dashboard Cards

6 cards in a responsive 2-column CSS grid:

### 1. Resumo Mensal
- Income (sum of Income records for the month)
- Expenses (sum of positive Entry amounts)
- Returns (sum of negative Entry amounts)
- Balance (income - net expenses)
- Budget utilization progress bar (total expenses / sum of all category ceilings)

### 2. Top Categorias
- Horizontal bar chart of top 5 categories by spending
- Each bar shows category name, amount, and percentage of total
- Colored bars with labels above (not inside)

### 3. Evolução
- Line chart (Recharts LineChart) showing last 6 months
- Two lines: expenses (solid red) and income (dashed green)
- Dots on data points, month labels on x-axis
- Legend inline with card title

### 4. Alertas
- Color-coded alert items with left border and tinted background:
  - Red (danger): categories exceeding budget ceiling
  - Yellow (warning): categories at 90-100% of ceiling
  - Blue (info): active installment count and monthly total
  - Green (success): count of categories within budget
- Sorted by severity (danger first)

### 5. Últimas Entradas
- 5 most recent entries (date, description, amount)
- Expenses in red, refunds in green
- "Ver todas →" link to entries page

### 6. Parcelas Ativas
- Active installment plans with current installment number (e.g., "4/12")
- Per-plan amount for current month
- Total installment amount for current month at bottom

## Architecture

### React Islands Pattern

Django template renders placeholder divs with data attributes:
```html
<div data-react-component="SummaryCard" data-api-url="/api/dashboard/summary/?year=2026&month=3"></div>
```

A thin `mount.tsx` script finds all `[data-react-component]` elements, imports the corresponding component, fetches data from the `data-api-url`, and mounts the React component with the API response as props.

### Vite Build Pipeline

```
src/backend/frontend/
├── package.json           # React, Recharts, Vite, TypeScript
├── tsconfig.json
├── vite.config.ts         # Library mode, outputs to Django static dir
├── src/
│   ├── mount.tsx          # Island hydration: finds divs, mounts components
│   ├── api.ts             # Fetch wrapper for DRF endpoints
│   ├── types.ts           # TypeScript interfaces for API responses
│   └── cards/
│       ├── SummaryCard.tsx
│       ├── TopCategoriesCard.tsx
│       ├── EvolutionCard.tsx
│       ├── AlertsCard.tsx
│       ├── RecentEntriesCard.tsx
│       └── InstallmentsCard.tsx
└── dist/                  # Built output → copied to static/frontend/
```

Build output goes to `src/backend/static/frontend/`. Django serves via `STATICFILES_DIRS`. No separate frontend deployment.

**Build command:** `cd src/backend/frontend && npm run build`

### DRF API Endpoints

All endpoints accept `?year=YYYY&month=MM` query params. All filter by `request.user`. All require authentication.

```
/api/dashboard/summary/         → { income, expenses, returns, balance, budget_pct }
/api/dashboard/top-categories/  → [{ name, amount, pct, color }]
/api/dashboard/evolution/       → [{ month, expenses, income }]  (last 6 months)
/api/dashboard/alerts/          → [{ type, severity, message }]
/api/dashboard/recent-entries/  → [{ date, description, amount, category }]
/api/dashboard/installments/    → [{ description, current, total, amount, monthly_total }]
```

### Django App Structure

Uses the existing `finances` app — adds:
- `finances/api/` — DRF viewsets/serializers
- `finances/views/dashboard.py` — Django template view for the dashboard page

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/finances/api/__init__.py` | API module |
| `src/backend/finances/api/serializers.py` | DRF serializers for dashboard data |
| `src/backend/finances/api/views.py` | DRF APIViews for each endpoint |
| `src/backend/finances/api/urls.py` | API URL patterns |
| `src/backend/finances/views/dashboard.py` | Dashboard template view |
| `src/backend/templates/dashboard/dashboard_page.html` | Full page with React island placeholders |
| `src/backend/frontend/package.json` | Node.js dependencies |
| `src/backend/frontend/tsconfig.json` | TypeScript config |
| `src/backend/frontend/vite.config.ts` | Vite build config |
| `src/backend/frontend/src/mount.tsx` | Island hydration script |
| `src/backend/frontend/src/api.ts` | API fetch wrapper |
| `src/backend/frontend/src/types.ts` | TypeScript interfaces |
| `src/backend/frontend/src/cards/SummaryCard.tsx` | Resumo Mensal card |
| `src/backend/frontend/src/cards/TopCategoriesCard.tsx` | Top Categorias card |
| `src/backend/frontend/src/cards/EvolutionCard.tsx` | Evolução chart card |
| `src/backend/frontend/src/cards/AlertsCard.tsx` | Alertas card |
| `src/backend/frontend/src/cards/RecentEntriesCard.tsx` | Últimas Entradas card |
| `src/backend/frontend/src/cards/InstallmentsCard.tsx` | Parcelas Ativas card |
| `src/backend/finances/tests/test_api_dashboard.py` | DRF API tests |

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/config/settings.py` | Add `rest_framework` to INSTALLED_APPS, DRF config |
| `src/backend/config/urls.py` | Include API URL patterns |
| `src/backend/finances/urls.py` | Add dashboard view URL |
| `src/backend/templates/partials/_navbar.html` | Wire Dashboard link |
| `.gitignore` | Add `node_modules/`, `frontend/dist/` |
| `pyproject.toml` | Add `djangorestframework` |

## URL Structure

```
/                              → Dashboard page (Django template with React islands)
/api/dashboard/summary/        → Monthly summary JSON
/api/dashboard/top-categories/ → Top categories JSON
/api/dashboard/evolution/      → 6-month evolution JSON
/api/dashboard/alerts/         → Alerts JSON
/api/dashboard/recent-entries/ → Recent entries JSON
/api/dashboard/installments/   → Active installments JSON
```

## Dependencies

### Python
```
djangorestframework>=3.15
```

### Node.js (in `src/backend/frontend/`)
```json
{
  "dependencies": {
    "react": "^18.3",
    "react-dom": "^18.3",
    "recharts": "^2.15"
  },
  "devDependencies": {
    "@types/react": "^18.3",
    "@types/react-dom": "^18.3",
    "typescript": "^5.7",
    "vite": "^6.0",
    "@vitejs/plugin-react": "^4.3"
  }
}
```

## Testing Strategy

### DRF API Tests (`test_api_dashboard.py`)
- Each endpoint returns correct JSON structure and values
- Data filtered by user (other user's data not included)
- Month/year query params work correctly
- Empty month returns zero/empty values (not errors)
- Authentication required (401 for anonymous)

### React Component Tests
Deferred — cards are thin presentation layers. Logic is tested via DRF endpoint tests.

### Build Verification
CI verifies `cd src/backend/frontend && npm run build` succeeds and output files exist in `static/frontend/`.

### BDD
One scenario: visit dashboard with test data, verify API endpoints return correct aggregations.
