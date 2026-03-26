# Sub-Project 2: HTMX Views — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all server-rendered pages for the expense tracker — entries with month tabs, consolidated views with expandable rows, settings with 4 CRUD tabs — using HTMX for dynamic interactions and DaisyUI for styling.

**Architecture:** Django class-based views with an HtmxMixin that returns full pages on direct navigation or HTML fragments on HTMX requests. Forms use Django ModelForms. All views filter by `request.user`. Templates use DaisyUI components with Alpine.js for client-side state (toasts, dropdowns). No JavaScript build step — HTMX and Alpine.js loaded via CDN.

**Tech Stack:** Django 6, django-htmx, HTMX 2.x (CDN), Alpine.js 3.x (CDN), TailwindCSS v4 + DaisyUI, pytest + pytest-django + pytest-bdd + model-bakery.

**Spec:** `docs/superpowers/specs/2026-03-26-htmx-views-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/finances/forms.py` | ModelForms for Entry, InstallmentPlan, Income, SystemicExpense, PaymentMethod, Category |
| `src/backend/finances/views/__init__.py` | Re-exports all views |
| `src/backend/finances/views/mixins.py` | HtmxMixin for template switching |
| `src/backend/finances/views/entries.py` | Entry list, create, update, delete views |
| `src/backend/finances/views/consolidated.py` | Consolidated table + category detail views |
| `src/backend/finances/views/settings.py` | Settings page + all tab CRUD views |
| `src/backend/finances/urls.py` | URL patterns for all finances views |
| `src/backend/templates/base.html` | Base layout: navbar, content area, chat placeholder, toast, scripts |
| `src/backend/templates/partials/_navbar.html` | Top navigation bar |
| `src/backend/templates/partials/_toast.html` | Alpine.js toast notifications |
| `src/backend/templates/partials/_modal_entry_form.html` | Modal form for new entry/installment |
| `src/backend/templates/entries/entries_page.html` | Full entries page (extends base) |
| `src/backend/templates/entries/_entries_table.html` | Entries table fragment (month tab swap) |
| `src/backend/templates/entries/_entry_row.html` | Single entry row |
| `src/backend/templates/entries/_entry_edit_row.html` | Editable entry row |
| `src/backend/templates/entries/_inline_entry_form.html` | Green inline form at top of table |
| `src/backend/templates/consolidated/consolidated_page.html` | Full consolidated page |
| `src/backend/templates/consolidated/_consolidated_table.html` | Table fragment |
| `src/backend/templates/consolidated/_category_detail.html` | Expandable detail rows |
| `src/backend/templates/settings/settings_page.html` | Full settings page with tabs |
| `src/backend/templates/settings/_income_tab.html` | Income tab content |
| `src/backend/templates/settings/_systemics_tab.html` | Systemic expenses tab |
| `src/backend/templates/settings/_payment_methods_tab.html` | Payment methods tab |
| `src/backend/templates/settings/_categories_tab.html` | Categories tab |
| `src/backend/finances/tests/test_forms.py` | Form validation tests |
| `src/backend/finances/tests/test_views_entries.py` | Entry view tests |
| `src/backend/finances/tests/test_views_consolidated.py` | Consolidated view tests |
| `src/backend/finances/tests/test_views_settings.py` | Settings view tests |
| `src/backend/finances/tests/features/views.feature` | BDD specs for key UI flows |
| `src/backend/finances/tests/features/test_views.py` | BDD step definitions |

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/config/settings.py` | Add `django_htmx` to INSTALLED_APPS and MIDDLEWARE |
| `src/backend/config/urls.py` | Include `finances.urls` |
| `pyproject.toml` | Add `django-htmx` dependency |
| `src/backend/finances/views.py` | Delete (replaced by views package) |

---

## Task 1: Infrastructure — django-htmx, Base Layout, HtmxMixin

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/backend/config/settings.py`
- Modify: `src/backend/config/urls.py`
- Delete: `src/backend/finances/views.py`
- Create: `src/backend/finances/views/__init__.py`
- Create: `src/backend/finances/views/mixins.py`
- Create: `src/backend/finances/urls.py`
- Create: `src/backend/templates/base.html`
- Create: `src/backend/templates/partials/_navbar.html`
- Create: `src/backend/templates/partials/_toast.html`

- [ ] **Step 1: Add django-htmx dependency**

```bash
uv add django-htmx
```

- [ ] **Step 2: Update settings.py**

Add `"django_htmx"` to INSTALLED_APPS after `"django_tailwind_cli"`. Add `"django_htmx.middleware.HtmxMiddleware"` to MIDDLEWARE after `CommonMiddleware`. Add `LOGIN_URL = "/admin/login/"` at the bottom (temporary — uses Django Admin login until auth UI is built).

- [ ] **Step 3: Delete old views.py and create views package**

```bash
rm src/backend/finances/views.py
mkdir -p src/backend/finances/views
```

```python
# src/backend/finances/views/__init__.py
```

- [ ] **Step 4: Create HtmxMixin**

```python
# src/backend/finances/views/mixins.py
from django.contrib.auth.mixins import LoginRequiredMixin


class HtmxMixin:
    """Return fragment template for HTMX requests, full page otherwise."""

    template_name = ""
    htmx_template_name = ""

    def get_template_names(self):
        if self.request.htmx:
            return [self.htmx_template_name]
        return [self.template_name]


class HtmxLoginRequiredMixin(LoginRequiredMixin, HtmxMixin):
    """Combines login requirement with HTMX template switching."""

    pass
```

- [ ] **Step 5: Create finances URL patterns (empty for now)**

```python
# src/backend/finances/urls.py
from django.urls import path

app_name = "finances"

urlpatterns = []
```

- [ ] **Step 6: Update config/urls.py to include finances URLs**

```python
# src/backend/config/urls.py
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("finances.urls")),
]
```

- [ ] **Step 7: Create base.html**

```html
<!-- src/backend/templates/base.html -->
<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Expense Tracker{% endblock %}</title>
    {% load django_tailwind_cli %}
    {% tailwind_css %}
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script defer src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"></script>
</head>
<body class="min-h-screen bg-base-200" x-data="{ showToast: false, toastMessage: '', toastType: 'success' }"
      @show-toast.window="showToast = true; toastMessage = $event.detail.message; toastType = $event.detail.type || 'success'; setTimeout(() => showToast = false, 3000)">

    {% include "partials/_navbar.html" %}

    <div class="flex">
        <!-- Main content -->
        <main class="flex-1 p-4">
            {% block content %}{% endblock %}
        </main>

        <!-- Chat placeholder -->
        <aside class="w-16 bg-base-300 min-h-[calc(100vh-4rem)] flex flex-col items-center pt-4 gap-2">
            <div class="w-10 h-10 bg-neutral text-neutral-content rounded-full flex items-center justify-center text-lg">
                💬
            </div>
            <span class="text-xs opacity-60 [writing-mode:vertical-rl]">Chat</span>
        </aside>
    </div>

    {% include "partials/_toast.html" %}

    <!-- Modal container for entry form -->
    <dialog id="entry-modal" class="modal">
        <div class="modal-box w-11/12 max-w-lg" id="entry-modal-content">
            <!-- Content loaded via HTMX -->
        </div>
        <form method="dialog" class="modal-backdrop"><button>close</button></form>
    </dialog>
</body>
</html>
```

- [ ] **Step 8: Create _navbar.html**

```html
<!-- src/backend/templates/partials/_navbar.html -->
<nav class="navbar bg-neutral text-neutral-content">
    <div class="flex-1 gap-2">
        <a href="/" class="btn btn-ghost text-xl">Expense Tracker</a>
        <ul class="menu menu-horizontal px-1 gap-1">
            <li><a href="/" class="{% if request.resolver_match.url_name == 'dashboard' %}active{% endif %}">Dashboard</a></li>
            <li><a href="{% url 'finances:entries' %}" class="{% if 'entries' in request.resolver_match.url_name %}active{% endif %}">Entradas</a></li>
            <li><a href="{% url 'finances:consolidated' %}" class="{% if 'consolidated' in request.resolver_match.url_name %}active{% endif %}">Consolidado</a></li>
            <li><a href="{% url 'finances:settings' %}" class="{% if 'settings' in request.resolver_match.url_name %}active{% endif %}">Configurações</a></li>
        </ul>
    </div>
    <div class="flex-none gap-2">
        <button class="btn btn-sm btn-accent"
                hx-get="{% url 'finances:entry_modal' %}"
                hx-target="#entry-modal-content"
                hx-swap="innerHTML"
                onclick="document.getElementById('entry-modal').showModal()">
            + Nova Entrada
        </button>
        <span class="text-sm opacity-70">{{ request.user.username }}</span>
    </div>
</nav>
```

- [ ] **Step 9: Create _toast.html**

```html
<!-- src/backend/templates/partials/_toast.html -->
<div x-show="showToast"
     x-transition:enter="transition ease-out duration-300"
     x-transition:enter-start="opacity-0 translate-y-2"
     x-transition:enter-end="opacity-100 translate-y-0"
     x-transition:leave="transition ease-in duration-200"
     x-transition:leave-start="opacity-100 translate-y-0"
     x-transition:leave-end="opacity-0 translate-y-2"
     class="toast toast-end toast-top z-50"
     style="display: none;">
    <div :class="toastType === 'error' ? 'alert alert-error' : 'alert alert-success'">
        <span x-text="toastMessage"></span>
    </div>
</div>
```

