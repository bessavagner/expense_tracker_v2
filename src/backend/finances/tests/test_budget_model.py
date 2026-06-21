from decimal import Decimal

import pytest
from django.db import IntegrityError
from model_bakery import baker


@pytest.mark.django_db
class TestBudgetModel:
    def test_create_budget_defaults_amount_zero(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        assert b.amount == Decimal("0")
        assert str(b.id)  # uuid pk

    def test_name_unique_per_user(self, user):
        baker.make("finances.Budget", user=user, name="Casa")
        with pytest.raises(IntegrityError):
            baker.make("finances.Budget", user=user, name="Casa")

    def test_deleting_budget_nulls_category_fk(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        cat = baker.make("finances.Category", user=user, name="Luz", budget=b)
        b.delete()
        cat.refresh_from_db()
        assert cat.budget is None

    def test_category_budget_related_name(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa")
        baker.make("finances.Category", user=user, name="Luz", budget=b)
        assert b.categories.count() == 1
