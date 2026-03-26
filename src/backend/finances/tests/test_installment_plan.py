import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker
from finances.models import Entry, EntryType


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Trabalho")

@pytest.fixture
def credit_card(user):
    return baker.make("finances.PaymentMethod", user=user, name="Crédito Santander",
        type="credit_card", closing_day=30)

@pytest.fixture
def credit_card_c6(user):
    return baker.make("finances.PaymentMethod", user=user, name="Crédito C6",
        type="credit_card", closing_day=25)


@pytest.mark.django_db
class TestInstallmentPlan:
    def test_create_plan(self, user, category, credit_card):
        plan = baker.make("finances.InstallmentPlan", user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("6699.00"), num_installments=12, installment_amount=Decimal("558.25"))
        assert plan.total_amount == Decimal("6699.00")
        assert plan.num_installments == 12

    def test_str_returns_description_and_installments(self, user, category, credit_card):
        plan = baker.make("finances.InstallmentPlan", user=user, description="notebook",
            num_installments=12, category=category, payment_method=credit_card)
        result = str(plan)
        assert "notebook" in result
        assert "12x" in result

    def test_generate_entries_creates_correct_count(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("6699.00"), num_installments=12, installment_amount=Decimal("558.25"))
        entries = plan.generate_entries()
        assert len(entries) == 12

    def test_generated_entries_are_installment_type(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("6699.00"), num_installments=12, installment_amount=Decimal("558.25"))
        entries = plan.generate_entries()
        assert all(e.entry_type == EntryType.INSTALLMENT for e in entries)
        assert all(e.installment_plan == plan for e in entries)

    def test_generated_entries_have_sequential_billing_months(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("600.00"), num_installments=3, installment_amount=Decimal("200.00"))
        entries = plan.generate_entries()
        billing_months = [e.billing_month for e in entries]
        assert billing_months == [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]

    def test_generated_entries_descriptions_numbered(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("600.00"), num_installments=3, installment_amount=Decimal("200.00"))
        entries = plan.generate_entries()
        assert entries[0].description == "notebook (1/3)"
        assert entries[1].description == "notebook (2/3)"
        assert entries[2].description == "notebook (3/3)"

    def test_rounding_remainder_on_last_installment(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2026, 1, 1),
            description="colchão", category=category, payment_method=credit_card,
            total_amount=Decimal("100.00"), num_installments=3, installment_amount=Decimal("33.33"))
        entries = plan.generate_entries()
        assert entries[0].amount == Decimal("33.33")
        assert entries[1].amount == Decimal("33.33")
        assert entries[2].amount == Decimal("33.34")
        total = sum(e.amount for e in entries)
        assert total == Decimal("100.00")

    def test_billing_month_respects_closing_day(self, user, category, credit_card_c6):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2026, 3, 26),
            description="tênis", category=category, payment_method=credit_card_c6,
            total_amount=Decimal("300.00"), num_installments=2, installment_amount=Decimal("150.00"))
        entries = plan.generate_entries()
        assert entries[0].billing_month == date(2026, 4, 1)
        assert entries[1].billing_month == date(2026, 5, 1)

    def test_entries_persisted_to_database(self, user, category, credit_card):
        from finances.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(user=user, date=date(2025, 12, 1),
            description="notebook", category=category, payment_method=credit_card,
            total_amount=Decimal("600.00"), num_installments=3, installment_amount=Decimal("200.00"))
        plan.generate_entries()
        assert Entry.objects.filter(installment_plan=plan).count() == 3
