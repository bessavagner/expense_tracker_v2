import pytest
from datetime import date
from decimal import Decimal
from model_bakery import baker
from finances.models.entry import EntryType


@pytest.fixture
def category(user):
    return baker.make("finances.Category", user=user, name="Alimentação")

@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")

@pytest.fixture
def credit_card(user):
    return baker.make("finances.PaymentMethod", user=user, name="Crédito Santander", type="credit_card", closing_day=30)

@pytest.fixture
def credit_card_c6(user):
    return baker.make("finances.PaymentMethod", user=user, name="Crédito C6", type="credit_card", closing_day=25)


@pytest.mark.django_db
class TestEntry:
    def test_create_regular_entry(self, user, category, pix):
        entry = baker.make("finances.Entry", user=user, date=date(2026, 3, 1),
            amount=Decimal("42.00"), description="Heineken - bebida",
            category=category, payment_method=pix, entry_type=EntryType.REGULAR)
        assert entry.amount == Decimal("42.00")
        assert entry.entry_type == EntryType.REGULAR

    def test_str_returns_description_and_amount(self, user, category, pix):
        entry = baker.make("finances.Entry", user=user, description="Supermercado Cosmos",
            amount=Decimal("119.61"), category=category, payment_method=pix)
        result = str(entry)
        assert "Supermercado Cosmos" in result
        assert "119.61" in result

    def test_negative_amount_is_refund(self, user, category, pix):
        entry = baker.make("finances.Entry", user=user, amount=Decimal("-226.21"),
            description="Google Cloud - estorno", category=category, payment_method=pix)
        assert entry.amount < 0

    def test_billing_month_computed_on_save_pix(self, user, category, pix):
        from finances.models import Entry
        entry = Entry(user=user, date=date(2026, 3, 15), amount=Decimal("50.00"),
            description="Test", category=category, payment_method=pix, entry_type=EntryType.REGULAR)
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_billing_month_credit_card_before_closing(self, user, category, credit_card_c6):
        from finances.models import Entry
        entry = Entry(user=user, date=date(2026, 3, 20), amount=Decimal("50.00"),
            description="Test", category=category, payment_method=credit_card_c6, entry_type=EntryType.REGULAR)
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_billing_month_credit_card_after_closing(self, user, category, credit_card_c6):
        from finances.models import Entry
        entry = Entry(user=user, date=date(2026, 3, 26), amount=Decimal("50.00"),
            description="Test", category=category, payment_method=credit_card_c6, entry_type=EntryType.REGULAR)
        entry.save()
        assert entry.billing_month == date(2026, 4, 1)

    def test_billing_month_override_preserved(self, user, category, credit_card_c6):
        from finances.models import Entry
        entry = Entry(user=user, date=date(2026, 3, 26), amount=Decimal("50.00"),
            description="Test", category=category, payment_method=credit_card_c6,
            entry_type=EntryType.REGULAR, billing_month=date(2026, 3, 1), billing_month_override=True)
        entry.save()
        assert entry.billing_month == date(2026, 3, 1)

    def test_ordering_by_date_desc(self, user, category, pix):
        from finances.models import Entry
        baker.make("finances.Entry", user=user, date=date(2026, 3, 1), category=category, payment_method=pix)
        baker.make("finances.Entry", user=user, date=date(2026, 3, 15), category=category, payment_method=pix)
        baker.make("finances.Entry", user=user, date=date(2026, 3, 10), category=category, payment_method=pix)
        dates = list(Entry.objects.filter(user=user).values_list("date", flat=True))
        assert dates == sorted(dates, reverse=True)

    def test_entry_type_choices(self):
        assert EntryType.REGULAR == "regular"
        assert EntryType.INSTALLMENT == "installment"
        assert EntryType.SYSTEMIC == "systemic"
