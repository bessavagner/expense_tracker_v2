from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.models.entry import EntryType
from finances.services.projection import build_projection


def _entry(user, cat, pm, amount, billing_month, entry_type=EntryType.REGULAR, d=None):
    return baker.make(
        "finances.Entry",
        user=user,
        date=d or billing_month,
        amount=Decimal(amount),
        category=cat,
        payment_method=pm,
        entry_type=entry_type,
        billing_month=billing_month,
        billing_month_override=True,  # pin so save() doesn't recompute
    )


@pytest.fixture
def cat(user):
    return baker.make("finances.Category", user=user, name="Diversos")


@pytest.fixture
def pix(user):
    return baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")


@pytest.mark.django_db
class TestBuildProjection:
    def test_returns_one_row_per_month(self, user):
        rows = build_projection(user, date(2026, 1, 1), 3, today=date(2026, 1, 15))
        assert [r["month"] for r in rows] == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]

    def test_past_month_all_rows(self, user, cat, pix):
        m = date(2026, 5, 1)
        _entry(user, cat, pix, "300", m, EntryType.SYSTEMIC)
        _entry(user, cat, pix, "200", m, EntryType.INSTALLMENT)
        _entry(user, cat, pix, "150", m, EntryType.REGULAR)
        baker.make("finances.Income", user=user, amount=Decimal("2000"), month=m)

        # May is in the past relative to this "today"
        row = build_projection(user, m, 1, today=date(2026, 6, 15))[0]

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

    def test_future_month_projects_systemics_from_templates(self, user, cat, pix):
        # Active templates → future systemic projection
        baker.make(
            "finances.SystemicExpense",
            user=user,
            category=cat,
            default_amount=Decimal("400"),
            is_active=True,
        )
        baker.make(
            "finances.SystemicExpense",
            user=user,
            category=cat,
            default_amount=Decimal("100"),
            is_active=True,
        )
        # An inactive template must NOT count
        baker.make(
            "finances.SystemicExpense",
            user=user,
            category=cat,
            default_amount=Decimal("9999"),
            is_active=False,
        )
        future = date(2026, 8, 1)
        # A future installment entry already materialized
        _entry(user, cat, pix, "250", future, EntryType.INSTALLMENT)

        row = build_projection(user, future, 1, today=date(2026, 6, 15))[0]

        assert row["systemic"] == Decimal("500")  # 400 + 100, inactive excluded
        assert row["installments"] == Decimal("250")
        assert row["programmed"] == Decimal("750")
        assert row["diverse"] == Decimal("0")
        assert row["total"] == Decimal("750")

    def test_future_systemic_ignores_actual_entries_uses_templates(self, user, cat, pix):
        """Even if a stray SYSTEMIC entry exists in a future month, the projection
        for a strictly-future month comes from active templates (predictable)."""
        baker.make(
            "finances.SystemicExpense",
            user=user,
            category=cat,
            default_amount=Decimal("400"),
            is_active=True,
        )
        future = date(2026, 8, 1)
        _entry(user, cat, pix, "777", future, EntryType.SYSTEMIC)

        row = build_projection(user, future, 1, today=date(2026, 6, 15))[0]
        assert row["systemic"] == Decimal("400")

    def test_acumulado_is_cumulative(self, user, cat, pix):
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 1, 1))
        _entry(user, cat, pix, "200", date(2026, 1, 1), EntryType.REGULAR)
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 2, 1))
        _entry(user, cat, pix, "300", date(2026, 2, 1), EntryType.REGULAR)

        rows = build_projection(user, date(2026, 1, 1), 2, today=date(2026, 3, 1))
        # Jan saldo projetado = 800; Feb = 700
        assert rows[0]["saldo_projetado"] == Decimal("800")
        assert rows[1]["saldo_projetado"] == Decimal("700")
        assert rows[0]["acumulado"] == Decimal("800")
        assert rows[1]["acumulado"] == Decimal("1500")  # 800 + 700

    def test_acumulado_is_historical_independent_of_window(self, user, cat, pix):
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 1, 1))
        _entry(user, cat, pix, "200", date(2026, 1, 1), EntryType.REGULAR)  # Jan saldo 800
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2026, 2, 1))
        _entry(user, cat, pix, "300", date(2026, 2, 1), EntryType.REGULAR)  # Feb saldo 700
        # Window starts in Feb, but acumulado must include January's history.
        rows = build_projection(user, date(2026, 2, 1), 1, today=date(2026, 3, 1))
        assert rows[0]["month"] == date(2026, 2, 1)
        assert rows[0]["saldo_projetado"] == Decimal("700")
        assert rows[0]["acumulado"] == Decimal("1500")  # 800 (Jan) + 700 (Feb)

    def test_pre_origin_data_excluded_from_acumulado(self, user, cat, pix):
        # Data before the projection origin (Nov 2025) is migration/seed noise and
        # must NOT leak into the running total, even though acumulado is otherwise
        # anchored at the earliest data.
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2025, 9, 1))
        _entry(user, cat, pix, "200", date(2025, 9, 1), EntryType.REGULAR)  # pre-origin
        baker.make("finances.Income", user=user, amount=Decimal("1000"), month=date(2025, 11, 1))
        _entry(user, cat, pix, "300", date(2025, 11, 1), EntryType.REGULAR)  # origin month

        rows = build_projection(user, date(2025, 11, 1), 1, today=date(2025, 12, 1))
        assert rows[0]["month"] == date(2025, 11, 1)
        assert rows[0]["saldo_projetado"] == Decimal("700")
        # Only November's 700 — September's 800 must be excluded.
        assert rows[0]["acumulado"] == Decimal("700")

    def test_zero_income_pct_is_none(self, user, cat, pix):
        _entry(user, cat, pix, "100", date(2026, 5, 1), EntryType.REGULAR)
        row = build_projection(user, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
        assert row["income"] == Decimal("0")
        assert row["pct_income"] is None

    def test_scoped_to_user(self, user, other_user, cat, pix):
        other_cat = baker.make("finances.Category", user=other_user)
        other_pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        _entry(other_user, other_cat, other_pm, "5000", date(2026, 5, 1), EntryType.REGULAR)

        row = build_projection(user, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
        assert row["diverse"] == Decimal("0")
        assert row["total"] == Decimal("0")

    def test_empty_month_is_all_zero(self, user):
        row = build_projection(user, date(2026, 5, 1), 1, today=date(2026, 6, 1))[0]
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
    def test_overlay_none_matches_baseline(self, user, cat, pix):
        m = date(2026, 5, 1)
        _entry(user, cat, pix, "150", m, EntryType.REGULAR)
        baker.make("finances.Income", user=user, amount=Decimal("2000"), month=m)
        base = build_projection(user, m, 2, today=date(2026, 6, 15))
        same = build_projection(user, m, 2, today=date(2026, 6, 15), overlay=None)
        assert [r["acumulado"] for r in base] == [r["acumulado"] for r in same]

    def test_overlay_expense_lowers_saldo_and_acumulado(self, user):
        m = date(2026, 6, 1)
        baker.make("finances.Income", user=user, amount=Decimal("2000"), month=m)
        overlay = {(m, "regular"): Decimal("500")}
        row = build_projection(user, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["diverse"] == Decimal("500")
        assert row["saldo_projetado"] == Decimal("1500")  # 2000 - 500
        assert row["acumulado"] == Decimal("1500")

    def test_overlay_income_raises_saldo(self, user):
        m = date(2026, 6, 1)
        overlay = {(m, "income"): Decimal("1000")}
        row = build_projection(user, m, 1, today=date(2026, 6, 15), overlay=overlay)[0]
        assert row["income"] == Decimal("1000")
        assert row["saldo_projetado"] == Decimal("1000")


@pytest.mark.django_db
class TestDiverseEstimator:
    def test_ceiling_estimator_uses_total_ceiling(self, user, cat, pix):
        from decimal import Decimal
        from model_bakery import baker
        b = baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("3000"))
        baker.make("finances.Category", user=user, name="Lazer", budget=None,
                   budget_ceiling=Decimal("500"))
        # future month, no posted diversas -> estimate drives diverse_estimated
        rows = build_projection(
            user, date(2026, 7, 1), 1, today=date(2026, 6, 15),
            diverse_estimator="ceiling",
        )
        assert rows[0]["diverse_estimated"] == Decimal("3500")

    def test_median_is_default(self, user, cat, pix):
        rows_default = build_projection(user, date(2026, 7, 1), 1, today=date(2026, 6, 15))
        rows_median = build_projection(user, date(2026, 7, 1), 1, today=date(2026, 6, 15),
                                       diverse_estimator="median")
        assert rows_default[0]["diverse_estimated"] == rows_median[0]["diverse_estimated"]
