"""One isolation assertion per statistics service.

Cheaper than converting each service's own test module to two tenants, and it
is the assertion that actually matters: a neighbour's spend must never reach
this household's dashboard.
"""

from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.budget_stats import total_diverse_ceiling
from finances.services.category_stats import monthly_diverse_total_median
from finances.services.daily_trend import daily_spend_trend

pytestmark = pytest.mark.django_db


@pytest.fixture
def neighbour_spend(other_user, other_household):
    category = baker.make(
        "finances.Category", user=other_user, household=other_household, name="Vizinho"
    )
    baker.make(
        "finances.Entry",
        user=other_user,
        household=other_household,
        category=category,
        amount=Decimal("999.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )
    return category


def test_diverse_median_excludes_other_households(household, neighbour_spend):
    assert monthly_diverse_total_median(household, as_of=date(2026, 4, 1)) == Decimal("0")


def test_daily_trend_excludes_other_households(household, neighbour_spend):
    rows = daily_spend_trend(household, period=30, as_of=date(2026, 3, 15))

    assert all(row["median"] == Decimal("0") for row in rows)


def test_ceiling_excludes_other_households(household, other_user, other_household):
    baker.make(
        "finances.Category",
        user=other_user,
        household=other_household,
        name="Teto do vizinho",
        budget_ceiling=Decimal("500.00"),
    )

    assert total_diverse_ceiling(household) == Decimal("0")
