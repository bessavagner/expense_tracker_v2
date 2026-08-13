import pytest
from django.core.management import call_command

from finances.models import Category, PaymentMethod


@pytest.mark.django_db
class TestSeedData:
    """The onboarding seed, read back through the household it writes into.

    E04 phase 4 moved the command's `get_or_create` key from (user, name) to
    (household, name) — so that a second person joining does not get a
    duplicate catalogue seeded beside the one their household already has.
    These read back the same way.
    """

    def test_creates_default_categories(self, user, household):
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.for_household(household).count() == 26

    def test_creates_default_payment_methods(self, user, household):
        call_command("seed_data", f"--user={user.username}")
        assert PaymentMethod.objects.for_household(household).count() == 6

    def test_categories_include_system_categories(self, user, household):
        call_command("seed_data", f"--user={user.username}")
        system_cats = Category.objects.for_household(household).filter(is_system=True)
        names = set(system_cats.values_list("name", flat=True))
        assert "Custeio" in names
        assert "Financiamentos" in names

    def test_payment_methods_include_credit_cards_with_closing_days(self, user, household):
        call_command("seed_data", f"--user={user.username}")
        santander = PaymentMethod.objects.for_household(household).get(name="Crédito Santander")
        assert santander.closing_day == 30
        assert santander.type == "credit_card"

    def test_idempotent_does_not_duplicate(self, user, household):
        call_command("seed_data", f"--user={user.username}")
        call_command("seed_data", f"--user={user.username}")
        assert Category.objects.for_household(household).count() == 26
        assert PaymentMethod.objects.for_household(household).count() == 6

    def test_seeded_rows_record_who_ran_the_command(self, user, household):
        """`created_by` is the provenance half of the old `user` column, and a
        seed run by a person is authored by them."""
        call_command("seed_data", f"--user={user.username}")
        assert not Category.objects.for_household(household).filter(created_by=None).exists()

    def test_fills_zero_ceiling_on_existing_category(self, user, household):
        from decimal import Decimal

        Category.objects.create(
            household=household, name="Alimentação", budget_ceiling=Decimal("0")
        )
        call_command("seed_data", f"--user={user.username}")
        cat = Category.objects.for_household(household).get(name="Alimentação")
        assert cat.budget_ceiling == Decimal("1300.00")

    def test_does_not_clobber_custom_ceiling(self, user, household):
        from decimal import Decimal

        Category.objects.create(
            household=household, name="Alimentação", budget_ceiling=Decimal("999.00")
        )
        call_command("seed_data", f"--user={user.username}")
        cat = Category.objects.for_household(household).get(name="Alimentação")
        assert cat.budget_ceiling == Decimal("999.00")
