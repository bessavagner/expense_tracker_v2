from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.projection import build_projection


def _entry(household, cat, pm, amount, billing_month, entry_type=EntryType.REGULAR, d=None):
    return baker.make(
        "finances.Entry",
        household=household,
        date=d or billing_month,
        amount=Decimal(amount),
        category=cat,
        payment_method=pm,
        entry_type=entry_type,
        billing_month=billing_month,
        billing_month_override=True,  # pin so save() doesn't recompute
    )


@pytest.fixture
def cat(household):
    return baker.make("finances.Category", household=household, name="Diversos")


@pytest.fixture
def pix(household):
    return baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")


@pytest.mark.django_db
class TestBuildProjection:
    def test_returns_one_row_per_month(self, user, household):
        rows = build_projection(household, date(2026, 1, 1), 3, today=date(2026, 1, 15))
        assert [r["month"] for r in rows] == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]

    def test_past_month_all_rows(self, user, household, cat, pix):
        m = date(2026, 5, 1)
        _entry(household, cat, pix, "300", m, EntryType.SYSTEMIC)
        _entry(household, cat, pix, "200", m, EntryType.INSTALLMENT)
        _entry(household, cat, pix, "150", m, EntryType.REGULAR)
        baker.make("finances.Income", household=household, amount=Decimal("2000"), month=m)

        # May is in the past relative to this "today"
        row = build_projection(household, m, 1, today=date(2026, 6, 15))[0]

        assert row["systemic"] == Decimal("300")
        assert row["installments"] == Decimal("200")
        assert row["programmed"] == Decimal("500")
        assert row["diverse"] == Decimal("150")
        assert row["total"] == Decimal("650")
        assert row["income"] == Decimal("2000")
        assert row["saldo_programado"] == Decimal("1500")  # 2000 - 500
        assert row["saldo_projetado"] == Decimal("1350")  # 2000 - 650
        # 650 / 2000 = 32.5%
        assert row["pct_income"] == pytest.approx(Decimal("32.5"))

    def test_future_month_projects_systemics_from_templates(self, user, household, cat, pix):
        # Active templates → future systemic projection
        baker.make(
            "finances.SystemicExpense",
            household=household,
            category=cat,
            default_amount=Decimal("400"),
            is_active=True,
        )
        baker.make(
            "finances.SystemicExpense",
            household=household,
            category=cat,
            default_amount=Decimal("100"),
            is_active=True,
        )
        # An inactive template must NOT count
        baker.make(
            "finances.SystemicExpense",
            household=household,
            category=cat,
            default_amount=Decimal("9999"),
            is_active=False,
        )
        future = date(2026, 8, 1)
        # A future installment entry already materialized
        _entry(household, cat, pix, "250", future, EntryType.INSTALLMENT)

        row = build_projection(household, future, 1, today=date(2026, 6, 15))[0]

        assert row["systemic"] == Decimal("500")  # 400 + 100, inactive excluded
        assert row["installments"] == Decimal("250")
        assert row["programmed"] == Decimal("750")
        assert row["diverse"] == Decimal("0")
        assert row["total"] == Decimal("750")

    def test_future_systemic_ignores_actual_entries_uses_templates(self, user, household, cat, pix):
        """Even if a stray SYSTEMIC entry exists in a future month, the projection
        for a strictly-future month comes from active templates (predictable)."""
        baker.make(
            "finances.SystemicExpense",
            household=household,
            category=cat,
            default_amount=Decimal("400"),
            is_active=True,
        )
        future = date(2026, 8, 1)
        _entry(household, cat, pix, "777", future, EntryType.SYSTEMIC)

        row = build_projection(household, future, 1, today=date(2026, 6, 15))[0]
        assert row["systemic"] == Decimal("400")

    def test_acumulado_is_cumulative(self, user, household, cat, pix):
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2026, 1, 1)
        )
        _entry(household, cat, pix, "200", date(2026, 1, 1), EntryType.REGULAR)
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2026, 2, 1)
        )
        _entry(household, cat, pix, "300", date(2026, 2, 1), EntryType.REGULAR)

        rows = build_projection(household, date(2026, 1, 1), 2, today=date(2026, 3, 1))
        # Jan saldo projetado = 800; Feb = 700
        assert rows[0]["saldo_projetado"] == Decimal("800")
        assert rows[1]["saldo_projetado"] == Decimal("700")
        assert rows[0]["acumulado"] == Decimal("800")
        assert rows[1]["acumulado"] == Decimal("1500")  # 800 + 700

    def test_acumulado_is_historical_independent_of_window(self, user, household, cat, pix):
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2026, 1, 1)
        )
        _entry(household, cat, pix, "200", date(2026, 1, 1), EntryType.REGULAR)  # Jan saldo 800
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2026, 2, 1)
        )
        _entry(household, cat, pix, "300", date(2026, 2, 1), EntryType.REGULAR)  # Feb saldo 700
        # Window starts in Feb, but acumulado must include January's history.
        rows = build_projection(household, date(2026, 2, 1), 1, today=date(2026, 3, 1))
        assert rows[0]["month"] == date(2026, 2, 1)
        assert rows[0]["saldo_projetado"] == Decimal("700")
        assert rows[0]["acumulado"] == Decimal("1500")  # 800 (Jan) + 700 (Feb)

    def test_pre_origin_data_excluded_from_acumulado(self, user, household, cat, pix):
        # Data before the projection origin (Nov 2025) is migration/seed noise and
        # must NOT leak into the running total, even though acumulado is otherwise
        # anchored at the earliest data.
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2025, 9, 1)
        )
        _entry(household, cat, pix, "200", date(2025, 9, 1), EntryType.REGULAR)  # pre-origin
        baker.make(
            "finances.Income", household=household, amount=Decimal("1000"), month=date(2025, 11, 1)
        )
        _entry(household, cat, pix, "300", date(2025, 11, 1), EntryType.REGULAR)  # origin month

        rows = build_projection(household, date(2025, 11, 1), 1, today=date(2025, 12, 1))
        assert rows[0]["month"] == date(2025, 11, 1)
        assert rows[0]["saldo_projetado"] == Decimal("700")
        # Only November's 700 — September's 800 must be excluded.
        assert rows[0]["acumulado"] == Decimal("700")

    def test_zero_income_pct_is_none(self, user, household, cat, pix):
        _entry(household, cat, pix, "100", date(2026, 5, 1), EntryType.REGULAR)
        row = build_projection(household, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
        assert row["income"] == Decimal("0")
        assert row["pct_income"] is None

    def test_scoped_to_household(self, household, other_household, cat, pix):
        other_cat = baker.make("finances.Category", household=other_household)
        other_pm = baker.make("finances.PaymentMethod", household=other_household, type="pix")
        _entry(other_household, other_cat, other_pm, "5000", date(2026, 5, 1), EntryType.REGULAR)

        row = build_projection(household, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
        assert row["diverse"] == Decimal("0")
        assert row["total"] == Decimal("0")

    def test_empty_month_is_all_zero(self, user, household):
        row = build_projection(household, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
        assert row["systemic"] == Decimal("0")
        assert row["installments"] == Decimal("0")
        assert row["programmed"] == Decimal("0")
        assert row["diverse"] == Decimal("0")
        assert row["total"] == Decimal("0")
        assert row["income"] == Decimal("0")
        assert row["saldo_projetado"] == Decimal("0")
        assert row["acumulado"] == Decimal("0")
        assert row["pct_income"] is None


@pytest.mark.django_db
class TestProjectionOverlay:
    def test_overlay_none_matches_baseline(self, user, household, cat, pix):
        m = date(2026, 5, 1)
        _entry(household, cat, pix, "150", m, EntryType.REGULAR)
        baker.make("finances.Income", household=household, amount=Decimal("2000"), month=m)
        base = build_projection(household, m, 2, today=date(2026, 6, 15))
        same = build_projection(household, m, 2, today=date(2026, 6, 15), overlay=None)
        assert [r["acumulado"] for r in base] == [r["acumulado"] for r in same]

    def test_overlay_expense_lowers_saldo_and_acumulado(self, user, household):
        m = date(2026, 6, 1)
        baker.make("finances.Income", household=household, amount=Decimal("2000"), month=m)
        overlay = {(m, "regular"): Decimal("500")}
        row = build_projection(household, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["diverse"] == Decimal("500")
        assert row["saldo_projetado"] == Decimal("1500")  # 2000 - 500
        assert row["acumulado"] == Decimal("1500")

    def test_overlay_income_raises_saldo(self, user, household):
        m = date(2026, 6, 1)
        overlay = {(m, "income"): Decimal("1000")}
        row = build_projection(household, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["income"] == Decimal("1000")
        assert row["saldo_projetado"] == Decimal("1000")


@pytest.mark.django_db
class TestDiverseEstimator:
    def test_ceiling_estimator_uses_total_ceiling(self, user, household, cat, pix):
        baker.make("finances.Budget", household=household, name="Casa", amount=Decimal("3000"))
        baker.make(
            "finances.Category",
            household=household,
            name="Lazer",
            budget=None,
            budget_ceiling=Decimal("500"),
        )
        # future month, no posted diversas -> estimate drives diverse_estimated
        rows = build_projection(
            household,
            date(2026, 7, 1),
            1,
            today=date(2026, 6, 15),
            diverse_estimator="ceiling",
        )
        assert rows[0]["diverse_estimated"] == Decimal("3500")

    def test_median_is_default(self, user, household, cat, pix):
        rows_default = build_projection(household, date(2026, 7, 1), 1, today=date(2026, 6, 15))
        rows_median = build_projection(
            household, date(2026, 7, 1), 1, today=date(2026, 6, 15), diverse_estimator="median"
        )
        assert rows_default[0]["diverse_estimated"] == rows_median[0]["diverse_estimated"]


@pytest.mark.django_db
def test_projection_is_scoped_to_the_household(user, household, other_user, other_household):
    """The neighbour's ledger must not appear in this household's projection."""
    baker.make(
        "finances.Entry",
        household=other_household,
        amount=Decimal("999.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )
    baker.make(
        "finances.Entry",
        household=household,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    rows = build_projection(household, date(2026, 3, 1), 1, today=date(2026, 3, 15))

    assert rows[0]["total"] == Decimal("10.00")


@pytest.mark.django_db
def test_projection_of_no_household_is_empty_not_everything(user, household):
    """Fail closed. An unresolved tenant must never mean 'the whole table'."""
    baker.make(
        "finances.Entry",
        household=household,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    rows = build_projection(None, date(2026, 3, 1), 1, today=date(2026, 3, 15))

    assert rows[0]["total"] == Decimal("0")
