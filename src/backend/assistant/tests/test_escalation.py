"""When a cheap read is not good enough to keep."""

from decimal import Decimal

from assistant.agents.escalation import should_escalate
from assistant.agents.extraction import ReceiptExtraction, ReceiptItem


def read(items, *, paid="10.00", confidence=0.9):
    return ReceiptExtraction(
        store="Loja",
        date="2026-06-12",
        discount=Decimal("0"),
        amount_paid=Decimal(paid) if paid is not None else None,
        confidence=confidence,
        items=items,
    )


ONE_ITEM = [ReceiptItem(description="X", line_total=Decimal("10.00"), category="Casa")]


class TestEscalates:
    def test_a_failed_call_escalates(self):
        assert should_escalate(None) == "error"

    def test_an_empty_read_escalates(self):
        assert should_escalate(read([])) == "no_items"

    def test_low_confidence_escalates(self):
        assert (
            should_escalate(read(ONE_ITEM, confidence=0.4), min_confidence=0.6) == "low_confidence"
        )

    def test_items_that_do_not_cover_the_total_escalate(self):
        """The money invariant is the gate the whole epic protects."""
        assert should_escalate(read(ONE_ITEM, paid="99.00")) == "inconsistent"


class TestAccepts:
    def test_a_confident_reconciling_read_is_kept(self):
        assert should_escalate(read(ONE_ITEM)) is None

    def test_a_receipt_with_no_printed_total_is_kept(self):
        """`amount_paid=None` is a correct read, not a failure to reconcile."""
        assert should_escalate(read(ONE_ITEM, paid=None)) is None

    def test_confidence_exactly_at_the_threshold_is_kept(self):
        """The threshold is a floor, not a wall — spending money on a tie is waste."""
        assert should_escalate(read(ONE_ITEM, confidence=0.6), min_confidence=0.6) is None


class TestPrecedence:
    def test_the_money_invariant_is_reported_over_confidence(self):
        """Both fire; the reported reason must be the one that tunes the threshold."""
        assert should_escalate(read(ONE_ITEM, paid="99.00", confidence=0.1)) == "inconsistent"


class TestTheThresholdDefaultsToSettings:
    def test_the_setting_is_read_lazily_not_at_import(self, settings):
        """Importing this module must never touch Django settings."""
        settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE = 0.95
        assert should_escalate(read(ONE_ITEM, confidence=0.9)) == "low_confidence"

    def test_a_read_above_the_configured_floor_is_kept(self, settings):
        settings.ASSISTANT_ESCALATE_MIN_CONFIDENCE = 0.5
        assert should_escalate(read(ONE_ITEM, confidence=0.55)) is None


class TestTheLedgerFigureIsWhatMustReconcile:
    """What reaches the ledger is `items - discount`, so that is the gate.

    Found by the E09 matrix, not by review: the escalating pipeline scored 0.689
    on the money invariant against a 0.711 gate while escalating only 22% of the
    time, because the dominant failure in the dataset never tripped the rule.
    """

    def test_a_net_line_plus_a_printed_discount_escalates(self):
        """Ultrafarma, verbatim: 40,00 line, 20,00 discount, 40,00 paid.

        `items` alone covers the total, so `receipt_is_consistent` is happy. The
        entry this would write is R$20 for a R$40 purchase.
        """
        read = ReceiptExtraction(
            store="Ultrafarma",
            date="2026-08-12",
            confidence=0.9,
            amount_paid=Decimal("40.00"),
            discount=Decimal("20.00"),
            items=[
                ReceiptItem(description="LENCOS", line_total=Decimal("40.00"), category="Higiene")
            ],
        )
        assert should_escalate(read) == "discount_mismatch"

    def test_gross_lines_with_the_same_printed_discount_are_kept(self):
        """The other correct reading of the same receipt. It reconciles."""
        read = ReceiptExtraction(
            store="Ultrafarma",
            date="2026-08-12",
            confidence=0.9,
            amount_paid=Decimal("40.00"),
            discount=Decimal("20.00"),
            items=[
                ReceiptItem(description="LENCOS", line_total=Decimal("60.00"), category="Higiene")
            ],
        )
        assert should_escalate(read) is None

    def test_a_missed_line_is_still_reported_as_inconsistent(self):
        """Two different defects, two different reasons — they tune differently."""
        read = ReceiptExtraction(
            store="Loja",
            date="2026-06-12",
            confidence=0.9,
            amount_paid=Decimal("99.00"),
            discount=Decimal("0"),
            items=ONE_ITEM,
        )
        assert should_escalate(read) == "inconsistent"

    def test_a_receipt_with_no_printed_total_is_still_kept(self):
        """No total means nothing to reconcile, in either direction."""
        read = ReceiptExtraction(
            store="Mercado Livre",
            date=None,
            confidence=0.9,
            amount_paid=None,
            discount=Decimal("5.00"),
            items=ONE_ITEM,
        )
        assert should_escalate(read) is None

    def test_five_cents_is_rounding_not_a_defect(self):
        read = ReceiptExtraction(
            store="Loja",
            date="2026-06-12",
            confidence=0.9,
            amount_paid=Decimal("10.05"),
            discount=Decimal("0"),
            items=ONE_ITEM,
        )
        assert should_escalate(read) is None
