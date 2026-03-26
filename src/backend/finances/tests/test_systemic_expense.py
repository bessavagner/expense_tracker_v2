from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Custeio", is_system=True)


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestSystemicExpense:
    def test_create_systemic_expense(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Enel",
            category=category,
            payment_method=pix,
            default_amount=Decimal("460.00"),
        )
        assert systemic.name == "Enel"
        assert systemic.default_amount == Decimal("460.00")
        assert systemic.is_active is True

    def test_str_returns_name(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Unimed - Amanda",
            category=category,
            payment_method=pix,
        )
        assert str(systemic) == "Unimed - Amanda"

    def test_nullable_payment_method(self, user, category):
        from finances.models import SystemicExpense

        systemic = SystemicExpense.objects.create(
            user=user,
            name="IPVA",
            category=category,
            payment_method=None,
            default_amount=Decimal("500.00"),
        )
        assert systemic.payment_method is None

    def test_deactivate(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            category=category,
            payment_method=pix,
            is_active=True,
        )
        systemic.is_active = False
        systemic.save()
        systemic.refresh_from_db()
        assert systemic.is_active is False

    def test_generate_monthly_entry(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Brisanet",
            category=category,
            payment_method=pix,
            default_amount=Decimal("104.12"),
        )
        entry = systemic.create_monthly_entry(month=date(2026, 3, 1), amount=Decimal("104.12"))
        assert entry.entry_type == "systemic"
        assert entry.systemic_expense == systemic
        assert entry.billing_month == date(2026, 3, 1)
        assert entry.amount == Decimal("104.12")
        assert entry.description == "Brisanet"

    def test_generate_monthly_entry_custom_amount(self, user, category, pix):
        systemic = baker.make(
            "finances.SystemicExpense",
            user=user,
            name="Enel",
            category=category,
            payment_method=pix,
            default_amount=Decimal("460.00"),
        )
        entry = systemic.create_monthly_entry(month=date(2026, 3, 1), amount=Decimal("1096.21"))
        assert entry.amount == Decimal("1096.21")
