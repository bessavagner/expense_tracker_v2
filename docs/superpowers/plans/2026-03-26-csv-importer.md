# Sub-Project 3: CSV Importer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 4-step HTMX wizard to import regular entries and installment plans from Google Sheets CSV exports, with auto-detected column mapping, conflict resolution, and duplicate warnings.

**Architecture:** Pure parsing functions in `csv_parser.py` (testable without Django). Wizard views in `importer.py` store state in Django session between steps. Bulk import within a single transaction. Templates follow the existing HTMX fragment pattern (HtmxMixin).

**Tech Stack:** Django 6, HTMX, DaisyUI, Python csv module, pytest + pytest-bdd + model-bakery.

**Spec:** `docs/superpowers/specs/2026-03-26-csv-importer-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/finances/services/csv_parser.py` | Pure functions: parse_amount, parse_date, detect_columns, parse_csv_rows |
| `src/backend/finances/views/importer.py` | Wizard views: ImportUploadView, ImportMappingView, ImportPreviewView, ImportExecuteView |
| `src/backend/templates/importer/import_page.html` | Full page (extends base) with wizard step container |
| `src/backend/templates/importer/_step_upload.html` | Step 1: file upload + type selector |
| `src/backend/templates/importer/_step_mapping.html` | Step 2: column mapping review |
| `src/backend/templates/importer/_step_preview.html` | Step 3: preview table with warnings |
| `src/backend/templates/importer/_step_result.html` | Step 4: success summary |
| `src/backend/finances/tests/test_csv_parser.py` | Unit tests for parsing functions |
| `src/backend/finances/tests/test_views_importer.py` | View tests for wizard flow |
| `src/backend/finances/tests/features/import.feature` | BDD spec |
| `src/backend/finances/tests/features/test_import.py` | BDD step definitions |

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/finances/urls.py` | Add import URL patterns |
| `src/backend/finances/views/__init__.py` | Export importer views |
| `src/backend/templates/partials/_navbar.html` | Add Importar nav link |

---

## Task 1: CSV Parser — Pure Functions (TDD)

**Files:**
- Create: `src/backend/finances/services/csv_parser.py`
- Create: `src/backend/finances/tests/test_csv_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_csv_parser.py
import io
from datetime import date
from decimal import Decimal

import pytest

from finances.services.csv_parser import (
    detect_columns,
    parse_amount,
    parse_csv_rows,
    parse_date,
)


class TestParseAmount:
    def test_with_r_prefix(self):
        assert parse_amount("R$ 42,00") == Decimal("42.00")

    def test_with_thousand_separator(self):
        assert parse_amount("R$ 1.300,00") == Decimal("1300.00")

    def test_negative(self):
        assert parse_amount("-R$ 226,21") == Decimal("-226.21")

    def test_no_prefix(self):
        assert parse_amount("30,5") == Decimal("30.50")

    def test_no_prefix_integer(self):
        assert parse_amount("100") == Decimal("100")

    def test_whitespace(self):
        assert parse_amount("  R$  42,00  ") == Decimal("42.00")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_amount("")

    def test_non_numeric(self):
        with pytest.raises(ValueError):
            parse_amount("abc")


class TestParseDate:
    def test_standard_format(self):
        assert parse_date("01/03/2026") == date(2026, 3, 1)

    def test_single_digit_day(self):
        assert parse_date("1/3/2026") == date(2026, 3, 1)

    def test_invalid_date(self):
        with pytest.raises(ValueError):
            parse_date("32/13/2026")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_date("")


