import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError
from model_bakery import baker


@pytest.mark.django_db
class TestCategory:
    def test_create_category(self, user):
        category = baker.make(
            "finances.Category",
            user=user,
            name="Alimentação",
            budget_ceiling=1300,
        )
        assert category.name == "Alimentação"
        assert category.budget_ceiling == 1300
        assert category.is_system is False
        assert category.user == user
        assert category.id is not None
        assert category.historical_avg is None
        assert category.quarterly_avg is None

    def test_str_returns_name(self, user):
        category = baker.make("finances.Category", user=user, name="Lanche")
        assert str(category) == "Lanche"

    def test_unique_name_per_user(self, user):
        baker.make("finances.Category", user=user, name="Alimentação")
        with pytest.raises(IntegrityError):
            baker.make("finances.Category", user=user, name="Alimentação")

    def test_same_name_different_users(self, user, other_user):
        baker.make("finances.Category", user=user, name="Alimentação")
        cat2 = baker.make("finances.Category", user=other_user, name="Alimentação")
        assert cat2.name == "Alimentação"

    def test_system_category_not_deletable(self, user):
        category = baker.make("finances.Category", user=user, name="Custeio", is_system=True)
        with pytest.raises(ProtectedError):
            category.delete()

    def test_ordering_by_name(self, user):
        baker.make("finances.Category", user=user, name="Lanche")
        baker.make("finances.Category", user=user, name="Alimentação")
        baker.make("finances.Category", user=user, name="Álcool")
        from finances.models import Category

        names = list(Category.objects.filter(user=user).values_list("name", flat=True))
        assert names == sorted(names)

    def test_default_budget_ceiling_is_zero(self, user):
        from finances.models import Category

        category = Category.objects.create(user=user, name="Nova")
        assert category.budget_ceiling == 0
