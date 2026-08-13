from decimal import Decimal

import pytest
from django.db import IntegrityError
from model_bakery import baker


@pytest.mark.django_db
class TestBudgetModel:
    def test_create_budget_defaults_amount_zero(self, household):
        b = baker.make("finances.Budget", household=household, name="Casa")
        assert b.amount == Decimal("0")
        assert str(b.id)  # uuid pk

    def test_name_unique_per_household(self, household):
        baker.make("finances.Budget", household=household, name="Casa")
        with pytest.raises(IntegrityError):
            baker.make("finances.Budget", household=household, name="Casa")

    def test_deleting_budget_nulls_category_fk(self, household):
        b = baker.make("finances.Budget", household=household, name="Casa")
        cat = baker.make("finances.Category", household=household, name="Luz", budget=b)
        b.delete()
        cat.refresh_from_db()
        assert cat.budget is None

    def test_category_budget_related_name(self, household):
        b = baker.make("finances.Budget", household=household, name="Casa")
        baker.make("finances.Category", household=household, name="Luz", budget=b)
        assert b.categories.count() == 1
