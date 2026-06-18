from datetime import date

import pytest
from model_bakery import baker

from core.models import CustomUser
from finances.models import PaymentMethod
from finances.services.billing import installment_billing_months


@pytest.mark.django_db
class TestInstallmentBillingMonths:
    def _pm(self, **kwargs):
        user = baker.make(CustomUser)
        return baker.make(PaymentMethod, user=user, **kwargs)

    def test_credit_card_after_closing_pushes_first_two_months_out(self):
        """Compra 12/06 num cartão que fecha dia 5 (após fechamento) → fatura
        fecha em julho e é paga em agosto: 1ª parcela em agosto."""
        pm = self._pm(type="credit_card", closing_day=5)
        months = installment_billing_months(date(2026, 6, 12), pm, 3)
        assert months == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]

    def test_credit_card_before_closing_pushes_first_to_payment_month(self):
        """Compra 12/06 num cartão que fecha dia 25 (antes do fechamento) →
        fatura fecha em junho e é paga em julho: 1ª parcela em julho."""
        pm = self._pm(type="credit_card", closing_day=25)
        months = installment_billing_months(date(2026, 6, 12), pm, 3)
        assert months == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]

    def test_pix_keeps_first_in_purchase_month(self):
        pm = self._pm(type="pix")
        months = installment_billing_months(date(2026, 6, 12), pm, 2)
        assert months == [date(2026, 6, 1), date(2026, 7, 1)]

    def test_credit_card_without_closing_day_keeps_first_in_purchase_month(self):
        pm = self._pm(type="credit_card", closing_day=None)
        months = installment_billing_months(date(2026, 6, 12), pm, 2)
        assert months == [date(2026, 6, 1), date(2026, 7, 1)]

    def test_year_rollover(self):
        pm = self._pm(type="pix")
        months = installment_billing_months(date(2026, 11, 10), pm, 3)
        assert months == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)]
