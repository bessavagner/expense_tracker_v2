# finances/tests/test_budget_stats.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services import budget_stats


def _entry(household, cat, amount, billing_month):
    return baker.make(
        "finances.Entry",
        household=household,
        date=billing_month,
        amount=Decimal(amount),
        category=cat,
        entry_type=EntryType.REGULAR,
        billing_month=billing_month,
        billing_month_override=True,
    )


@pytest.mark.django_db
class TestBudgetStats:
    def test_spend_and_status(self, user, household):
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", household=household, name="Luz", budget=b)
        agua = baker.make("finances.Category", household=household, name="Água", budget=b)
        _entry(household, luz, "600", date(2026, 6, 1))
        _entry(household, agua, "550", date(2026, 6, 1))  # total 1150 -> over
        [row] = budget_stats.budget_spend_for_month(household, date(2026, 6, 1))
        assert row["spent"] == Decimal("1150")
        assert row["pct"] == 115
        assert row["status"] == "error"

    def test_warning_band(self, user, household):
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", household=household, name="Luz", budget=b)
        _entry(household, luz, "950", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(household, date(2026, 6, 1))
        assert row["status"] == "warning"

    def test_pct_truncates_below_warning_threshold(self, user, household):
        # 899.50 / 1000 = 89.95% must truncate to 89 (success), not round to 90 (warning).
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", household=household, name="Luz", budget=b)
        _entry(household, luz, "899.50", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(household, date(2026, 6, 1))
        assert row["pct"] == 89
        assert row["status"] == "success"

    def test_excludes_adjustment_entries(self, user, household):
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("1000"))
        ajuste = baker.make(
            "finances.Category", household=household, name="Ajuste de saldo", budget=b
        )
        _entry(household, ajuste, "5000", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(household, date(2026, 6, 1))
        assert row["spent"] == Decimal("0")

    def test_orphan_categories(self, user, household):
        orphan = baker.make(
            "finances.Category",
            household=household,
            name="Lazer",
            budget=None,
            budget_ceiling=Decimal("200"),
        )
        _entry(household, orphan, "250", date(2026, 6, 1))
        [row] = budget_stats.orphan_category_spend_for_month(household, date(2026, 6, 1))
        assert row["name"] == "Lazer"
        assert row["status"] == "error"

    def test_orphan_ignores_zero_ceiling(self, user, household):
        orphan = baker.make(
            "finances.Category",
            household=household,
            name="SemTeto",
            budget=None,
            budget_ceiling=Decimal("0"),
        )
        _entry(household, orphan, "100", date(2026, 6, 1))
        assert budget_stats.orphan_category_spend_for_month(household, date(2026, 6, 1)) == []

    def test_total_diverse_ceiling(self, user, household):
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("1000"))
        baker.make(
            "finances.Category",
            household=household,
            name="Luz",
            budget=b,
            budget_ceiling=Decimal("400"),
        )  # ceiling ignored; budget.amount used
        baker.make(
            "finances.Category",
            household=household,
            name="Lazer",
            budget=None,
            budget_ceiling=Decimal("200"),
        )
        assert budget_stats.total_diverse_ceiling(household) == Decimal("1200")

    def test_seed_amount_from_ceilings(self, user, household):
        b = baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("0"))
        baker.make(
            "finances.Category",
            household=household,
            name="Luz",
            budget=b,
            budget_ceiling=Decimal("400"),
        )
        baker.make(
            "finances.Category",
            household=household,
            name="Água",
            budget=b,
            budget_ceiling=Decimal("150"),
        )
        assert budget_stats.seed_amount_from_ceilings(b) == Decimal("550")
