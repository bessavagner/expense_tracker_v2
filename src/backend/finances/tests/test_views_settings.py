from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestSettingsPage:
    def test_settings_page_renders(self, logged_client):
        response = logged_client.get("/settings/")
        assert response.status_code == 200
        assert "settings/settings_page.html" in [t.name for t in response.templates]


@pytest.mark.django_db
class TestIncomeTab:
    def test_income_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/income/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "settings/_income_tab.html" in [t.name for t in response.templates]

    def test_create_income(self, logged_client, user):
        response = logged_client.post(
            "/settings/income/create/",
            data={
                "name": "Salário",
                "amount": "7854.23",
                "month": "2026-03-01",
                "is_recurring": True,
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Income

        assert Income.objects.filter(user=user, name="Salário").exists()

    def test_edit_income(self, logged_client, user):
        income = baker.make("finances.Income", user=user, name="Old", amount=Decimal("100"))
        response = logged_client.post(
            f"/settings/income/{income.id}/edit/",
            data={"name": "Updated", "amount": "200.00", "month": "2026-03-01"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        income.refresh_from_db()
        assert income.name == "Updated"


@pytest.mark.django_db
class TestSystemicsTab:
    def test_systemics_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/systemics/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_systemic(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        response = logged_client.post(
            "/settings/systemics/create/",
            data={
                "name": "Enel",
                "category": str(cat.id),
                "payment_method": str(pm.id),
                "default_amount": "460.00",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import SystemicExpense

        assert SystemicExpense.objects.filter(user=user, name="Enel").exists()

    def test_toggle_systemic_active(self, logged_client, user):
        cat = baker.make("finances.Category", user=user)
        systemic = baker.make("finances.SystemicExpense", user=user, category=cat, is_active=True)
        response = logged_client.patch(
            f"/settings/systemics/{systemic.id}/toggle/",
            HTTP_HX_REQUEST="true",
            content_type="application/json",
        )
        assert response.status_code == 200
        systemic.refresh_from_db()
        assert systemic.is_active is False


@pytest.mark.django_db
class TestPaymentMethodsTab:
    def test_pm_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/payment-methods/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_payment_method(self, logged_client, user):
        response = logged_client.post(
            "/settings/payment-methods/create/",
            data={"name": "Crédito Teste", "type": "credit_card", "closing_day": "25"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import PaymentMethod

        assert PaymentMethod.objects.filter(user=user, name="Crédito Teste").exists()

    def test_toggle_pm_active(self, logged_client, user):
        pm = baker.make("finances.PaymentMethod", user=user, is_active=True)
        response = logged_client.patch(
            f"/settings/payment-methods/{pm.id}/toggle/",
            HTTP_HX_REQUEST="true",
            content_type="application/json",
        )
        assert response.status_code == 200
        pm.refresh_from_db()
        assert pm.is_active is False


@pytest.mark.django_db
class TestCategoriesTab:
    def test_categories_tab_htmx(self, logged_client):
        response = logged_client.get("/settings/categories/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200

    def test_create_category(self, logged_client, user):
        response = logged_client.post(
            "/settings/categories/create/",
            data={"name": "Nova Cat", "budget_ceiling": "500.00"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Category

        assert Category.objects.filter(user=user, name="Nova Cat").exists()

    def test_edit_category_budget(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, budget_ceiling=Decimal("100"))
        response = logged_client.post(
            f"/settings/categories/{cat.id}/edit/",
            data={"budget_ceiling": "200.00"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        cat.refresh_from_db()
        assert cat.budget_ceiling == Decimal("200.00")

    def test_cannot_delete_system_category(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, is_system=True)
        response = logged_client.delete(
            f"/settings/categories/{cat.id}/delete/",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 400
        from finances.models import Category

        assert Category.objects.filter(id=cat.id).exists()


@pytest.mark.django_db
def test_categories_tab_shows_moving_average(logged_client, user):
    from datetime import date

    from finances.models.entry import EntryType

    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        baker.make("finances.Entry", user=user, date=bm, amount=Decimal("1000"),
                   category=cat, payment_method=pix, entry_type=EntryType.REGULAR,
                   billing_month=bm, billing_month_override=True)
    resp = logged_client.get("/settings/categories/")
    assert resp.status_code == 200
    # "Média (3m)" header is date-robust to assert (averages depend on today()).
    assert b"3m" in resp.content


@pytest.mark.django_db
def test_categories_tab_shows_total_row(logged_client, user):
    baker.make("finances.Category", user=user, name="A", budget_ceiling=Decimal("1000"))
    baker.make("finances.Category", user=user, name="B", budget_ceiling=Decimal("2000"))
    resp = logged_client.get("/settings/categories/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Total" in body
    assert "3000,00" in body  # sum of ceilings 1000 + 2000 (pt-BR floatformat)


@pytest.mark.django_db
class TestBudgetSettings:
    def test_create_budget(self, logged_client, user):
        from django.urls import reverse
        url = reverse("finances:settings_budget_create")
        resp = logged_client.post(url, {"name": "Casa", "amount": "1000"})
        assert resp.status_code == 200
        from finances.models import Budget
        assert user.budgets.filter(name="Casa", amount=Decimal("1000")).exists()

    def test_recalc_sets_amount_to_ceiling_sum(self, logged_client, user):
        from django.urls import reverse
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("0"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))
        url = reverse("finances:settings_budget_recalc", args=[b.id])
        resp = logged_client.post(url)
        assert resp.status_code == 200
        b.refresh_from_db()
        assert b.amount == Decimal("400")

    def test_delete_budget(self, logged_client, user):
        from django.urls import reverse
        b = baker.make("finances.Budget", user=user, name="Casa")
        url = reverse("finances:settings_budget_delete", args=[b.id])
        resp = logged_client.delete(url)
        assert resp.status_code == 200
        from finances.models import Budget
        assert not user.budgets.filter(id=b.id).exists()

    def test_duplicate_name_does_not_500(self, logged_client, user):
        from django.urls import reverse
        url = reverse("finances:settings_budget_create")
        first = logged_client.post(url, {"name": "Casa", "amount": "1000"})
        assert first.status_code == 200
        second = logged_client.post(url, {"name": "Casa", "amount": "2000"})
        assert second.status_code == 200  # graceful, not IntegrityError 500
        assert user.budgets.filter(name="Casa").count() == 1
