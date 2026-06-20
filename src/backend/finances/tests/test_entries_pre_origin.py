"""Months before the projection origin (nov/2025) must degrade gracefully.

`build_projection` returns no rows for a month that precedes the origin, so the
entries summary cannot derive projection figures. It must NOT blow up with an
IndexError (regression: GET /entries/2025/10/ returned a 500).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker

from finances.views.entries import compute_entry_summary


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


def _regular(user, d, amount, billing_month):
    return baker.make(
        "finances.Entry",
        user=user,
        date=d,
        amount=Decimal(amount),
        category=baker.make("finances.Category", user=user),
        payment_method=baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix"),
        entry_type="regular",
        billing_month=billing_month,
    )


@pytest.mark.django_db
class TestPreOriginSummary:
    def test_summary_before_origin_does_not_raise(self, user):
        # October 2025 precedes the projection origin (nov/2025).
        _regular(user, date(2025, 10, 15), "100.00", date(2025, 10, 1))

        summary = compute_entry_summary(user, 2025, 10)

        assert summary["before_origin"] is True
        assert summary["total_lancado"] == Decimal("100.00")
        assert summary["entry_count"] == 1
        # Projection-derived figures don't apply; zeroed so the template renders.
        assert summary["total_gastos"] == Decimal("0")
        assert summary["saldo_projetado"] == Decimal("0")
        assert summary["acumulado"] == Decimal("0")
        assert summary["origin_month"] == date(2025, 11, 1)

    def test_summary_in_origin_not_flagged(self, user):
        _regular(user, date(2026, 1, 10), "100.00", date(2026, 1, 1))

        summary = compute_entry_summary(user, 2026, 1)

        assert summary["before_origin"] is False
        assert summary["total_gastos"] == Decimal("100.00")

    def test_entries_page_before_origin_returns_200_with_notice(self, logged_client, user):
        _regular(user, date(2025, 10, 15), "100.00", date(2025, 10, 1))

        response = logged_client.get("/entries/2025/10/")

        assert response.status_code == 200
        assert "origem da projeção" in response.content.decode()


@pytest.mark.django_db
class TestEntriesListShowsAll:
    def test_renders_all_entries_when_more_than_100(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        # 124 entries in nov/2025 — the oldest (day 1) must still be reachable.
        for i in range(124):
            day = (i % 28) + 1
            baker.make(
                "finances.Entry",
                user=user,
                date=date(2025, 11, day),
                amount=Decimal("10.00"),
                description=f"Lanc {i}",
                category=cat,
                payment_method=pix,
                entry_type="regular",
                billing_month=date(2025, 11, 1),
            )

        response = logged_client.get("/entries/2025/11/")

        assert response.status_code == 200
        assert len(response.context["entries"]) == 124
