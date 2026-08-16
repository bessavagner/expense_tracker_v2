"""Does this household have a ledger at all, or just not in the month on screen?

Frozen because the endpoint defaults to the current month when the query string
omits it, and "the current month" is exactly what the walkthrough's user was
staring at.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models import Category, PaymentMethod

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
URL = "/api/dashboard/ledger-elsewhere/"


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


def _entry(household, when):
    """One expense, billed in its own purchase month.

    Pix rather than a card so `billing_month` is the purchase month and the test
    reads as what it asserts — no invoice arithmetic in the way. The catalogue is
    fetched rather than re-created: a household may hold only one category per
    name, and several of these tests write two entries.
    """
    category, _ = Category.objects.get_or_create(household=household, name="Alimentação")
    payment_method, _ = PaymentMethod.objects.get_or_create(
        household=household, name="Pix", defaults={"type": "pix", "closing_day": None}
    )
    return baker.make(
        "finances.Entry",
        household=household,
        date=when,
        amount=Decimal("10.00"),
        description="compra",
        category=category,
        payment_method=payment_method,
    )


def test_a_household_with_nothing_has_nothing_anywhere(logged_client, household):
    body = logged_client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_entries_in_another_month_are_reported_with_that_month(logged_client, household):
    """The walkthrough's exact shape: an entry in 06/2023, a dashboard on 08/2026,
    and an empty state that currently claims the ledger is empty."""
    _entry(household, date(2023, 6, 4))

    body = logged_client.get(URL).json()

    assert body["has_any"] is True
    assert body["nearest"] == {"year": 2023, "month": 6, "label": "junho/2023"}


def test_entries_in_the_month_on_screen_do_not_count_as_elsewhere(logged_client, household):
    _entry(household, date(2026, 8, 2))

    body = logged_client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_the_nearest_month_wins(logged_client, household):
    """Two candidates, and the one closest to the month on screen is the one a
    user is most likely to have meant."""
    _entry(household, date(2023, 6, 4))
    _entry(household, date(2026, 5, 4))

    body = logged_client.get(URL).json()

    assert body["nearest"]["year"] == 2026
    assert body["nearest"]["month"] == 5


def test_a_tie_prefers_the_more_recent_month(logged_client, household):
    """June and October are both two months from August. Recent data is the more
    useful answer, and a deterministic rule beats whichever row sorted first."""
    _entry(household, date(2026, 6, 4))
    _entry(household, date(2026, 10, 4))

    body = logged_client.get(URL).json()

    assert body["nearest"]["month"] == 10


def test_it_answers_about_the_month_asked_for(logged_client, household):
    _entry(household, date(2023, 6, 4))

    body = logged_client.get(f"{URL}?year=2023&month=6").json()

    assert body == {"has_any": False, "nearest": None}


def test_another_households_entries_are_invisible(logged_client, household, other_household):
    """The scoping test this codebase requires of every read."""
    _entry(other_household, date(2023, 6, 4))

    body = logged_client.get(URL).json()

    assert body == {"has_any": False, "nearest": None}


def test_it_requires_a_login(client):
    assert client.get(URL).status_code in (302, 401, 403)
