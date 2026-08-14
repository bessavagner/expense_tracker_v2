"""Score one extraction against its ground truth. Pure, deterministic, offline.

Two models that are both imperfect cannot be compared with assertions, so every
dimension here is a ratio — except the money invariant, which is a gate. A read
whose items do not reconcile with the amount paid produces a wrong ledger entry
in production; scoring it 0.8 because the descriptions were nice would make the
harness recommend exactly the failure this product cannot afford.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from assistant.agents.extraction import ReceiptExtraction
from assistant.eval.dataset import ReceiptCase

# Below this similarity two descriptions are different products, not a sloppy
# read of the same one. Tuned against the real fixtures: "BACONZITOS B&G ELMA
# CHIPS M" vs "Baconzitos ELMA CHIPS" scores ~0.8; two different snacks ~0.4.
MATCH_THRESHOLD = 0.6

# Same tolerance the production consistency check uses, for the same reason:
# a five-cent gap is a rounding artefact on a thermal print, not a miscount.
MONEY_TOLERANCE = Decimal("0.05")

# Sums to 1.0. Recall dominates because a missed item is a missed expense; store
# and date are cheap to fix by hand and weighted accordingly.
WEIGHTS = {
    "item_recall": 0.35,
    "amount_accuracy": 0.25,
    "item_precision": 0.15,
    "category_accuracy": 0.15,
    "store": 0.05,
    "date": 0.05,
}

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_description(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_description(a), normalize_description(b)).ratio()


@dataclass(frozen=True)
class ExtractionScore:
    """One case, one model, every dimension the epic asked for."""

    case_id: str
    money_ok: bool
    item_recall: float
    item_precision: float
    amount_accuracy: float
    category_accuracy: float
    store_ok: bool
    date_ok: bool
    missed: tuple[str, ...]
    spurious: tuple[str, ...]

    @property
    def overall(self) -> float:
        """Weighted score, or 0.0 when the money invariant failed."""
        if not self.money_ok:
            return 0.0
        return round(
            WEIGHTS["item_recall"] * self.item_recall
            + WEIGHTS["amount_accuracy"] * self.amount_accuracy
            + WEIGHTS["item_precision"] * self.item_precision
            + WEIGHTS["category_accuracy"] * self.category_accuracy
            + WEIGHTS["store"] * (1.0 if self.store_ok else 0.0)
            + WEIGHTS["date"] * (1.0 if self.date_ok else 0.0),
            6,
        )


def _match_items(case: ReceiptCase, ext: ReceiptExtraction) -> dict[int, int]:
    """Greedy truth-index -> extracted-index map. Deterministic by construction.

    Truth items are visited in file order and each takes its best unclaimed
    candidate; ties break to the lowest extracted index. No global optimum is
    attempted — a receipt has tens of lines, not thousands, and a reproducible
    answer matters more here than an optimal one.
    """
    taken: set[int] = set()
    matched: dict[int, int] = {}
    for t_idx, truth in enumerate(case.items):
        best_idx, best_score = None, MATCH_THRESHOLD
        for e_idx, got in enumerate(ext.items):
            if e_idx in taken:
                continue
            score = _similarity(truth.description, got.description)
            if score > best_score:
                best_idx, best_score = e_idx, score
        if best_idx is not None:
            taken.add(best_idx)
            matched[t_idx] = best_idx
    return matched


def _money_ok(case: ReceiptCase, ext: ReceiptExtraction) -> bool:
    """Do the model's own numbers reconcile with what was actually paid?

    Requires BOTH: it reported the right amount paid, and its line totals minus
    its discount land on that amount. Either half alone lets a real bug through
    — the Americanas split reported the right total and produced R$0.00 on one
    category; the Mercado Livre read produced lines that summed to R$66.48 more
    than the order.
    """
    if ext.amount_paid is None:
        return False
    if abs(ext.amount_paid - case.amount_paid) > MONEY_TOLERANCE:
        return False
    lines = sum((i.line_total for i in ext.items), Decimal("0"))
    net = lines - (ext.discount or Decimal("0"))
    return abs(net - case.amount_paid) <= MONEY_TOLERANCE


def score_extraction(case: ReceiptCase, ext: ReceiptExtraction) -> ExtractionScore:
    """Every dimension of one read, against one gabarito."""
    matched = _match_items(case, ext)
    n_truth = len(case.items)
    n_got = len(ext.items)

    amount_hits = 0
    category_hits = 0
    for t_idx, e_idx in matched.items():
        truth, got = case.items[t_idx], ext.items[e_idx]
        if truth.line_total == got.line_total:
            amount_hits += 1
        if (got.category or "").strip().lower() == truth.category.strip().lower():
            category_hits += 1

    claimed = set(matched.values())
    return ExtractionScore(
        case_id=case.id,
        money_ok=_money_ok(case, ext),
        item_recall=(len(matched) / n_truth) if n_truth else 1.0,
        item_precision=(len(matched) / n_got) if n_got else (1.0 if not n_truth else 0.0),
        amount_accuracy=(amount_hits / n_truth) if n_truth else 1.0,
        category_accuracy=(category_hits / n_truth) if n_truth else 1.0,
        store_ok=case.store_key.lower() in normalize_description(ext.store or ""),
        date_ok=ext.date == case.date,
        missed=tuple(case.items[i].description for i in range(n_truth) if i not in matched),
        spurious=tuple(ext.items[i].description for i in range(n_got) if i not in claimed),
    )


@dataclass(frozen=True)
class AggregateScore:
    """A model's performance across the dataset."""

    n: int
    money_ok_rate: float
    item_recall: float
    item_precision: float
    amount_accuracy: float
    category_accuracy: float
    store_accuracy: float
    date_accuracy: float
    overall: float


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def aggregate_extraction(scores: Sequence[ExtractionScore]) -> AggregateScore:
    """Mean of each dimension.

    ``overall`` is the mean of the per-case overalls, so a single money failure
    costs a full case rather than being diluted.
    """
    return AggregateScore(
        n=len(scores),
        money_ok_rate=_mean([1.0 if s.money_ok else 0.0 for s in scores]),
        item_recall=_mean([s.item_recall for s in scores]),
        item_precision=_mean([s.item_precision for s in scores]),
        amount_accuracy=_mean([s.amount_accuracy for s in scores]),
        category_accuracy=_mean([s.category_accuracy for s in scores]),
        store_accuracy=_mean([1.0 if s.store_ok else 0.0 for s in scores]),
        date_accuracy=_mean([1.0 if s.date_ok else 0.0 for s in scores]),
        overall=_mean([s.overall for s in scores]),
    )
