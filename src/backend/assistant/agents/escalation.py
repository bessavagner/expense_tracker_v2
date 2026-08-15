"""When a cheap vision read is not good enough to keep (E09 S09-3).

One function, called by BOTH production (`assistant/views.py`) and the eval
harness (`assistant/eval/extraction_runner.py`). That sharing is the point: the
harness scores the escalating pipeline end to end, and a harness that
reimplemented this rule would score a pipeline that does not ship.

Pure by construction — no I/O, no database, no settings read at import time — so
the decision is unit-testable without a provider and cannot drift between the
two callers.
"""

from decimal import Decimal

from assistant.agents.extraction import ReceiptExtraction, receipt_is_consistent

# Returned in priority order, most diagnostic first. When several signals fire at
# once the reported reason is the one that should drive tuning: "the money did
# not add up" tells you something the confidence score does not.
ERROR = "error"
NO_ITEMS = "no_items"
INCONSISTENT = "inconsistent"
DISCOUNT_MISMATCH = "discount_mismatch"
LOW_CONFIDENCE = "low_confidence"

# The same five cents the production consistency check allows: a rounding
# artefact on a thermal print, not a miscount.
_TOLERANCE = Decimal("0.05")


def _lands_on_the_amount_paid(extraction: ReceiptExtraction) -> bool:
    """Do the model's OWN numbers produce the total it says was paid?

    `receipt_is_consistent` deliberately does NOT subtract the discount, and
    must not start: it exists to catch a line the model failed to read, and
    subtracting an already-embedded discount gave false alarms on receipts that
    print a net "Valor Liquido" (the DROGASIL bug it was written for).

    That makes it one-sided — it only fires when the lines fall BELOW the amount
    paid — and blind to the failure that dominates this dataset: a model that
    reports an already-net line total AND the receipt's printed discount.
    Measured on the E09 matrix, that read escalated 0% of the time while
    scoring 0 on the money invariant, because `items` alone covered the total.
    What reaches the ledger is `items - discount`, so that is what has to land
    on the amount paid.

    Ultrafarma, verbatim from a real run: one line of 40.00, discount 20.00,
    amount paid 40.00. `items` covers the total, so the old check was happy —
    and the entry it would have written is R$20 for a R$40 purchase.
    """
    if extraction.amount_paid is None:
        return True  # nothing printed to reconcile against
    lines = sum((i.line_total for i in extraction.items), Decimal("0"))
    net = lines - (extraction.discount or Decimal("0"))
    return abs(net - extraction.amount_paid) <= _TOLERANCE


def should_escalate(
    extraction: ReceiptExtraction | None,
    *,
    min_confidence: float | None = None,
) -> str | None:
    """Why this read needs a stronger model, or ``None`` to keep it.

    ``extraction=None`` means the first attempt raised. ``min_confidence``
    defaults to ``ASSISTANT_ESCALATE_MIN_CONFIDENCE``, read lazily so importing
    this module never touches Django settings.
    """
    if extraction is None:
        return ERROR
    if not extraction.items:
        return NO_ITEMS
    # Both money checks come before confidence: a model that is confidently
    # wrong about money is the exact failure this epic must not ship, and
    # whether the numbers add up is a fact where confidence is only an opinion.
    #
    # They are separate reasons because they are separate defects and want
    # separate fixes. `inconsistent` means a line was missed; `discount_mismatch`
    # means the lines and the stated discount disagree with the total, which is
    # the pharmacy shape.
    if not receipt_is_consistent(extraction):
        return INCONSISTENT
    if not _lands_on_the_amount_paid(extraction):
        return DISCOUNT_MISMATCH
    if min_confidence is None:
        from django.conf import settings

        min_confidence = settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE
    if extraction.confidence < min_confidence:
        return LOW_CONFIDENCE
    return None
