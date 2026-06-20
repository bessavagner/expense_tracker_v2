from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.projection import build_projection


def _e(user, cat, pm, amount, bm, et=EntryType.REGULAR):
    return baker.make("finances.Entry", user=user, date=bm, amount=Decimal(amount),
                      category=cat, payment_method=pm, entry_type=et,
                      billing_month=bm, billing_month_override=True)


@pytest.fixture
def cat(user):
    return baker.make("finances.Category", user=user, name="Alimentação")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestEstimatedTrack:
    TODAY = date(2026, 6, 20)  # window mar/abr/mai

    def _seed_avg_1000(self, user, cat, pix):
        for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
            _e(user, cat, pix, "1000", bm)

    def test_future_month_uses_average(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        rows = build_projection(user, date(2026, 6, 1), 2, today=self.TODAY)
        july = next(r for r in rows if r["month"] == date(2026, 7, 1))
        assert july["diverse"] == Decimal("0")          # nothing posted
        assert july["diverse_estimated"] == Decimal("1000.00")

    def test_past_month_estimated_equals_real(self, user, cat, pix):
        m = date(2026, 5, 1)
        _e(user, cat, pix, "750", m)
        rows = build_projection(user, m, 1, today=self.TODAY)
        assert rows[0]["diverse"] == Decimal("750")
        assert rows[0]["diverse_estimated"] == Decimal("750")

    def test_current_month_max_actual_over_average(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        _e(user, cat, pix, "1400", date(2026, 6, 1))  # already over average
        rows = build_projection(user, date(2026, 6, 1), 1, today=self.TODAY)
        assert rows[0]["diverse_estimated"] == Decimal("1400.00")

    def test_current_month_average_when_under(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        _e(user, cat, pix, "200", date(2026, 6, 1))  # under average
        rows = build_projection(user, date(2026, 6, 1), 1, today=self.TODAY)
        assert rows[0]["diverse_estimated"] == Decimal("1000.00")

    def test_acumulado_estimado_accumulates(self, user, cat, pix):
        self._seed_avg_1000(user, cat, pix)
        baker.make("finances.Income", user=user, amount=Decimal("3000"), month=date(2026, 7, 1))
        rows = build_projection(user, date(2026, 7, 1), 1, today=self.TODAY)
        r = rows[0]
        assert r["saldo_projetado_estimado"] == r["income"] - r["total_estimated"]
