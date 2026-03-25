# Sub-Project 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the expense tracker project using the project generator, add Docker Compose with Postgres + Redis, implement all core financial data models with full TDD coverage, configure Django Admin, and establish CI pipeline.

**Architecture:** Monolithic Django 6 app scaffolded from the project generator template. The `finances` app holds all financial models (Category, PaymentMethod, Income, Entry, InstallmentPlan, SystemicExpense) with a billing month computation service. Models use UUID primary keys and user FK for future multi-tenancy. Docker Compose provides Postgres 16 + Redis 7 for local dev.

**Tech Stack:** Django 6, PostgreSQL 16, Redis 7, uv, pytest + pytest-django + pytest-bdd + model-bakery, Ruff, TailwindCSS v4 + DaisyUI, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-03-25-expense-tracker-design.md`

---

## File Map

### Files from Project Generator (copied + adapted)

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Dependencies, tool configs (pytest, ruff, coverage) |
| `.pre-commit-config.yaml` | Ruff, django-upgrade, test + coverage hooks |
| `.coveragerc` | Coverage config (80% threshold) |
| `.gitignore` | Ignore patterns |
| `.env.example` | Environment variable template |
| `src/backend/config/settings.py` | Django settings (Postgres, Redis, i18n) |
| `src/backend/config/urls.py` | URL routing |
| `src/backend/core/models.py` | CustomUser (AbstractUser) |
| `src/backend/core/admin.py` | User admin |

### New Files

| File | Responsibility |
|------|---------------|
| `docker-compose.yml` | Postgres 16 + Redis 7 containers |
| `src/backend/finances/__init__.py` | App module |
| `src/backend/finances/apps.py` | App config |
| `src/backend/finances/models/__init__.py` | Model exports |
| `src/backend/finances/models/category.py` | Category model |
| `src/backend/finances/models/payment_method.py` | PaymentMethod model |
| `src/backend/finances/models/income.py` | Income model |
| `src/backend/finances/models/entry.py` | Entry model |
| `src/backend/finances/models/installment_plan.py` | InstallmentPlan model + child entry generation |
| `src/backend/finances/models/systemic_expense.py` | SystemicExpense model |
| `src/backend/finances/services/__init__.py` | Services module |
| `src/backend/finances/services/billing.py` | Billing month computation |
| `src/backend/finances/admin.py` | Admin registration for all models |
| `src/backend/finances/migrations/__init__.py` | Migrations package |
| `src/backend/finances/tests/__init__.py` | Tests package |
| `src/backend/finances/tests/conftest.py` | Shared test fixtures |
| `src/backend/finances/tests/test_category.py` | Category model tests |
| `src/backend/finances/tests/test_payment_method.py` | PaymentMethod model tests |
| `src/backend/finances/tests/test_income.py` | Income model tests |
| `src/backend/finances/tests/test_billing.py` | Billing service tests |
| `src/backend/finances/tests/test_entry.py` | Entry model tests |
| `src/backend/finances/tests/test_systemic_expense.py` | SystemicExpense model tests |
| `src/backend/finances/tests/test_installment_plan.py` | InstallmentPlan model tests |
| `src/backend/finances/tests/features/billing_cycle.feature` | BDD spec: billing cycle behavior |
| `src/backend/finances/tests/features/installments.feature` | BDD spec: installment behavior |
| `src/backend/finances/tests/features/test_billing_cycle.py` | BDD step definitions: billing |
| `src/backend/finances/tests/features/test_installments.py` | BDD step definitions: installments |
| `src/backend/finances/management/__init__.py` | Management module |
| `src/backend/finances/management/commands/__init__.py` | Commands module |
| `src/backend/finances/management/commands/seed_data.py` | Load initial categories + payment methods |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |

---

## Task 1: Generate Project Scaffold

**Files:**
- Create: `docs/.ai/specs/expense_tracker_spec.yaml`
- Modify: multiple files from generator output
- Remove: `src/backend/pages/` directory, landing page templates

- [ ] **Step 1: Create spec YAML for the generator**

```yaml
# docs/.ai/specs/expense_tracker_spec.yaml
project:
  name: "Expense Tracker"
  slug: "expense-tracker"
  language: "pt-br"
  timezone: "America/Sao_Paulo"

professional:
  name: "Expense Tracker"
  title: "Personal Finance Manager"

brand:
  daisyui_theme: "light"

sections:
  hero: false
  about: false
  services: false
  testimonials: false
  contact: false
  cta: false
```

- [ ] **Step 2: Run the project generator**

```bash
bash /home/bessa/Documents/trabalhos/project_generator/scripts/generate.sh \
  docs/.ai/specs/expense_tracker_spec.yaml \
  /tmp/expense-tracker-scaffold
```

Expected: scaffold created at `/tmp/expense-tracker-scaffold/`

- [ ] **Step 3: Copy scaffold files into project root**

Copy everything from the generated scaffold into the project root, preserving existing `docs/` directory:

```bash
# Copy all non-docs files from scaffold
cp -r /tmp/expense-tracker-scaffold/pyproject.toml .
cp -r /tmp/expense-tracker-scaffold/.pre-commit-config.yaml .
cp -r /tmp/expense-tracker-scaffold/.coveragerc .
cp -r /tmp/expense-tracker-scaffold/.env.example .
cp -r /tmp/expense-tracker-scaffold/.python-version .
cp -r /tmp/expense-tracker-scaffold/src .
# Don't copy .gitignore — we already have one, merge manually if needed
```

- [ ] **Step 4: Remove landing page artifacts**

```bash
rm -rf src/backend/pages
rm -rf src/backend/templates/partials
rm -rf src/backend/templates/pages
rm -f src/backend/templates/base.html
rm -rf src/backend/.django_tailwind_cli
rm -rf src/backend/assets
rm -rf src/backend/static/css/tailwind.css
```

- [ ] **Step 5: Create minimal static directory with Tailwind source**

```bash
mkdir -p src/backend/static/css src/backend/static/js src/backend/static/images
```

```css
/* src/backend/static/css/tailwind.css */
@import "tailwindcss";
@plugin "daisyui";
```

- [ ] **Step 6: Update settings.py**

Replace `src/backend/config/settings.py` with adapted version. Key changes: remove `pages` from INSTALLED_APPS, add `finances`, configure Postgres via env var, add i18n config.

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Environment
DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-change-me-in-production")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "http://localhost:8000").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_tailwind_cli",
    # Local apps
    "core",
    "finances",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "core.CustomUser"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "expense_tracker"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# TailwindCSS v4 + DaisyUI
TAILWIND_CLI_USE_DAISY_UI = True
TAILWIND_CLI_SRC_CSS = "static/css/tailwind.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
```

- [ ] **Step 7: Update urls.py**

