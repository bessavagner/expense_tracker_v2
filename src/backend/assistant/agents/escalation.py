"""When a cheap vision read is not good enough to keep (E09 S09-3).

One function, called by BOTH production (`assistant/views.py`) and the eval
harness (`assistant/eval/extraction_runner.py`). That sharing is the point: the
harness scores the escalating pipeline end to end, and a harness that
reimplemented this rule would score a pipeline that does not ship.

Pure by construction — no I/O, no database, no settings read at import time — so
the decision is unit-testable without a provider and cannot drift between the
two callers.
"""

from assistant.agents.extraction import ReceiptExtraction, receipt_is_consistent

# Returned in priority order, most diagnostic first. When several signals fire at
# once the reported reason is the one that should drive tuning: "the money did
# not add up" tells you something the confidence score does not.
ERROR = "error"
NO_ITEMS = "no_items"
INCONSISTENT = "inconsistent"
LOW_CONFIDENCE = "low_confidence"


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
    # Before confidence: a model that is confidently wrong about money is the
    # exact failure this epic must not ship, and a reconciliation failure is a
    # fact where confidence is only an opinion.
    if not receipt_is_consistent(extraction):
        return INCONSISTENT
    if min_confidence is None:
        from django.conf import settings

        min_confidence = settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE
    if extraction.confidence < min_confidence:
        return LOW_CONFIDENCE
    return None
