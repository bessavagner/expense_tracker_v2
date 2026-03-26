from datetime import date

from finances.services.billing import compute_billing_month


class TestComputeBillingMonth:
    def test_pix_same_month(self):
        result = compute_billing_month(date(2026, 3, 15), "pix", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_cash_same_month(self):
        result = compute_billing_month(date(2026, 3, 28), "cash", closing_day=None)
        assert result == date(2026, 3, 1)

    def test_credit_card_before_closing_day(self):
        result = compute_billing_month(date(2026, 3, 20), "credit_card", closing_day=25)
        assert result == date(2026, 3, 1)

    def test_credit_card_on_closing_day(self):
        result = compute_billing_month(date(2026, 3, 25), "credit_card", closing_day=25)
        assert result == date(2026, 3, 1)

    def test_credit_card_after_closing_day(self):
        result = compute_billing_month(date(2026, 3, 26), "credit_card", closing_day=25)
        assert result == date(2026, 4, 1)

    def test_credit_card_after_closing_december(self):
        result = compute_billing_month(date(2025, 12, 31), "credit_card", closing_day=25)
        assert result == date(2026, 1, 1)

    def test_credit_card_closing_day_30_february(self):
        result = compute_billing_month(date(2026, 2, 28), "credit_card", closing_day=30)
        assert result == date(2026, 2, 1)

    def test_credit_card_no_closing_day_fallback(self):
        result = compute_billing_month(date(2026, 3, 15), "credit_card", closing_day=None)
        assert result == date(2026, 3, 1)