```python
# src/backend/config/urls.py
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

- [ ] **Step 8: Update pyproject.toml**

Add new dependencies and update isort config:

```toml
[project]
name = "expense-tracker"
version = "0.1.0"
description = "Personal expense tracking system with AI assistant"
requires-python = ">=3.12"
dependencies = [
    "django>=6.0",
    "django-tailwind-cli>=4.5.1",
    "whitenoise>=6.12.0",
    "psycopg[binary]>=3.2",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
pythonpath = ["src/backend"]
testpaths = ["src/backend"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]

[dependency-groups]
dev = [
    "coverage>=7.13.4",
    "pre-commit>=4.5.1",
    "pytest>=9.0.2",
    "pytest-django>=4.12.0",
    "pytest-bdd>=8.0",
    "model-bakery>=1.20",
    "ruff>=0.15.4",
]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src/backend"]

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
    "DJ",  # flake8-django
    "S",   # flake8-bandit
]
ignore = [
    "S101",  # allow assert in tests
]

[tool.ruff.lint.per-file-ignores]
"*/migrations/*" = ["E501"]
"*/tests/*" = ["S106"]

[tool.ruff.lint.isort]
known-first-party = ["config", "core", "finances"]

[tool.ruff.format]
quote-style = "double"
```

- [ ] **Step 9: Update .gitignore**

Append Docker and project-specific entries to existing `.gitignore`:

```
# Docker
docker-compose.override.yml

# Superpowers
.superpowers/

# Django
db.sqlite3
src/backend/staticfiles/
src/backend/mediafiles/
*.log

# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
*.egg-info/

# Environment
.env
.env.local
.env.*.local

# IDE
.vscode/
.idea/
*.swp

# Coverage
htmlcov/
.coverage
.coverage.*

# Tools
.pytest_cache/
.ruff_cache/
.django_tailwind_cli/
```

- [ ] **Step 10: Install dependencies and verify**

```bash
uv sync
uv run ruff check src/backend/ --fix
```

Expected: dependencies installed, no lint errors (or only fixable ones from generated code).

- [ ] **Step 11: Commit scaffold**

```bash
git add -A
git commit -m "feat: scaffold project from generator

Generate base Django project from project_generator template.
Remove landing page artifacts (pages app, partials).
Configure PostgreSQL, add finances to INSTALLED_APPS,
update dependencies for expense tracker needs."
```

---

## Task 2: Docker Compose + Database Setup

**Files:**
- Create: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: expense_tracker
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

- [ ] **Step 2: Update .env.example**

```bash
# Django Settings
SECRET_KEY=django-insecure-change-me-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Database (Docker Compose defaults)
POSTGRES_DB=expense_tracker
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

- [ ] **Step 3: Start containers**

```bash
docker compose up -d
```

Expected: Postgres and Redis running.

- [ ] **Step 4: Create .env from example**

```bash
cp .env.example .env
```

- [ ] **Step 5: Run initial migration and verify database connection**

```bash
uv run python src/backend/manage.py migrate
```

Expected: all Django default migrations applied to Postgres.

- [ ] **Step 6: Verify Django starts**

```bash
uv run python src/backend/manage.py check
```

Expected: `System check identified no issues.`

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "infra: add Docker Compose with Postgres 16 and Redis 7"
```

---

## Task 3: Create Finances App Skeleton + Test Fixtures

**Files:**
- Create: `src/backend/finances/` (app directory)
- Create: `src/backend/finances/tests/conftest.py`

- [ ] **Step 1: Create the finances app**

```bash
cd src/backend && uv run python manage.py startapp finances && cd ../..
```

- [ ] **Step 2: Convert models.py to models package**

```bash
rm src/backend/finances/models.py
mkdir -p src/backend/finances/models
touch src/backend/finances/models/__init__.py
```

- [ ] **Step 3: Create services directory**

```bash
mkdir -p src/backend/finances/services
touch src/backend/finances/services/__init__.py
```

- [ ] **Step 4: Create tests directory structure**

```bash
rm src/backend/finances/tests.py
mkdir -p src/backend/finances/tests/features
touch src/backend/finances/tests/__init__.py
touch src/backend/finances/tests/features/__init__.py
```

- [ ] **Step 5: Create management command directory**

```bash
mkdir -p src/backend/finances/management/commands
touch src/backend/finances/management/__init__.py
touch src/backend/finances/management/commands/__init__.py
```

- [ ] **Step 6: Update apps.py**

```python
# src/backend/finances/apps.py
from django.apps import AppConfig


class FinancesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finances"
    verbose_name = "Finanças"
```

- [ ] **Step 7: Create stub model files for all models**

Django needs all FK targets to exist before `makemigrations` can resolve references. Create stub files now; they'll be fleshed out in subsequent tasks.

```python
# src/backend/finances/models/category.py
# Stub — implemented in Task 4
```

```python
# src/backend/finances/models/payment_method.py
# Stub — implemented in Task 5
```

```python
# src/backend/finances/models/income.py
# Stub — implemented in Task 6
```

```python
# src/backend/finances/models/entry.py
# Stub — implemented in Task 8
```

```python
# src/backend/finances/models/installment_plan.py
# Stub — implemented in Task 10
```

```python
# src/backend/finances/models/systemic_expense.py
# Stub — implemented in Task 9
```

- [ ] **Step 8: Create shared test fixtures (conftest.py)**

```python
# src/backend/finances/tests/conftest.py
import pytest
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    return baker.make("core.CustomUser", username="amanda")
```

- [ ] **Step 9: Verify app loads**

```bash
uv run python src/backend/manage.py check
```

Expected: `System check identified no issues.`

- [ ] **Step 10: Commit**

```bash
git add src/backend/finances/
git commit -m "feat: create finances app skeleton with models package and test structure"
```

---

## Task 4: Category Model (TDD)

**Files:**
- Create: `src/backend/finances/models/category.py`
- Create: `src/backend/finances/tests/test_category.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_category.py
import pytest
from django.db import IntegrityError
from model_bakery import baker


@pytest.mark.django_db
class TestCategory:
    def test_create_category(self, user):
        category = baker.make(
            "finances.Category",
            user=user,
            name="Alimentação",
            budget_ceiling=1300,
        )
        assert category.name == "Alimentação"
        assert category.budget_ceiling == 1300
        assert category.is_system is False
        assert category.user == user
        assert category.id is not None
        assert category.historical_avg is None
        assert category.quarterly_avg is None

    def test_str_returns_name(self, user):
        category = baker.make("finances.Category", user=user, name="Lanche")
        assert str(category) == "Lanche"

    def test_unique_name_per_user(self, user):
        baker.make("finances.Category", user=user, name="Alimentação")
        with pytest.raises(IntegrityError):
            baker.make("finances.Category", user=user, name="Alimentação")

    def test_same_name_different_users(self, user, other_user):
        baker.make("finances.Category", user=user, name="Alimentação")
        cat2 = baker.make("finances.Category", user=other_user, name="Alimentação")
        assert cat2.name == "Alimentação"

    def test_system_category_not_deletable(self, user):
        """System categories raise ProtectedError when deleted."""
        category = baker.make("finances.Category", user=user, name="Custeio", is_system=True)
        with pytest.raises(Exception):
            category.delete()

    def test_ordering_by_name(self, user):
        baker.make("finances.Category", user=user, name="Lanche")
        baker.make("finances.Category", user=user, name="Alimentação")
        baker.make("finances.Category", user=user, name="Álcool")
        from finances.models import Category

        names = list(Category.objects.filter(user=user).values_list("name", flat=True))
        assert names == sorted(names)

    def test_default_budget_ceiling_is_zero(self, user):
        from finances.models import Category

        category = Category.objects.create(user=user, name="Nova")
        assert category.budget_ceiling == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_category.py -v
