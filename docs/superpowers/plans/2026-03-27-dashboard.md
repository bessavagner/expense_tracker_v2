# Sub-Project 4: Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive dashboard at `/` with 6 React island card components (Recharts) consuming DRF JSON endpoints, rendered via Vite into Django static files.

**Architecture:** DRF APIViews serve aggregated financial data as JSON. A Vite-built React bundle hydrates `<div data-react-component="...">` elements in a Django template. Each card is a self-contained React component fetching its own data from a dedicated API endpoint. Month selector is HTMX-driven (re-renders the Django template with new query params, which updates the `data-api-url` attributes).

**Tech Stack:** Django REST Framework, React 18, TypeScript, Recharts, Vite, HTMX (month selector only).

**Spec:** `docs/superpowers/specs/2026-03-27-dashboard-design.md`

---

## File Map

### New Files — Python

| File | Responsibility |
|------|---------------|
| `src/backend/finances/api/__init__.py` | API module |
| `src/backend/finances/api/views.py` | 6 DRF APIViews (one per card endpoint) |
| `src/backend/finances/api/urls.py` | API URL patterns under `/api/dashboard/` |
| `src/backend/finances/views/dashboard.py` | Dashboard template view (serves the page with React island placeholders) |
| `src/backend/templates/dashboard/dashboard_page.html` | Full page template with React mount points |
| `src/backend/finances/tests/test_api_dashboard.py` | DRF API endpoint tests |

### New Files — Frontend

| File | Responsibility |
|------|---------------|
| `src/backend/frontend/package.json` | Node.js dependencies (React, Recharts, Vite) |
| `src/backend/frontend/tsconfig.json` | TypeScript config |
| `src/backend/frontend/vite.config.ts` | Vite build config → outputs to `static/frontend/` |
| `src/backend/frontend/src/mount.tsx` | Island hydration: finds `[data-react-component]` divs, mounts components |
| `src/backend/frontend/src/api.ts` | Fetch wrapper with CSRF token handling |
| `src/backend/frontend/src/types.ts` | TypeScript interfaces for API responses |
| `src/backend/frontend/src/cards/SummaryCard.tsx` | Resumo Mensal |
| `src/backend/frontend/src/cards/TopCategoriesCard.tsx` | Top Categorias (horizontal bars) |
| `src/backend/frontend/src/cards/EvolutionCard.tsx` | Evolução (Recharts LineChart) |
| `src/backend/frontend/src/cards/AlertsCard.tsx` | Alertas (color-coded items) |
| `src/backend/frontend/src/cards/RecentEntriesCard.tsx` | Últimas Entradas |
| `src/backend/frontend/src/cards/InstallmentsCard.tsx` | Parcelas Ativas |

### Modified Files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `djangorestframework` |
| `src/backend/config/settings.py` | Add `rest_framework` to INSTALLED_APPS, add DRF config |
| `src/backend/finances/urls.py` | Add dashboard view + include API urls |
| `src/backend/templates/partials/_navbar.html` | Wire Dashboard link to `/` |
| `.gitignore` | Add `node_modules/`, `src/backend/frontend/dist/` |

---

## Task 1: DRF Setup + Dashboard API Endpoints (TDD)

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/backend/config/settings.py`
- Create: `src/backend/finances/api/__init__.py`
- Create: `src/backend/finances/api/views.py`
- Create: `src/backend/finances/api/urls.py`
- Modify: `src/backend/finances/urls.py`
- Create: `src/backend/finances/tests/test_api_dashboard.py`

- [ ] **Step 1: Add djangorestframework dependency**

```bash
uv add djangorestframework
```

- [ ] **Step 2: Update settings.py**

Add `"rest_framework"` to INSTALLED_APPS after `"django_htmx"`. Add DRF config at the bottom:

```python
# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}
```

- [ ] **Step 3: Create API module**

```bash
mkdir -p src/backend/finances/api
touch src/backend/finances/api/__init__.py
```

- [ ] **Step 4: Write failing tests**

```python
# src/backend/finances/tests/test_api_dashboard.py
import pytest
from datetime import date
from decimal import Decimal

