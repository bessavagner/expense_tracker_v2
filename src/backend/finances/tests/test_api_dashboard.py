from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker


@pytest.mark.django_db
class TestSummaryEndpoint:
    def test_returns_json(self, logged_client, user):
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

    def test_correct_values(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        # Income
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("5000"))
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("2000"))
        # Expenses
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("500"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 10),
            amount=Decimal("-100"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        data = response.json()
        assert data["income"] == "7000.00"
        assert data["expenses"] == "500.00"
        assert data["returns"] == "100.00"
        assert data["balance"] == "6600.00"

    def test_filters_by_user(self, logged_client, user, other_user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("100"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        other_cat = baker.make("finances.Category", user=other_user)
        other_pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            amount=Decimal("999"),
            category=other_cat,
            payment_method=other_pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=3")
        data = response.json()
        assert data["expenses"] == "100.00"

    def test_empty_month(self, logged_client, user):
        response = logged_client.get("/api/dashboard/summary/?year=2026&month=6")
        data = response.json()
        assert data["income"] == "0.00"
        assert data["expenses"] == "0.00"

    def test_budget_pct_null_when_no_ceiling(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, budget_ceiling=Decimal("0"))
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("500"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        data = logged_client.get("/api/dashboard/summary/?year=2026&month=3").json()
        assert data["budget_pct"] is None

    def test_budget_pct_computed_when_ceiling_set(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, budget_ceiling=Decimal("1000"))
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("500"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        data = logged_client.get("/api/dashboard/summary/?year=2026&month=3").json()
        assert data["budget_pct"] == 50.0

    def test_unauthenticated(self):
        client = Client()
        response = client.get("/api/dashboard/summary/?year=2026&month=3")
        assert response.status_code == 403


@pytest.mark.django_db
class TestTopCategoriesEndpoint:
    def test_returns_top_5(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        for i in range(7):
            cat = baker.make("finances.Category", user=user, name=f"Cat{i}")
            baker.make(
                "finances.Entry",
                user=user,
                date=date(2026, 3, 1),
                amount=Decimal(str((7 - i) * 100)),
                category=cat,
                payment_method=pm,
                billing_month=date(2026, 3, 1),
            )
        response = logged_client.get("/api/dashboard/top-categories/?year=2026&month=3")
        data = response.json()
        assert len(data) == 5
        assert data[0]["amount"] >= data[1]["amount"]


@pytest.mark.django_db
class TestEvolutionEndpoint:
    def test_returns_6_months(self, logged_client, user):
        response = logged_client.get("/api/dashboard/evolution/?year=2026&month=3")
        data = response.json()
        assert len(data) == 6

    def test_includes_expenses_and_income(self, logged_client, user):
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("5000"))
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("1000"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/evolution/?year=2026&month=3")
        data = response.json()
        march = next(m for m in data if m["month"] == "2026-03")
        assert march["expenses"] == "1000.00"
        assert march["income"] == "5000.00"


@pytest.mark.django_db
class TestAlertsEndpoint:
    def test_over_budget_alert(self, logged_client, user):
        cat = baker.make(
            "finances.Category",
            user=user,
            name="Alimentação",
            budget_ceiling=Decimal("100"),
        )
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("150"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/alerts/?year=2026&month=3")
        data = response.json()
        danger_alerts = [a for a in data if a["severity"] == "danger"]
        assert len(danger_alerts) >= 1
        assert "Alimentação" in danger_alerts[0]["message"]

    def test_warning_alert(self, logged_client, user):
        cat = baker.make(
            "finances.Category",
            user=user,
            name="Álcool",
            budget_ceiling=Decimal("100"),
        )
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("95"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/alerts/?year=2026&month=3")
        data = response.json()
        warning_alerts = [a for a in data if a["severity"] == "warning"]
        assert len(warning_alerts) >= 1


@pytest.mark.django_db
class TestRecentEntriesEndpoint:
    def test_returns_5_entries(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        for d in range(1, 8):
            baker.make(
                "finances.Entry",
                user=user,
                date=date(2026, 3, d),
                amount=Decimal("50"),
                description=f"Entry {d}",
                category=cat,
                payment_method=pm,
                billing_month=date(2026, 3, 1),
            )
        response = logged_client.get("/api/dashboard/recent-entries/?year=2026&month=3")
        data = response.json()
        assert len(data) == 5

    def test_ordered_by_date_desc(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 1),
            amount=Decimal("10"),
            description="First",
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 20),
            amount=Decimal("20"),
            description="Last",
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/api/dashboard/recent-entries/?year=2026&month=3")
        data = response.json()
        assert data[0]["description"] == "Last"


@pytest.mark.django_db
class TestInstallmentsEndpoint:
    def test_returns_active_plans(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=30)
        plan = baker.make(
            "finances.InstallmentPlan",
            user=user,
            date=date(2025, 12, 1),
            description="Notebook",
            category=cat,
            payment_method=pm,
            total_amount=Decimal("6699"),
            num_installments=12,
            installment_amount=Decimal("558.25"),
        )
        plan.generate_entries()
        response = logged_client.get("/api/dashboard/installments/?year=2026&month=3")
        data = response.json()
        assert len(data["plans"]) >= 1
        assert "monthly_total" in data


@pytest.mark.django_db
class TestDashboardView:
    def test_dashboard_renders(self, logged_client):
        response = logged_client.get("/")
        assert response.status_code == 200
        assert "dashboard/dashboard_page.html" in [t.name for t in response.templates]

    def test_month_in_context(self, logged_client):
        response = logged_client.get("/?year=2026&month=3")
        assert response.context["current_month"] == 3
        assert response.context["current_year"] == 2026

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/")
        assert response.status_code == 302
