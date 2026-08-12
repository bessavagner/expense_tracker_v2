from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from assistant.agents import analytics
from finances.models.entry import EntryType


@pytest.mark.django_db
def test_category_averages_text(user, household, scope):
    cat = baker.make("finances.Category", user=user, household=household, name="Alimentação")
    pix = baker.make(
        "finances.PaymentMethod", user=user, household=household, name="Pix", type="pix"
    )
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        baker.make(
            "finances.Entry",
            user=user,
            household=household,
            date=bm,
            amount=Decimal("1000"),
            category=cat,
            payment_method=pix,
            entry_type=EntryType.REGULAR,
            billing_month=bm,
            billing_month_override=True,
        )
    out = analytics.category_averages(scope, 2026, 6)
    assert "Alimentação" in out
    assert "1000.00" in out
