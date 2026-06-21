# finances/tests/test_budget_stats.py
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services import budget_stats


def _entry(user, cat, amount, billing_month):
    return baker.make(
        "finances.Entry", user=user, date=billing_month, amount=Decimal(amount),
        category=cat, entry_type=EntryType.REGULAR, billing_month=billing_month,
        billing_month_override=True,
    )


@pytest.mark.django_db
class TestBudgetStats:
    def test_spend_and_status(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        agua = baker.make("finances.Category", user=user, name="Água", budget=b)
        _entry(user, luz, "600", date(2026, 6, 1))
        _entry(user, agua, "550", date(2026, 6, 1))  # total 1150 -> over
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["spent"] == Decimal("1150")
        assert row["pct"] == 115
        assert row["status"] == "error"

    def test_warning_band(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        _entry(user, luz, "950", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["status"] == "warning"

    def test_pct_truncates_below_warning_threshold(self, user):
        # 899.50 / 1000 = 89.95% must truncate to 89 (success), not round to 90 (warning).
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        luz = baker.make("finances.Category", user=user, name="Luz", budget=b)
        _entry(user, luz, "899.50", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["pct"] == 89
        assert row["status"] == "success"

    def test_excludes_adjustment_entries(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        ajuste = baker.make("finances.Category", user=user, name="Ajuste de saldo", budget=b)
        _entry(user, ajuste, "5000", date(2026, 6, 1))
        [row] = budget_stats.budget_spend_for_month(user, date(2026, 6, 1))
        assert row["spent"] == Decimal("0")

    def test_orphan_categories(self, user):
        orphan = baker.make(
            "finances.Category", user=user, name="Lazer",
            budget=None, budget_ceiling=Decimal("200"),
        )
        _entry(user, orphan, "250", date(2026, 6, 1))
        [row] = budget_stats.orphan_category_spend_for_month(user, date(2026, 6, 1))
        assert row["name"] == "Lazer"
        assert row["status"] == "error"

    def test_orphan_ignores_zero_ceiling(self, user):
        orphan = baker.make(
            "finances.Category", user=user, name="SemTeto",
            budget=None, budget_ceiling=Decimal("0"),
        )
        _entry(user, orphan, "100", date(2026, 6, 1))
        assert budget_stats.orphan_category_spend_for_month(user, date(2026, 6, 1)) == []

    def test_total_diverse_ceiling(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("1000"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))  # ceiling ignored; budget.amount used
        baker.make("finances.Category", user=user, name="Lazer", budget=None,
                   budget_ceiling=Decimal("200"))
        assert budget_stats.total_diverse_ceiling(user) == Decimal("1200")

    def test_seed_amount_from_ceilings(self, user):
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("0"))
        baker.make("finances.Category", user=user, name="Luz", budget=b,
                   budget_ceiling=Decimal("400"))
        baker.make("finances.Category", user=user, name="Água", budget=b,
                   budget_ceiling=Decimal("150"))
        assert budget_stats.seed_amount_from_ceilings(b) == Decimal("550")
