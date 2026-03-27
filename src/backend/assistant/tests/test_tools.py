from datetime import date
from decimal import Decimal

import pytest

from assistant.agents.tools import (
    create_category,
    create_entry,
    create_payment_method,
    list_categories,
    list_payment_methods,
    query_balance,
    query_budget_status,
    query_expenses,
    query_installments,
    update_category_budget,
    update_income,
)
from finances.models import Category, Income, PaymentMethod


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


@pytest.mark.django_db
class TestQueryExpenses:
    def test_total_for_month(self, seeded_user):
        from model_bakery import baker

        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        pm = PaymentMethod.objects.get(user=seeded_user, name="Pix")
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 5),
            amount=Decimal("500"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 10),
            amount=Decimal("300"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        result = query_expenses(seeded_user, 2026, 3)
        assert "800" in result

    def test_filtered_by_category(self, seeded_user):
        from model_bakery import baker

        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        cat2 = Category.objects.get(user=seeded_user, name="Lanche")
        pm = PaymentMethod.objects.get(user=seeded_user, name="Pix")
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 5),
            amount=Decimal("500"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 5),
            amount=Decimal("100"),
            category=cat2,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        result = query_expenses(seeded_user, 2026, 3, category_name="Alimentação")
        assert "500" in result
        assert "100" not in result

    def test_empty_month(self, seeded_user):
        result = query_expenses(seeded_user, 2026, 6)
        assert "0" in result or "nenhum" in result.lower()


@pytest.mark.django_db
class TestQueryBalance:
    def test_returns_income_and_expenses(self, seeded_user):
        from model_bakery import baker

        baker.make(
            "finances.Income",
            user=seeded_user,
            month=date(2026, 3, 1),
            amount=Decimal("5000"),
            name="Salário",
        )
        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        pm = PaymentMethod.objects.get(user=seeded_user, name="Pix")
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 5),
            amount=Decimal("1000"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 10),
            amount=Decimal("-200"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        result = query_balance(seeded_user, 2026, 3)
        assert "5000" in result or "5.000" in result
        assert "1000" in result or "1.000" in result
        assert "200" in result


@pytest.mark.django_db
class TestQueryBudgetStatus:
    def test_over_budget_category(self, seeded_user):
        from model_bakery import baker

        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        cat.budget_ceiling = Decimal("100")
        cat.save()
        pm = PaymentMethod.objects.get(user=seeded_user, name="Pix")
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 5),
            amount=Decimal("150"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        result = query_budget_status(seeded_user, 2026, 3)
        assert "Alimentação" in result
        assert "150" in result or "🔴" in result


@pytest.mark.django_db
class TestQueryInstallments:
    def test_active_installments(self, seeded_user):
        from model_bakery import baker

        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        pm = PaymentMethod.objects.get(user=seeded_user, name="Crédito C6")
        plan = baker.make(
            "finances.InstallmentPlan",
            user=seeded_user,
            date=date(2025, 12, 1),
            description="Notebook",
            category=cat,
            payment_method=pm,
            total_amount=Decimal("600"),
            num_installments=3,
            installment_amount=Decimal("200"),
        )
        plan.generate_entries()
        result = query_installments(seeded_user)
        assert "Notebook" in result

    def test_no_installments(self, seeded_user):
        result = query_installments(seeded_user)
        assert "nenhum" in result.lower() or "ativ" in result.lower()


@pytest.mark.django_db
class TestCreateCategory:
    def test_creates_category(self, seeded_user):
        result = create_category(seeded_user, "Assinatura", "200.00")
        assert "criada" in result.lower()
        assert Category.objects.filter(user=seeded_user, name="Assinatura").exists()

    def test_duplicate_name(self, seeded_user):
        result = create_category(seeded_user, "Alimentação", "500.00")
        assert "erro" in result.lower() or "já existe" in result.lower()


@pytest.mark.django_db
class TestUpdateCategoryBudget:
    def test_updates_ceiling(self, seeded_user):
        result = update_category_budget(seeded_user, "Alimentação", "1500.00")
        assert "atualizado" in result.lower()
        cat = Category.objects.get(user=seeded_user, name="Alimentação")
        assert cat.budget_ceiling == Decimal("1500.00")

    def test_nonexistent_category(self, seeded_user):
        result = update_category_budget(seeded_user, "NonExistent", "500.00")
        assert "erro" in result.lower() or "não encontrada" in result.lower()


@pytest.mark.django_db
class TestCreatePaymentMethod:
    def test_creates_pix(self, seeded_user):
        result = create_payment_method(seeded_user, "Novo Pix", "pix")
        assert "criada" in result.lower()
        assert PaymentMethod.objects.filter(user=seeded_user, name="Novo Pix").exists()

    def test_creates_credit_card(self, seeded_user):
        result = create_payment_method(seeded_user, "Crédito Teste", "credit_card", "25")
        assert "criada" in result.lower()
        pm = PaymentMethod.objects.get(user=seeded_user, name="Crédito Teste")
        assert pm.closing_day == 25

    def test_invalid_type(self, seeded_user):
        result = create_payment_method(seeded_user, "Bad", "invalid_type")
        assert "erro" in result.lower()


@pytest.mark.django_db
class TestUpdateIncome:
    def test_creates_new_income(self, seeded_user):
        result = update_income(seeded_user, "Salário", "8000.00", "2026-03-01")
        lowered = result.lower()
        assert "salv" in lowered or "criada" in lowered or "atualizada" in lowered
        assert Income.objects.filter(
            user=seeded_user, name="Salário", month=date(2026, 3, 1)
        ).exists()

    def test_updates_existing(self, seeded_user):
        from model_bakery import baker

        baker.make(
            "finances.Income",
            user=seeded_user,
            name="Salário",
            amount=Decimal("5000"),
            month=date(2026, 3, 1),
        )
        update_income(seeded_user, "Salário", "8000.00", "2026-03-01")
        income = Income.objects.get(user=seeded_user, name="Salário", month=date(2026, 3, 1))
        assert income.amount == Decimal("8000.00")