```

Expected: FAIL — `finances.Category` model does not exist yet.

- [ ] **Step 3: Implement Category model**

```python
# src/backend/finances/models/category.py
import uuid

from django.conf import settings
from django.db import models


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    budget_ceiling = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    historical_avg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Média histórica (computada a partir das entradas)",
    )
    quarterly_avg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Média dos últimos 3 meses (computada a partir das entradas)",
    )
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise models.ProtectedError(
                "Categorias do sistema não podem ser excluídas.",
                set(),
            )
        return super().delete(*args, **kwargs)
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category

__all__ = ["Category"]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_category.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add Category model with unique name per user and system protection"
```

---

## Task 5: PaymentMethod Model (TDD)

**Files:**
- Create: `src/backend/finances/models/payment_method.py`
- Create: `src/backend/finances/tests/test_payment_method.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_payment_method.py
import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestPaymentMethod:
    def test_create_pix(self, user):
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Pix",
            type="pix",
        )
        assert pm.name == "Pix"
        assert pm.type == "pix"
        assert pm.closing_day is None
        assert pm.is_active is True

    def test_create_credit_card_with_closing_day(self, user):
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Crédito Santander",
            type="credit_card",
            closing_day=30,
        )
        assert pm.closing_day == 30
        assert pm.type == "credit_card"

    def test_str_returns_name(self, user):
        pm = baker.make("finances.PaymentMethod", user=user, name="Crédito C6")
        assert str(pm) == "Crédito C6"

    def test_closing_day_null_for_non_credit(self, user):
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Dinheiro",
            type="cash",
            closing_day=None,
        )
        assert pm.closing_day is None

    def test_payment_type_choices(self):
        from finances.models.payment_method import PaymentType

        assert PaymentType.CASH == "cash"
        assert PaymentType.PIX == "pix"
        assert PaymentType.CREDIT_CARD == "credit_card"

    def test_soft_delete_via_is_active(self, user):
        pm = baker.make("finances.PaymentMethod", user=user, is_active=True)
        pm.is_active = False
        pm.save()
        pm.refresh_from_db()
        assert pm.is_active is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_payment_method.py -v
```

Expected: FAIL — model does not exist.

- [ ] **Step 3: Implement PaymentMethod model**

```python
# src/backend/finances/models/payment_method.py
import uuid

from django.conf import settings
from django.db import models


class PaymentType(models.TextChoices):
    CASH = "cash", "Dinheiro"
    PIX = "pix", "Pix"
    CREDIT_CARD = "credit_card", "Cartão de Crédito"


class PaymentMethod(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_methods",
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=PaymentType.choices)
    closing_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Dia de fechamento da fatura (apenas cartão de crédito)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "forma de pagamento"
        verbose_name_plural = "formas de pagamento"
        ordering = ["name"]

    def __str__(self):
        return self.name
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category
from finances.models.payment_method import PaymentMethod, PaymentType

__all__ = ["Category", "PaymentMethod", "PaymentType"]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_payment_method.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add PaymentMethod model with type choices and closing day"
```

---

## Task 6: Income Model (TDD)

**Files:**
- Create: `src/backend/finances/models/income.py`
- Create: `src/backend/finances/tests/test_income.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_income.py
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker


