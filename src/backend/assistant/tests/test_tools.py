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


@pytest.mark.django_db
class TestSystemicTools:
    """Tests for list_systemic_expenses and set_systemic_amount."""

    def _make_systemic(self, user, name="Análise - Vagner", amount="300.00", is_active=True):
        from model_bakery import baker

        from finances.models import Category, PaymentMethod

        cat, _ = Category.objects.get_or_create(user=user, name="Saúde")
        pm, _ = PaymentMethod.objects.get_or_create(
            user=user, name="Débito", defaults={"type": "pix"}
        )
        return baker.make(
            "finances.SystemicExpense",
            user=user,
            name=name,
            category=cat,
            payment_method=pm,
            default_amount=Decimal(amount),
            is_active=is_active,
        )

    # ── list_systemic_expenses ────────────────────────────────────────────────

    def test_list_returns_active_systemic_expenses(self, seeded_user):
        from assistant.agents.tools import list_systemic_expenses

        self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        self._make_systemic(seeded_user, "Unimed", "450.00")
        result = list_systemic_expenses(seeded_user)
        assert any("Análise - Vagner" in item for item in result)
        assert any("Unimed" in item for item in result)

    def test_list_excludes_inactive(self, seeded_user):
        from assistant.agents.tools import list_systemic_expenses

        self._make_systemic(seeded_user, "Spotify", "45.00", is_active=True)
        self._make_systemic(seeded_user, "InativoXYZ", "10.00", is_active=False)
        result = list_systemic_expenses(seeded_user)
        assert not any("InativoXYZ" in item for item in result)

    def test_list_excludes_other_users(self, seeded_user, db):
        from model_bakery import baker

        from assistant.agents.tools import list_systemic_expenses

        other = baker.make("core.CustomUser")
        cat = baker.make("finances.Category", user=other, name="X")
        baker.make(
            "finances.SystemicExpense",
            user=other,
            name="OtherSystemic",
            category=cat,
            default_amount=Decimal("100"),
            is_active=True,
        )
        result = list_systemic_expenses(seeded_user)
        assert not any("OtherSystemic" in item for item in result)

    # ── set_systemic_amount: happy paths ─────────────────────────────────────

    def test_set_creates_systemic_entry_for_month(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount
        from finances.models import Entry, EntryType

        s = self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        result = set_systemic_amount(seeded_user, "Análise - Vagner", "350.00", "2026-06-01")
        assert "Análise - Vagner" in result
        assert "350" in result
        entry = Entry.objects.get(
            user=seeded_user,
            systemic_expense=s,
            billing_month=date(2026, 6, 1),
            entry_type=EntryType.SYSTEMIC,
        )
        assert entry.amount == Decimal("350.00")

    def test_set_updates_existing_entry_no_duplicate(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount
        from finances.models import Entry, EntryType

        s = self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        # First call creates
        set_systemic_amount(seeded_user, "Análise - Vagner", "350.00", "2026-06-01")
        # Second call updates, must NOT duplicate
        result = set_systemic_amount(seeded_user, "Análise - Vagner", "400.00", "2026-06-01")
        assert "400" in result
        entries = Entry.objects.filter(
            user=seeded_user,
            systemic_expense=s,
            billing_month=date(2026, 6, 1),
            entry_type=EntryType.SYSTEMIC,
        )
        assert entries.count() == 1
        assert entries.first().amount == Decimal("400.00")

    def test_set_case_insensitive_name_match(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount
        from finances.models import Entry, EntryType

        s = self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        result = set_systemic_amount(seeded_user, "análise - vagner", "320.00", "2026-06-01")
        assert "320" in result
        assert Entry.objects.filter(
            user=seeded_user,
            systemic_expense=s,
            billing_month=date(2026, 6, 1),
            entry_type=EntryType.SYSTEMIC,
        ).exists()

    # ── set_systemic_amount: error paths ─────────────────────────────────────

    def test_unknown_name_returns_error_creates_nothing(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount
        from finances.models import Entry

        self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        result = set_systemic_amount(seeded_user, "DesconhecidoXYZ", "300.00", "2026-06-01")
        assert "Não encontrei" in result
        assert "DesconhecidoXYZ" in result
        assert "Análise - Vagner" in result  # lists available names
        assert Entry.objects.filter(user=seeded_user).count() == 0

    def test_invalid_amount_returns_error(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount

        self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        result = set_systemic_amount(seeded_user, "Análise - Vagner", "abc", "2026-06-01")
        assert "inválido" in result.lower() or "erro" in result.lower()

    def test_invalid_date_returns_error(self, seeded_user):
        from assistant.agents.tools import set_systemic_amount

        self._make_systemic(seeded_user, "Análise - Vagner", "300.00")
        result = set_systemic_amount(seeded_user, "Análise - Vagner", "300.00", "not-a-date")
        assert "inválido" in result.lower() or "erro" in result.lower()


@pytest.mark.django_db
class TestRegisterReceipt:
    """register_receipt: split multi-categoria com rateio determinístico de desconto."""

    def _add_roupa(self, user):
        from model_bakery import baker

        baker.make("finances.Category", user=user, name="Roupa")

    def test_splits_categories_and_prorates_discount(self, seeded_user):
        from django.db.models import Sum

        from assistant.agents.tools import register_receipt
        from finances.models import Entry

        self._add_roupa(seeded_user)
        register_receipt(
            user=seeded_user,
            date_str="2026-06-12",
            store="Lojas Americanas",
            payment_method_name="Crédito C6",
            items_by_category={
                "Roupa": ["9.99"],
                "Lanche": ["9.99", "9.99", "6.19", "9.99"],
            },
            discount="3.99",
        )
        entries = Entry.objects.filter(user=seeded_user)
        assert entries.count() == 2
        # soma das linhas bate EXATAMENTE com o valor pago (46.15 - 3.99)
        assert entries.aggregate(s=Sum("amount"))["s"] == Decimal("42.16")
        # desconto rateado proporcionalmente; resíduo de centavo na maior categoria
        assert entries.get(category__name="Roupa").amount == Decimal("9.13")
        assert entries.get(category__name="Lanche").amount == Decimal("33.03")

    def test_no_discount_keeps_category_sums(self, seeded_user):
        from assistant.agents.tools import register_receipt
        from finances.models import Entry

        self._add_roupa(seeded_user)
        register_receipt(
            user=seeded_user,
            date_str="2026-06-12",
            store="Loja X",
            payment_method_name="Crédito C6",
            items_by_category={"Roupa": ["10.00"], "Lanche": ["5.00", "2.50"]},
            discount="0",
        )
        entries = Entry.objects.filter(user=seeded_user)
        assert entries.get(category__name="Roupa").amount == Decimal("10.00")
        assert entries.get(category__name="Lanche").amount == Decimal("7.50")

    def test_unknown_category_creates_nothing(self, seeded_user):
        from assistant.agents.tools import register_receipt
        from finances.models import Entry

        msg = register_receipt(
            user=seeded_user,
            date_str="2026-06-12",
            store="Loja X",
            payment_method_name="Crédito C6",
            items_by_category={"Inexistente": ["10.00"]},
            discount="0",
        )
        assert "não encontrada" in msg.lower() or "erro" in msg.lower()
        assert Entry.objects.filter(user=seeded_user).count() == 0

    def test_unknown_payment_method_creates_nothing(self, seeded_user):
        from assistant.agents.tools import register_receipt
        from finances.models import Entry

        self._add_roupa(seeded_user)
        msg = register_receipt(
            user=seeded_user,
            date_str="2026-06-12",
            store="Loja X",
            payment_method_name="NãoExiste",
            items_by_category={"Roupa": ["10.00"]},
            discount="0",
        )
        assert "não encontrada" in msg.lower() or "erro" in msg.lower()
        assert Entry.objects.filter(user=seeded_user).count() == 0
