from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.whatif import HypotheticalItem, HypoType, simulate_projection_summary


@pytest.mark.django_db
def test_summary_reports_delta(user):
    baker.make("finances.Income", user=user, amount=Decimal("3000"), month=date(2026, 7, 1))
    items = [HypotheticalItem(id="a", type=HypoType.INCOME, label="bônus",
                              amount=Decimal("1000"), month=date(2026, 7, 1))]
    out = simulate_projection_summary(user, items, start=date(2026, 7, 1), months=1,
                                      today=date(2026, 6, 20))
    assert "1000" in out
    assert "2026-07" in out or "07/2026" in out