@pytest.mark.django_db
class TestIncome:
    def test_create_one_time_income(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="13°",
            amount=Decimal("3998.74"),
            month=date(2025, 12, 1),
            is_recurring=False,
        )
        assert income.name == "13°"
        assert income.amount == Decimal("3998.74")
        assert income.month == date(2025, 12, 1)
        assert income.is_recurring is False

    def test_create_recurring_income(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Salário",
            amount=Decimal("7854.23"),
            month=date(2026, 3, 1),
            is_recurring=True,
            recurrence_start=date(2026, 1, 1),
            recurrence_end=None,
        )
        assert income.is_recurring is True
        assert income.recurrence_start == date(2026, 1, 1)
        assert income.recurrence_end is None

    def test_str_returns_name_and_month(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Salário",
            month=date(2026, 3, 1),
        )
        assert "Salário" in str(income)
        assert "2026-03" in str(income)

    def test_recurring_with_bounded_period(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Bolsa PIBID",
            amount=Decimal("2000.00"),
            month=date(2025, 11, 1),
            is_recurring=True,
            recurrence_start=date(2025, 11, 1),
            recurrence_end=date(2026, 10, 1),
        )
        assert income.recurrence_end == date(2026, 10, 1)

    def test_ordering_by_month_desc(self, user):
        baker.make("finances.Income", user=user, month=date(2026, 1, 1), name="Jan")
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), name="Mar")
        baker.make("finances.Income", user=user, month=date(2026, 2, 1), name="Fev")
        from finances.models import Income

        names = list(Income.objects.filter(user=user).values_list("name", flat=True))
        assert names == ["Mar", "Fev", "Jan"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_income.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement Income model**

```python
# src/backend/finances/models/income.py
import uuid

from django.conf import settings
from django.db import models


class Income(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="incomes",
    )
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    month = models.DateField(help_text="Primeiro dia do mês aplicável")
    is_recurring = models.BooleanField(default=False)
    recurrence_start = models.DateField(null=True, blank=True)
    recurrence_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "renda"
        verbose_name_plural = "rendas"
        ordering = ["-month", "name"]

    def __str__(self):
        return f"{self.name} — {self.month:%Y-%m}"
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category
from finances.models.income import Income
from finances.models.payment_method import PaymentMethod, PaymentType

__all__ = ["Category", "Income", "PaymentMethod", "PaymentType"]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_income.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add Income model with recurring support"
```

---

## Task 7: Billing Month Service (TDD)

**Files:**
- Create: `src/backend/finances/services/billing.py`
- Create: `src/backend/finances/tests/test_billing.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_billing.py
from datetime import date

import pytest

from finances.services.billing import compute_billing_month


class TestComputeBillingMonth:
    def test_pix_same_month(self):
        result = compute_billing_month(date(2026, 3, 15), "pix", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_cash_same_month(self):
        result = compute_billing_month(date(2026, 3, 28), "cash", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_credit_card_before_closing_day(self):
        """Purchase on day 20, closing day 25 → same month."""
        result = compute_billing_month(date(2026, 3, 20), "credit_card", closing_day=25)
        assert result == date(2026, 3, 1)

    def test_credit_card_on_closing_day(self):
        """Purchase on closing day → same month."""
        result = compute_billing_month(date(2026, 3, 25), "credit_card", closing_day=25)
        assert result == date(2026, 3, 1)

    def test_credit_card_after_closing_day(self):
        """Purchase on day 26, closing day 25 → next month."""
        result = compute_billing_month(date(2026, 3, 26), "credit_card", closing_day=25)
        assert result == date(2026, 4, 1)

    def test_credit_card_after_closing_december(self):
        """Purchase after closing in December → January next year."""
        result = compute_billing_month(date(2025, 12, 31), "credit_card", closing_day=25)
        assert result == date(2026, 1, 1)

    def test_credit_card_closing_day_30_february(self):
        """Purchase on Feb 28 (which is < 30) → same month."""
        result = compute_billing_month(date(2026, 2, 28), "credit_card", closing_day=30)
        assert result == date(2026, 2, 1)

    def test_credit_card_no_closing_day_fallback(self):
        """Credit card with no closing day → same month (defensive)."""
        result = compute_billing_month(date(2026, 3, 15), "credit_card", closing_day=None)
        assert result == date(2026, 3, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_billing.py -v
```

Expected: FAIL — `ImportError: cannot import name 'compute_billing_month'`.

- [ ] **Step 3: Implement billing service**

```python
# src/backend/finances/services/billing.py
from datetime import date


def compute_billing_month(
    entry_date: date,
    payment_type: str,
    closing_day: int | None,
) -> date:
    """Compute which month an expense entry belongs to for billing purposes.

    Rules:
    - Non-credit-card or no closing day: entry belongs to its calendar month.
    - Credit card with closing day: if entry_date.day > closing_day, belongs to next month.
    """
    first_of_month = entry_date.replace(day=1)

    if payment_type != "credit_card" or closing_day is None:
        return first_of_month

    if entry_date.day > closing_day:
        if entry_date.month == 12:
            return date(entry_date.year + 1, 1, 1)
        return date(entry_date.year, entry_date.month + 1, 1)

    return first_of_month
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_billing.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/services/ src/backend/finances/tests/test_billing.py
git commit -m "feat(finances): add billing month computation service"
```

---

## Task 8: Entry Model (TDD)

**Files:**
- Create: `src/backend/finances/models/entry.py`
- Create: `src/backend/finances/tests/test_entry.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_entry.py
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker

from finances.models.entry import EntryType


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Alimentação")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.fixture
def credit_card(user):
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito Santander",
        type="credit_card",
        closing_day=30,
    )


@pytest.fixture
def credit_card_c6(user):
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )


@pytest.mark.django_db
class TestEntry:
    def test_create_regular_entry(self, user, category, pix):
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 1),
            amount=Decimal("42.00"),
            description="Heineken - bebida",
            category=category,
            payment_method=pix,
            entry_type=EntryType.REGULAR,
        )
        assert entry.amount == Decimal("42.00")
        assert entry.entry_type == EntryType.REGULAR

    def test_str_returns_description_and_amount(self, user, category, pix):
        entry = baker.make(
            "finances.Entry",
            user=user,
            description="Supermercado Cosmos",
            amount=Decimal("119.61"),
            category=category,
            payment_method=pix,
        )
        result = str(entry)
        assert "Supermercado Cosmos" in result
        assert "119.61" in result

    def test_negative_amount_is_refund(self, user, category, pix):
        entry = baker.make(
            "finances.Entry",
            user=user,
            amount=Decimal("-226.21"),
            description="Google Cloud - estorno",
            category=category,
            payment_method=pix,
        )
        assert entry.amount < 0

    def test_billing_month_computed_on_save_pix(self, user, category, pix):
        from finances.models import Entry

        entry = Entry(
            user=user,
            date=date(2026, 3, 15),
            amount=Decimal("50.00"),
            description="Test",
            category=category,
            payment_method=pix,
            entry_type=EntryType.REGULAR,
        )
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_billing_month_credit_card_before_closing(self, user, category, credit_card_c6):
        from finances.models import Entry

        entry = Entry(
            user=user,
            date=date(2026, 3, 20),
            amount=Decimal("50.00"),
            description="Test",
            category=category,
            payment_method=credit_card_c6,
            entry_type=EntryType.REGULAR,
        )
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_billing_month_credit_card_after_closing(self, user, category, credit_card_c6):
        from finances.models import Entry

        entry = Entry(
            user=user,
            date=date(2026, 3, 26),
            amount=Decimal("50.00"),
            description="Test",
            category=category,
            payment_method=credit_card_c6,
            entry_type=EntryType.REGULAR,
        )
        entry.save()
        assert entry.billing_month == date(2026, 4, 1)

    def test_billing_month_override_preserved(self, user, category, credit_card_c6):
        from finances.models import Entry

        entry = Entry(
            user=user,
            date=date(2026, 3, 26),
            amount=Decimal("50.00"),
            description="Test",
            category=category,
            payment_method=credit_card_c6,
            entry_type=EntryType.REGULAR,
            billing_month=date(2026, 3, 1),
            billing_month_override=True,
        )
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_ordering_by_date_desc(self, user, category, pix):
        from finances.models import Entry

        baker.make("finances.Entry", user=user, date=date(2026, 3, 1), category=category, payment_method=pix)
        baker.make("finances.Entry", user=user, date=date(2026, 3, 15), category=category, payment_method=pix)
        baker.make("finances.Entry", user=user, date=date(2026, 3, 10), category=category, payment_method=pix)

        dates = list(Entry.objects.filter(user=user).values_list("date", flat=True))
        assert dates == sorted(dates, reverse=True)

    def test_entry_type_choices(self):
        assert EntryType.REGULAR == "regular"
        assert EntryType.INSTALLMENT == "installment"
        assert EntryType.SYSTEMIC == "systemic"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_entry.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement Entry model**

```python
# src/backend/finances/models/entry.py
import uuid

from django.conf import settings
from django.db import models

from finances.services.billing import compute_billing_month


class EntryType(models.TextChoices):
    REGULAR = "regular", "Regular"
    INSTALLMENT = "installment", "Parcela"
    SYSTEMIC = "systemic", "Sistemático"


class Entry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=500)
    category = models.ForeignKey(
        "finances.Category",
        on_delete=models.PROTECT,
        related_name="entries",
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod",
        on_delete=models.PROTECT,
        related_name="entries",
    )
    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices,
        default=EntryType.REGULAR,
    )
    billing_month = models.DateField(
        help_text="Mês de contabilização (primeiro dia do mês)",
    )
    billing_month_override = models.BooleanField(default=False)
    installment_plan = models.ForeignKey(
        "finances.InstallmentPlan",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entries",
    )
    systemic_expense = models.ForeignKey(
        "finances.SystemicExpense",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "entrada"
        verbose_name_plural = "entradas"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.description} — R$ {self.amount}"

    def save(self, *args, **kwargs):
        if not self.billing_month_override:
            self.billing_month = compute_billing_month(
                self.date,
                self.payment_method.type,
                self.payment_method.closing_day,
            )
        super().save(*args, **kwargs)
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category
from finances.models.entry import Entry, EntryType
from finances.models.income import Income
from finances.models.payment_method import PaymentMethod, PaymentType

