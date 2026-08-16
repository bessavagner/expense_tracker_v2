"""The parsed rows -- derived, never stored.

The old wizard wrote the whole parsed row set into a database-backed session on
the mapping step and rewrote it on the preview step. For a 4000-row file that is
two multi-megabyte session writes per import, and it is why the row set had to
be small enough to serialise, which it was not.

Re-deriving is cheap and it is *correct*: the file and the mapping are the
inputs, parsing is deterministic, and a job's rows can therefore never disagree
with the file it was made from. The cap is 2 MB, so a re-parse is milliseconds.
"""

import csv
from decimal import Decimal

from finances.models import Entry, InstallmentPlan
from finances.services.csv_parser import detect_columns, parse_csv_rows
from finances.services.import_storage import open_text

FIELDS_BY_TYPE = {
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

# Excel writes one on every CSV it saves, and so does our own exporter (it has
# to -- Excel reads BOM-less UTF-8 as Latin-1). Left in place it makes the
# first header unmatchable by detect_columns, so the date column silently fails
# to auto-detect on every file Excel ever touched.
_BOM = "﻿"


def fields_for(import_type: str) -> list[str]:
    return FIELDS_BY_TYPE.get(import_type, FIELDS_BY_TYPE["regular"])


def headers_for(job) -> list[str]:
    """The CSV's header row, for the mapping dropdowns. BOM stripped."""
    with open_text(job.storage_key) as handle:
        headers = next(csv.reader(handle))
    if headers and headers[0].startswith(_BOM):
        headers[0] = headers[0].lstrip(_BOM)
    return headers


def detected_mapping(job) -> dict[str, int]:
    return detect_columns(headers_for(job), job.import_type)


def rows_for(job, *, mark_duplicates: bool = True) -> list[dict]:
    """Parse the stored CSV with the job's mapping, marking known duplicates.

    ``mark_duplicates`` is False for the runner: it has already been told which
    lines to skip, and re-running the duplicate query there would both cost a
    query and change the answer, since the rows created earlier in the same run
    are now themselves in the table.
    """
    mapping = {field: int(index) for field, index in job.column_mapping.items()}
    with open_text(job.storage_key) as handle:
        rows = parse_csv_rows(handle, mapping, job.import_type)
    if mark_duplicates:
        _mark_duplicates(job, rows)
    return rows


def _mark_duplicates(job, rows: list[dict]) -> None:
    """One query for the whole file, narrowed to the dates it mentions.

    Carried over verbatim from the session-based importer (E03 S03-4): a
    per-row ``.exists()`` made this step's cost linear in the file, and a
    500-row statement export is a common import. Narrowing to the file's own
    dates keeps the fetched set small however long the household's history is.
    """
    is_installment = job.import_type == "installment"
    amount_field = "total_amount" if is_installment else "amount"
    candidates = [row for row in rows if row["status"] == "ok"]
    if not candidates:
        return
    dates = {row["date"] for row in candidates}

    model = InstallmentPlan if is_installment else Entry
    already_imported = set(
        model.objects.for_household(job.household)
        .filter(date__in=dates)
        .values_list("date", amount_field, "description")
    )

    for row in candidates:
        key = (row["date"], Decimal(row[amount_field]), row["description"])
        if key in already_imported:
            row["status"] = "duplicate"


def unmatched_names(job, rows: list[dict]) -> tuple[list[str], list[str]]:
    """Category and payment-method names in the file that the household lacks."""
    from finances.models import Category, PaymentMethod

    existing_categories = {
        name.lower()
        for name in Category.objects.for_household(job.household).values_list("name", flat=True)
    }
    existing_pms = {
        name.lower()
        for name in PaymentMethod.objects.for_household(job.household).values_list(
            "name", flat=True
        )
    }

    categories, payment_methods = set(), set()
    for row in rows:
        if row["status"] != "ok":
            continue
        category = row.get("category", "")
        if category and category.lower() not in existing_categories:
            categories.add(category)
        payment_method = row.get("payment_method", "")
        if payment_method and payment_method.lower() not in existing_pms:
            payment_methods.add(payment_method)
    return sorted(categories), sorted(payment_methods)
