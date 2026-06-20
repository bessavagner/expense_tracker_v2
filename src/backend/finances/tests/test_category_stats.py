from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.category_stats import (
    category_moving_averages,
    category_moving_averages_named,
)


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
class TestCategoryMovingAverages:
    AS_OF = date(2026, 6, 20)  # window = mar, abr, mai

    def test_three_full_months_average(self, user, cat, pix):
        _e(user, cat, pix, "900", date(2026, 3, 1))
        _e(user, cat, pix, "1000", date(2026, 4, 1))
        _e(user, cat, pix, "1100", date(2026, 5, 1))
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("1000.00")

    def test_excludes_current_incomplete_month(self, user, cat, pix):
        _e(user, cat, pix, "900", date(2026, 3, 1))
        _e(user, cat, pix, "5000", date(2026, 6, 1))  # current month — ignored
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("900.00")  # only mar had data; /1

    def test_excludes_refunds(self, user, cat, pix):
        _e(user, cat, pix, "1000", date(2026, 3, 1))
        _e(user, cat, pix, "-200", date(2026, 3, 1))  # refund, excluded
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("1000.00")

    def test_partial_history_divides_by_months_with_data(self, user, cat, pix):
        _e(user, cat, pix, "600", date(2026, 4, 1))
        _e(user, cat, pix, "800", date(2026, 5, 1))  # 2 of 3 months
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert avg[cat.id] == Decimal("700.00")  # 1400 / 2

    def test_category_without_spend_absent(self, user, cat, pix):
        avg = category_moving_averages(user, as_of=self.AS_OF)
        assert cat.id not in avg

    def test_entry_type_filter_regular_only(self, user, cat, pix):
        _e(user, cat, pix, "300", date(2026, 4, 1), EntryType.REGULAR)
        _e(user, cat, pix, "900", date(2026, 4, 1), EntryType.SYSTEMIC)
        reg = category_moving_averages(user, as_of=self.AS_OF, entry_type="regular")
        allt = category_moving_averages(user, as_of=self.AS_OF)
        assert reg[cat.id] == Decimal("300.00")
        assert allt[cat.id] == Decimal("1200.00")

    def test_named_sorted_desc(self, user, cat, pix):
        other = baker.make("finances.Category", user=user, name="Lanche")
        _e(user, cat, pix, "1000", date(2026, 4, 1))
        _e(user, other, pix, "200", date(2026, 4, 1))
        named = category_moving_averages_named(user, as_of=self.AS_OF)
        assert [n["name"] for n in named] == ["Alimentação", "Lanche"]
        assert named[0]["avg"] == Decimal("1000.00")
        assert named[0]["months_used"] == 1