__all__ = ["Category", "Entry", "EntryType", "Income", "PaymentMethod", "PaymentType"]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_entry.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add Entry model with automatic billing month computation"
```

---

## Task 9: SystemicExpense Model (TDD)

**Files:**
- Create: `src/backend/finances/models/systemic_expense.py`
- Create: `src/backend/finances/tests/test_systemic_expense.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_systemic_expense.py
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Custeio", is_system=True)


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestSystemicExpense:
    def test_create_systemic_expense(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Enel",
            category=category,
            payment_method=pix,
            default_amount=Decimal("460.00"),
        )
        assert systemic.name == "Enel"
        assert systemic.default_amount == Decimal("460.00")
        assert systemic.is_active is True

    def test_str_returns_name(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Unimed - Amanda",
            category=category,
            payment_method=pix,
        )
        assert str(systemic) == "Unimed - Amanda"

    def test_nullable_payment_method(self, user, category):
        from finances.models import SystemicExpense

        systemic = SystemicExpense.objects.create(
            user=user,
            name="IPVA",
            category=category,
            payment_method=None,
            default_amount=Decimal("500.00"),
        )
        assert systemic.payment_method is None

    def test_deactivate(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            category=category,
            payment_method=pix,
            is_active=True,
        )
        systemic.is_active = False
        systemic.save()
        systemic.refresh_from_db()
        assert systemic.is_active is False

    def test_generate_monthly_entry(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Brisanet",
            category=category,
            payment_method=pix,
            default_amount=Decimal("104.12"),
        )
        entry = systemic.create_monthly_entry(
            month=date(2026, 3, 1),
            amount=Decimal("104.12"),
        )
        assert entry.entry_type == "systemic"
        assert entry.systemic_expense == systemic
        assert entry.billing_month == date(2026, 3, 1)
        assert entry.amount == Decimal("104.12")
        assert entry.description == "Brisanet"

    def test_generate_monthly_entry_custom_amount(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Enel",
            category=category,
            payment_method=pix,
            default_amount=Decimal("460.00"),
        )
        entry = systemic.create_monthly_entry(
            month=date(2026, 3, 1),
            amount=Decimal("1096.21"),
        )
        assert entry.amount == Decimal("1096.21")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_systemic_expense.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement SystemicExpense model**

```python
# src/backend/finances/models/systemic_expense.py
import uuid
from datetime import date as date_type

from django.conf import settings
from django.db import models


class SystemicExpense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="systemic_expenses",
    )
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        "finances.Category",
        on_delete=models.PROTECT,
        related_name="systemic_expenses",
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="systemic_expenses",
    )
    default_amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "gasto sistemático"
        verbose_name_plural = "gastos sistemáticos"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def create_monthly_entry(
        self,
        month: date_type,
        amount: "models.DecimalField | None" = None,
        payment_method: "models.ForeignKey | None" = None,
    ) -> "Entry":
        from finances.models.entry import Entry, EntryType

        return Entry.objects.create(
            user=self.user,
            date=month,
            amount=amount if amount is not None else self.default_amount,
            description=self.name,
            category=self.category,
            payment_method=payment_method or self.payment_method,
            entry_type=EntryType.SYSTEMIC,
            billing_month=month,
            billing_month_override=True,
            systemic_expense=self,
        )
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category
from finances.models.entry import Entry, EntryType
from finances.models.income import Income
from finances.models.payment_method import PaymentMethod, PaymentType
from finances.models.systemic_expense import SystemicExpense

__all__ = [
    "Category",
    "Entry",
    "EntryType",
    "Income",
    "PaymentMethod",
    "PaymentType",
    "SystemicExpense",
]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_systemic_expense.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add SystemicExpense model with monthly entry generation"
```

---

## Task 10: InstallmentPlan Model (TDD)

**Files:**
- Create: `src/backend/finances/models/installment_plan.py`
- Create: `src/backend/finances/tests/test_installment_plan.py`
- Modify: `src/backend/finances/models/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_installment_plan.py
import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker

from finances.models import Entry, EntryType


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Trabalho")


@pytest.fixture
def credit_card(user):
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito Santander",
        type="credit_card",
        closing_day=30,
    )


@pytest.fixture
def credit_card_c6(user):
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )


@pytest.mark.django_db
class TestInstallmentPlan:
    def test_create_plan(self, user, category, credit_card):
        plan = baker.make(
            "finances.InstallmentPlan",
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("6699.00"),
            num_installments=12,
            installment_amount=Decimal("558.25"),
        )
        assert plan.total_amount == Decimal("6699.00")
        assert plan.num_installments == 12

    def test_str_returns_description_and_installments(self, user, category, credit_card):
        plan = baker.make(
            "finances.InstallmentPlan",
            user=user,
            description="notebook",
            num_installments=12,
            category=category,
            payment_method=credit_card,
        )
        result = str(plan)
        assert "notebook" in result
        assert "12x" in result

    def test_generate_entries_creates_correct_count(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("6699.00"),
            num_installments=12,
            installment_amount=Decimal("558.25"),
        )
        entries = plan.generate_entries()
        assert len(entries) == 12

    def test_generated_entries_are_installment_type(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("6699.00"),
            num_installments=12,
            installment_amount=Decimal("558.25"),
        )
        entries = plan.generate_entries()
        assert all(e.entry_type == EntryType.INSTALLMENT for e in entries)
        assert all(e.installment_plan == plan for e in entries)

    def test_generated_entries_have_sequential_billing_months(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("600.00"),
            num_installments=3,
            installment_amount=Decimal("200.00"),
        )
        entries = plan.generate_entries()
        billing_months = [e.billing_month for e in entries]
        assert billing_months == [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]

    def test_generated_entries_descriptions_numbered(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("600.00"),
            num_installments=3,
            installment_amount=Decimal("200.00"),
        )
        entries = plan.generate_entries()
        assert entries[0].description == "notebook (1/3)"
        assert entries[1].description == "notebook (2/3)"
        assert entries[2].description == "notebook (3/3)"

    def test_rounding_remainder_on_last_installment(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2026, 1, 1),
            description="colchão",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("100.00"),
            num_installments=3,
            installment_amount=Decimal("33.33"),
        )
        entries = plan.generate_entries()
        assert entries[0].amount == Decimal("33.33")
        assert entries[1].amount == Decimal("33.33")
        assert entries[2].amount == Decimal("33.34")
        total = sum(e.amount for e in entries)
        assert total == Decimal("100.00")

    def test_billing_month_respects_closing_day(self, user, category, credit_card_c6):
        """Purchase on March 26, C6 closing day 25 → first billing month is April."""
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2026, 3, 26),
            description="tênis",
            category=category,
            payment_method=credit_card_c6,
            total_amount=Decimal("300.00"),
            num_installments=2,
            installment_amount=Decimal("150.00"),
        )
        entries = plan.generate_entries()
        assert entries[0].billing_month == date(2026, 4, 1)
        assert entries[1].billing_month == date(2026, 5, 1)

    def test_entries_persisted_to_database(self, user, category, credit_card):
        from finances.models import InstallmentPlan

        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2025, 12, 1),
            description="notebook",
            category=category,
            payment_method=credit_card,
            total_amount=Decimal("600.00"),
            num_installments=3,
            installment_amount=Decimal("200.00"),
        )
        plan.generate_entries()
        assert Entry.objects.filter(installment_plan=plan).count() == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_installment_plan.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement InstallmentPlan model**

```python
# src/backend/finances/models/installment_plan.py
import uuid
from datetime import date