from django.test import Client
from model_bakery import baker


@pytest.mark.django_db
class TestSummaryEndpoint:
    def test_returns_json(self, logged_client, user):
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

    def test_correct_values(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        # Income
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("5000"))
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("2000"))
        # Expenses
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5),
            amount=Decimal("500"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 10),
            amount=Decimal("-100"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        data = response.json()
        assert data["income"] == "7000.00"
        assert data["expenses"] == "500.00"
        assert data["returns"] == "100.00"
        assert data["balance"] == "6600.00"

    def test_filters_by_user(self, logged_client, user, other_user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5),
            amount=Decimal("100"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        other_cat = baker.make("finances.Category", user=other_user)
        other_pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry", user=other_user, date=date(2026, 3, 5),
            amount=Decimal("999"), category=other_cat, payment_method=other_pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        data = response.json()
        assert data["expenses"] == "100.00"

    def test_empty_month(self, logged_client, user):
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=6")
        data = response.json()
        assert data["income"] == "0.00"
        assert data["expenses"] == "0.00"

    def test_unauthenticated(self):
        client = Client()
        response = client.get("/api/dashboard/summary/?year=2026&month=3")
        assert response.status_code == 403


@pytest.mark.django_db
class TestTopCategoriesEndpoint:
    def test_returns_top_5(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        for i in range(7):
            cat = baker.make("finances.Category", user=user, name=f"Cat{i}")
            baker.make(
                "finances.Entry", user=user, date=date(2026, 3, 1),
                amount=Decimal(str((7 - i) * 100)), category=cat,
                payment_method=pm, billing_month=date(2026, 3, 1),
            )
        response = logged_client.get("/api/dashboard/top-categories/?year=2026&month=3")
        data = response.json()
        assert len(data) == 5
        assert data[0]["amount"] >= data[1]["amount"]


@pytest.mark.django_db
class TestEvolutionEndpoint:
    def test_returns_6_months(self, logged_client, user):
        response = logged_client.get("/api/dashboard/evolution/?year=2026&month=3")
        data = response.json()
        assert len(data) == 6

    def test_includes_expenses_and_income(self, logged_client, user):
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("5000"))
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5),
            amount=Decimal("1000"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/evolution/?year=2026&month=3")
        data = response.json()
        march = next(m for m in data if m["month"] == "2026-03")
        assert march["expenses"] == "1000.00"
        assert march["income"] == "5000.00"


@pytest.mark.django_db
class TestAlertsEndpoint:
    def test_over_budget_alert(self, logged_client, user):
        cat = baker.make(
            "finances.Category", user=user, name="Alimentação",
            budget_ceiling=Decimal("100"),
        )
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5),
            amount=Decimal("150"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/alerts/?year=2026&month=3")
        data = response.json()
        danger_alerts = [a for a in data if a["severity"] == "danger"]
        assert len(danger_alerts) >= 1
        assert "Alimentação" in danger_alerts[0]["message"]

    def test_warning_alert(self, logged_client, user):
        cat = baker.make(
            "finances.Category", user=user, name="Álcool",
            budget_ceiling=Decimal("100"),
        )
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 5),
            amount=Decimal("95"), category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/alerts/?year=2026&month=3")
        data = response.json()
        warning_alerts = [a for a in data if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1


@pytest.mark.django_db
class TestRecentEntriesEndpoint:
    def test_returns_5_entries(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        for d in range(1, 8):
            baker.make(
                "finances.Entry", user=user, date=date(2026, 3, d),
                amount=Decimal("50"), description=f"Entry {d}",
                category=cat, payment_method=pm,
                billing_month=date(2026, 3, 1),
            )
        response = logged_client.get("/api/dashboard/recent-entries/?year=2026&month=3")
        data = response.json()
        assert len(data) == 5

    def test_ordered_by_date_desc(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 1),
            amount=Decimal("10"), description="First",
            category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry", user=user, date=date(2026, 3, 20),
            amount=Decimal("20"), description="Last",
            category=cat, payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/recent-entries/?year=2026&month=3")
        data = response.json()
        assert data[0]["description"] == "Last"


@pytest.mark.django_db
class TestInstallmentsEndpoint:
    def test_returns_active_plans(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=30)
        plan = baker.make(
            "finances.InstallmentPlan", user=user, date=date(2025, 12, 1),
            description="Notebook", category=cat, payment_method=pm,
            total_amount=Decimal("6699"), num_installments=12,
            installment_amount=Decimal("558.25"),
        )
        plan.generate_entries()
        response = logged_client.get("/api/dashboard/installments/?year=2026&month=3")
        data = response.json()
        assert len(data["plans"]) >= 1
        assert "monthly_total" in data
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_api_dashboard.py -v
```

- [ ] **Step 6: Implement API views**

```python
# src/backend/finances/api/views.py
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from finances.models import Category, Entry, Income, InstallmentPlan


def _get_month_params(request):
    """Extract year/month from query params, defaulting to current month."""
    today = date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))
    return year, month, date(year, month, 1)


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        income = Income.objects.filter(
            user=user, month=billing_month
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        entries = Entry.objects.filter(user=user, billing_month=billing_month)
        expenses = sum(e.amount for e in entries if e.amount > 0)
        returns = abs(sum(e.amount for e in entries if e.amount < 0))

        total_ceiling = Category.objects.filter(
            user=user
        ).aggregate(total=Sum("budget_ceiling"))["total"] or Decimal("1")
        budget_pct = round(float(expenses) / float(total_ceiling) * 100, 1) if total_ceiling else 0

        return Response({
            "income": f"{income:.2f}",
            "expenses": f"{expenses:.2f}",
            "returns": f"{returns:.2f}",
            "balance": f"{income - expenses + returns:.2f}",
            "budget_pct": budget_pct,
        })


class TopCategoriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        from django.db.models import Sum

        category_totals = (
            Entry.objects.filter(
                user=user, billing_month=billing_month, amount__gt=0
            )
            .values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )

        total = sum(ct["total"] for ct in category_totals) or Decimal("1")
        result = [
            {
                "name": ct["category__name"],
                "amount": f"{ct['total']:.2f}",
                "pct": round(float(ct["total"]) / float(total) * 100, 1),
            }
            for ct in category_totals
        ]
        return Response(result)


class EvolutionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        from django.db.models import Sum

        result = []
        current = billing_month
        for _ in range(6):
            expenses = (
                Entry.objects.filter(
                    user=user, billing_month=current, amount__gt=0
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
            )
            income = (
                Income.objects.filter(
                    user=user, month=current
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
            )
            result.append({
                "month": f"{current:%Y-%m}",
                "expenses": f"{expenses:.2f}",
                "income": f"{income:.2f}",
            })
            # Go back one month
            if current.month == 1:
                current = date(current.year - 1, 12, 1)
            else:
                current = date(current.year, current.month - 1, 1)

        result.reverse()  # oldest first
        return Response(result)


class AlertsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        from django.db.models import Sum

        alerts = []

        # Budget alerts
        category_totals = (
            Entry.objects.filter(
                user=user, billing_month=billing_month, amount__gt=0
            )
            .values("category__name", "category__budget_ceiling")
            .annotate(total=Sum("amount"))
        )

        ok_count = 0
        for ct in category_totals:
            ceiling = ct["category__budget_ceiling"]
            if not ceiling or ceiling <= 0:
                ok_count += 1
                continue
            ratio = ct["total"] / ceiling
            if ratio >= 1:
                over = ct["total"] - ceiling
                alerts.append({
                    "severity": "danger",
                    "message": f"{ct['category__name']} ultrapassou teto em R$ {over:.2f}",
                })
            elif ratio >= Decimal("0.9"):
                alerts.append({
                    "severity": "warning",
                    "message": (
                        f"{ct['category__name']} em {ratio * 100:.0f}% do teto "
                        f"(R$ {ct['total']:.0f} / R$ {ceiling:.0f})"
                    ),
                })
            else:
                ok_count += 1

        # Installment info
        active_entries = Entry.objects.filter(
            user=user, billing_month=billing_month,
            entry_type="installment",
        )
        if active_entries.exists():
            plan_count = active_entries.values("installment_plan").distinct().count()
            installment_total = active_entries.aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0")
            alerts.append({
                "severity": "info",
                "message": f"{plan_count} parcelas ativas, R$ {installment_total:.0f} este mês",
            })

        if ok_count > 0:
            alerts.append({
                "severity": "success",
                "message": f"{ok_count} categorias dentro do orçamento",
            })

        # Sort: danger first, then warning, info, success
        severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
        alerts.sort(key=lambda a: severity_order.get(a["severity"], 4))

        return Response(alerts)


class RecentEntriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        entries = (
            Entry.objects.filter(user=user, billing_month=billing_month)
            .select_related("category")
            .order_by("-date", "-created_at")[:5]
        )
        result = [
            {
                "date": f"{e.date:%d/%m}",
                "description": e.description,
                "amount": f"{e.amount:.2f}",
                "category": e.category.name,
            }
            for e in entries
        ]
        return Response(result)


class InstallmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        # Find installment entries for this month
        installment_entries = (
            Entry.objects.filter(
                user=user, billing_month=billing_month,
                entry_type="installment", installment_plan__isnull=False,
            )
            .select_related("installment_plan")
        )

        plans = []
        monthly_total = Decimal("0")
        for entry in installment_entries:
            plan = entry.installment_plan
            # Determine current installment number
            plan_entries = (
                Entry.objects.filter(installment_plan=plan)
                .order_by("billing_month")
                .values_list("billing_month", flat=True)
            )
            months_list = list(plan_entries)
            try:
                current_num = months_list.index(billing_month) + 1
            except ValueError:
                current_num = 0

            plans.append({
                "description": plan.description,
                "current": current_num,
                "total": plan.num_installments,
                "amount": f"{entry.amount:.2f}",
            })
            monthly_total += entry.amount

        return Response({
            "plans": plans,
            "monthly_total": f"{monthly_total:.2f}",
        })
```

Note: `from django.db.models import Sum` is already imported at the top. Remove the inline `from django.db.models import Sum` inside individual view methods — it's redundant.

- [ ] **Step 7: Create API URLs**

```python
# src/backend/finances/api/urls.py
from django.urls import path

from finances.api.views import (
    AlertsView,
    EvolutionView,
    InstallmentsView,
    RecentEntriesView,
    SummaryView,
    TopCategoriesView,
)

urlpatterns = [
    path("summary/", SummaryView.as_view(), name="api_summary"),
    path("top-categories/", TopCategoriesView.as_view(), name="api_top_categories"),
    path("evolution/", EvolutionView.as_view(), name="api_evolution"),
    path("alerts/", AlertsView.as_view(), name="api_alerts"),
    path("recent-entries/", RecentEntriesView.as_view(), name="api_recent_entries"),
    path("installments/", InstallmentsView.as_view(), name="api_installments"),
]
```

- [ ] **Step 8: Wire API URLs into finances/urls.py**

Add to `src/backend/finances/urls.py`:
```python
from django.urls import include

# Add to urlpatterns:
path("api/dashboard/", include("finances.api.urls")),
```

- [ ] **Step 9: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_api_dashboard.py -v
```

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add DRF API endpoints for dashboard cards"
```

---

## Task 2: Dashboard Django View + Template

**Files:**
- Create: `src/backend/finances/views/dashboard.py`
- Create: `src/backend/templates/dashboard/dashboard_page.html`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`
- Modify: `src/backend/templates/partials/_navbar.html`

- [ ] **Step 1: Create dashboard view**

```python
# src/backend/finances/views/dashboard.py
from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        year = int(self.request.GET.get("year", today.year))
        month = int(self.request.GET.get("month", today.month))
        context["current_year"] = year
        context["current_month"] = month
        context["months"] = list(range(1, 13))
        context["year_range"] = range(2024, today.year + 2)
        context["api_params"] = f"year={year}&month={month}"
        return context
```

- [ ] **Step 2: Create dashboard template**

```html
<!-- src/backend/templates/dashboard/dashboard_page.html -->
{% extends "base.html" %}
{% load static %}

{% block title %}Dashboard — {{ current_month|stringformat:"02d" }}/{{ current_year }}{% endblock %}

{% block content %}
<div class="flex justify-between items-center mb-4">
    <h2 class="text-2xl font-bold">Dashboard</h2>
    <div class="flex gap-2 items-center">
        <select class="select select-sm select-bordered"
                onchange="window.location.href='/?year={{ current_year }}&month=' + this.value">
            {% for m in months %}
            <option value="{{ m }}" {% if m == current_month %}selected{% endif %}>
                {{ m|stringformat:"02d" }}/{{ current_year }}
            </option>
            {% endfor %}
        </select>
        <select class="select select-sm select-bordered"
                onchange="window.location.href='/?year=' + this.value + '&month={{ current_month }}'">
            {% for y in year_range %}
            <option value="{{ y }}" {% if y == current_year %}selected{% endif %}>{{ y }}</option>
            {% endfor %}
        </select>
    </div>
</div>

<!-- React island cards grid -->
<div class="grid grid-cols-1 md:grid-cols-2 gap-4" id="dashboard-cards">
    <div data-react-component="SummaryCard" data-api-url="/api/dashboard/summary/?{{ api_params }}"></div>
    <div data-react-component="TopCategoriesCard" data-api-url="/api/dashboard/top-categories/?{{ api_params }}"></div>
    <div data-react-component="EvolutionCard" data-api-url="/api/dashboard/evolution/?{{ api_params }}"></div>
    <div data-react-component="AlertsCard" data-api-url="/api/dashboard/alerts/?{{ api_params }}"></div>
    <div data-react-component="RecentEntriesCard" data-api-url="/api/dashboard/recent-entries/?{{ api_params }}"></div>
    <div data-react-component="InstallmentsCard" data-api-url="/api/dashboard/installments/?{{ api_params }}"></div>
</div>

<!-- Load React bundle (built by Vite) -->
<script type="module" src="{% static 'frontend/mount.js' %}"></script>
{% endblock %}
```

- [ ] **Step 3: Wire dashboard URL**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.dashboard import DashboardView

# Add at the END of urlpatterns (so it doesn't catch other routes):
path("", DashboardView.as_view(), name="dashboard"),
```

Update navbar — change Dashboard link from `#` to `{% url 'finances:dashboard' %}`.

- [ ] **Step 4: Write view test**

Add to `test_api_dashboard.py`:
```python
@pytest.mark.django_db
class TestDashboardView:
    def test_dashboard_renders(self, logged_client):
        response = logged_client.get("/")
        assert response.status_code == 200
        assert "dashboard_page.html" in [t.name for t in response.templates]

    def test_month_in_context(self, logged_client):
        response = logged_client.get("/?year=2026&month=3")
        assert response.context["current_month"] == 3
        assert response.context["current_year"] == 2026

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/")
        assert response.status_code == 302
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_api_dashboard.py -v
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add dashboard page view with React island mount points"
```

---

## Task 3: Vite + React Frontend Setup

**Files:**
- Create: `src/backend/frontend/package.json`
- Create: `src/backend/frontend/tsconfig.json`
- Create: `src/backend/frontend/vite.config.ts`
- Create: `src/backend/frontend/src/mount.tsx`
- Create: `src/backend/frontend/src/api.ts`
- Create: `src/backend/frontend/src/types.ts`
- Modify: `.gitignore`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "expense-tracker-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "recharts": "^2.15.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.18",
    "@types/react-dom": "^18.3.5",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.7.3",
    "vite": "^6.0.7"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

```typescript
// src/backend/frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../static/frontend"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "src/mount.tsx"),
      output: {
        entryFileNames: "mount.js",
        chunkFileNames: "[name].js",
        assetFileNames: "[name].[ext]",
      },
    },
  },
});
```

- [ ] **Step 4: Create types.ts**

```typescript
// src/backend/frontend/src/types.ts
export interface SummaryData {
  income: string;
  expenses: string;
  returns: string;
  balance: string;
  budget_pct: number;
}

export interface CategoryData {
  name: string;
  amount: string;
  pct: number;
}

export interface EvolutionPoint {
  month: string;
  expenses: string;
  income: string;
}

export interface AlertData {
  severity: "danger" | "warning" | "info" | "success";
  message: string;
}

export interface EntryData {
  date: string;
  description: string;
  amount: string;
  category: string;
}

export interface InstallmentData {
  description: string;
  current: number;
  total: number;
  amount: string;
}

export interface InstallmentsResponse {
  plans: InstallmentData[];
  monthly_total: string;
}
```

- [ ] **Step 5: Create api.ts**

```typescript
// src/backend/frontend/src/api.ts
function getCsrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

export async function fetchApi<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "X-CSRFToken": getCsrfToken(),
      Accept: "application/json",
    },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 6: Create mount.tsx (placeholder — card imports added in Task 4)**

```tsx
// src/backend/frontend/src/mount.tsx
import React from "react";
import { createRoot } from "react-dom/client";

// Card components will be imported here in Task 4
const COMPONENTS: Record<string, React.ComponentType<{ apiUrl: string }>> = {};

function mountAll() {
  const elements = document.querySelectorAll("[data-react-component]");
  elements.forEach((el) => {
    const name = el.getAttribute("data-react-component");
    const apiUrl = el.getAttribute("data-api-url") || "";
    if (name && COMPONENTS[name]) {
      const Component = COMPONENTS[name];
      const root = createRoot(el);
      root.render(<Component apiUrl={apiUrl} />);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAll);
} else {
  mountAll();
}
```

- [ ] **Step 7: Install npm dependencies and build**

```bash
cd src/backend/frontend && npm install && npm run build && cd ../../..
```

- [ ] **Step 8: Update .gitignore**

Append:
```
# Frontend
src/backend/frontend/node_modules/
src/backend/frontend/dist/
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: add Vite + React + TypeScript frontend build pipeline"
```

---

## Task 4: React Card Components

**Files:**
- Create: `src/backend/frontend/src/cards/SummaryCard.tsx`
- Create: `src/backend/frontend/src/cards/TopCategoriesCard.tsx`
- Create: `src/backend/frontend/src/cards/EvolutionCard.tsx`
- Create: `src/backend/frontend/src/cards/AlertsCard.tsx`
- Create: `src/backend/frontend/src/cards/RecentEntriesCard.tsx`
- Create: `src/backend/frontend/src/cards/InstallmentsCard.tsx`
- Modify: `src/backend/frontend/src/mount.tsx`

- [ ] **Step 1: Create SummaryCard.tsx**

```tsx
// src/backend/frontend/src/cards/SummaryCard.tsx
import React, { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { SummaryData } from "../types";

interface Props {
  apiUrl: string;
}

export default function SummaryCard({ apiUrl }: Props) {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    fetchApi<SummaryData>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  const balance = parseFloat(data.balance);

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">📊 Resumo Mensal</h3>
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="opacity-70">Renda</span>
            <span className="font-bold text-success">R$ {data.income}</span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">Gastos</span>
            <span className="font-bold text-error">R$ {data.expenses}</span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">Retornos</span>
            <span className="text-success">R$ {data.returns}</span>
          </div>
          <div className="divider my-1" />
          <div className="flex justify-between font-bold">
            <span>Saldo</span>
            <span className={balance >= 0 ? "text-success" : "text-error"}>
              R$ {data.balance}
            </span>
          </div>
          <div className="mt-2">
            <div className="text-xs opacity-60 mb-1">
              Orçamento utilizado: {data.budget_pct}%
            </div>
            <progress
              className={`progress w-full ${data.budget_pct > 100 ? "progress-error" : data.budget_pct > 90 ? "progress-warning" : "progress-accent"}`}
              value={data.budget_pct}
              max="100"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create TopCategoriesCard.tsx**

```tsx
// src/backend/frontend/src/cards/TopCategoriesCard.tsx
import React, { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { CategoryData } from "../types";

const COLORS = ["#e94560", "#0f3460", "#16c79a", "#533483", "#f59e0b"];

interface Props {
  apiUrl: string;
}

export default function TopCategoriesCard({ apiUrl }: Props) {
  const [data, setData] = useState<CategoryData[] | null>(null);

  useEffect(() => {
    fetchApi<CategoryData[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  const maxAmount = Math.max(...data.map((d) => parseFloat(d.amount)));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">🏷 Top Categorias</h3>
        <div className="space-y-2">
          {data.map((cat, i) => (
            <div key={cat.name}>
              <div className="flex justify-between text-xs mb-0.5">
                <span className="opacity-70">{cat.name}</span>
                <span className="font-bold" style={{ color: COLORS[i % COLORS.length] }}>
                  R$ {cat.amount}
                </span>
              </div>
              <div className="bg-base-200 rounded h-2.5">
                <div
                  className="h-full rounded"
                  style={{
                    width: `${(parseFloat(cat.amount) / maxAmount) * 100}%`,
                    backgroundColor: COLORS[i % COLORS.length],
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create EvolutionCard.tsx**

```tsx
// src/backend/frontend/src/cards/EvolutionCard.tsx
import React, { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fetchApi } from "../api";
import type { EvolutionPoint } from "../types";

interface Props {
  apiUrl: string;
}

export default function EvolutionCard({ apiUrl }: Props) {
  const [data, setData] = useState<EvolutionPoint[] | null>(null);

  useEffect(() => {
    fetchApi<EvolutionPoint[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-64" />;

  const chartData = data.map((d) => ({
    month: d.month.slice(5),  // "2026-03" → "03"
    expenses: parseFloat(d.expenses),
    income: parseFloat(d.income),
  }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">📈 Evolução</h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData}>
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 10 }} width={50} />
            <Tooltip formatter={(value: number) => `R$ ${value.toFixed(2)}`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              type="monotone"
              dataKey="expenses"
              name="Gastos"
              stroke="#e94560"
              strokeWidth={2}
              dot={{ r: 3 }}
            />
            <Line
              type="monotone"
              dataKey="income"
              name="Renda"
              stroke="#16c79a"
              strokeWidth={2}
              strokeDasharray="6 3"
              dot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create AlertsCard.tsx**

```tsx
// src/backend/frontend/src/cards/AlertsCard.tsx
import React, { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { AlertData } from "../types";

interface Props {
  apiUrl: string;
}

const SEVERITY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  danger: { bg: "bg-red-50", border: "border-l-red-500", text: "text-red-700" },
  warning: { bg: "bg-amber-50", border: "border-l-amber-500", text: "text-amber-800" },
  info: { bg: "bg-blue-50", border: "border-l-blue-500", text: "text-blue-700" },
  success: { bg: "bg-green-50", border: "border-l-green-500", text: "text-green-700" },
};

export default function AlertsCard({ apiUrl }: Props) {
  const [data, setData] = useState<AlertData[] | null>(null);

  useEffect(() => {
    fetchApi<AlertData[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">🔔 Alertas</h3>
        <div className="space-y-2">
          {data.map((alert, i) => {
            const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.info;
            return (
              <div
                key={i}
                className={`${style.bg} border-l-4 ${style.border} px-3 py-2 rounded-r text-xs font-medium ${style.text}`}
              >
                {alert.message}
              </div>
            );
          })}
          {data.length === 0 && (
            <div className="text-sm opacity-60 text-center py-4">
              Nenhum alerta este mês
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create RecentEntriesCard.tsx**

```tsx
// src/backend/frontend/src/cards/RecentEntriesCard.tsx
import React, { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { EntryData } from "../types";

interface Props {
  apiUrl: string;
}

export default function RecentEntriesCard({ apiUrl }: Props) {
  const [data, setData] = useState<EntryData[] | null>(null);

  useEffect(() => {
    fetchApi<EntryData[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">📝 Últimas Entradas</h3>
        <div className="space-y-1">
          {data.map((entry, i) => {
            const amount = parseFloat(entry.amount);
            return (
              <div
                key={i}
                className="flex justify-between text-xs py-1 border-b border-base-200 last:border-0"
              >
                <span className={amount < 0 ? "text-success" : "opacity-70"}>
                  {entry.date} {entry.description}
                </span>
                <span className={`font-bold ${amount < 0 ? "text-success" : "text-error"}`}>
                  R$ {entry.amount}
                </span>
              </div>
            );
          })}
        </div>
        <a href="/entries/" className="text-xs text-primary font-bold text-center mt-2 block">
          Ver todas →
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create InstallmentsCard.tsx**

```tsx
// src/backend/frontend/src/cards/InstallmentsCard.tsx
import React, { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { InstallmentsResponse } from "../types";

interface Props {
  apiUrl: string;
}

export default function InstallmentsCard({ apiUrl }: Props) {
  const [data, setData] = useState<InstallmentsResponse | null>(null);

  useEffect(() => {
    fetchApi<InstallmentsResponse>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data) return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">💳 Parcelas Ativas</h3>
        <div className="space-y-1">
          {data.plans.map((plan, i) => (
            <div
              key={i}
              className="flex justify-between text-xs py-1 border-b border-base-200 last:border-0"
            >
              <span className="opacity-70">
                {plan.description}{" "}
                <span className="text-base-content/50">({plan.current}/{plan.total})</span>
              </span>
              <span className="font-bold">R$ {plan.amount}</span>
            </div>
          ))}
          {data.plans.length > 0 && (
            <>
              <div className="divider my-1" />
              <div className="flex justify-between text-xs font-bold">
                <span>Total este mês</span>
                <span className="text-error">R$ {data.monthly_total}</span>
              </div>
            </>
          )}
          {data.plans.length === 0 && (
            <div className="text-sm opacity-60 text-center py-4">
              Nenhuma parcela ativa este mês
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Update mount.tsx with all card imports**

```tsx
// src/backend/frontend/src/mount.tsx
import React from "react";
import { createRoot } from "react-dom/client";
import SummaryCard from "./cards/SummaryCard";
import TopCategoriesCard from "./cards/TopCategoriesCard";
import EvolutionCard from "./cards/EvolutionCard";
import AlertsCard from "./cards/AlertsCard";
import RecentEntriesCard from "./cards/RecentEntriesCard";
import InstallmentsCard from "./cards/InstallmentsCard";

const COMPONENTS: Record<string, React.ComponentType<{ apiUrl: string }>> = {
  SummaryCard,
  TopCategoriesCard,
  EvolutionCard,
  AlertsCard,
  RecentEntriesCard,
  InstallmentsCard,
};

function mountAll() {
  const elements = document.querySelectorAll("[data-react-component]");
  elements.forEach((el) => {
    const name = el.getAttribute("data-react-component");
    const apiUrl = el.getAttribute("data-api-url") || "";
    if (name && COMPONENTS[name]) {
      const Component = COMPONENTS[name];
      const root = createRoot(el);
      root.render(<Component apiUrl={apiUrl} />);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAll);
} else {
  mountAll();
}
```

- [ ] **Step 8: Build and verify**

```bash
cd src/backend/frontend && npm run build && cd ../../..
ls src/backend/static/frontend/mount.js
```

Expected: `mount.js` exists in static/frontend/.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: add React dashboard cards with Recharts (Summary, Categories, Evolution, Alerts, Entries, Installments)"
```

---

## Task 5: Final Validation

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

- [ ] **Step 4: Verify frontend build**

```bash
cd src/backend/frontend && npm run build && cd ../../..
test -f src/backend/static/frontend/mount.js && echo "OK" || echo "MISSING"
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "chore: fix lint and formatting from final validation"
```
