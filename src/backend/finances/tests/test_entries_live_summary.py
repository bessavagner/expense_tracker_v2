from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def march_setup(user):
    category = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for d, amount in [(1, "50.00"), (10, "50.00"), (20, "50.00")]:
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, d),
            amount=Decimal(amount),
            description=f"Entry {d}",
            category=category,
            payment_method=pix,
            billing_month=date(2026, 3, 1),
        )
    # A refund (negative) in the same month.
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 25),
        amount=Decimal("-20.00"),
        description="Estorno",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 3, 1),
    )
    return {"category": category, "pix": pix}


@pytest.mark.django_db
class TestEntriesSummaryView:
    def test_requires_login(self):
        response = Client().get("/entries/2026/3/summary/")
        assert response.status_code in (302, 401, 403)

    def test_renders_summary_partial_with_totals(self, logged_client, march_setup):
        response = logged_client.get("/entries/2026/3/summary/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "entries/_entries_summary.html" in [t.name for t in response.templates]
        summary = response.context["summary"]
        assert summary["total_expenses"] == Decimal("150.00")
        assert summary["total_returns"] == Decimal("20.00")
        assert summary["net"] == Decimal("130.00")
        assert summary["entry_count"] == 4

    def test_scoped_to_user(self, logged_client, other_user):
        cat = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            amount=Decimal("999.00"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/entries/2026/3/summary/", HTTP_HX_REQUEST="true")
        assert response.context["summary"]["total_expenses"] == Decimal("0")


@pytest.mark.django_db
class TestMutationsTriggerSummaryRefresh:
    """Every entry mutation emits `entries-changed` so the top totals refresh."""

    def _cat_pm(self, user):
        return (
            baker.make("finances.Category", user=user),
            baker.make("finances.PaymentMethod", user=user, type="pix"),
        )

    def test_inline_create_triggers(self, logged_client, user):
        cat, pm = self._cat_pm(user)
        response = logged_client.post(
            "/entries/create/",
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "x",
                "category": str(cat.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert "entries-changed" in response.headers.get("HX-Trigger", "")

    def test_delete_triggers(self, logged_client, user):
        cat, pm = self._cat_pm(user)
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.delete(f"/entries/{entry.id}/delete/", HTTP_HX_REQUEST="true")
        assert "entries-changed" in response.headers.get("HX-Trigger", "")

    def test_inline_edit_triggers(self, logged_client, user):
        cat, pm = self._cat_pm(user)
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            amount=Decimal("50.00"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.post(
            f"/entries/{entry.id}/edit/",
            data={
                "date": "2026-03-15",
                "amount": "75.00",
                "description": "Updated",
                "category": str(cat.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert "entries-changed" in response.headers.get("HX-Trigger", "")

    def test_modal_regular_create_triggers(self, logged_client, user):
        cat, pm = self._cat_pm(user)
        response = logged_client.post(
            "/entries/modal/",
            data={
                "entry_mode": "regular",
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "modal",
                "category": str(cat.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert "entries-changed" in response.headers.get("HX-Trigger", "")

    def test_edit_modal_triggers(self, logged_client, user):
        cat, pm = self._cat_pm(user)
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            amount=Decimal("50.00"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.post(
            f"/entries/{entry.id}/edit-modal/",
            data={
                "date": "2026-03-15",
                "amount": "75.00",
                "description": "Updated",
                "category": str(cat.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert "entries-changed" in response.headers.get("HX-Trigger", "")