from django.conf import settings
from django.db import models

from finances.services.billing import compute_billing_month


class InstallmentPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="installment_plans",
    )
    date = models.DateField()
    description = models.CharField(max_length=500)
    category = models.ForeignKey(
        "finances.Category",
        on_delete=models.PROTECT,
        related_name="installment_plans",
    )
    payment_method = models.ForeignKey(
        "finances.PaymentMethod",
        on_delete=models.PROTECT,
        related_name="installment_plans",
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    num_installments = models.PositiveIntegerField()
    installment_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "parcelamento"
        verbose_name_plural = "parcelamentos"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.description} ({self.num_installments}x)"

    def generate_entries(self) -> list:
        from finances.models.entry import Entry, EntryType

        billing_month = compute_billing_month(
            self.date,
            self.payment_method.type,
            self.payment_method.closing_day,
        )

        entries = []
        for i in range(self.num_installments):
            if i == self.num_installments - 1:
                amount = self.total_amount - (
                    self.installment_amount * (self.num_installments - 1)
                )
            else:
                amount = self.installment_amount

            entry = Entry(
                user=self.user,
                date=self.date,
                amount=amount,
                description=f"{self.description} ({i + 1}/{self.num_installments})",
                category=self.category,
                payment_method=self.payment_method,
                entry_type=EntryType.INSTALLMENT,
                billing_month=billing_month,
                billing_month_override=True,
                installment_plan=self,
            )
            entries.append(entry)

            # Advance billing month
            if billing_month.month == 12:
                billing_month = date(billing_month.year + 1, 1, 1)
            else:
                billing_month = date(billing_month.year, billing_month.month + 1, 1)

        Entry.objects.bulk_create(entries)
        return list(Entry.objects.filter(installment_plan=self).order_by("billing_month"))
```

```python
# src/backend/finances/models/__init__.py
from finances.models.category import Category
from finances.models.entry import Entry, EntryType
from finances.models.income import Income
from finances.models.installment_plan import InstallmentPlan
from finances.models.payment_method import PaymentMethod, PaymentType
from finances.models.systemic_expense import SystemicExpense

__all__ = [
    "Category",
    "Entry",
    "EntryType",
    "Income",
    "InstallmentPlan",
    "PaymentMethod",
    "PaymentType",
    "SystemicExpense",
]
```

- [ ] **Step 4: Create migration and run tests**

```bash
uv run python src/backend/manage.py makemigrations finances
uv run pytest src/backend/finances/tests/test_installment_plan.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest src/backend/ -v
```

Expected: all tests across all test files pass (Category: 7, PaymentMethod: 6, Income: 5, Billing: 8, Entry: 10, SystemicExpense: 6, InstallmentPlan: 9 = ~51 tests).

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances/
git commit -m "feat(finances): add InstallmentPlan model with child entry generation and rounding"
```

---

## Task 11: BDD Feature Specs

**Files:**
- Create: `src/backend/finances/tests/features/billing_cycle.feature`
- Create: `src/backend/finances/tests/features/installments.feature`
- Create: `src/backend/finances/tests/features/test_billing_cycle.py`
- Create: `src/backend/finances/tests/features/test_installments.py`

- [ ] **Step 1: Write billing cycle feature file**

```gherkin
# src/backend/finances/tests/features/billing_cycle.feature
Feature: Billing cycle computation
  As a user with credit cards
  I want expenses to be assigned to the correct billing month
  Based on the credit card closing day

  Scenario: Pix purchase stays in current month
    Given a user with payment method "Pix" of type "pix"
    When I create an expense on "2026-03-15" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: Credit card purchase before closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-20" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: Credit card purchase after closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-26" with that payment method
    Then the billing month should be "2026-04-01"

  Scenario: Credit card purchase on closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-25" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: December purchase after closing rolls to January
    Given a user with a credit card closing on day 25
    When I create an expense on "2025-12-31" with that payment method
    Then the billing month should be "2026-01-01"
```

- [ ] **Step 2: Write installments feature file**

```gherkin
# src/backend/finances/tests/features/installments.feature
Feature: Installment plan management
  As a user making installment purchases
  I want the system to generate individual entries for each installment
  So I can track monthly payments correctly

  Scenario: Create a 3-installment plan
    Given a user with a credit card closing on day 30
    And a category "Trabalho"
    When I create an installment plan for R$ 600.00 in 3 installments
    Then 3 entries should be created
    And each entry should have amount R$ 200.00
    And entries should have sequential billing months

  Scenario: Rounding remainder goes to last installment
    Given a user with a credit card closing on day 30
    And a category "Casa"
    When I create an installment plan for R$ 100.00 in 3 installments at R$ 33.33 each
    Then the last entry should have amount R$ 33.34
    And the total of all entries should equal R$ 100.00
```

- [ ] **Step 3: Implement step definitions for billing cycle**

