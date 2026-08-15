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
    # One entry per photo. A till roll longer than an arm gets photographed in
    # two overlapping shots, and production already handles that: `extract_receipt`
    # takes a LIST of images and reads them as one document. A case that pinned a
    # single photo could not represent the longest receipt in the set.
    images: list[str]
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
    # ISO YYYY-MM-DD, or None when the document does not print one. Marketplace
    # order screens often do not, and EXTRACTION_PROMPT tells the model to leave
    # such a field null — so `None` here is a real expectation, not missing data.
    date: str | None = None
    payment_hint: str | None = None
    discount: Decimal = Decimal("0")
    # None when no total is printed. Scoring then expects the model to return
    # None as well: inventing a total it could not read is the failure mode.
    amount_paid: Decimal | None = None
    items: list[TruthItem]

    @property
    def items_total(self) -> Decimal:
        return sum((i.line_total for i in self.items), Decimal("0"))

    def image_paths(self) -> list[Path] | None:
        """Every photo of this receipt, or ``None`` if any one is unresolvable.

        All-or-nothing on purpose: reading page 1 of a two-page receipt and
        scoring it against the full gabarito would report a perfect model as
        having missed half the items.
        """
        root = (settings.EVAL_FIXTURES_DIR or "").strip()
        paths: list[Path] = []
        for name in self.images:
            if self.image_source == "tracked":
                path = TRACKED_FIXTURES_DIR / name
            else:
                if not root:
                    return None
                path = Path(root) / name
            if not path.exists():
                return None
            paths.append(path)
        return paths or None

    def read_images(self) -> list[tuple[bytes, str]]:
        """``[(data, media_type), ...]``, shaped for ``build_extraction_prompt``."""
        paths = self.image_paths()
        if paths is None:
            raise DatasetError(f"{self.id}: image(s) {self.images!r} not found")
        return [(p.read_bytes(), self.media_type) for p in paths]


def arithmetic_error(case: ReceiptCase) -> str | None:
    """``None`` when the ground truth adds up, else a message saying how it does not.

    The rule is exact, not tolerant: these numbers were typed by a person off a
    piece of paper, and a one-cent slip is a typo, not a rounding artefact.
    """
    if not case.items:
        return "a case with no items cannot be scored"
    if case.amount_paid is None:
        # Nothing to reconcile against — the document prints no total. Guard the
        # one thing that is still checkable: a case that also declares a discount
        # is claiming arithmetic it has no total to support.
        if case.discount:
            return f"discount {case.discount} declared, but no amount_paid to reconcile it with"
    else:
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
        if case.image_paths() is None:
            skipped.append(case.id)
        else:
            runnable.append(case)
    return runnable, skipped
