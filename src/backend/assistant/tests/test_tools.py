from datetime import date
from decimal import Decimal

import pytest

from assistant.agents.tools import create_entry, list_categories, list_payment_methods


@pytest.mark.django_db
class TestListCategories:
    def test_returns_user_categories(self, seeded_user):
        result = list_categories(seeded_user)
        assert "Alimentação" in result
        assert "Lanche" in result
        assert "Álcool" in result

    def test_excludes_other_users(self, seeded_user, db):
        from model_bakery import baker

        other = baker.make("core.CustomUser")
        baker.make("finances.Category", user=other, name="OtherCat")
        result = list_categories(seeded_user)
        assert "OtherCat" not in result


@pytest.mark.django_db
class TestListPaymentMethods:
    def test_returns_user_pms(self, seeded_user):
        result = list_payment_methods(seeded_user)
        assert "Pix" in result
        assert "Crédito C6" in result

    def test_excludes_inactive(self, seeded_user):
        from model_bakery import baker

        baker.make(
            "finances.PaymentMethod",
            user=seeded_user,
            name="Inactive",
            type="pix",
            is_active=False,
        )
        result = list_payment_methods(seeded_user)
        assert "Inactive" not in result


@pytest.mark.django_db
class TestCreateEntry:
    def test_creates_entry(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Supermercado Cosmos",
            category_name="Alimentação",
            payment_method_name="Pix",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        from finances.models import Entry

        entry = Entry.objects.get(user=seeded_user, description="Supermercado Cosmos")
        assert entry.amount == Decimal("50.00")
        assert entry.category.name == "Alimentação"
        assert entry.payment_method.name == "Pix"

    def test_computes_billing_month(self, seeded_user):
        create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="100.00",
            description="Test CC",
            category_name="Alimentação",
            payment_method_name="Crédito C6",
        )
        from finances.models import Entry

        entry = Entry.objects.get(user=seeded_user, description="Test CC")
        # March 27 with C6 closing day 25 → April billing
        assert entry.billing_month == date(2026, 4, 1)

    def test_invalid_category_returns_error(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Test",
            category_name="NonExistent",
            payment_method_name="Pix",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()
        from finances.models import Entry

        assert not Entry.objects.filter(user=seeded_user, description="Test").exists()

    def test_invalid_payment_method_returns_error(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-03-27",
            amount_str="50.00",
            description="Test",
            category_name="Alimentação",
            payment_method_name="NonExistent",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()

    def test_negative_amount_for_refund(self, seeded_user):
        create_entry(
            user=seeded_user,
            date_str="2026-03-17",
            amount_str="-150.00",
            description="Amanda - reembolso",
            category_name="Alimentação",
            payment_method_name="Pix",
        )
        from finances.models import Entry

        entry = Entry.objects.get(user=seeded_user, description="Amanda - reembolso")
        assert entry.amount == Decimal("-150.00")