```python
# src/backend/finances/tests/features/test_billing_cycle.py
import pytest
from datetime import date, datetime
from decimal import Decimal

from model_bakery import baker
from pytest_bdd import given, when, then, scenario, parsers

from finances.models import Entry, EntryType


@scenario("billing_cycle.feature", "Pix purchase stays in current month")
def test_pix_stays_in_current_month():
    pass


@scenario("billing_cycle.feature", "Credit card purchase before closing day")
def test_credit_before_closing():
    pass


@scenario("billing_cycle.feature", "Credit card purchase after closing day")
def test_credit_after_closing():
    pass


@scenario("billing_cycle.feature", "Credit card purchase on closing day")
def test_credit_on_closing():
    pass


@scenario("billing_cycle.feature", "December purchase after closing rolls to January")
def test_december_rolls_to_january():
    pass


@pytest.fixture
def context():
    return {}


@given(parsers.parse('a user with payment method "{name}" of type "{pm_type}"'), target_fixture="context")
def given_user_with_payment_method(db, name, pm_type, context):
    user = baker.make("core.CustomUser")
    pm = baker.make("finances.PaymentMethod", user=user, name=name, type=pm_type)
    category = baker.make("finances.Category", user=user, name="Test")
    context["user"] = user
    context["payment_method"] = pm
    context["category"] = category
    return context


@given(parsers.parse("a user with a credit card closing on day {day:d}"), target_fixture="context")
def given_user_with_credit_card(db, day, context):
    user = baker.make("core.CustomUser")
    pm = baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Cartão Teste",
        type="credit_card",
        closing_day=day,
    )
    category = baker.make("finances.Category", user=user, name="Test")
    context["user"] = user
    context["payment_method"] = pm
    context["category"] = category
    return context


@when(parsers.parse('I create an expense on "{date_str}" with that payment method'))
def when_create_expense(context, date_str):
    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    entry = Entry.objects.create(
        user=context["user"],
        date=entry_date,
        amount=Decimal("100.00"),
        description="Test expense",
        category=context["category"],
        payment_method=context["payment_method"],
        entry_type=EntryType.REGULAR,
    )
    context["entry"] = entry


@then(parsers.parse('the billing month should be "{expected_str}"'))
def then_billing_month_is(context, expected_str):
    expected = datetime.strptime(expected_str, "%Y-%m-%d").date()
    assert context["entry"].billing_month == expected
```

- [ ] **Step 4: Implement step definitions for installments**

```python
# src/backend/finances/tests/features/test_installments.py
import pytest
from datetime import date, datetime
from decimal import Decimal

from model_bakery import baker
from pytest_bdd import given, when, then, scenario, parsers

from finances.models import Entry, InstallmentPlan


@scenario("installments.feature", "Create a 3-installment plan")
def test_create_3_installment_plan():
    pass


@scenario("installments.feature", "Rounding remainder goes to last installment")
def test_rounding_remainder():
    pass


@pytest.fixture
def context():
    return {}


@given(parsers.parse("a user with a credit card closing on day {day:d}"), target_fixture="context")
def given_user_with_credit_card(db, day, context):
    user = baker.make("core.CustomUser")
    pm = baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Cartão",
        type="credit_card",
        closing_day=day,
    )
    context["user"] = user
    context["payment_method"] = pm
    return context


@given(parsers.parse('a category "{name}"'))
def given_category(context, name):
    category = baker.make("finances.Category", user=context["user"], name=name)
    context["category"] = category


@when(parsers.parse("I create an installment plan for R$ {total} in {count:d} installments"))
def when_create_plan_even(context, total, count):
    total_decimal = Decimal(total)
    installment = (total_decimal / count).quantize(Decimal("0.01"))
    plan = InstallmentPlan.objects.create(
        user=context["user"],
        date=date(2026, 3, 1),
        description="Test plan",
        category=context["category"],
        payment_method=context["payment_method"],
        total_amount=total_decimal,
        num_installments=count,
        installment_amount=installment,
    )
    context["plan"] = plan
    context["entries"] = plan.generate_entries()


@when(
    parsers.parse(
        "I create an installment plan for R$ {total} in {count:d} installments at R$ {each} each"
    )
)
def when_create_plan_with_amount(context, total, count, each):
    plan = InstallmentPlan.objects.create(
        user=context["user"],
        date=date(2026, 3, 1),
        description="Test plan",
        category=context["category"],
        payment_method=context["payment_method"],
        total_amount=Decimal(total),
        num_installments=count,
        installment_amount=Decimal(each),
    )
    context["plan"] = plan
    context["entries"] = plan.generate_entries()


@then(parsers.parse("{count:d} entries should be created"))
def then_entry_count(context, count):
    assert len(context["entries"]) == count


@then(parsers.parse("each entry should have amount R$ {amount}"))
def then_each_amount(context, amount):
    expected = Decimal(amount)
    assert all(e.amount == expected for e in context["entries"])


@then("entries should have sequential billing months")
def then_sequential_months(context):
    months = [e.billing_month for e in context["entries"]]
    for i in range(1, len(months)):
        prev, curr = months[i - 1], months[i]
        if prev.month == 12:
            assert curr == date(prev.year + 1, 1, 1)
        else:
            assert curr == date(prev.year, prev.month + 1, 1)


@then(parsers.parse("the last entry should have amount R$ {amount}"))
def then_last_amount(context, amount):
    assert context["entries"][-1].amount == Decimal(amount)


@then(parsers.parse("the total of all entries should equal R$ {total}"))
def then_total_equals(context, total):
    actual_total = sum(e.amount for e in context["entries"])
    assert actual_total == Decimal(total)
```

- [ ] **Step 5: Run BDD tests**

```bash
uv run pytest src/backend/finances/tests/features/ -v
```

Expected: all 7 BDD scenarios pass.

- [ ] **Step 6: Commit**

```bash
git add src/backend/finances/tests/features/
git commit -m "test(finances): add BDD specs for billing cycle and installment behavior"
```

---

## Task 12: Django Admin Configuration

**Files:**
- Modify: `src/backend/finances/admin.py`

- [ ] **Step 1: Write admin tests**

```python
# src/backend/finances/tests/test_admin.py
import pytest
from django.contrib.admin.sites import AdminSite

from finances.admin import (
    CategoryAdmin,
    EntryAdmin,
    IncomeAdmin,
    InstallmentPlanAdmin,
    PaymentMethodAdmin,
    SystemicExpenseAdmin,
)
from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


class TestAdminRegistration:
    def test_category_admin_registered(self):
        admin = CategoryAdmin(Category, AdminSite())
        assert "name" in admin.list_display
        assert "budget_ceiling" in admin.list_display

    def test_payment_method_admin_registered(self):
        admin = PaymentMethodAdmin(PaymentMethod, AdminSite())
        assert "name" in admin.list_display
        assert "type" in admin.list_display

    def test_entry_admin_registered(self):
        admin = EntryAdmin(Entry, AdminSite())
        assert "date" in admin.list_display
        assert "description" in admin.list_display
        assert "amount" in admin.list_display

    def test_income_admin_registered(self):
        admin = IncomeAdmin(Income, AdminSite())
        assert "name" in admin.list_display

    def test_installment_plan_admin_registered(self):
        admin = InstallmentPlanAdmin(InstallmentPlan, AdminSite())
        assert "description" in admin.list_display

    def test_systemic_expense_admin_registered(self):
        admin = SystemicExpenseAdmin(SystemicExpense, AdminSite())
        assert "name" in admin.list_display
```

- [ ] **Step 2: Implement admin configuration**