class TestDetectColumns:
    def test_regular_entries_headers(self):
        headers = ["data", "valor", "descrição", "categoria", "forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping == {
            "date": 0,
            "amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
        }

    def test_installment_headers(self):
        headers = ["data", "valor", "descrição", "categoria", "forma", "parcelas", "valor_parcela"]
        mapping = detect_columns(headers, import_type="installment")
        assert mapping == {
            "date": 0,
            "total_amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
            "num_installments": 5,
            "installment_amount": 6,
        }

    def test_case_insensitive(self):
        headers = ["Data", "Valor", "Descrição", "Categoria", "Forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping["date"] == 0

    def test_descricao_without_accent(self):
        headers = ["data", "valor", "descricao", "categoria", "forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping["description"] == 2

    def test_missing_required_column(self):
        headers = ["data", "valor"]
        mapping = detect_columns(headers, import_type="regular")
        assert "description" not in mapping  # missing, not mapped


class TestParseCsvRows:
    def test_parse_regular_entries(self):
        csv_content = (
            'data,valor,descrição,categoria,forma\n'
            '01/03/2026,"R$ 42,00",Heineken - bebida,Álcool,Pix\n'
            '01/03/2026,"R$ 14,00",Disk Bebida,Lanche,Pix\n'
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-03-01"
        assert rows[0]["amount"] == "42.00"
        assert rows[0]["description"] == "Heineken - bebida"
        assert rows[0]["category"] == "Álcool"
        assert rows[0]["payment_method"] == "Pix"

    def test_parse_installments(self):
        csv_content = (
            'data,valor,descrição,categoria,forma,parcelas,valor_parcela\n'
            '01/11/2025,"R$ 193,19",Mercado Livre - Camisetas,Roupa,Crédito C6,2,"R$ 96,60"\n'
        )
        mapping = {
            "date": 0, "total_amount": 1, "description": 2, "category": 3,
            "payment_method": 4, "num_installments": 5, "installment_amount": 6,
        }
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="installment")
        assert len(rows) == 1
        assert rows[0]["total_amount"] == "193.19"
        assert rows[0]["num_installments"] == "2"
        assert rows[0]["installment_amount"] == "96.60"

    def test_invalid_row_marked_as_error(self):
        csv_content = (
            'data,valor,descrição,categoria,forma\n'
            '01/03/2026,"R$ 42,00",Good entry,Álcool,Pix\n'
            'invalid-date,"R$ 10,00",Bad entry,Lanche,Pix\n'
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert rows[0]["status"] == "ok"
        assert rows[1]["status"] == "error"
        assert "date" in rows[1].get("error", "").lower()

    def test_empty_amount_marked_as_error(self):
        csv_content = (
            'data,valor,descrição,categoria,forma\n'
            '01/03/2026,,Missing amount,Álcool,Pix\n'
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert rows[0]["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_csv_parser.py -v
```

- [ ] **Step 3: Implement csv_parser.py**

```python
# src/backend/finances/services/csv_parser.py
import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def parse_amount(value: str) -> Decimal:
    """Parse Brazilian currency format to Decimal.

    Examples: 'R$ 42,00' → 42.00, 'R$ 1.300,00' → 1300.00, '-R$ 226,21' → -226.21
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Empty amount")

    # Extract sign
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-").strip()

    # Remove R$ prefix
    cleaned = re.sub(r"R\$\s*", "", cleaned).strip()

    if not cleaned:
        raise ValueError("Empty amount after cleaning")

    # Handle Brazilian format: 1.300,00 → 1300.00
    if "," in cleaned:
        # Remove thousand separators (dots before comma)
        cleaned = cleaned.replace(".", "")
        # Replace decimal comma with dot
        cleaned = cleaned.replace(",", ".")

    try:
        result = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Cannot parse amount: {value}")

    return -result if negative else result


def parse_date(value: str) -> date:
    """Parse dd/mm/yyyy date format."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Empty date")

    try:
        return datetime.strptime(cleaned, "%d/%m/%Y").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {value}")


# Header aliases for auto-detection (lowercase)
HEADER_ALIASES = {
    "date": ["data"],
    "amount": ["valor"],
    "total_amount": ["valor"],
    "description": ["descrição", "descricao", "desc", "descriçao"],
    "category": ["categoria"],
    "payment_method": ["forma", "forma de pagamento"],
    "num_installments": ["parcelas"],
    "installment_amount": ["valor_parcela", "valor parcela"],
}

REQUIRED_FIELDS = {
    "regular": ["date", "amount", "description", "category", "payment_method"],
    "installment": [
        "date", "total_amount", "description", "category", "payment_method",
        "num_installments", "installment_amount",
    ],
}


def detect_columns(headers: list[str], import_type: str) -> dict[str, int]:
    """Auto-detect column mapping from CSV headers.

    Returns dict mapping field names to column indices.
    """
    headers_lower = [h.strip().lower() for h in headers]
    required = REQUIRED_FIELDS.get(import_type, REQUIRED_FIELDS["regular"])
    mapping = {}

    for field in required:
        aliases = HEADER_ALIASES.get(field, [])
        for i, header in enumerate(headers_lower):
            if header in aliases and i not in mapping.values():
                mapping[field] = i
                break

    return mapping


def parse_csv_rows(
    file_obj,
    column_mapping: dict[str, int],
    import_type: str,
) -> list[dict]:
    """Parse CSV rows using the provided column mapping.

    Returns list of dicts with parsed values and status ('ok' or 'error').
    """
    reader = csv.reader(file_obj)
    next(reader)  # skip header

    rows = []
    amount_field = "total_amount" if import_type == "installment" else "amount"

    for line_num, csv_row in enumerate(reader, start=2):
        row = {"status": "ok", "error": "", "line": line_num}

        try:
            # Parse date
            date_idx = column_mapping.get("date")
            if date_idx is not None and date_idx < len(csv_row):
                parsed_date = parse_date(csv_row[date_idx])
                row["date"] = parsed_date.isoformat()
            else:
                raise ValueError("Missing date column")

            # Parse amount
            amt_idx = column_mapping.get(amount_field)
            if amt_idx is not None and amt_idx < len(csv_row):
                parsed_amount = parse_amount(csv_row[amt_idx])
                row[amount_field] = str(parsed_amount)
            else:
                raise ValueError(f"Missing {amount_field} column")

            # Parse description
            desc_idx = column_mapping.get("description")
            if desc_idx is not None and desc_idx < len(csv_row):
                row["description"] = csv_row[desc_idx].strip()
            else:
                raise ValueError("Missing description column")

            # Category and payment method (strings, resolved later)
            cat_idx = column_mapping.get("category")
            if cat_idx is not None and cat_idx < len(csv_row):
                row["category"] = csv_row[cat_idx].strip()
            else:
                raise ValueError("Missing category column")

            pm_idx = column_mapping.get("payment_method")
            if pm_idx is not None and pm_idx < len(csv_row):
                row["payment_method"] = csv_row[pm_idx].strip()
            else:
                raise ValueError("Missing payment method column")

            # Installment-specific fields
            if import_type == "installment":
                ni_idx = column_mapping.get("num_installments")
                if ni_idx is not None and ni_idx < len(csv_row):
                    row["num_installments"] = csv_row[ni_idx].strip()
                else:
                    raise ValueError("Missing num_installments column")

                ia_idx = column_mapping.get("installment_amount")
                if ia_idx is not None and ia_idx < len(csv_row):
                    parsed_ia = parse_amount(csv_row[ia_idx])
                    row["installment_amount"] = str(parsed_ia)
                else:
                    raise ValueError("Missing installment_amount column")

            # Validate required fields are non-empty
            if not row.get("description"):
                raise ValueError("Empty description")

        except (ValueError, IndexError) as e:
            row["status"] = "error"
            row["error"] = str(e)

        rows.append(row)

    return rows
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_csv_parser.py -v
```

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add src/backend/finances/services/csv_parser.py src/backend/finances/tests/test_csv_parser.py
git commit -m "feat(finances): add CSV parser with amount, date, and column detection"
```

---

## Task 2: Import Wizard Views — Upload + Mapping (TDD)

**Files:**
- Create: `src/backend/finances/views/importer.py`
- Create: `src/backend/templates/importer/import_page.html`
- Create: `src/backend/templates/importer/_step_upload.html`
- Create: `src/backend/templates/importer/_step_mapping.html`
- Create: `src/backend/finances/tests/test_views_importer.py`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/views/__init__.py`
- Modify: `src/backend/templates/partials/_navbar.html`

- [ ] **Step 1: Write failing tests**

```python
# src/backend/finances/tests/test_views_importer.py
import io

import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestImportUploadView:
    def test_upload_page_renders(self, logged_client):
        response = logged_client.get("/import/")
        assert response.status_code == 200
        assert "import_page.html" in [t.name for t in response.templates]

    def test_upload_csv_file(self, logged_client):
        csv_content = b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n01/03/2026,"R$ 42,00",Test,Food,Pix\n'
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        response = logged_client.post(
            "/import/",
            data={"file": csv_file, "import_type": "regular"},
        )
        assert response.status_code == 302  # redirects to mapping step

    def test_upload_no_file_shows_error(self, logged_client):
        response = logged_client.post(
            "/import/",
            data={"import_type": "regular"},
        )
        assert response.status_code == 200  # re-renders form with error

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/import/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestImportMappingView:
    def _upload_first(self, logged_client):
        csv_content = b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n01/03/2026,"R$ 42,00",Test,Food,Pix\n'
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})

    def test_mapping_page_renders(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.get("/import/map/")
        assert response.status_code == 200
        assert "mapping" in response.context

    def test_mapping_auto_detects_columns(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.get("/import/map/")
        mapping = response.context["mapping"]
        assert mapping["date"] == 0
        assert mapping["amount"] == 1
        assert mapping["description"] == 2

    def test_confirm_mapping_redirects_to_preview(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.post(
            "/import/map/",
            data={"date": "0", "amount": "1", "description": "2", "category": "3", "payment_method": "4"},
        )
        assert response.status_code == 302  # redirects to preview

    def test_no_session_redirects_to_upload(self, logged_client):
        response = logged_client.get("/import/map/")
        assert response.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_importer.py -v
```

- [ ] **Step 3: Implement upload and mapping views**

```python
# src/backend/finances/views/importer.py
import csv
import io
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views import View

from finances.models import Category, Entry, EntryType, InstallmentPlan, PaymentMethod
from finances.services.billing import compute_billing_month
from finances.services.csv_parser import detect_columns, parse_csv_rows


class ImportUploadView(LoginRequiredMixin, View):
    """Step 1: Upload CSV file and select import type."""

    def get(self, request):
        return render(request, "importer/import_page.html", {"step": "upload"})

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        import_type = request.POST.get("import_type", "regular")

        if not uploaded_file:
            return render(
                request,
                "importer/import_page.html",
                {"step": "upload", "error": "Selecione um arquivo CSV."},
            )

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Read headers for auto-detection
        try:
            with open(tmp_path, encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader)
        except UnicodeDecodeError:
            return render(
                request,
                "importer/import_page.html",
                {"step": "upload", "error": "Arquivo não está em formato UTF-8. Re-exporte do Google Sheets."},
            )

        # Store in session
        request.session["import_data"] = {
            "file_path": tmp_path,
            "import_type": import_type,
            "headers": headers,
        }

        return redirect("finances:import_map")


class ImportMappingView(LoginRequiredMixin, View):
    """Step 2: Review and confirm column mapping."""

    def get(self, request):
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        headers = import_data["headers"]
        import_type = import_data["import_type"]
        mapping = detect_columns(headers, import_type)

        # Determine which fields are needed
        if import_type == "installment":
            fields = [
                "date", "total_amount", "description", "category",
                "payment_method", "num_installments", "installment_amount",
            ]
        else:
            fields = ["date", "amount", "description", "category", "payment_method"]

        return render(request, "importer/import_page.html", {
            "step": "mapping",
            "mapping": mapping,
            "headers": headers,
            "fields": fields,
            "import_type": import_type,
        })

    def post(self, request):
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        # Build mapping from form data
        import_type = import_data["import_type"]
        if import_type == "installment":
            fields = [
                "date", "total_amount", "description", "category",
                "payment_method", "num_installments", "installment_amount",
            ]
        else:
            fields = ["date", "amount", "description", "category", "payment_method"]

        mapping = {}
        for field in fields:
            val = request.POST.get(field)
            if val is not None:
                mapping[field] = int(val)

        # Parse rows
        with open(import_data["file_path"], encoding="utf-8") as f:
            rows = parse_csv_rows(f, mapping, import_type)

        # Find unmatched categories and payment methods
        user = request.user
        existing_categories = {
            c.lower(): c for c in Category.objects.filter(user=user).values_list("name", flat=True)
        }
        existing_pms = {
            p.lower(): p for p in PaymentMethod.objects.filter(user=user).values_list("name", flat=True)
        }

        unmatched_categories = set()
        unmatched_pms = set()
        for row in rows:
            if row["status"] == "ok":
                cat = row.get("category", "")
                if cat and cat.lower() not in existing_categories:
                    unmatched_categories.add(cat)
                pm = row.get("payment_method", "")
                if pm and pm.lower() not in existing_pms:
                    unmatched_pms.add(pm)

        # Check duplicates
        duplicate_indices = []
        amount_field = "total_amount" if import_type == "installment" else "amount"
        for i, row in enumerate(rows):
            if row["status"] != "ok":
                continue
            if import_type == "installment":
                exists = InstallmentPlan.objects.filter(
                    user=user,
                    date=row["date"],
                    total_amount=Decimal(row["total_amount"]),
                    description=row["description"],
                ).exists()
            else:
                exists = Entry.objects.filter(
                    user=user,
                    date=row["date"],
                    amount=Decimal(row[amount_field]),
                    description=row["description"],
                ).exists()
            if exists:
                row["status"] = "duplicate"
                duplicate_indices.append(i)

        # Store in session
        import_data["column_mapping"] = mapping
        import_data["rows"] = rows
        import_data["unmatched_categories"] = sorted(unmatched_categories)
        import_data["unmatched_pms"] = sorted(unmatched_pms)
        import_data["duplicate_indices"] = duplicate_indices
        import_data["skip_indices"] = []
        request.session["import_data"] = import_data
        request.session.modified = True

        return redirect("finances:import_preview")
```

- [ ] **Step 4: Create templates**

```html
<!-- src/backend/templates/importer/import_page.html -->
{% extends "base.html" %}

{% block title %}Importar CSV{% endblock %}

{% block content %}
<h2 class="text-2xl font-bold mb-4">Importar CSV</h2>

<!-- Steps indicator -->
<ul class="steps mb-6">
    <li class="step {% if step == 'upload' %}step-primary{% endif %}">Upload</li>
    <li class="step {% if step == 'mapping' %}step-primary{% endif %}">Mapeamento</li>
    <li class="step {% if step == 'preview' %}step-primary{% endif %}">Preview</li>
    <li class="step {% if step == 'result' %}step-primary{% endif %}">Resultado</li>
</ul>

<div id="import-step">
    {% if step == "upload" %}{% include "importer/_step_upload.html" %}
    {% elif step == "mapping" %}{% include "importer/_step_mapping.html" %}
    {% elif step == "preview" %}{% include "importer/_step_preview.html" %}
    {% elif step == "result" %}{% include "importer/_step_result.html" %}
    {% endif %}
</div>
{% endblock %}
```

```html
<!-- src/backend/templates/importer/_step_upload.html -->
<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <h3 class="card-title">1. Selecione o arquivo CSV</h3>

        {% if error %}
        <div class="alert alert-error mb-4">{{ error }}</div>
        {% endif %}

        <form method="post" enctype="multipart/form-data" action="{% url 'finances:import_upload' %}">
            {% csrf_token %}
            <div class="form-control mb-4">
                <label class="label"><span class="label-text">Tipo de importação</span></label>
                <select name="import_type" class="select select-bordered">
                    <option value="regular">Entradas regulares</option>
                    <option value="installment">Parcelamentos</option>
                </select>
            </div>
            <div class="form-control mb-4">
                <label class="label"><span class="label-text">Arquivo CSV</span></label>
                <input type="file" name="file" accept=".csv" class="file-input file-input-bordered w-full" required>
            </div>
            <button type="submit" class="btn btn-accent">Próximo →</button>
        </form>
    </div>
</div>
```

```html
<!-- src/backend/templates/importer/_step_mapping.html -->
<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <h3 class="card-title">2. Mapeamento de colunas</h3>
        <p class="text-sm opacity-70 mb-4">Verifique se as colunas foram detectadas corretamente.</p>

        <form method="post" action="{% url 'finances:import_map' %}">
            {% csrf_token %}
            <div class="overflow-x-auto">
            <table class="table table-sm">
                <thead><tr><th>Campo</th><th>Coluna CSV</th></tr></thead>
                <tbody>
                    {% for field in fields %}
                    <tr>
                        <td class="font-medium">{{ field }}</td>
                        <td>
                            <select name="{{ field }}" class="select select-bordered select-sm">
                                {% for i, h in headers_indexed %}
                                <option value="{{ i }}" {% if mapping|get_item:field == i %}selected{% endif %}>{{ h }}</option>
                                {% endfor %}
                            </select>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
            <div class="flex gap-2 mt-4">
                <a href="{% url 'finances:import_upload' %}" class="btn btn-ghost">← Voltar</a>
                <button type="submit" class="btn btn-accent">Próximo →</button>
            </div>
        </form>
    </div>
</div>
```

- [ ] **Step 5: Update URLs and navbar**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.importer import ImportUploadView, ImportMappingView

# Import
path("import/", ImportUploadView.as_view(), name="import_upload"),
path("import/map/", ImportMappingView.as_view(), name="import_map"),
```

Update `_navbar.html` to add Importar link (between Configurações and the "Nova Entrada" button).

- [ ] **Step 6: Add headers_indexed to mapping view context**

The mapping template needs `headers_indexed` (list of `(index, header)` tuples). Add to `ImportMappingView.get()`:
```python
context["headers_indexed"] = list(enumerate(headers))
```

Also add `{% load finance_filters %}` at the top of `_step_mapping.html` for the `get_item` filter.

- [ ] **Step 7: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_importer.py -v
```

- [ ] **Step 8: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add CSV import wizard — upload and column mapping steps"
```

---

## Task 3: Import Wizard Views — Preview + Execute (TDD)

**Files:**
- Modify: `src/backend/finances/views/importer.py`
- Create: `src/backend/templates/importer/_step_preview.html`
- Create: `src/backend/templates/importer/_step_result.html`
- Modify: `src/backend/finances/urls.py`
- Modify: `src/backend/finances/tests/test_views_importer.py`

- [ ] **Step 1: Write failing tests**

Append to `test_views_importer.py`:

```python
@pytest.mark.django_db
class TestImportPreviewView:
    def _setup_session(self, logged_client, user):
        """Upload and map a CSV to get to preview step."""
        baker.make("finances.Category", user=user, name="Álcool")
        baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        csv_content = (
            b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n'
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'02/03/2026,"R$ 14,00",Disk Bebida,NewCat,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post(
            "/import/map/",
            data={"date": "0", "amount": "1", "description": "2", "category": "3", "payment_method": "4"},
        )

    def test_preview_page_renders(self, logged_client, user):
        self._setup_session(logged_client, user)
        response = logged_client.get("/import/preview/")
        assert response.status_code == 200
        assert "rows" in response.context

    def test_preview_shows_unmatched_categories(self, logged_client, user):
        self._setup_session(logged_client, user)
        response = logged_client.get("/import/preview/")
        assert "NewCat" in response.context["unmatched_categories"]

    def test_no_session_redirects(self, logged_client):
        response = logged_client.get("/import/preview/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestImportExecuteView:
    def _setup_to_preview(self, logged_client, user):
        baker.make("finances.Category", user=user, name="Álcool")
        baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        csv_content = (
            b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n'
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'05/03/2026,"R$ 14,00",Disk Bebida,\xc3\x81lcool,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post(
            "/import/map/",
            data={"date": "0", "amount": "1", "description": "2", "category": "3", "payment_method": "4"},
        )

    def test_execute_creates_entries(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        assert Entry.objects.filter(user=user).count() == 2

    def test_execute_entries_have_correct_billing_month(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        logged_client.post("/import/execute/")
        from datetime import date
        entry = Entry.objects.filter(user=user, description="Heineken").first()
        assert entry is not None
        assert entry.billing_month == date(2026, 3, 1)

    def test_execute_clears_session(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        logged_client.post("/import/execute/")
        assert "import_data" not in logged_client.session

    def test_execute_installments(self, logged_client, user):
        baker.make("finances.Category", user=user, name="Roupa")
        baker.make("finances.PaymentMethod", user=user, name="Crédito C6", type="credit_card", closing_day=25)
        csv_content = (
            b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma,parcelas,valor_parcela\n'
            b'01/11/2025,"R$ 193,19",Mercado Livre - Camisetas,Roupa,Cr\xc3\xa9dito C6,2,"R$ 96,60"\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "installment"})
        logged_client.post(
            "/import/map/",
            data={
                "date": "0", "total_amount": "1", "description": "2", "category": "3",
                "payment_method": "4", "num_installments": "5", "installment_amount": "6",
            },
        )
        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        assert InstallmentPlan.objects.filter(user=user).count() == 1
        assert Entry.objects.filter(user=user, entry_type="installment").count() == 2

    def test_execute_skips_duplicates_marked_for_skip(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, name="Álcool")
        pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        # Pre-existing entry
        baker.make(
            "finances.Entry", user=user, date="2026-03-01", amount="42.00",
            description="Heineken", category=cat, payment_method=pm,
            billing_month="2026-03-01",
        )
        csv_content = (
            b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n'
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post(
            "/import/map/",
            data={"date": "0", "amount": "1", "description": "2", "category": "3", "payment_method": "4"},
        )
        # Mark duplicate for skip
        session = logged_client.session
        import_data = session["import_data"]
        import_data["skip_indices"] = [0]
        session["import_data"] = import_data
        session.save()

        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        # Should still have only the pre-existing entry
        assert Entry.objects.filter(user=user).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest src/backend/finances/tests/test_views_importer.py -v -k "Preview or Execute"
```

- [ ] **Step 3: Implement preview and execute views**

Add to `src/backend/finances/views/importer.py`:

```python
class ImportPreviewView(LoginRequiredMixin, View):
    """Step 3: Preview parsed rows with warnings."""

    def get(self, request):
        import_data = request.session.get("import_data")
        if not import_data or "rows" not in import_data:
            return redirect("finances:import_upload")

        rows = import_data["rows"]
        ok_count = sum(1 for r in rows if r["status"] == "ok")
        dup_count = sum(1 for r in rows if r["status"] == "duplicate")
        err_count = sum(1 for r in rows if r["status"] == "error")

        # Get existing categories/PMs for resolution dropdowns
        categories = Category.objects.filter(user=request.user).order_by("name")
        payment_methods = PaymentMethod.objects.filter(user=request.user, is_active=True).order_by("name")

        return render(request, "importer/import_page.html", {
            "step": "preview",
            "rows": rows,
            "ok_count": ok_count,
            "dup_count": dup_count,
            "err_count": err_count,
            "import_type": import_data["import_type"],
            "unmatched_categories": import_data.get("unmatched_categories", []),
            "unmatched_pms": import_data.get("unmatched_pms", []),
            "categories": categories,
            "payment_methods": payment_methods,
            "skip_indices": import_data.get("skip_indices", []),
        })

    def post(self, request):
        """Handle conflict resolution and skip toggling."""
        import_data = request.session.get("import_data")
        if not import_data:
            return redirect("finances:import_upload")

        # Process skip toggles
        skip_indices = []
        for key, value in request.POST.items():
            if key.startswith("skip_") and value == "on":
                idx = int(key.replace("skip_", ""))
                skip_indices.append(idx)
        import_data["skip_indices"] = skip_indices

        # Process category resolutions
        category_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("cat_resolve_") and value:
                cat_name = key.replace("cat_resolve_", "")
                if value == "__new__":
                    category_resolutions[cat_name] = "__new__"
                else:
                    category_resolutions[cat_name] = value
        import_data["category_resolutions"] = category_resolutions

        # Process PM resolutions
        pm_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("pm_resolve_") and value:
                pm_name = key.replace("pm_resolve_", "")
                if value == "__new__":
                    pm_resolutions[pm_name] = "__new__"
                else:
                    pm_resolutions[pm_name] = value
        import_data["pm_resolutions"] = pm_resolutions

        request.session["import_data"] = import_data
        request.session.modified = True

        return redirect("finances:import_preview")


class ImportExecuteView(LoginRequiredMixin, View):
    """Step 4: Execute the import."""

    @transaction.atomic
    def post(self, request):
        import_data = request.session.get("import_data")
        if not import_data or "rows" not in import_data:
            return redirect("finances:import_upload")

        rows = import_data["rows"]
        import_type = import_data["import_type"]
        skip_indices = set(import_data.get("skip_indices", []))
        category_resolutions = import_data.get("category_resolutions", {})
        pm_resolutions = import_data.get("pm_resolutions", {})
        user = request.user

        # Build category and PM lookup maps
        cat_map = {c.name: c for c in Category.objects.filter(user=user)}
        pm_map = {p.name: p for p in PaymentMethod.objects.filter(user=user)}

        # Create new categories/PMs from resolutions
        for name, resolution in category_resolutions.items():
            if resolution == "__new__" and name not in cat_map:
                cat_map[name] = Category.objects.create(user=user, name=name)

        for name, resolution in pm_resolutions.items():
            if resolution == "__new__" and name not in pm_map:
                pm_map[name] = PaymentMethod.objects.create(
                    user=user, name=name, type="pix"
                )

        created_count = 0
        skipped_count = 0
        error_count = 0

        for i, row in enumerate(rows):
            if i in skip_indices:
                skipped_count += 1
                continue
            if row["status"] == "error":
                error_count += 1
                continue
            cat_name = row.get("category", "")
            pm_name = row.get("payment_method", "")

            # Resolve category
            category = cat_map.get(cat_name)
            if not category and cat_name in category_resolutions:
                res = category_resolutions[cat_name]
                if res != "__new__":
                    category = Category.objects.filter(user=user, pk=res).first()
            if not category:
                error_count += 1
                continue

            # Resolve payment method
            payment_method = pm_map.get(pm_name)
            if not payment_method and pm_name in pm_resolutions:
                res = pm_resolutions[pm_name]
                if res != "__new__":
                    payment_method = PaymentMethod.objects.filter(user=user, pk=res).first()
            if not payment_method:
                error_count += 1
                continue

            try:
                if import_type == "installment":
                    plan = InstallmentPlan.objects.create(
                        user=user,
                        date=row["date"],
                        description=row["description"],
                        category=category,
                        payment_method=payment_method,
                        total_amount=Decimal(row["total_amount"]),
                        num_installments=int(row["num_installments"]),
                        installment_amount=Decimal(row["installment_amount"]),
                    )
                    plan.generate_entries()
                else:
                    entry_date = date.fromisoformat(row["date"])
                    billing_month = compute_billing_month(
                        entry_date, payment_method.type, payment_method.closing_day,
                    )
                    Entry.objects.create(
                        user=user,
                        date=entry_date,
                        amount=Decimal(row["amount"]),
                        description=row["description"],
                        category=category,
                        payment_method=payment_method,
                        entry_type=EntryType.REGULAR,
                        billing_month=billing_month,
                        billing_month_override=False,
                    )
                created_count += 1
            except Exception:
                error_count += 1

        # Clean up temp file and session
        import os
        file_path = import_data.get("file_path")
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
        if "import_data" in request.session:
            del request.session["import_data"]

        return render(request, "importer/import_page.html", {
            "step": "result",
            "created_count": created_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "import_type": import_type,
        })
```

- [ ] **Step 4: Create preview and result templates**

```html
<!-- src/backend/templates/importer/_step_preview.html -->
<div class="card bg-base-100 shadow-sm">
    <div class="card-body">
        <h3 class="card-title">3. Preview</h3>

        <!-- Summary badges -->
        <div class="flex gap-2 mb-4">
            <span class="badge badge-success">{{ ok_count }} OK</span>
            {% if dup_count %}<span class="badge badge-warning">{{ dup_count }} Duplicados</span>{% endif %}
            {% if err_count %}<span class="badge badge-error">{{ err_count }} Erros</span>{% endif %}
        </div>

        <!-- Unmatched categories resolution -->
        {% if unmatched_categories %}
        <div class="alert alert-warning mb-4">
            <div>
                <h4 class="font-bold">Categorias não encontradas</h4>
                <form method="post" action="{% url 'finances:import_preview' %}">
                    {% csrf_token %}
                    {% for name in unmatched_categories %}
                    <div class="flex items-center gap-2 mt-2">
                        <span class="font-medium">{{ name }}</span>
                        <span>→</span>
                        <select name="cat_resolve_{{ name }}" class="select select-bordered select-sm">
                            <option value="__new__">Criar nova</option>
                            {% for cat in categories %}
                            <option value="{{ cat.id }}">{{ cat.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endfor %}
                    <button type="submit" class="btn btn-sm btn-warning mt-2">Aplicar</button>
                </form>
            </div>
        </div>
        {% endif %}

        <!-- Unmatched payment methods resolution -->
        {% if unmatched_pms %}
        <div class="alert alert-warning mb-4">
            <div>
                <h4 class="font-bold">Formas de pagamento não encontradas</h4>
                <form method="post" action="{% url 'finances:import_preview' %}">
                    {% csrf_token %}
                    {% for name in unmatched_pms %}
                    <div class="flex items-center gap-2 mt-2">
                        <span class="font-medium">{{ name }}</span>
                        <span>→</span>
                        <select name="pm_resolve_{{ name }}" class="select select-bordered select-sm">
                            <option value="__new__">Criar nova (Pix)</option>
                            {% for pm in payment_methods %}
                            <option value="{{ pm.id }}">{{ pm.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endfor %}
                    <button type="submit" class="btn btn-sm btn-warning mt-2">Aplicar</button>
                </form>
            </div>
        </div>
        {% endif %}

        <!-- Rows table -->
        <div class="overflow-x-auto">
        <table class="table table-sm">
            <thead>
                <tr><th>#</th><th>Status</th><th>Data</th><th>Valor</th><th>Descrição</th><th>Categoria</th><th>Forma</th>
                {% if import_type == "installment" %}<th>Parcelas</th>{% endif %}
                <th>Pular</th></tr>
            </thead>
            <tbody>
                {% for row in rows %}
                <tr class="{% if row.status == 'error' %}bg-error/10{% elif row.status == 'duplicate' %}bg-warning/10{% endif %}">
                    <td>{{ row.line }}</td>
                    <td>
                        {% if row.status == "ok" %}<span class="badge badge-sm badge-success">OK</span>
                        {% elif row.status == "duplicate" %}<span class="badge badge-sm badge-warning">Dup</span>
                        {% elif row.status == "error" %}<span class="badge badge-sm badge-error" title="{{ row.error }}">Erro</span>
                        {% endif %}
                    </td>
                    <td>{{ row.date|default:"—" }}</td>
                    <td>{{ row.amount|default:row.total_amount|default:"—" }}</td>
                    <td>{{ row.description|default:"—" }}</td>
                    <td>{{ row.category|default:"—" }}</td>
                    <td>{{ row.payment_method|default:"—" }}</td>
                    {% if import_type == "installment" %}<td>{{ row.num_installments|default:"—" }}x</td>{% endif %}
                    <td>
                        {% if row.status != "error" %}
                        <input type="checkbox" class="checkbox checkbox-sm"
                               name="skip_{{ forloop.counter0 }}"
                               {% if forloop.counter0 in skip_indices %}checked{% endif %}>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        </div>

        <div class="flex gap-2 mt-4">
            <a href="{% url 'finances:import_map' %}" class="btn btn-ghost">← Voltar</a>
            <form method="post" action="{% url 'finances:import_execute' %}">
                {% csrf_token %}
                <button type="submit" class="btn btn-accent">Importar {{ ok_count }} entradas →</button>
            </form>
        </div>
    </div>
</div>
```

```html
<!-- src/backend/templates/importer/_step_result.html -->
<div class="card bg-base-100 shadow-sm">
    <div class="card-body text-center">
        <h3 class="card-title justify-center text-2xl mb-4">Importação concluída!</h3>

        <div class="stats shadow mb-6">
            <div class="stat">
                <div class="stat-title">Importados</div>
                <div class="stat-value text-success">{{ created_count }}</div>
            </div>
            <div class="stat">
                <div class="stat-title">Pulados</div>
                <div class="stat-value text-warning">{{ skipped_count }}</div>
            </div>
            <div class="stat">
                <div class="stat-title">Erros</div>
                <div class="stat-value text-error">{{ error_count }}</div>
            </div>
        </div>

        <div class="flex gap-2 justify-center">
            <a href="{% url 'finances:entries' %}" class="btn btn-accent">Ver entradas</a>
            <a href="{% url 'finances:import_upload' %}" class="btn btn-ghost">Importar outro arquivo</a>
        </div>
    </div>
</div>
```

- [ ] **Step 5: Update URLs**

Add to `src/backend/finances/urls.py`:
```python
from finances.views.importer import ImportPreviewView, ImportExecuteView

path("import/preview/", ImportPreviewView.as_view(), name="import_preview"),
path("import/execute/", ImportExecuteView.as_view(), name="import_execute"),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest src/backend/finances/tests/test_views_importer.py -v
```

- [ ] **Step 7: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "feat(finances): add CSV import preview and execute steps with conflict resolution"
```

---

## Task 4: BDD Feature Specs

**Files:**
- Create: `src/backend/finances/tests/features/import.feature`
- Create: `src/backend/finances/tests/features/test_import.py`

- [ ] **Step 1: Write feature file**

```gherkin
# src/backend/finances/tests/features/import.feature
Feature: CSV import wizard
  As a user migrating from Google Sheets
  I want to import my expense history from CSV files
  So I can have all my data in the new system

  Scenario: Import regular entries from CSV
    Given a logged-in user with seed data
    And a CSV file with 3 regular entries
    When I upload the CSV as regular entries
    And I confirm the column mapping
    And I execute the import
    Then 3 entries should exist in the database

  Scenario: Import installments from CSV
    Given a logged-in user with seed data
    And a CSV file with 1 installment of 2 parcels
    When I upload the CSV as installments
    And I confirm the column mapping
    And I execute the import
    Then 1 installment plan should exist
    And 2 installment entries should exist
```

- [ ] **Step 2: Write step definitions**

```python
# src/backend/finances/tests/features/test_import.py
import io

import pytest
from django.test import Client
from model_bakery import baker
from pytest_bdd import given, scenario, then, when

from finances.models import Entry, InstallmentPlan


@scenario("import.feature", "Import regular entries from CSV")
def test_import_regular():
    pass


@scenario("import.feature", "Import installments from CSV")
def test_import_installments():
    pass


@pytest.fixture
def ctx():
    return {}


@given("a logged-in user with seed data", target_fixture="ctx")
def given_user_with_seed(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    baker.make("finances.Category", user=user, name="Álcool")
    baker.make("finances.Category", user=user, name="Lanche")
    baker.make("finances.Category", user=user, name="Roupa")
    baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.PaymentMethod", user=user, name="Crédito C6",
        type="credit_card", closing_day=25,
    )
    ctx.update({"user": user, "client": client})
    return ctx


@given("a CSV file with 3 regular entries", target_fixture="ctx")
def given_csv_regular(ctx):
    ctx["csv_content"] = (
        b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n'
        b'01/03/2026,"R$ 42,00",Entry 1,\xc3\x81lcool,Pix\n'
        b'02/03/2026,"R$ 14,00",Entry 2,Lanche,Pix\n'
        b'03/03/2026,"R$ 50,00",Entry 3,\xc3\x81lcool,Pix\n'
    )
    ctx["import_type"] = "regular"
    return ctx


@given("a CSV file with 1 installment of 2 parcels", target_fixture="ctx")
def given_csv_installment(ctx):
    ctx["csv_content"] = (
        b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma,parcelas,valor_parcela\n'
        b'01/11/2025,"R$ 193,19",Mercado Livre,Roupa,Cr\xc3\xa9dito C6,2,"R$ 96,60"\n'
    )
    ctx["import_type"] = "installment"
    return ctx


@when("I upload the CSV as regular entries")
def when_upload_regular(ctx):
    csv_file = io.BytesIO(ctx["csv_content"])
    csv_file.name = "test.csv"
    ctx["client"].post("/import/", data={"file": csv_file, "import_type": "regular"})


@when("I upload the CSV as installments")
def when_upload_installments(ctx):
    csv_file = io.BytesIO(ctx["csv_content"])
    csv_file.name = "test.csv"
    ctx["client"].post("/import/", data={"file": csv_file, "import_type": "installment"})


@when("I confirm the column mapping")
def when_confirm_mapping(ctx):
    import_type = ctx.get("import_type", "regular")
    if import_type == "installment":
        data = {
            "date": "0", "total_amount": "1", "description": "2", "category": "3",
            "payment_method": "4", "num_installments": "5", "installment_amount": "6",
        }
    else:
        data = {"date": "0", "amount": "1", "description": "2", "category": "3", "payment_method": "4"}
    ctx["client"].post("/import/map/", data=data)


@when("I execute the import")
def when_execute(ctx):
    ctx["response"] = ctx["client"].post("/import/execute/")


@then("3 entries should exist in the database")
def then_3_entries(ctx):
    assert Entry.objects.filter(user=ctx["user"], entry_type="regular").count() == 3


@then("1 installment plan should exist")
def then_1_plan(ctx):
    assert InstallmentPlan.objects.filter(user=ctx["user"]).count() == 1


@then("2 installment entries should exist")
def then_2_entries(ctx):
    assert Entry.objects.filter(user=ctx["user"], entry_type="installment").count() == 2
```

- [ ] **Step 3: Run BDD tests**

```bash
uv run pytest src/backend/finances/tests/features/test_import.py -v
```

- [ ] **Step 4: Commit**

```bash
uv run ruff check src/backend/ --fix && uv run ruff format src/backend/
git add -A
git commit -m "test(finances): add BDD specs for CSV import wizard flow"
```

---

## Task 5: Final Validation

- [ ] **Step 1: Run full lint**

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

- [ ] **Step 4: Commit any remaining fixes**

```bash
git add -u
git commit -m "chore: fix lint and formatting from final validation"
```
