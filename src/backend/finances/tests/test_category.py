import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError
from model_bakery import baker


@pytest.mark.django_db
class TestCategory:
    def test_create_category(self, household):
        category = baker.make(
            "finances.Category",
            household=household,
            name="Alimentação",
            budget_ceiling=1300,
        )
        assert category.name == "Alimentação"
        assert category.budget_ceiling == 1300
        assert category.is_system is False
        assert category.household == household
        assert category.id is not None
        assert category.historical_avg is None
        assert category.quarterly_avg is None

    def test_str_returns_name(self, household):
        category = baker.make("finances.Category", household=household, name="Lanche")
        assert str(category) == "Lanche"

    def test_unique_name_per_household(self, household):
        """One household, one category list — a repeat of the name collides."""
        baker.make("finances.Category", household=household, name="Alimentação")
        with pytest.raises(IntegrityError):
            baker.make("finances.Category", household=household, name="Alimentação")

    def test_same_name_in_two_households(self, household, other_household):
        """The boundary is tenancy, not identity: the neighbours may keep their
        own 'Alimentação' without colliding with ours."""
        ours = baker.make("finances.Category", household=household, name="Alimentação")
        theirs = baker.make("finances.Category", household=other_household, name="Alimentação")

        assert theirs.name == "Alimentação"
        assert theirs.pk != ours.pk

    def test_system_category_not_deletable(self, household):
        category = baker.make(
            "finances.Category", household=household, name="Custeio", is_system=True
        )
        with pytest.raises(ProtectedError):
            category.delete()

    def test_ordering_by_name(self, household):
        baker.make("finances.Category", household=household, name="Lanche")
        baker.make("finances.Category", household=household, name="Alimentação")
        baker.make("finances.Category", household=household, name="Zebra")
        from finances.models import Category

        names = list(Category.objects.for_household(household).values_list("name", flat=True))
        assert names.index("Alimentação") < names.index("Lanche")
        assert names.index("Lanche") < names.index("Zebra")

    def test_default_budget_ceiling_is_zero(self, household):
        from finances.models import Category

        category = Category.objects.create(household=household, name="Nova")
        assert category.budget_ceiling == 0