```python
# src/backend/finances/admin.py
from django.contrib import admin

from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "budget_ceiling", "is_system", "user")
    list_filter = ("is_system", "user")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "closing_day", "is_active", "user")
    list_filter = ("type", "is_active", "user")
    search_fields = ("name",)


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "month", "is_recurring", "user")
    list_filter = ("is_recurring", "user", "month")
    search_fields = ("name",)
    ordering = ("-month",)


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "description",
        "amount",
        "category",
        "payment_method",
        "entry_type",
        "billing_month",
    )
    list_filter = ("entry_type", "category", "payment_method", "billing_month")
    search_fields = ("description",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "total_amount",
        "num_installments",
        "installment_amount",
        "payment_method",
        "date",
    )
    list_filter = ("payment_method", "category")
    search_fields = ("description",)
    ordering = ("-date",)


@admin.register(SystemicExpense)
class SystemicExpenseAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "default_amount", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name",)
    ordering = ("name",)
```

- [ ] **Step 3: Run admin tests**

```bash
uv run pytest src/backend/finances/tests/test_admin.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/backend/finances/admin.py src/backend/finances/tests/test_admin.py
git commit -m "feat(finances): configure Django Admin for all financial models"
```

---

## Task 13: Seed Data Management Command

**Files:**
- Create: `src/backend/finances/management/commands/seed_data.py`
- Create: `src/backend/finances/tests/test_seed_data.py`

- [ ] **Step 1: Write failing test**

```python
# src/backend/finances/tests/test_seed_data.py
import pytest
from django.core.management import call_command

from finances.models import Category, PaymentMethod


@pytest.mark.django_db
class TestSeedData:
    def test_creates_default_categories(self, user):
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.filter(user=user).count() == 26

    def test_creates_default_payment_methods(self, user):
        call_command("seed_data", f"--user={user.username}")
        assert PaymentMethod.objects.filter(user=user).count() == 6

    def test_categories_include_system_categories(self, user):
        call_command("seed_data", f"--user={user.username}")
        system_cats = Category.objects.filter(user=user, is_system=True)
        names = set(system_cats.values_list("name", flat=True))
        assert "Custeio" in names
        assert "Financiamentos" in names

    def test_payment_methods_include_credit_cards_with_closing_days(self, user):
        call_command("seed_data", f"--user={user.username}")
        santander = PaymentMethod.objects.get(user=user, name="Crédito Santander")
        assert santander.closing_day == 30
        assert santander.type == "credit_card"

    def test_idempotent_does_not_duplicate(self, user):
        call_command("seed_data", f"--user={user.username}")
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.filter(user=user).count() == 26
        assert PaymentMethod.objects.filter(user=user).count() == 6
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_seed_data.py -v
```

Expected: FAIL — command does not exist.

- [ ] **Step 3: Implement seed_data command**

```python
# src/backend/finances/management/commands/seed_data.py
from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import CustomUser
from finances.models import Category, PaymentMethod


CATEGORIES = [
    ("Alimentação", Decimal("1300.00"), False),
    ("Lanche", Decimal("438.90"), False),
    ("Lazer", Decimal("567.87"), False),
    ("Combustível", Decimal("460.00"), False),
    ("Álcool", Decimal("511.00"), False),
    ("Higiene", Decimal("100.00"), False),
    ("Limpeza", Decimal("100.00"), False),
    ("Farmácia", Decimal("300.00"), False),
    ("Serviços", Decimal("240.00"), False),
    ("Pets", Decimal("250.00"), False),
    ("Saúde", Decimal("360.00"), False),
    ("Casa", Decimal("100.00"), False),
    ("Trabalho", Decimal("100.00"), False),
    ("Educação", Decimal("100.00"), False),
    ("Escritório", Decimal("100.00"), False),
    ("Perfumaria", Decimal("100.00"), False),
    ("Roupa", Decimal("100.00"), False),
    ("Carro", Decimal("140.00"), False),
    ("Estética", Decimal("100.00"), False),
    ("Esporte", Decimal("100.00"), False),
    ("Viagem", Decimal("100.00"), False),
    ("Transporte", Decimal("100.00"), False),
    ("Dívida", Decimal("100.00"), False),
    ("Outros", Decimal("100.00"), False),
    ("Custeio", Decimal("2000.00"), True),
    ("Financiamentos", Decimal("1000.00"), True),
]

PAYMENT_METHODS = [
    ("Dinheiro", "cash", None),
    ("Pix", "pix", None),
    ("Crédito BB - Afonso", "credit_card", 25),
    ("Crédito Santander", "credit_card", 30),
    ("Crédito Nubank", "credit_card", 30),
    ("Crédito C6", "credit_card", 25),
]


class Command(BaseCommand):
    help = "Seed initial categories and payment methods for a user"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, required=True, help="Username to seed data for")

    def handle(self, *args, **options):
        username = options["user"]
        user = CustomUser.objects.get(username=username)

        cat_created = 0
        for name, ceiling, is_system in CATEGORIES:
            _, created = Category.objects.get_or_create(
                user=user,
                name=name,
                defaults={"budget_ceiling": ceiling, "is_system": is_system},
            )
            if created:
                cat_created += 1

        pm_created = 0
        for name, pm_type, closing_day in PAYMENT_METHODS:
            _, created = PaymentMethod.objects.get_or_create(
                user=user,
                name=name,
                defaults={"type": pm_type, "closing_day": closing_day},
            )
            if created:
                pm_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {cat_created} categories and {pm_created} payment methods for {username}"
            )
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_seed_data.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/management/ src/backend/finances/tests/test_seed_data.py
git commit -m "feat(finances): add seed_data management command with 26 categories and 6 payment methods"
```

---

## Task 14: CI Pipeline + Final Validation

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create GitHub Actions workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: expense_tracker_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      POSTGRES_DB: expense_tracker_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      SECRET_KEY: test-secret-key
      DEBUG: "true"

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync

      - name: Lint
        run: uv run ruff check src/backend/

      - name: Format check
        run: uv run ruff format --check src/backend/

      - name: Run tests with coverage
        run: |
          uv run coverage run -m pytest src/backend/ -v
          uv run coverage report --fail-under=80

      - name: Django system check
        run: uv run python src/backend/manage.py check
```

- [ ] **Step 2: Run full lint**

```bash
uv run ruff check src/backend/ --fix
uv run ruff format src/backend/
```

Expected: no errors after fixes.

- [ ] **Step 3: Run full test suite with coverage**

```bash
uv run coverage run -m pytest src/backend/ -v
uv run coverage report --fail-under=80
```

Expected: all tests pass, coverage >= 80%.

- [ ] **Step 4: Run Django checks**

```bash
uv run python src/backend/manage.py check
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: no issues, no pending migrations.

- [ ] **Step 5: Commit CI and any remaining fixes**

```bash
git add .github/ && git add -u
git commit -m "ci: add GitHub Actions workflow with lint, test, and coverage gates"
```

- [ ] **Step 6: Final summary commit (if any accumulated fixes)**

Run `git status` to check for uncommitted changes. If clean, skip. If not, commit remaining fixes:

```bash
git add -u
git commit -m "chore: fix lint and formatting issues from CI validation"
```
