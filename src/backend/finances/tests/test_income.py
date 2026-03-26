from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestIncome:
    def test_create_one_time_income(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="13°",
            amount=Decimal("3998.74"),
            month=date(2025, 12, 1),
            is_recurring=False,
        )
        assert income.name == "13°"
        assert income.amount == Decimal("3998.74")
        assert income.month == date(2025, 12, 1)
        assert income.is_recurring is False

    def test_create_recurring_income(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Salário",
            amount=Decimal("7854.23"),
            month=date(2026, 3, 1),
            is_recurring=True,
            recurrence_start=date(2026, 1, 1),
            recurrence_end=None,
        )
        assert income.is_recurring is True
        assert income.recurrence_start == date(2026, 1, 1)
        assert income.recurrence_end is None

    def test_str_returns_name_and_month(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Salário",
            month=date(2026, 3, 1),
        )
        assert "Salário" in str(income)
        assert "2026-03" in str(income)

    def test_recurring_with_bounded_period(self, user):
        income = baker.make(
            "finances.Income",
            user=user,
            name="Bolsa PIBID",
            amount=Decimal("2000.00"),
            month=date(2025, 11, 1),
            is_recurring=True,
            recurrence_start=date(2025, 11, 1),
            recurrence_end=date(2026, 10, 1),
        )
        assert income.recurrence_end == date(2026, 10, 1)

    def test_ordering_by_month_desc(self, user):
        baker.make("finances.Income", user=user, month=date(2026, 1, 1), name="Jan")
        baker.make("finances.Income", user=user, month=date(2026, 3, 1), name="Mar")
        baker.make("finances.Income", user=user, month=date(2026, 2, 1), name="Fev")
        from finances.models import Income

        names = list(Income.objects.filter(user=user).values_list("name", flat=True))
        assert names == ["Mar", "Fev", "Jan"]
