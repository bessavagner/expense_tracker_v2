"""Query count on the hot read paths must not scale with row count.

Each test loads a page or endpoint twice — once with a few rows, once with many —
and asserts the query count barely moves. Measuring the *slope* rather than an
absolute bound means these survive refactors that legitimately add or remove a
query, while still failing loudly on an N+1.

E04 rewrites every tenant-scoped queryset in the project. These tests are what
that rewrite gets measured against.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from model_bakery import baker

from finances.models import Entry

BILLING_MONTH = date(2026, 3, 1)


@pytest.fixture
def scenario(user):
    """Categories and payment methods; entries are added per measurement."""
    categories = [
        baker.make("finances.Category", user=user, name=name)
        for name in ("Alimentação", "Lazer", "Casa", "Saúde")
    ]
    pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.Income",
        user=user,
        name="Salário",
        amount=Decimal("5000"),
        month=BILLING_MONTH,
    )
    return categories, pm


def _add_entries(user, categories, pm, count):
    Entry.objects.bulk_create(
        [
            Entry(
                user=user,
                date=date(2026, 3, 1 + (i % 27)),
                amount=Decimal("25.00"),
                description=f"lançamento {i}",
                category=categories[i % len(categories)],
                payment_method=pm,
                billing_month=BILLING_MONTH,
                billing_month_override=True,
            )
            for i in range(count)
        ],
        batch_size=200,
    )


def _queries_for(client, path):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"
    return len(captured.captured_queries)


HOT_PATHS = [
    "/api/dashboard/summary/?year=2026&month=3",
    "/api/dashboard/top-categories/?year=2026&month=3",
    "/api/dashboard/evolution/?year=2026&month=3",
    "/api/dashboard/alerts/?year=2026&month=3",
    "/api/dashboard/recent-entries/?year=2026&month=3",
    "/api/dashboard/installments/?year=2026&month=3",
    "/entries/2026/3/",
    "/consolidated/",
    "/projection/?start=2026-03&months=6",
    # Renders settings/_systemics_tab.html, which dereferences .category and
    # .payment_method per row — the other paths cover the three remaining
    # templates that do the same.
    "/settings/systemics/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("path", HOT_PATHS)
def test_query_count_does_not_scale_with_rows(logged_client, user, scenario, path):
    categories, pm = scenario

    _add_entries(user, categories, pm, 5)
    logged_client.get(path)  # warm any per-session work out of the measurement
    few = _queries_for(logged_client, path)

    _add_entries(user, categories, pm, 95)
    many = _queries_for(logged_client, path)

    assert many <= few + 2, (
        f"{path}: {few} queries at 5 entries, {many} at 100 — the count scales with row count (N+1)"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("path", HOT_PATHS)
def test_query_count_does_not_scale_with_categories_and_budgets(
    logged_client, user, scenario, path
):
    """The second dimension, and the one row count cannot see.

    ``AlertsView`` loops over budgets and over orphan categories rather than over
    entries (``finances/api/views.py``, ``budget_spend_for_month`` and
    ``orphan_category_spend_for_month``), so an N+1 there would be invisible to
    the test above however many entries it creates. The baseline measurement
    showed this endpoint issuing 7 queries against one seeded database and 9
    against another with the same code, which is what prompted this guard.
    """
    categories, pm = scenario
    _add_entries(user, categories, pm, 20)
    logged_client.get(path)
    few = _queries_for(logged_client, path)

    for i in range(20):
        budget = baker.make(
            "finances.Budget", user=user, name=f"orçamento {i}", amount=Decimal(500)
        )
        extra = baker.make(
            "finances.Category",
            user=user,
            name=f"categoria extra {i}",
            budget=budget,
            budget_ceiling=Decimal(100),
        )
        _add_entries(user, [extra], pm, 2)
    many = _queries_for(logged_client, path)

    assert many <= few + 2, (
        f"{path}: {few} queries with 4 categories and no budgets, {many} with 24 "
        f"categories and 20 budgets — the count scales with them (N+1)"
    )
