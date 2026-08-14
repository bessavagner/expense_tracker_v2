"""The golden dataset: real receipts plus hand-written ground truth.

Ground truth is the expensive part and the part that must be right — a wrong
gabarito silently teaches the harness to prefer a worse model. So it is
committed JSON, reviewed like code, and every case is arithmetic-checked by the
normal test suite.

The IMAGES are deliberately not committed (plan decision D-A): this repository
is public and these are real household receipts. ``image_source="private"``
resolves under ``settings.EVAL_FIXTURES_DIR``; a case whose image is missing is
SKIPPED, so a fresh clone and CI both stay green.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from django.conf import settings
from pydantic import BaseModel

CASES_DIR = Path(__file__).parent / "cases"
TRACKED_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


class DatasetError(Exception):
    """A case file is missing, unparseable, or asked for by an unknown id."""


class TruthItem(BaseModel):
    """One line of the receipt, as a human read it off the paper."""

    description: str
    line_total: Decimal
    category: str
    quantity: Decimal = Decimal("1")


class PaymentMethodSpec(BaseModel):
    """A payment method the harness seeds for this case (plan decision D-B)."""

    name: str
    type: str  # "cash" | "pix" | "credit_card"
    closing_day: int | None = None


class ReceiptCase(BaseModel):
    """One scored receipt: an image plus everything a correct read produces."""

    id: str
    image: str
    image_source: Literal["tracked", "private"]
    media_type: str
    provenance: str
    hard_cases: list[str] = []
    categories: list[str]
    payment_methods: list[PaymentMethodSpec]
    store: str
    # A lowercase substring a correct read must contain. The header says
    # "americanas sa - 1063" and a model may answer "Lojas Americanas"; both are
    # right, and only a substring rule scores them that way.
    store_key: str
    date: str  # ISO YYYY-MM-DD
    payment_hint: str | None = None
    discount: Decimal = Decimal("0")
    amount_paid: Decimal
    items: list[TruthItem]

    @property
    def items_total(self) -> Decimal:
        return sum((i.line_total for i in self.items), Decimal("0"))

    def image_path(self) -> Path | None:
        """Where the photo lives, or ``None`` when it cannot be resolved."""
        if self.image_source == "tracked":
            path = TRACKED_FIXTURES_DIR / self.image
        else:
            root = (settings.EVAL_FIXTURES_DIR or "").strip()
            if not root:
                return None
            path = Path(root) / self.image
        return path if path.exists() else None

    def read_image(self) -> tuple[bytes, str]:
        """``(data, media_type)``, shaped for ``extract_receipt``."""
        path = self.image_path()
        if path is None:
            raise DatasetError(f"{self.id}: image {self.image!r} not found")
        return path.read_bytes(), self.media_type


def arithmetic_error(case: ReceiptCase) -> str | None:
    """``None`` when the ground truth adds up, else a message saying how it does not.

    The rule is exact, not tolerant: these numbers were typed by a person off a
    piece of paper, and a one-cent slip is a typo, not a rounding artefact.
    """
    expected = case.items_total - case.discount
    if expected != case.amount_paid:
        return (
            f"items ({case.items_total}) - discount ({case.discount}) = {expected}, "
            f"but amount_paid is {case.amount_paid}"
        )
    unknown = sorted({i.category for i in case.items} - set(case.categories))
    if unknown:
        return f"items use categories not declared in `categories`: {unknown}"
    return None


def load_receipt_cases(ids: list[str] | None = None) -> list[ReceiptCase]:
    """Every committed case, or just the ids asked for, ordered by id."""
    cases: dict[str, ReceiptCase] = {}
    for path in sorted(CASES_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path.name}: {exc}") from exc
        case = ReceiptCase(**raw)
        if case.id in cases:
            raise DatasetError(f"duplicate case id {case.id!r} in {path.name}")
        cases[case.id] = case
    if ids is None:
        return list(cases.values())
    missing = [i for i in ids if i not in cases]
    if missing:
        raise DatasetError(f"unknown case id(s): {', '.join(missing)}")
    return [cases[i] for i in ids]


def available_receipt_cases(
    ids: list[str] | None = None,
) -> tuple[list[ReceiptCase], list[str]]:
    """Split the dataset into runnable cases and ids skipped for a missing image."""
    runnable: list[ReceiptCase] = []
    skipped: list[str] = []
    for case in load_receipt_cases(ids):
        if case.image_path() is None:
            skipped.append(case.id)
        else:
            runnable.append(case)
    return runnable, skipped
