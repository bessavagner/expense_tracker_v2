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
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse amount: {value}") from exc

    return -result if negative else result


def parse_date(value: str) -> date:
    """Parse dd/mm/yyyy date format."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Empty date")

    try:
        return datetime.strptime(cleaned, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {value}") from exc


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
        "date",
        "total_amount",
        "description",
        "category",
        "payment_method",
        "num_installments",
        "installment_amount",
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
