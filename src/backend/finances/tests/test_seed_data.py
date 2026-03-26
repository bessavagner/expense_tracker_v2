import pytest
from django.core.management import call_command
from finances.models import Category, PaymentMethod


@pytest.mark.django_db
class TestSeedData:
    def test_creates_default_categories(self, user):
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.filter(user=user).count() == 26

    def test_creates_default_payment_methods(self, user):
        call_command("seed_data", f"--user={user.username}")
        assert PaymentMethod.objects.filter(user=user).count() == 6

    def test_categories_include_system_categories(self, user):
        call_command("seed_data", f"--user={user.username}")
        system_cats = Category.objects.filter(user=user, is_system=True)
        names = set(system_cats.values_list("name", flat=True))
        assert "Custeio" in names
        assert "Financiamentos" in names

    def test_payment_methods_include_credit_cards_with_closing_days(self, user):
        call_command("seed_data", f"--user={user.username}")
        santander = PaymentMethod.objects.get(user=user, name="Crédito Santander")
        assert santander.closing_day == 30
        assert santander.type == "credit_card"

    def test_idempotent_does_not_duplicate(self, user):
        call_command("seed_data", f"--user={user.username}")
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.filter(user=user).count() == 26
        assert PaymentMethod.objects.filter(user=user).count() == 6
