# Sub-Project 3: CSV Importer — Design Spec

## Overview

One-time migration tool to import historical financial data from Google Sheets CSV exports. Supports regular expense entries and installment plans. A 4-step HTMX wizard guides the user through upload, column mapping, preview with conflict resolution, and bulk import.

**Builds on:** Sub-Project 1 (models, billing service) and Sub-Project 2 (HTMX views, base layout).

**Does NOT include:** Systemic expense import (managed via Settings tab — systemics are recurring like income, user creates/edits them directly).

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Import scope | Regular entries + installments | Systemics are few, recurring, managed via settings |
| Column mapping | Auto-detect with confirmation | Recognizes known headers, user reviews/corrects before import |
| Unmatched names | Preview with resolution | User maps to existing or creates new — avoids duplicates/rejections |
| Duplicate detection | Warn, let user decide | Same-day entries at same store are legitimate — warn, don't block |

## Import Wizard Flow

### Step 1 — Upload (`/import/`)

User uploads a CSV file and selects import type:
- **Regular Entries** — expense/return entries
- **Installments** — installment plans (parcelamentos)

File is saved to a temporary path. Import type and file path stored in session.

### Step 2 — Column Mapping (`/import/map/`)

System auto-detects columns by matching header names (case-insensitive, accent-insensitive):

**Regular entries — required columns:**
| Target Field | Auto-detect headers |
|-------------|-------------------|
| date | `data` |
| amount | `valor` |
| description | `descrição`, `descricao`, `desc` |
| category | `categoria` |
| payment_method | `forma`, `forma de pagamento` |

**Installments — required columns:**
| Target Field | Auto-detect headers | Notes |
|-------------|-------------------|-------|
| date | `data` | Purchase date |
| total_amount | `valor` | Maps to `InstallmentPlan.total_amount` (NOT `Entry.amount`) |
| description | `descrição`, `descricao`, `desc` | |
| category | `categoria` | |
| payment_method | `forma`, `forma de pagamento` | |
| num_installments | `parcelas` | |
| installment_amount | `valor_parcela`, `valor parcela` | Per-installment value |

Shows the mapping as dropdowns. User can correct any mismatched column. Confirms to proceed.

### Step 3 — Preview & Resolve (`/import/preview/`)

Shows a table of parsed rows with row-level status:

**Status indicators:**
- **OK** — row is valid and ready to import
- **Warning: Duplicate** — for regular entries: matches an existing Entry (same date + amount + description). For installments: matches an existing InstallmentPlan (same date + total_amount + description). User can toggle skip/include.
- **Warning: Unmatched category** — category name not found. User maps to existing category via dropdown or creates new.
- **Warning: Unmatched payment method** — same as above for payment methods.
- **Error** — invalid data (missing required field, unparseable date/amount). Row is excluded.

Unmatched categories/payment methods are aggregated at the top — user resolves each unique name once (not per-row).

### Step 4 — Confirm & Import (`/import/execute/`)

Shows summary:
- X entries to import
- Y rows skipped (duplicates or errors)
- Z new categories to create
- W new payment methods to create

User clicks "Importar". System:
1. Creates any new categories/payment methods
2. For regular entries: pre-computes `billing_month` for each entry using `compute_billing_month()`, then bulk creates `Entry` rows. Note: `bulk_create` does NOT call `Entry.save()`, so billing month must be computed explicitly before insertion.
3. For installments: creates `InstallmentPlan` for each row + calls `generate_entries()`
4. All within a single database transaction

Shows success message with final count.

## Data Parsing

### CSV Encoding
UTF-8 assumed (Google Sheets default). If decoding fails, show a clear error message suggesting the user re-export as UTF-8.

### Date Format
Brazilian standard: `dd/mm/yyyy` (e.g., `01/03/2026`)

### Amount Format
Strip `R$` prefix and whitespace, handle Brazilian number format:
- `"R$ 1.300,00"` → `1300.00`
- `"R$ 42,00"` → `42.00`
- `"-R$ 226,21"` → `-226.21`
- `"30,5"` → `30.50` (no R$ prefix)

### Category/Payment Method Matching
Case-insensitive exact match against existing user records. Accent-sensitive (Portuguese characters preserved).

## Session State

Wizard state stored in `request.session["import_data"]` between steps:

```python
{
    "file_path": "/tmp/import_xyz.csv",
    "import_type": "regular",  # or "installment"
    "column_mapping": {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4},
    "rows": [
        {"date": "2026-03-01", "amount": "42.00", "description": "...", "category": "Álcool", "payment_method": "Pix", "status": "ok"},
        ...
    ],
    "unmatched_categories": ["NewCat"],
    "unmatched_payment_methods": [],
    "category_resolutions": {"NewCat": "<uuid-of-existing-or-new>"},
    "pm_resolutions": {},
    "duplicate_indices": [5, 12],
    "skip_indices": [5],
}
```

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/backend/finances/services/csv_parser.py` | Pure functions: parse_amount, parse_date, detect_columns, parse_csv_rows |
| `src/backend/finances/views/importer.py` | Wizard views: upload, mapping, preview, execute |
| `src/backend/templates/importer/import_page.html` | Full page (extends base) with wizard container |
| `src/backend/templates/importer/_step_upload.html` | Step 1: file upload + type selector |
| `src/backend/templates/importer/_step_mapping.html` | Step 2: column mapping with dropdowns |
| `src/backend/templates/importer/_step_preview.html` | Step 3: preview table with warnings/resolve |
| `src/backend/templates/importer/_step_result.html` | Step 4: success summary |
| `src/backend/finances/tests/test_csv_parser.py` | Unit tests for parsing functions |
| `src/backend/finances/tests/test_views_importer.py` | View tests for wizard flow |
| `src/backend/finances/tests/features/import.feature` | BDD spec for import flow |
| `src/backend/finances/tests/features/test_import.py` | BDD step definitions |

### Modified Files

| File | Changes |
|------|---------|
| `src/backend/finances/urls.py` | Add import URL patterns |
| `src/backend/finances/views/__init__.py` | Export importer views |
| `src/backend/templates/partials/_navbar.html` | Add Importar nav link |

## URL Structure

```
/import/              → Step 1: upload form (GET) / process upload (POST)
/import/map/          → Step 2: column mapping (GET shows mapping, POST confirms)
/import/preview/      → Step 3: preview (GET shows table, POST resolves conflicts)
/import/execute/      → Step 4: execute import (POST)
```

## Testing Strategy

### Unit Tests (csv_parser.py)
- `parse_amount`: all format variants (R$ prefix, thousand separators, negative, no prefix)
- `parse_date`: dd/mm/yyyy format, invalid dates
- `detect_columns`: auto-detection from various header styles
- `parse_csv_rows`: end-to-end parsing of sample CSVs

### View Tests
- Upload: valid CSV accepted, invalid file rejected
- Mapping: auto-detection works, manual override works
- Preview: duplicates flagged, unmatched names shown
- Execute: entries created in DB, correct count, transaction rollback on error

### BDD
- Full import flow: upload → map → preview → import → verify entries exist
- Test with actual sample CSV data from `docs/.ai/prompts/SETUP/context/`
