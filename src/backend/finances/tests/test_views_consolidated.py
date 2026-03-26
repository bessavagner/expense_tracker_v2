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
def consolidated_data(user):
    cat_food = baker.make("finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300.00"))
    cat_fuel = baker.make("finances.Category", user=user, name="Combustível", budget_ceiling=Decimal("460.00"))
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    # March entries
    baker.make("finances.Entry", user=user, date=date(2026, 3, 5), amount=Decimal("500.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 10), amount=Decimal("800.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    baker.make("finances.Entry", user=user, date=date(2026, 3, 15), amount=Decimal("200.00"),
               category=cat_fuel, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="regular")
    # Feb entry
    baker.make("finances.Entry", user=user, date=date(2026, 2, 10), amount=Decimal("100.00"),
               category=cat_food, payment_method=pix, billing_month=date(2026, 2, 1), entry_type="regular")
    return {"cat_food": cat_food, "cat_fuel": cat_fuel}


@pytest.mark.django_db
class TestConsolidatedView:
    def test_page_renders(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/")
        assert response.status_code == 200
        assert "consolidated/consolidated_page.html" in [t.name for t in response.templates]

    def test_aggregation_by_category(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026")
        data = response.context["aggregation"]
        # Find Alimentação row
        food_row = next(r for r in data if r["category__name"] == "Alimentação")
        assert food_row["months"][3] == Decimal("1300.00")  # 500 + 800
        assert food_row["months"][2] == Decimal("100.00")

    def test_budget_status(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026")
        data = response.context["aggregation"]
        food_row = next(r for r in data if r["category__name"] == "Alimentação")
        # 1300 / 1300 ceiling = 100% → danger (>= 1.0)
        assert food_row["budget_status"][3] == "danger"

    def test_systemics_tab(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, name="Custeio", is_system=True)
        pix = baker.make("finances.PaymentMethod", user=user, type="pix")
        baker.make("finances.Entry", user=user, date=date(2026, 3, 1), amount=Decimal("460.00"),
                   category=cat, payment_method=pix, billing_month=date(2026, 3, 1), entry_type="systemic")
        response = logged_client.get("/consolidated/systemics/?year=2026")
        assert response.status_code == 200

    def test_htmx_returns_fragment(self, logged_client, consolidated_data):
        response = logged_client.get("/consolidated/?year=2026", HTTP_HX_REQUEST="true")
        assert "consolidated/_consolidated_table.html" in [t.name for t in response.templates]


@pytest.mark.django_db
class TestCategoryDetailView:
    def test_detail_returns_entries(self, logged_client, consolidated_data):
        cat_food = consolidated_data["cat_food"]
        response = logged_client.get(
            f"/consolidated/detail/{cat_food.id}/2026/3/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        entries = response.context["entries"]
        assert len(entries) == 2
        assert all(e.category == cat_food for e in entries)
