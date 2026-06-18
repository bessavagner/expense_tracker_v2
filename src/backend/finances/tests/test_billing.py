from datetime import date

from finances.services.billing import compute_billing_month


class TestComputeBillingMonth:
    """Credit-card purchases are accounted in the month the invoice is *paid*.

    The invoice that closes this cycle is paid the following month, so a
    purchase on/before the closing day counts in M+1; a purchase after the
    closing day rolls to the next invoice and counts in M+2. Cash/Pix always
    count in the purchase month.
    """

    def test_pix_same_month(self):
        result = compute_billing_month(date(2026, 3, 15), "pix", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_cash_same_month(self):
        result = compute_billing_month(date(2026, 3, 28), "cash", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_credit_card_before_closing_day(self):
        # Purchase before closing → invoice closes this month → paid next month.
        result = compute_billing_month(date(2026, 3, 20), "credit_card", closing_day=25)
        assert result == date(2026, 4, 1)

    def test_credit_card_on_closing_day(self):
        result = compute_billing_month(date(2026, 3, 25), "credit_card", closing_day=25)
        assert result == date(2026, 4, 1)

    def test_credit_card_after_closing_day(self):
        # Purchase after closing → next invoice → paid two months out.
        result = compute_billing_month(date(2026, 3, 26), "credit_card", closing_day=25)
        assert result == date(2026, 5, 1)

    def test_credit_card_before_closing_december_rolls_year(self):
        result = compute_billing_month(date(2025, 12, 10), "credit_card", closing_day=25)
        assert result == date(2026, 1, 1)

    def test_credit_card_after_closing_november_rolls_to_january(self):
        # Nov 26 after closing → invoice closes Dec → paid January next year.
        result = compute_billing_month(date(2025, 11, 26), "credit_card", closing_day=25)
        assert result == date(2026, 1, 1)

    def test_credit_card_after_closing_december_rolls_to_february(self):
        result = compute_billing_month(date(2025, 12, 31), "credit_card", closing_day=25)
        assert result == date(2026, 2, 1)

    def test_credit_card_closing_day_30_february(self):
        # Feb 28 ≤ closing 30 → invoice closes Feb → paid March.
        result = compute_billing_month(date(2026, 2, 28), "credit_card", closing_day=30)
        assert result == date(2026, 3, 1)

    def test_credit_card_no_closing_day_fallback(self):
        # No closing day configured → treated like cash/pix (purchase month).
        result = compute_billing_month(date(2026, 3, 15), "credit_card", closing_day=None)
        assert result == date(2026, 3, 1)