- [ ] **Step 10: Install dependencies, build Tailwind, verify**

```bash
uv sync
uv run python src/backend/manage.py tailwind build
uv run python src/backend/manage.py check
```

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: add base layout with HTMX, Alpine.js, DaisyUI navbar, and toast notifications"
```

---

## Task 2: Forms

**Files:**
- Create: `src/backend/finances/forms.py`
- Create: `src/backend/finances/tests/test_forms.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_forms.py
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker

from finances.forms import EntryForm, InstallmentForm, IncomeForm, SystemicExpenseForm


@pytest.mark.django_db
class TestEntryForm:
    def test_valid_entry(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "Test entry",
                "category": category.id,
                "payment_method": pm.id,
            },
            user=user,
        )
        assert form.is_valid(), form.errors

    def test_missing_required_fields(self, user):
        form = EntryForm(data={}, user=user)
        assert not form.is_valid()
        assert "date" in form.errors
        assert "amount" in form.errors
        assert "description" in form.errors

    def test_negative_amount_allowed(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        form = EntryForm(
            data={
                "date": "2026-03-15",
                "amount": "-50.00",
                "description": "Refund",
                "category": category.id,
                "payment_method": pm.id,
            },
            user=user,
        )
        assert form.is_valid()

    def test_filters_categories_by_user(self, user, other_user):
        cat_mine = baker.make("finances.Category", user=user, name="Mine")
        baker.make("finances.Category", user=other_user, name="Theirs")
        form = EntryForm(data={}, user=user)
        assert list(form.fields["category"].queryset) == [cat_mine]

    def test_filters_payment_methods_by_user(self, user, other_user):
        pm_mine = baker.make("finances.PaymentMethod", user=user, name="Mine")
        baker.make("finances.PaymentMethod", user=other_user, name="Theirs")
        form = EntryForm(data={}, user=user)
        assert list(form.fields["payment_method"].queryset) == [pm_mine]


@pytest.mark.django_db
class TestInstallmentForm:
    def test_valid_installment(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=25)
        form = InstallmentForm(
            data={
                "date": "2026-03-15",
                "description": "Notebook",
                "category": category.id,
                "payment_method": pm.id,
                "total_amount": "6699.00",
                "num_installments": "12",
                "installment_amount": "558.25",
            },
            user=user,
        )
        assert form.is_valid(), form.errors

    def test_num_installments_must_be_positive(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user)
        form = InstallmentForm(
            data={
                "date": "2026-03-15",
                "description": "Test",
                "category": category.id,
                "payment_method": pm.id,
                "total_amount": "100.00",
                "num_installments": "0",
                "installment_amount": "50.00",
            },
            user=user,
        )
        assert not form.is_valid()


@pytest.mark.django_db
class TestIncomeForm:
    def test_valid_income(self):
        form = IncomeForm(
            data={
                "name": "Salário",
                "amount": "7854.23",
                "month": "2026-03-01",
                "is_recurring": True,
            }
        )
        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestSystemicExpenseForm:
    def test_valid_systemic(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user)
        form = SystemicExpenseForm(
            data={
                "name": "Enel",
                "category": category.id,
                "payment_method": pm.id,
                "default_amount": "460.00",
            },
            user=user,
        )
        assert form.is_valid(), form.errors
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_forms.py -v
```

- [ ] **Step 3: Implement forms**

```python
# src/backend/finances/forms.py
from django import forms

from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


class EntryForm(forms.ModelForm):
    class Meta:
        model = Entry
        fields = ["date", "amount", "description", "category", "payment_method"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full", "placeholder": "R$ 0,00"}),
            "description": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full", "placeholder": "Descrição"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )


class InstallmentForm(forms.ModelForm):
    class Meta:
        model = InstallmentPlan
        fields = [
            "date",
            "description",
            "category",
            "payment_method",
            "total_amount",
            "num_installments",
            "installment_amount",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "description": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "total_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
            "num_installments": forms.NumberInput(attrs={"min": "1", "class": "input input-bordered input-sm w-full"}),
            "installment_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )


class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = ["name", "amount", "month", "is_recurring", "recurrence_start", "recurrence_end"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
            "month": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
            "recurrence_start": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
            "recurrence_end": forms.DateInput(attrs={"type": "date", "class": "input input-bordered input-sm w-full"}),
        }


class SystemicExpenseForm(forms.ModelForm):
    class Meta:
        model = SystemicExpense
        fields = ["name", "category", "payment_method", "default_amount"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "category": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "payment_method": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "default_amount": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["payment_method"].queryset = PaymentMethod.objects.filter(
                user=user, is_active=True
            )
            self.fields["payment_method"].required = False


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "type", "closing_day"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "type": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "closing_day": forms.NumberInput(attrs={"min": "1", "max": "31", "class": "input input-bordered input-sm w-full"}),
        }


class CategoryBudgetForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["budget_ceiling"]
        widgets = {
            "budget_ceiling": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }


class CategoryCreateForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "budget_ceiling"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "budget_ceiling": forms.NumberInput(attrs={"step": "0.01", "class": "input input-bordered input-sm w-full"}),
        }
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_forms.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/forms.py src/backend/finances/tests/test_forms.py
git commit -m "feat(finances): add ModelForms for all CRUD operations"
```

---

## Task 3: Entries Page — List View with Month Tabs

**Files:**
- Create: `src/backend/finances/views/entries.py`
- Create: `src/backend/templates/entries/entries_page.html`
- Create: `src/backend/templates/entries/_entries_table.html`
- Create: `src/backend/templates/entries/_entry_row.html`
- Create: `src/backend/templates/entries/_inline_entry_form.html`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`
- Create: `src/backend/finances/tests/test_views_entries.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_views_entries.py
import pytest
from datetime import date
from decimal import Decimal

from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def sample_entries(user):
    category = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    entries = [
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, d),
            amount=Decimal("50.00"),
            description=f"Entry {d}",
            category=category,
            payment_method=pix,
            billing_month=date(2026, 3, 1),
        )
        for d in [1, 10, 20]
    ]
    # Entry in different month
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 2, 15),
        amount=Decimal("30.00"),
        description="Feb entry",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 2, 1),
    )
    return entries


@pytest.mark.django_db
class TestEntryListView:
    def test_redirects_to_current_month(self, logged_client):
        response = logged_client.get("/entries/")
        assert response.status_code == 302

    def test_entries_page_renders(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert response.status_code == 200
        assert "entries_page.html" in [t.name for t in response.templates]

    def test_htmx_returns_fragment(self, logged_client, sample_entries):
        response = logged_client.get(
            "/entries/2026/3/", HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 200
        assert "_entries_table.html" in [t.name for t in response.templates]

    def test_filters_by_billing_month(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert len(entries) == 3
        assert all(e.billing_month == date(2026, 3, 1) for e in entries)

    def test_feb_entries_not_in_march(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert not any(e.description == "Feb entry" for e in entries)

    def test_other_user_entries_not_visible(self, logged_client, other_user, sample_entries):
        other_cat = baker.make("finances.Category", user=other_user)
        other_pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            category=other_cat,
            payment_method=other_pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert len(entries) == 3

    def test_context_has_summary(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "summary" in response.context
        summary = response.context["summary"]
        assert summary["total_expenses"] == Decimal("150.00")
        assert summary["entry_count"] == 3

    def test_context_has_month_tabs(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "months" in response.context
        assert "current_month" in response.context
        assert response.context["current_month"] == 3
        assert response.context["current_year"] == 2026

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/entries/2026/3/")
        assert response.status_code == 302

    def test_context_has_entry_form(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "form" in response.context
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_entries.py -v
```

- [ ] **Step 3: Implement entry views**

```python
# src/backend/finances/views/entries.py
from datetime import date
from decimal import Decimal

from django.db.models import Sum, Q
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from finances.forms import EntryForm
from finances.models import Entry
from finances.views.mixins import HtmxLoginRequiredMixin


class EntryRedirectView(HtmxLoginRequiredMixin, View):
    """Redirect /entries/ to current month."""

    def get(self, request, *args, **kwargs):
        today = date.today()
        return redirect("finances:entries_month", year=today.year, month=today.month)


class EntryListView(HtmxLoginRequiredMixin, ListView):
    """Display entries for a specific billing month."""

    model = Entry
    template_name = "entries/entries_page.html"
    htmx_template_name = "entries/_entries_table.html"
    context_object_name = "entries"
    paginate_by = 100

    def get_queryset(self):
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])
        billing_month = date(year, month, 1)
        return (
            Entry.objects.filter(user=self.request.user, billing_month=billing_month)
            .select_related("category", "payment_method")
            .order_by("-date", "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.kwargs["year"])
        month = int(self.kwargs["month"])

        context["current_year"] = year
        context["current_month"] = month
        context["months"] = list(range(1, 13))
        context["year_range"] = range(2024, date.today().year + 2)

        # Summary
        entries = context["entries"]
        expenses = sum(e.amount for e in entries if e.amount > 0)
        returns = sum(e.amount for e in entries if e.amount < 0)
        context["summary"] = {
            "total_expenses": expenses,
            "total_returns": abs(returns),
            "net": expenses + returns,
            "entry_count": len(entries),
        }

        # Inline form
        context["form"] = EntryForm(user=self.request.user)

        return context
```

- [ ] **Step 4: Update URLs**

```python
# src/backend/finances/urls.py
from django.urls import path

from finances.views.entries import EntryListView, EntryRedirectView

app_name = "finances"

urlpatterns = [
    # Entries
    path("entries/", EntryRedirectView.as_view(), name="entries"),
    path("entries/<int:year>/<int:month>/", EntryListView.as_view(), name="entries_month"),
]
```

```python
# src/backend/finances/views/__init__.py
from finances.views.entries import EntryListView, EntryRedirectView

__all__ = ["EntryListView", "EntryRedirectView"]
```

- [ ] **Step 5: Create templates**

Create `src/backend/templates/entries/entries_page.html`:
```html
{% extends "base.html" %}

{% block title %}Entradas — {{ current_year }}{% endblock %}

{% block content %}
<div class="flex justify-between items-center mb-4">
    <h2 class="text-2xl font-bold">Entradas</h2>
</div>

<!-- Month tabs -->
<div class="tabs tabs-bordered mb-4">
    {% for m in months %}
    <a class="tab {% if m == current_month %}tab-active{% endif %}"
       hx-get="{% url 'finances:entries_month' current_year m %}"
       hx-target="#entries-container"
       hx-swap="innerHTML"
       hx-push-url="true">
        {{ m|stringformat:"02d" }}
    </a>
    {% endfor %}
    <select class="select select-sm select-bordered ml-2"
            hx-get=""
            hx-target="#entries-container"
            hx-swap="innerHTML"
            onchange="htmx.ajax('GET', '/entries/' + this.value + '/{{ current_month }}/', {target: '#entries-container', swap: 'innerHTML'})">
        {% for y in year_range %}
        <option value="{{ y }}" {% if y == current_year %}selected{% endif %}>{{ y }}</option>
        {% endfor %}
    </select>
</div>

<div id="entries-container">
    {% include "entries/_entries_table.html" %}
</div>
{% endblock %}
```

Create `src/backend/templates/entries/_entries_table.html`:
```html
<!-- Inline entry form -->
{% include "entries/_inline_entry_form.html" %}

<!-- Entries table -->
<div class="overflow-x-auto">
<table class="table table-sm">
    <thead>
        <tr>
            <th>Data</th>
            <th>Valor</th>
            <th>Descrição</th>
            <th>Categoria</th>
            <th>Forma</th>
            <th>Fatura</th>
            <th></th>
        </tr>
    </thead>
    <tbody id="entries-tbody">
        {% for entry in entries %}
        {% include "entries/_entry_row.html" %}
        {% empty %}
        <tr><td colspan="7" class="text-center opacity-60">Nenhuma entrada neste mês.</td></tr>
        {% endfor %}
    </tbody>
</table>
</div>

<!-- Summary -->
<div class="flex gap-6 mt-4 text-sm opacity-70">
    <span>Total gastos: <strong class="text-error">R$ {{ summary.total_expenses }}</strong></span>
    <span>Total retornos: <strong class="text-success">R$ {{ summary.total_returns }}</strong></span>
    <span>Líquido: <strong>R$ {{ summary.net }}</strong></span>
    <span>Entradas: <strong>{{ summary.entry_count }}</strong></span>
</div>
```

Create `src/backend/templates/entries/_entry_row.html`:
```html
<tr id="entry-{{ entry.id }}" class="{% if entry.amount < 0 %}text-success{% endif %} {% if entry.entry_type == 'systemic' %}bg-base-200{% endif %}">
    <td>{{ entry.date|date:"d/m" }}</td>
    <td>R$ {{ entry.amount }}</td>
    <td>{{ entry.description }}</td>
    <td><span class="badge badge-sm">{{ entry.category.name }}</span></td>
    <td>{{ entry.payment_method.name }}</td>
    <td>{{ entry.billing_month|date:"M" }}</td>
    <td>
        {% if entry.entry_type == 'regular' %}
        <button class="btn btn-ghost btn-xs"
                hx-get="{% url 'finances:entry_edit' entry.id %}"
                hx-target="#entry-{{ entry.id }}"
                hx-swap="outerHTML">✏️</button>
        <button class="btn btn-ghost btn-xs text-error"
                hx-delete="{% url 'finances:entry_delete' entry.id %}"
                hx-target="#entry-{{ entry.id }}"
                hx-swap="outerHTML swap:1s"
                hx-confirm="Excluir esta entrada?">🗑️</button>
        {% endif %}
    </td>
</tr>
```

Create `src/backend/templates/entries/_inline_entry_form.html`:
```html
<form hx-post="{% url 'finances:entry_create' %}"
      hx-target="#entries-tbody"
      hx-swap="afterbegin"
      hx-on::after-request="if(event.detail.successful) this.reset()"
      class="flex gap-2 p-2 bg-success/10 rounded-lg mb-2 items-end">
    {{ form.date }}
    {{ form.amount }}
    {{ form.description }}
    {{ form.category }}
    {{ form.payment_method }}
    <button type="submit" class="btn btn-sm btn-accent">Salvar</button>
</form>
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_entries.py -v
```

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add entries page with month tabs and inline form"
```

---

## Task 4: Entry Create, Edit, Delete Views

**Files:**
- Modify: `src/backend/finances/views/entries.py`
- Create: `src/backend/templates/entries/_entry_edit_row.html`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`
- Modify: `src/backend/finances/tests/test_views_entries.py`

- [ ] **Step 1: Write failing tests**

Append to `test_views_entries.py`:

```python
@pytest.mark.django_db
class TestEntryCreateView:
    def test_create_entry_via_inline(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        response = logged_client.post(
            "/entries/create/",
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "Test inline",
                "category": str(category.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Entry
        assert Entry.objects.filter(user=user, description="Test inline").exists()

    def test_create_entry_invalid_returns_form(self, logged_client, user):
        response = logged_client.post(
            "/entries/create/",
            data={},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        # Should re-render the form with errors


@pytest.mark.django_db
class TestEntryUpdateView:
    def test_get_edit_form(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get(
            f"/entries/{entry.id}/edit/", HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 200
        assert "_entry_edit_row.html" in [t.name for t in response.templates]

    def test_post_edit_updates_entry(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            amount=Decimal("50.00"),
            description="Old",
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.post(
            f"/entries/{entry.id}/edit/",
            data={
                "date": "2026-03-15",
                "amount": "75.00",
                "description": "Updated",
                "category": str(category.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        entry.refresh_from_db()
        assert entry.description == "Updated"
        assert entry.amount == Decimal("75.00")

    def test_cannot_edit_other_user_entry(self, logged_client, other_user):
        category = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=other_user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get(f"/entries/{entry.id}/edit/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestEntryDeleteView:
    def test_delete_entry(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.delete(
            f"/entries/{entry.id}/delete/", HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 200
        from finances.models import Entry
        assert not Entry.objects.filter(id=entry.id).exists()

    def test_cannot_delete_other_user_entry(self, logged_client, other_user):
        category = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=other_user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.delete(f"/entries/{entry.id}/delete/")
        assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_entries.py -v -k "Create or Update or Delete"
```

- [ ] **Step 3: Implement create, edit, delete views**

Add to `src/backend/finances/views/entries.py`:

```python
from django.http import HttpResponse
from django.views.generic import CreateView, UpdateView, View

from finances.forms import EntryForm, InstallmentForm
from finances.models import Entry, InstallmentPlan


class EntryCreateView(HtmxLoginRequiredMixin, CreateView):
    """Create entry from inline form or modal."""

    model = Entry
    form_class = EntryForm
    template_name = "entries/_inline_entry_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        entry = form.save()
        return self.render_to_response(
            self.get_context_data(entry=entry),
            template="entries/_entry_row.html",
        )

    def render_to_response(self, context, **kwargs):
        template = kwargs.pop("template", self.template_name)
        from django.template.loader import render_to_string

        html = render_to_string(template, context, request=self.request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Entrada criada!", "type": "success"}}'
        return response

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class EntryUpdateView(HtmxLoginRequiredMixin, UpdateView):
    """Edit entry inline."""

    model = Entry
    form_class = EntryForm
    template_name = "entries/_entry_edit_row.html"

    def get_queryset(self):
        return Entry.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        entry = form.save()
        from django.template.loader import render_to_string

        html = render_to_string(
            "entries/_entry_row.html", {"entry": entry}, request=self.request
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Entrada atualizada!", "type": "success"}}'
        return response


class EntryDeleteView(HtmxLoginRequiredMixin, View):
    """Delete entry."""

    def delete(self, request, pk):
        entry = Entry.objects.filter(user=request.user, pk=pk).first()
        if not entry:
            from django.http import Http404

            raise Http404
        entry.delete()
        response = HttpResponse("")
        response["HX-Trigger"] = '{"showToast": {"message": "Entrada excluída!", "type": "success"}}'
        return response
```

- [ ] **Step 4: Create edit row template**

```html
<!-- src/backend/templates/entries/_entry_edit_row.html -->
<tr id="entry-{{ object.id }}" class="bg-warning/10">
    <form hx-post="{% url 'finances:entry_edit' object.id %}"
          hx-target="#entry-{{ object.id }}"
          hx-swap="outerHTML">
        {% csrf_token %}
        <td>{{ form.date }}</td>
        <td>{{ form.amount }}</td>
        <td>{{ form.description }}</td>
        <td>{{ form.category }}</td>
        <td>{{ form.payment_method }}</td>
        <td>
            <button type="submit" class="btn btn-xs btn-success">✓</button>
            <button type="button" class="btn btn-xs btn-ghost"
                    hx-get="{% url 'finances:entries_month' current_year current_month %}"
                    hx-target="#entries-container"
                    hx-swap="innerHTML">✕</button>
        </td>
    </form>
</tr>
```

- [ ] **Step 5: Update URLs**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.entries import EntryCreateView, EntryUpdateView, EntryDeleteView

# Add to urlpatterns:
path("entries/create/", EntryCreateView.as_view(), name="entry_create"),
path("entries/<uuid:pk>/edit/", EntryUpdateView.as_view(), name="entry_edit"),
path("entries/<uuid:pk>/delete/", EntryDeleteView.as_view(), name="entry_delete"),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_entries.py -v
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add entry create, edit, delete views with HTMX"
```

---

## Task 5: Modal Entry Form with Installment Support

**Files:**
- Create: `src/backend/templates/partials/_modal_entry_form.html`
- Modify: `src/backend/finances/views/entries.py`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/tests/test_views_entries.py`

- [ ] **Step 1: Write failing tests**

Append to `test_views_entries.py`:

```python
@pytest.mark.django_db
class TestModalEntryForm:
    def test_get_modal_form(self, logged_client):
        response = logged_client.get("/entries/modal/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "_modal_entry_form.html" in [t.name for t in response.templates]

    def test_create_installment_via_modal(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            type="credit_card",
            closing_day=25,
        )
        response = logged_client.post(
            "/entries/modal/",
            data={
                "entry_mode": "installment",
                "date": "2026-03-15",
                "description": "Notebook",
                "category": str(category.id),
                "payment_method": str(pm.id),
                "total_amount": "600.00",
                "num_installments": "3",
                "installment_amount": "200.00",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import InstallmentPlan, Entry

        assert InstallmentPlan.objects.filter(user=user).count() == 1
        assert Entry.objects.filter(user=user, entry_type="installment").count() == 3
```

- [ ] **Step 2: Implement modal view**

Add to `src/backend/finances/views/entries.py`:

```python
class EntryModalView(HtmxLoginRequiredMixin, View):
    """Serve modal form and handle both regular and installment creation."""

    def get(self, request):
        from django.template.loader import render_to_string

        context = {
            "entry_form": EntryForm(user=request.user),
            "installment_form": InstallmentForm(user=request.user),
        }
        html = render_to_string(
            "partials/_modal_entry_form.html", context, request=request
        )
        return HttpResponse(html)

    def post(self, request):
        entry_mode = request.POST.get("entry_mode", "regular")

        if entry_mode == "installment":
            form = InstallmentForm(request.POST, user=request.user)
            if form.is_valid():
                plan = form.save(commit=False)
                plan.user = request.user
                plan.save()
                plan.generate_entries()
                response = HttpResponse("")
                import json
                trigger = json.dumps({"showToast": {
                    "message": f"Parcelamento criado com {plan.num_installments} parcelas!",
                    "type": "success",
                }})
                response["HX-Trigger"] = trigger
                return response
        else:
            form = EntryForm(request.POST, user=request.user)
            if form.is_valid():
                entry = form.save(commit=False)
                entry.user = request.user
                entry.save()
                response = HttpResponse("")
                response["HX-Trigger"] = '{"showToast": {"message": "Entrada criada!", "type": "success"}}'
                return response

        from django.template.loader import render_to_string

        context = {
            "entry_form": EntryForm(user=request.user) if entry_mode == "installment" else form,
            "installment_form": form if entry_mode == "installment" else InstallmentForm(user=request.user),
            "errors": True,
        }
        html = render_to_string(
            "partials/_modal_entry_form.html", context, request=request
        )
        return HttpResponse(html)
```

- [ ] **Step 3: Create modal template**

```html
<!-- src/backend/templates/partials/_modal_entry_form.html -->
<h3 class="font-bold text-lg mb-4">Nova Entrada</h3>

<div x-data="{ mode: 'regular' }" class="space-y-4">
    <!-- Mode toggle -->
    <div class="tabs tabs-boxed">
        <a class="tab" :class="mode === 'regular' && 'tab-active'" @click="mode = 'regular'">Regular</a>
        <a class="tab" :class="mode === 'installment' && 'tab-active'" @click="mode = 'installment'">Parcelamento</a>
    </div>

    <!-- Regular entry form -->
    <form x-show="mode === 'regular'"
          hx-post="{% url 'finances:entry_modal' %}"
          hx-target="#entry-modal-content"
          hx-swap="innerHTML"
          class="space-y-3">
        {% csrf_token %}
        <input type="hidden" name="entry_mode" value="regular">
        {% for field in entry_form %}
        <div class="form-control">
            <label class="label"><span class="label-text">{{ field.label }}</span></label>
            {{ field }}
            {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
        </div>
        {% endfor %}
        <button type="submit" class="btn btn-accent w-full">Salvar</button>
    </form>

    <!-- Installment form -->
    <form x-show="mode === 'installment'"
          hx-post="{% url 'finances:entry_modal' %}"
          hx-target="#entry-modal-content"
          hx-swap="innerHTML"
          class="space-y-3">
        {% csrf_token %}
        <input type="hidden" name="entry_mode" value="installment">
        {% for field in installment_form %}
        <div class="form-control">
            <label class="label"><span class="label-text">{{ field.label }}</span></label>
            {{ field }}
            {% if field.errors %}<span class="text-error text-sm">{{ field.errors.0 }}</span>{% endif %}
        </div>
        {% endfor %}
        <button type="submit" class="btn btn-accent w-full">Criar Parcelamento</button>
    </form>
</div>
```

- [ ] **Step 4: Update URLs**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.entries import EntryModalView

path("entries/modal/", EntryModalView.as_view(), name="entry_modal"),
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_entries.py -v
```

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add modal entry form with installment support"
```

---

## Task 6: Consolidated Views

**Files:**
- Create: `src/backend/finances/views/consolidated.py`
- Create: `src/backend/templates/consolidated/consolidated_page.html`
- Create: `src/backend/templates/consolidated/_consolidated_table.html`
- Create: `src/backend/templates/consolidated/_category_detail.html`
- Create: `src/backend/finances/tests/test_views_consolidated.py`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_views_consolidated.py
import pytest
from datetime import date
from decimal import Decimal

from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def consolidated_data(user):
    cat_food = baker.make("finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300.00"))
    cat_fuel = baker.make("finances.Category", user=user, name="Combustível", budget_ceiling=Decimal("460.00"))
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    # March entries
    baker.make("finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("500.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 10), amount=Decimal("800.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 15), amount=Decimal("200.00"),
               category=cat_fuel, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    # Feb entry
    baker.make("finances.Entry", user=user, date=date(2026, 2, 10), amount=Decimal("100.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 2, 1), entry_type="regular")
    return {"cat_food": cat_food, "cat_fuel": cat_fuel}


@pytest.mark.django_db
class TestConsolidatedView:
    def test_page_renders(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/")
        assert response.status_code == 200
        assert "consolidated_page.html" in [t.name for t in response.templates]

    def test_aggregation_by_category(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026")
        data = response.context["aggregation"]
        # Find Alimentação row
        food_row = next(r for r in data if r["category__name"] == "Alimentação")
        assert food_row["months"][3] == Decimal("1300.00")  # 500 + 800
        assert food_row["months"][2] == Decimal("100.00")

    def test_budget_status(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026")
        data = response.context["aggregation"]
        food_row = next(r for r in data if r["category__name"] == "Alimentação")
        # 1300 / 1300 ceiling = 100% → warning
        assert food_row["budget_status"][3] == "warning"

    def test_systemics_tab(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, name="Custeio", is_system=True)
        pix = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make("finances.Entry", user=user, date=date(2026, 3, 1), amount=Decimal("460.00"),
                   category=cat, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="systemic")
        response = logged_client.get("/consolidated/systemics/?year=2026")
        assert response.status_code == 200

    def test_htmx_returns_fragment(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026", HTTP_HX_REQUEST="true")
        assert "_consolidated_table.html" in [t.name for t in response.templates]


@pytest.mark.django_db
class TestCategoryDetailView:
    def test_detail_returns_entries(self, logged_client, consolidated_data):
        cat_food = consolidated_data["cat_food"]
        response = logged_client.get(
            f"/consolidated/detail/{cat_food.id}/2026/3/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        entries = response.context["entries"]
        assert len(entries) == 2
        assert all(e.category == cat_food for e in entries)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_consolidated.py -v
```

- [ ] **Step 3: Implement consolidated views**

```python
# src/backend/finances/views/consolidated.py
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import ListView, TemplateView

from finances.models import Category, Entry, EntryType
from finances.views.mixins import HtmxLoginRequiredMixin


class ConsolidatedView(HtmxLoginRequiredMixin, TemplateView):
    """Consolidated view of expenses by category, one column per month."""

    template_name = "consolidated/consolidated_page.html"
    htmx_template_name = "consolidated/_consolidated_table.html"
    entry_type_filter = None  # None = diverse (non-systemic), "systemic" = systemics only

    def get_entry_type_filter(self):
        return self.entry_type_filter

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.request.GET.get("year", date.today().year))
        context["current_year"] = year
        context["tab"] = "systemics" if self.entry_type_filter == EntryType.SYSTEMIC else "diverse"
        context["year_range"] = range(2024, date.today().year + 2)

        # Get all entries for the year, grouped by category and month
        entries_qs = Entry.objects.filter(
            user=self.request.user,
            billing_month__year=year,
        )
        if self.entry_type_filter == EntryType.SYSTEMIC:
            entries_qs = entries_qs.filter(entry_type=EntryType.SYSTEMIC)
        else:
            entries_qs = entries_qs.exclude(entry_type=EntryType.SYSTEMIC)

        # Aggregate by category and month
        aggregated = (
            entries_qs.values("category__id", "category__name", "category__budget_ceiling", "billing_month__month")
            .annotate(total=Sum("amount"))
            .order_by("category__name", "billing_month__month")
        )

        # Build rows: one per category with monthly totals
        categories = {}
        for row in aggregated:
            cat_name = row["category__name"]
            if cat_name not in categories:
                categories[cat_name] = {
                    "category__name": cat_name,
                    "category__id": row["category__id"],
                    "budget_ceiling": row["category__budget_ceiling"],
                    "months": {m: Decimal("0") for m in range(1, 13)},
                    "budget_status": {m: "ok" for m in range(1, 13)},
                }
            categories[cat_name]["months"][row["billing_month__month"]] = row["total"]

        # Compute budget status
        for cat in categories.values():
            ceiling = cat["budget_ceiling"]
            if ceiling and ceiling > 0:
                for m in range(1, 13):
                    ratio = cat["months"][m] / ceiling
                    if ratio >= 1:
                        cat["budget_status"][m] = "danger"
                    elif ratio >= Decimal("0.9"):
                        cat["budget_status"][m] = "warning"

        context["aggregation"] = sorted(categories.values(), key=lambda c: c["category__name"])
        context["months"] = list(range(1, 13))

        # Column totals
        context["column_totals"] = {
            m: sum(c["months"][m] for c in categories.values()) for m in range(1, 13)
        }

        return context


class ConsolidatedSystemicsView(ConsolidatedView):
    """Consolidated view filtered to systemic entries only."""

    entry_type_filter = EntryType.SYSTEMIC


class CategoryDetailView(HtmxLoginRequiredMixin, ListView):
    """Expandable detail: individual entries for a category in a month."""

    model = Entry
    template_name = "consolidated/_category_detail.html"
    context_object_name = "entries"

    def get_queryset(self):
        return (
            Entry.objects.filter(
                user=self.request.user,
                category_id=self.kwargs["category_id"],
                billing_month=date(int(self.kwargs["year"]), int(self.kwargs["month"]), 1),
            )
            .select_related("payment_method")
            .order_by("-date")
        )
```

- [ ] **Step 4: Create templates**

Create `src/backend/templates/consolidated/consolidated_page.html`:
```html
{% extends "base.html" %}

{% block title %}Consolidado — {{ current_year }}{% endblock %}

{% block content %}
<div class="flex justify-between items-center mb-4">
    <h2 class="text-2xl font-bold">Consolidado</h2>
    <select class="select select-sm select-bordered"
            onchange="htmx.ajax('GET', '/consolidated/{% if tab == 'systemics' %}systemics/{% endif %}?year=' + this.value, {target: '#consolidated-container', swap: 'innerHTML'})">
        {% for y in year_range %}
        <option value="{{ y }}" {% if y == current_year %}selected{% endif %}>{{ y }}</option>
        {% endfor %}
    </select>
</div>

<!-- Sub-tabs -->
<div class="tabs tabs-bordered mb-4">
    <a class="tab {% if tab == 'diverse' %}tab-active{% endif %}"
       hx-get="{% url 'finances:consolidated' %}?year={{ current_year }}"
       hx-target="#consolidated-container"
       hx-swap="innerHTML">Gastos Diversos</a>
    <a class="tab {% if tab == 'systemics' %}tab-active{% endif %}"
       hx-get="{% url 'finances:consolidated_systemics' %}?year={{ current_year }}"
       hx-target="#consolidated-container"
       hx-swap="innerHTML">Gastos Sistemáticos</a>
</div>

<div id="consolidated-container">
    {% include "consolidated/_consolidated_table.html" %}
</div>
{% endblock %}
```

Create `src/backend/templates/consolidated/_consolidated_table.html`:
```html
<div class="overflow-x-auto">
<table class="table table-sm table-pin-rows">
    <thead>
        <tr>
            <th>Categoria</th>
            {% for m in months %}
            <th class="text-right">{{ m|stringformat:"02d" }}/{{ current_year|stringformat:"d"|truncatechars:2 }}</th>
            {% endfor %}
        </tr>
    </thead>
    <tbody>
        {% load finance_filters %}
        {% for row in aggregation %}
        <tr>
            <td class="font-medium">{{ row.category__name }}</td>
            {% for m in months %}
            <td class="text-right cursor-pointer hover:bg-base-200 {% if row.budget_status|get_item:m == 'danger' %}text-error font-bold{% elif row.budget_status|get_item:m == 'warning' %}text-warning font-bold{% endif %}"
                hx-get="{% url 'finances:category_detail' row.category__id current_year m %}"
                hx-target="#detail-{{ row.category__id }}-{{ m }}"
                hx-swap="innerHTML">
                {% if row.months|get_item:m %}R$ {{ row.months|get_item:m }}{% else %}—{% endif %}
            </td>
            {% endfor %}
        </tr>
        {% for m in months %}
        <tr id="detail-{{ row.category__id }}-{{ m }}" style="display:none;"></tr>
        {% endfor %}
        {% endfor %}
    </tbody>
    <tfoot>
        <tr class="font-bold">
            <td>Total</td>
            {% for m in months %}
            <td class="text-right">R$ {{ column_totals|get_item:m }}</td>
            {% endfor %}
        </tr>
    </tfoot>
</table>
</div>
```

Create `src/backend/templates/consolidated/_category_detail.html`:
```html
<td colspan="13" class="bg-base-200 p-0">
    <table class="table table-xs">
        {% for entry in entries %}
        <tr>
            <td>{{ entry.date|date:"d/m" }}</td>
            <td>{{ entry.description }}</td>
            <td class="text-right">R$ {{ entry.amount }}</td>
            <td>{{ entry.payment_method.name }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="4" class="text-center opacity-60">Sem entradas.</td></tr>
        {% endfor %}
    </table>
</td>
```

- [ ] **Step 5: Create template filter for dict access**

```python
# src/backend/finances/templatetags/__init__.py
```

```python
# src/backend/finances/templatetags/finance_filters.py
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Access dict value by key in templates: {{ dict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""
```

- [ ] **Step 6: Update URLs**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.consolidated import ConsolidatedView, ConsolidatedSystemicsView, CategoryDetailView

# Consolidated
path("consolidated/", ConsolidatedView.as_view(), name="consolidated"),
path("consolidated/systemics/", ConsolidatedSystemicsView.as_view(), name="consolidated_systemics"),
path("consolidated/detail/<uuid:category_id>/<int:year>/<int:month>/",
     CategoryDetailView.as_view(), name="category_detail"),
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_consolidated.py -v
```

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add consolidated views with expandable category detail"
```

---

## Task 7: Settings Page with All Tabs

**Files:**
- Create: `src/backend/finances/views/settings.py`
- Create: `src/backend/templates/settings/settings_page.html`
- Create: `src/backend/templates/settings/_income_tab.html`
- Create: `src/backend/templates/settings/_systemics_tab.html`
- Create: `src/backend/templates/settings/_payment_methods_tab.html`
- Create: `src/backend/templates/settings/_categories_tab.html`
- Create: `src/backend/finances/tests/test_views_settings.py`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_views_settings.py
import pytest
from datetime import date
from decimal import Decimal

from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestSettingsPage:
    def test_settings_page_renders(self, logged_client):
        response = logged_client.get("/settings/")
        assert response.status_code == 200
        assert "settings_page.html" in [t.name for t in response.templates]


@pytest.mark.django_db
class TestIncomeTab:
    def test_income_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/income/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "_income_tab.html" in [t.name for t in response.templates]

    def test_create_income(self, logged_client, user):
        response = logged_client.post(
            "/settings/income/create/",
            data={"name": "Salário", "amount": "7854.23", "month": "2026-03-01", "is_recurring": True},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Income
        assert Income.objects.filter(user=user, name="Salário").exists()

    def test_edit_income(self, logged_client, user):
        income = baker.make("finances.Income", user=user, name="Old", amount=Decimal("100"))
        response = logged_client.post(
            f"/settings/income/{income.id}/edit/",
            data={"name": "Updated", "amount": "200.00", "month": "2026-03-01"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        income.refresh_from_db()
        assert income.name == "Updated"


@pytest.mark.django_db
class TestSystemicsTab:
    def test_systemics_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/systemics/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_systemic(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        response = logged_client.post(
            "/settings/systemics/create/",
            data={"name": "Enel", "category": str(cat.id), "payment_method": str(pm.id), "default_amount": "460.00"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import SystemicExpense
        assert SystemicExpense.objects.filter(user=user, name="Enel").exists()

    def test_toggle_systemic_active(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        systemic = baker.make("finances.SystemicExpense", user=user, category=cat, is_active=True)
        response = logged_client.patch(
            f"/settings/systemics/{systemic.id}/toggle/",
            HTTP_HX_REQUEST="true",
            content_type="application/json",
        )
        assert response.status_code == 200
        systemic.refresh_from_db()
        assert systemic.is_active is False


@pytest.mark.django_db
class TestPaymentMethodsTab:
    def test_pm_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/payment-methods/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_payment_method(self, logged_client, user):
        response = logged_client.post(
            "/settings/payment-methods/create/",
            data={"name": "Crédito Teste", "type": "credit_card", "closing_day": "25"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import PaymentMethod
        assert PaymentMethod.objects.filter(user=user, name="Crédito Teste").exists()

    def test_toggle_pm_active(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, is_active=True)
        response = logged_client.patch(
            f"/settings/payment-methods/{pm.id}/toggle/",
            HTTP_HX_REQUEST="true",
            content_type="application/json",
        )
        assert response.status_code == 200
        pm.refresh_from_db()
        assert pm.is_active is False


@pytest.mark.django_db
class TestCategoriesTab:
    def test_categories_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/categories/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_category(self, logged_client, user):
        response = logged_client.post(
            "/settings/categories/create/",
            data={"name": "Nova Cat", "budget_ceiling": "500.00"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Category
        assert Category.objects.filter(user=user, name="Nova Cat").exists()

    def test_edit_category_budget(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, budget_ceiling=Decimal("100"))
        response = logged_client.post(
            f"/settings/categories/{cat.id}/edit/",
            data={"budget_ceiling": "200.00"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        cat.refresh_from_db()
        assert cat.budget_ceiling == Decimal("200.00")

    def test_cannot_delete_system_category(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, is_system=True)
        response = logged_client.delete(
            f"/settings/categories/{cat.id}/delete/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 400
        from finances.models import Category
        assert Category.objects.filter(id=cat.id).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_settings.py -v
```

- [ ] **Step 3: Implement settings views**

```python
# src/backend/finances/views/settings.py
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.generic import CreateView, TemplateView, UpdateView, View

from finances.forms import (
    CategoryBudgetForm,
    CategoryCreateForm,
    IncomeForm,
    PaymentMethodForm,
    SystemicExpenseForm,
)
from finances.models import Category, Income, PaymentMethod, SystemicExpense
from finances.views.mixins import HtmxLoginRequiredMixin


class SettingsView(HtmxLoginRequiredMixin, TemplateView):
    """Settings page with tabs."""

    template_name = "settings/settings_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.request.GET.get("tab", "income")
        return context


# --- Income ---


class IncomeTabView(HtmxLoginRequiredMixin, TemplateView):
    """Income tab content."""

    template_name = "settings/_income_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["incomes"] = Income.objects.filter(user=self.request.user)
        context["form"] = IncomeForm()
        return context


class IncomeCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = IncomeForm(request.POST)
        if form.is_valid():
            income = form.save(commit=False)
            income.user = request.user
            income.save()
        return self._render_tab(request)

    def _render_tab(self, request):
        context = {
            "incomes": Income.objects.filter(user=request.user),
            "form": IncomeForm(),
        }
        html = render_to_string("settings/_income_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Renda salva!", "type": "success"}}'
        return response


class IncomeUpdateView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        income = Income.objects.filter(user=request.user, pk=pk).first()
        if not income:
            from django.http import Http404
            raise Http404
        form = IncomeForm(request.POST, instance=income)
        if form.is_valid():
            form.save()
        context = {
            "incomes": Income.objects.filter(user=request.user),
            "form": IncomeForm(),
        }
        html = render_to_string("settings/_income_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Renda atualizada!", "type": "success"}}'
        return response


# --- Systemic Expenses ---


class SystemicsTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_systemics_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["systemics"] = SystemicExpense.objects.filter(
            user=self.request.user
        ).select_related("category", "payment_method")
        context["form"] = SystemicExpenseForm(user=self.request.user)
        return context


class SystemicCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = SystemicExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            systemic = form.save(commit=False)
            systemic.user = request.user
            systemic.save()
        return self._render_tab(request)

    def _render_tab(self, request):
        context = {
            "systemics": SystemicExpense.objects.filter(user=request.user).select_related("category", "payment_method"),
            "form": SystemicExpenseForm(user=request.user),
        }
        html = render_to_string("settings/_systemics_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Gasto sistemático salvo!", "type": "success"}}'
        return response


class SystemicEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            from django.http import Http404
            raise Http404
        form = SystemicExpenseForm(request.POST, instance=systemic, user=request.user)
        if form.is_valid():
            form.save()
        return SystemicCreateView._render_tab(SystemicCreateView(), request)


class SystemicToggleView(HtmxLoginRequiredMixin, View):
    def patch(self, request, pk):
        systemic = SystemicExpense.objects.filter(user=request.user, pk=pk).first()
        if not systemic:
            from django.http import Http404
            raise Http404
        systemic.is_active = not systemic.is_active
        systemic.save()
        html = render_to_string(
            "settings/_systemics_tab.html",
            {
                "systemics": SystemicExpense.objects.filter(user=request.user).select_related("category", "payment_method"),
                "form": SystemicExpenseForm(user=request.user),
            },
            request=request,
        )
        response = HttpResponse(html)
        status = "ativado" if systemic.is_active else "desativado"
        response["HX-Trigger"] = f'{{"showToast": {{"message": "{systemic.name} {status}!", "type": "success"}}}}'
        return response


# --- Payment Methods ---


class PaymentMethodsTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_payment_methods_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["payment_methods"] = PaymentMethod.objects.filter(user=self.request.user)
        context["form"] = PaymentMethodForm()
        return context


class PaymentMethodCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = PaymentMethodForm(request.POST)
        if form.is_valid():
            pm = form.save(commit=False)
            pm.user = request.user
            pm.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Forma de pagamento criada!", "type": "success"}}'
        return response


class PaymentMethodEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            from django.http import Http404
            raise Http404
        form = PaymentMethodForm(request.POST, instance=pm)
        if form.is_valid():
            form.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Forma de pagamento atualizada!", "type": "success"}}'
        return response


class PaymentMethodToggleView(HtmxLoginRequiredMixin, View):
    def patch(self, request, pk):
        pm = PaymentMethod.objects.filter(user=request.user, pk=pk).first()
        if not pm:
            from django.http import Http404
            raise Http404
        pm.is_active = not pm.is_active
        pm.save()
        context = {
            "payment_methods": PaymentMethod.objects.filter(user=request.user),
            "form": PaymentMethodForm(),
        }
        html = render_to_string("settings/_payment_methods_tab.html", context, request=request)
        response = HttpResponse(html)
        return response


# --- Categories ---


class CategoriesTabView(HtmxLoginRequiredMixin, TemplateView):
    template_name = "settings/_categories_tab.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.filter(user=self.request.user)
        context["form"] = CategoryCreateForm()
        return context


class CategoryCreateView(HtmxLoginRequiredMixin, View):
    def post(self, request):
        form = CategoryCreateForm(request.POST)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.user = request.user
            cat.save()
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Categoria criada!", "type": "success"}}'
        return response


class CategoryEditView(HtmxLoginRequiredMixin, View):
    def post(self, request, pk):
        cat = Category.objects.filter(user=request.user, pk=pk).first()
        if not cat:
            from django.http import Http404
            raise Http404
        form = CategoryBudgetForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        response = HttpResponse(html)
        response["HX-Trigger"] = '{"showToast": {"message": "Teto atualizado!", "type": "success"}}'
        return response


class CategoryDeleteView(HtmxLoginRequiredMixin, View):
    def delete(self, request, pk):
        cat = Category.objects.filter(user=request.user, pk=pk).first()
        if not cat:
            from django.http import Http404
            raise Http404
        if cat.is_system:
            return HttpResponse(
                '{"error": "Categorias do sistema não podem ser excluídas."}',
                status=400,
                content_type="application/json",
            )
        try:
            cat.delete()
        except Exception:
            return HttpResponse(
                '{"error": "Categoria possui entradas vinculadas."}',
                status=400,
                content_type="application/json",
            )
        context = {
            "categories": Category.objects.filter(user=request.user),
            "form": CategoryCreateForm(),
        }
        html = render_to_string("settings/_categories_tab.html", context, request=request)
        return HttpResponse(html)
```

- [ ] **Step 4: Create settings templates**

Create `src/backend/templates/settings/settings_page.html`:
```html
{% extends "base.html" %}

{% block title %}Configurações{% endblock %}

{% block content %}
<h2 class="text-2xl font-bold mb-4">Configurações</h2>

<div class="tabs tabs-bordered mb-4">
    <a class="tab tab-active" id="tab-income"
       hx-get="{% url 'finances:settings_income' %}"
       hx-target="#settings-content"
       hx-swap="innerHTML"
       @click="document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('tab-active')); this.classList.add('tab-active')">Renda</a>
    <a class="tab" id="tab-systemics"
       hx-get="{% url 'finances:settings_systemics' %}"
       hx-target="#settings-content"
       hx-swap="innerHTML"
       @click="document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('tab-active')); this.classList.add('tab-active')">Gastos Sistemáticos</a>
    <a class="tab" id="tab-pm"
       hx-get="{% url 'finances:settings_payment_methods' %}"
       hx-target="#settings-content"
       hx-swap="innerHTML"
       @click="document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('tab-active')); this.classList.add('tab-active')">Formas de Pagamento</a>
    <a class="tab" id="tab-cats"
       hx-get="{% url 'finances:settings_categories' %}"
       hx-target="#settings-content"
       hx-swap="innerHTML"
       @click="document.querySelectorAll('.tabs .tab').forEach(t => t.classList.remove('tab-active')); this.classList.add('tab-active')">Categorias</a>
</div>

<div id="settings-content"
     hx-get="{% url 'finances:settings_income' %}"
     hx-trigger="load"
     hx-swap="innerHTML">
</div>
{% endblock %}
```

Create `src/backend/templates/settings/_income_tab.html`:
```html
<div class="overflow-x-auto">
<table class="table table-sm">
    <thead>
        <tr><th>Nome</th><th>Valor</th><th>Mês</th><th>Recorrente</th><th></th></tr>
    </thead>
    <tbody>
        {% for income in incomes %}
        <tr>
            <td>{{ income.name }}</td>
            <td>R$ {{ income.amount }}</td>
            <td>{{ income.month|date:"m/Y" }}</td>
            <td>{% if income.is_recurring %}<span class="badge badge-sm badge-accent">Sim</span>{% endif %}</td>
            <td>
                <button class="btn btn-ghost btn-xs"
                        hx-get="{% url 'finances:settings_income_edit' income.id %}"
                        hx-target="#settings-content"
                        hx-swap="innerHTML">✏️</button>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

<!-- Add form -->
<form hx-post="{% url 'finances:settings_income_create' %}"
      hx-target="#settings-content"
      hx-swap="innerHTML"
      class="flex gap-2 mt-4 items-end">
    {% csrf_token %}
    {{ form.name }}
    {{ form.amount }}
    {{ form.month }}
    <label class="flex items-center gap-1"><span class="text-sm">Recorrente</span>{{ form.is_recurring }}</label>
    <button type="submit" class="btn btn-sm btn-accent">Adicionar</button>
</form>
```

Create `src/backend/templates/settings/_systemics_tab.html`:
```html
<div class="overflow-x-auto">
<table class="table table-sm">
    <thead>
        <tr><th>Nome</th><th>Categoria</th><th>Valor Padrão</th><th>Pagamento</th><th>Ativo</th><th></th></tr>
    </thead>
    <tbody>
        {% for s in systemics %}
        <tr>
            <td>{{ s.name }}</td>
            <td><span class="badge badge-sm">{{ s.category.name }}</span></td>
            <td>R$ {{ s.default_amount }}</td>
            <td>{{ s.payment_method.name|default:"—" }}</td>
            <td>
                <input type="checkbox" class="toggle toggle-sm toggle-accent"
                       {% if s.is_active %}checked{% endif %}
                       hx-patch="{% url 'finances:settings_systemic_toggle' s.id %}"
                       hx-target="#settings-content"
                       hx-swap="innerHTML">
            </td>
            <td></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

<form hx-post="{% url 'finances:settings_systemic_create' %}"
      hx-target="#settings-content"
      hx-swap="innerHTML"
      class="flex gap-2 mt-4 items-end">
    {% csrf_token %}
    {{ form.name }}
    {{ form.category }}
    {{ form.default_amount }}
    {{ form.payment_method }}
    <button type="submit" class="btn btn-sm btn-accent">Adicionar</button>
</form>
```

Create `src/backend/templates/settings/_payment_methods_tab.html`:
```html
<div class="overflow-x-auto">
<table class="table table-sm">
    <thead>
        <tr><th>Nome</th><th>Tipo</th><th>Fechamento</th><th>Ativo</th></tr>
    </thead>
    <tbody>
        {% for pm in payment_methods %}
        <tr>
            <td>{{ pm.name }}</td>
            <td><span class="badge badge-sm">{{ pm.get_type_display }}</span></td>
            <td>{% if pm.closing_day %}Dia {{ pm.closing_day }}{% else %}—{% endif %}</td>
            <td>
                <input type="checkbox" class="toggle toggle-sm toggle-accent"
                       {% if pm.is_active %}checked{% endif %}
                       hx-patch="{% url 'finances:settings_pm_toggle' pm.id %}"
                       hx-target="#settings-content"
                       hx-swap="innerHTML">
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

<form hx-post="{% url 'finances:settings_pm_create' %}"
      hx-target="#settings-content"
      hx-swap="innerHTML"
      class="flex gap-2 mt-4 items-end">
    {% csrf_token %}
    {{ form.name }}
    {{ form.type }}
    {{ form.closing_day }}
    <button type="submit" class="btn btn-sm btn-accent">Adicionar</button>
</form>
```

Create `src/backend/templates/settings/_categories_tab.html`:
```html
<div class="overflow-x-auto">
<table class="table table-sm">
    <thead>
        <tr><th>Nome</th><th>Teto</th><th>Sistema</th><th></th></tr>
    </thead>
    <tbody>
        {% for cat in categories %}
        <tr>
            <td>{{ cat.name }}</td>
            <td>
                <form hx-post="{% url 'finances:settings_cat_edit' cat.id %}"
                      hx-target="#settings-content"
                      hx-swap="innerHTML"
                      class="flex gap-1 items-center">
                    {% csrf_token %}
                    <input type="number" name="budget_ceiling" value="{{ cat.budget_ceiling }}" step="0.01"
                           class="input input-bordered input-xs w-24"
                           hx-trigger="change"
                           hx-post="{% url 'finances:settings_cat_edit' cat.id %}"
                           hx-include="closest form"
                           hx-target="#settings-content"
                           hx-swap="innerHTML">
                </form>
            </td>
            <td>{% if cat.is_system %}<span class="badge badge-sm">🔒</span>{% endif %}</td>
            <td>
                {% if not cat.is_system %}
                <button class="btn btn-ghost btn-xs text-error"
                        hx-delete="{% url 'finances:settings_cat_delete' cat.id %}"
                        hx-target="#settings-content"
                        hx-swap="innerHTML"
                        hx-confirm="Excluir categoria {{ cat.name }}?">🗑️</button>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

<form hx-post="{% url 'finances:settings_cat_create' %}"
      hx-target="#settings-content"
      hx-swap="innerHTML"
      class="flex gap-2 mt-4 items-end">
    {% csrf_token %}
    {{ form.name }}
    {{ form.budget_ceiling }}
    <button type="submit" class="btn btn-sm btn-accent">Adicionar</button>
</form>
```

- [ ] **Step 5: Update URLs with all settings routes**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.settings import (
    SettingsView, IncomeTabView, IncomeCreateView, IncomeUpdateView,
    SystemicsTabView, SystemicCreateView, SystemicEditView, SystemicToggleView,
    PaymentMethodsTabView, PaymentMethodCreateView, PaymentMethodEditView, PaymentMethodToggleView,
    CategoriesTabView, CategoryCreateView, CategoryEditView, CategoryDeleteView,
)

# Settings
path("settings/", SettingsView.as_view(), name="settings"),
path("settings/income/", IncomeTabView.as_view(), name="settings_income"),
path("settings/income/create/", IncomeCreateView.as_view(), name="settings_income_create"),
path("settings/income/<uuid:pk>/edit/", IncomeUpdateView.as_view(), name="settings_income_edit"),
path("settings/systemics/", SystemicsTabView.as_view(), name="settings_systemics"),
path("settings/systemics/create/", SystemicCreateView.as_view(), name="settings_systemic_create"),
path("settings/systemics/<uuid:pk>/edit/", SystemicEditView.as_view(), name="settings_systemic_edit"),
path("settings/systemics/<uuid:pk>/toggle/", SystemicToggleView.as_view(), name="settings_systemic_toggle"),
path("settings/payment-methods/", PaymentMethodsTabView.as_view(), name="settings_payment_methods"),
path("settings/payment-methods/create/", PaymentMethodCreateView.as_view(), name="settings_pm_create"),
path("settings/payment-methods/<uuid:pk>/edit/", PaymentMethodEditView.as_view(), name="settings_pm_edit"),
path("settings/payment-methods/<uuid:pk>/toggle/", PaymentMethodToggleView.as_view(), name="settings_pm_toggle"),
path("settings/categories/", CategoriesTabView.as_view(), name="settings_categories"),
path("settings/categories/create/", CategoryCreateView.as_view(), name="settings_cat_create"),
path("settings/categories/<uuid:pk>/edit/", CategoryEditView.as_view(), name="settings_cat_edit"),
path("settings/categories/<uuid:pk>/delete/", CategoryDeleteView.as_view(), name="settings_cat_delete"),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_settings.py -v
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add settings page with income, systemics, payment methods, and categories tabs"
```

---

## Task 8: BDD Feature Specs for Views

**Files:**
- Create: `src/backend/finances/tests/features/views.feature`
- Create: `src/backend/finances/tests/features/test_views.py`

- [ ] **Step 1: Write feature file**

```gherkin
# src/backend/finances/tests/features/views.feature
Feature: Expense tracker views
  As a user managing personal finances
  I want to view, create, and edit entries through the web interface

  Scenario: View entries for a specific month
    Given a logged-in user with entries in March 2026
    When I visit the entries page for March 2026
    Then I should see only March entries
    And I should see a summary with total expenses

  Scenario: Create entry via inline form
    Given a logged-in user with categories and payment methods
    When I submit an inline entry for "Supermercado" with amount 150.00
    Then the entry should be created
    And the entry should appear in the table

  Scenario: Create installment via modal
    Given a logged-in user with a credit card closing on day 25
    When I create a 3-installment plan for R$ 600.00
    Then 3 installment entries should be created
    And the first billing month should be the computed month

  Scenario: View consolidated expenses by category
    Given a logged-in user with entries in multiple categories
    When I visit the consolidated page for 2026
    Then I should see category totals per month
    And categories over budget should be highlighted

  Scenario: Change category budget in settings
    Given a logged-in user with a category "Alimentação" with ceiling 1300
    When I change the budget ceiling to 1500
    Then the ceiling should be updated to 1500
```

- [ ] **Step 2: Write step definitions**

```python
# src/backend/finances/tests/features/test_views.py
import pytest
from datetime import date
from decimal import Decimal

from django.test import Client
from model_bakery import baker
from pytest_bdd import given, when, then, scenario, parsers


@scenario("views.feature", "View entries for a specific month")
def test_view_entries_for_month():
    pass


@scenario("views.feature", "Create entry via inline form")
def test_create_entry_inline():
    pass


@scenario("views.feature", "Create installment via modal")
def test_create_installment():
    pass


@scenario("views.feature", "View consolidated expenses by category")
def test_view_consolidated():
    pass


@scenario("views.feature", "Change category budget in settings")
def test_change_budget():
    pass


@pytest.fixture
def ctx():
    return {}


@given("a logged-in user with entries in March 2026", target_fixture="ctx")
def given_user_with_march_entries(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300"))
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("100"),
               category=cat, payment_method=pm, billing_month=date(2026, 3, 1))
    baker.make("finances.Entry", user=user, date=date(2026, 3, 15), amount=Decimal("200"),
               category=cat, payment_method=pm, billing_month=date(2026, 3, 1))
    baker.make("finances.Entry", user=user, date=date(2026, 2, 10), amount=Decimal("50"),
               category=cat, payment_method=pm, billing_month=date(2026, 2, 1))
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with categories and payment methods", target_fixture="ctx")
def given_user_with_cats_pms(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with a credit card closing on day 25", target_fixture="ctx")
def given_user_with_cc(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name="Trabalho")
    pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=25)
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with entries in multiple categories", target_fixture="ctx")
def given_user_with_multi_cat(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat1 = baker.make("finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300"))
    cat2 = baker.make("finances.Category", user=user, name="Combustível", budget_ceiling=Decimal("460"))
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("1400"),
               category=cat1, payment_method=pm, billing_month=date(2026, 3, 1))
    baker.make("finances.Entry", user=user, date=date(2026, 3, 10), amount=Decimal("200"),
               category=cat2, payment_method=pm, billing_month=date(2026, 3, 1))
    ctx.update({"user": user, "client": client, "cat1": cat1, "cat2": cat2})
    return ctx


@given(parsers.parse('a logged-in user with a category "{name}" with ceiling {ceiling:d}'), target_fixture="ctx")
def given_user_with_category(db, name, ceiling, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name=name, budget_ceiling=Decimal(str(ceiling)))
    ctx.update({"user": user, "client": client, "category": cat})
    return ctx


@when("I visit the entries page for March 2026")
def when_visit_entries(ctx):
    ctx["response"] = ctx["client"].get("/entries/2026/3/")


@then("I should see only March entries")
def then_see_march_entries(ctx):
    entries = ctx["response"].context["entries"]
    assert len(entries) == 2
    assert all(e.billing_month.month == 3 for e in entries)


@then("I should see a summary with total expenses")
def then_see_summary(ctx):
    summary = ctx["response"].context["summary"]
    assert summary["total_expenses"] == Decimal("300")
    assert summary["entry_count"] == 2


@when(parsers.parse('I submit an inline entry for "{desc}" with amount {amount}'))
def when_submit_inline(ctx, desc, amount):
    ctx["response"] = ctx["client"].post(
        "/entries/create/",
        data={
            "date": "2026-03-15",
            "amount": amount,
            "description": desc,
            "category": str(ctx["category"].id),
            "payment_method": str(ctx["pm"].id),
        },
        HTTP_HX_REQUEST="true",
    )


@then("the entry should be created")
def then_entry_created(ctx):
    from finances.models import Entry
    assert Entry.objects.filter(user=ctx["user"]).exists()


@then("the entry should appear in the table")
def then_entry_in_table(ctx):
    assert ctx["response"].status_code == 200


@when(parsers.parse("I create a {count:d}-installment plan for R$ {total}"))
def when_create_installment(ctx, count, total):
    total_decimal = Decimal(total)
    installment = (total_decimal / count).quantize(Decimal("0.01"))
    ctx["response"] = ctx["client"].post(
        "/entries/modal/",
        data={
            "entry_mode": "installment",
            "date": "2026-03-15",
            "description": "Test plan",
            "category": str(ctx["category"].id),
            "payment_method": str(ctx["pm"].id),
            "total_amount": str(total_decimal),
            "num_installments": str(count),
            "installment_amount": str(installment),
        },
        HTTP_HX_REQUEST="true",
    )


@then(parsers.parse("{count:d} installment entries should be created"))
def then_installment_entries(ctx, count):
    from finances.models import Entry
    assert Entry.objects.filter(user=ctx["user"], entry_type="installment").count() == count


@then("the first billing month should be the computed month")
def then_first_billing_month(ctx):
    from finances.models import Entry
    first = Entry.objects.filter(user=ctx["user"], entry_type="installment").order_by("billing_month").first()
    # March 15 with closing day 25 → March (15 <= 25)
    assert first.billing_month == date(2026, 3, 1)


@when(parsers.parse("I visit the consolidated page for {year:d}"))
def when_visit_consolidated(ctx, year):
    ctx["response"] = ctx["client"].get(f"/consolidated/?year={year}")


@then("I should see category totals per month")
def then_see_category_totals(ctx):
    data = ctx["response"].context["aggregation"]
    assert len(data) >= 2


@then("categories over budget should be highlighted")
def then_over_budget_highlighted(ctx):
    data = ctx["response"].context["aggregation"]
    food = next(r for r in data if r["category__name"] == "Alimentação")
    assert food["budget_status"][3] == "danger"


@when(parsers.parse("I change the budget ceiling to {new_ceiling:d}"))
def when_change_ceiling(ctx, new_ceiling):
    ctx["response"] = ctx["client"].post(
        f"/settings/categories/{ctx['category'].id}/edit/",
        data={"budget_ceiling": str(new_ceiling)},
        HTTP_HX_REQUEST="true",
    )


@then(parsers.parse("the ceiling should be updated to {expected:d}"))
def then_ceiling_updated(ctx, expected):
    ctx["category"].refresh_from_db()
    assert ctx["category"].budget_ceiling == Decimal(str(expected))
```

- [ ] **Step 3: Run BDD tests**

```bash
uv run pytest src/backend/finances/tests/features/test_views.py -v
```

- [ ] **Step 4: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "test(finances): add BDD specs for entries, consolidated, and settings views"
```

---

## Task 9: Final Validation

**Files:** None new — validation only.

- [ ] **Step 1: Run full lint**

```bash
uv run ruff check src/backend/ --fix
uv run ruff format src/backend/
```

- [ ] **Step 2: Run full test suite with coverage**

```bash
uv run coverage run -m pytest src/backend/ -v
uv run coverage report --fail-under=80
```

Expected: all tests pass, coverage >= 80%.

- [ ] **Step 3: Django checks**

```bash
uv run python src/backend/manage.py check
uv run python src/backend/manage.py makemigrations --check --dry-run
```

- [ ] **Step 4: Commit any remaining fixes**

```bash
git add -u
git commit -m "chore: fix lint and formatting from final validation"
```

- [ ] **Step 5: Run Tailwind build to verify templates work**

```bash
uv run python src/backend/manage.py tailwind build
```
