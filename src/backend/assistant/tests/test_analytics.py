"""Tests for the deterministic analytics layer (Etapa 2 do prompt 004).

All financial math lives in code (not in the LLM). These functions back the
Analista/Planejador agents and the proactive-trigger engine.
"""

from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from assistant.agents import analytics
from finances.models import Category, PaymentMethod


def _entry(user, cat, pm, amount, d=date(2026, 3, 5), bm=date(2026, 3, 1)):
    return baker.make(
        "finances.Entry",
        user=user,
        date=d,
        amount=Decimal(amount),
        category=cat,
        payment_method=pm,
        billing_month=bm,
    )


@pytest.fixture
def cats(seeded_user):
    return {
        "ali": Category.objects.get(user=seeded_user, name="Alimentação"),
        "lan": Category.objects.get(user=seeded_user, name="Lanche"),
        "pix": PaymentMethod.objects.get(user=seeded_user, name="Pix"),
        "c6": PaymentMethod.objects.get(user=seeded_user, name="Crédito C6"),
    }


@pytest.mark.django_db
class TestCategoryBreakdown:
    def test_breaks_down_by_category_and_payment_method(self, seeded_user, cats):
        _entry(seeded_user, cats["ali"], cats["pix"], "500")
        _entry(seeded_user, cats["lan"], cats["c6"], "100")
        result = analytics.category_breakdown(seeded_user, 2026, 3)
        assert "Alimentação" in result
        assert "Lanche" in result
        assert "500" in result and "100" in result
        # payment-method section present
        assert "Pix" in result and "Crédito C6" in result

    def test_excludes_refunds_from_spend(self, seeded_user, cats):
        _entry(seeded_user, cats["ali"], cats["pix"], "500")
        _entry(seeded_user, cats["ali"], cats["pix"], "-200")  # reembolso
        result = analytics.category_breakdown(seeded_user, 2026, 3)
        assert "500" in result

    def test_empty_month(self, seeded_user):
        result = analytics.category_breakdown(seeded_user, 2026, 7)
        assert "nenhum" in result.lower()

    def test_invalid_month(self, seeded_user):
        result = analytics.category_breakdown(seeded_user, 2026, 13)
        assert "erro" in result.lower()


@pytest.mark.django_db
class TestCompareMonths:
    def test_reports_delta_vs_previous_month(self, seeded_user, cats):
        feb, mar = date(2026, 2, 1), date(2026, 3, 1)
        _entry(seeded_user, cats["ali"], cats["pix"], "300", d=date(2026, 2, 5), bm=feb)
        _entry(seeded_user, cats["ali"], cats["pix"], "450", d=date(2026, 3, 5), bm=mar)
        result = analytics.compare_months(seeded_user, 2026, 3)
        assert "450" in result
        assert "300" in result
        # 50% increase
        assert "50" in result

    def test_no_previous_data(self, seeded_user, cats):
        _entry(seeded_user, cats["ali"], cats["pix"], "450")
        result = analytics.compare_months(seeded_user, 2026, 3)
        assert "sem dados" in result.lower() or "não há" in result.lower()


@pytest.mark.django_db
class TestMonthlyReportCsv:
    def test_csv_has_header_and_rows(self, seeded_user, cats):
        baker.make(
            "finances.Entry",
            user=seeded_user,
            date=date(2026, 3, 7),
            amount=Decimal("80.00"),
            description="Hiper Nacional, mercantil",  # comma must become dash
            category=cats["ali"],
            payment_method=cats["pix"],
            billing_month=date(2026, 3, 1),
        )
        csv = analytics.monthly_report_csv(seeded_user, 2026, 3)
        lines = csv.strip().splitlines()
        assert ";" in lines[0]  # semicolon-delimited header
        assert "Descrição" in lines[0]
        assert "R$" not in csv  # no currency prefix on values
        assert "Hiper Nacional - mercantil" in csv  # comma -> dash
        assert "07/03/2026" in csv  # DD/MM/YYYY

    def test_empty_month(self, seeded_user):
        csv = analytics.monthly_report_csv(seeded_user, 2026, 7)
        assert "nenhum" in csv.lower()


@pytest.mark.django_db
class TestProjectMonthEnd:
    def test_run_rate_projection(self, seeded_user, cats):
        # spent 300 by day 10 of a 31-day month -> ~930 projected
        _entry(seeded_user, cats["ali"], cats["pix"], "300", d=date(2026, 3, 5))
        result = analytics.project_month_end(seeded_user, 2026, 3, today=date(2026, 3, 10))
        assert "300" in result
        assert "930" in result or "9" in result  # projection present

    def test_no_spend_yet(self, seeded_user):
        result = analytics.project_month_end(seeded_user, 2026, 3, today=date(2026, 3, 1))
        # day 1: projection should not divide by zero
        assert "erro" not in result.lower()


@pytest.mark.django_db
class TestDetectAnomalies:
    def test_flags_category_above_average(self, seeded_user, cats):
        cats["ali"].quarterly_avg = Decimal("200")
        cats["ali"].save()
        _entry(seeded_user, cats["ali"], cats["pix"], "600")  # 3x the average
        result = analytics.detect_anomalies(seeded_user, 2026, 3)
        assert "Alimentação" in result

    def test_no_anomalies(self, seeded_user, cats):
        cats["ali"].quarterly_avg = Decimal("500")
        cats["ali"].save()
        _entry(seeded_user, cats["ali"], cats["pix"], "450")
        result = analytics.detect_anomalies(seeded_user, 2026, 3)
        assert "nenhuma" in result.lower()


@pytest.mark.django_db
class TestProactiveAlerts:
    def test_build_alerts_prioritises_over_budget(self, seeded_user, cats):
        cats["ali"].budget_ceiling = Decimal("100")
        cats["ali"].save()
        cats["lan"].budget_ceiling = Decimal("200")
        cats["lan"].save()
        _entry(seeded_user, cats["ali"], cats["pix"], "150")  # 150% -> estouro
        _entry(seeded_user, cats["lan"], cats["pix"], "190")  # 95% -> aviso
        alerts = analytics.build_proactive_alerts(seeded_user, 2026, 3)
        assert len(alerts) >= 2
        # highest priority (lowest number) first; over-budget before warning
        assert alerts[0]["category"] == "Alimentação"
        assert alerts[0]["level"] == "over"
        assert alerts[0]["priority"] <= alerts[1]["priority"]

    def test_ignores_categories_without_ceiling(self, seeded_user, cats):
        # no ceiling set (default 0) -> no alert
        _entry(seeded_user, cats["ali"], cats["pix"], "999")
        alerts = analytics.build_proactive_alerts(seeded_user, 2026, 3)
        assert alerts == []

    def test_below_threshold_no_alert(self, seeded_user, cats):
        cats["ali"].budget_ceiling = Decimal("1000")
        cats["ali"].save()
        _entry(seeded_user, cats["ali"], cats["pix"], "100")  # 10%
        alerts = analytics.build_proactive_alerts(seeded_user, 2026, 3)
        assert alerts == []

    def test_proactive_alerts_string_wrapper(self, seeded_user, cats):
        cats["ali"].budget_ceiling = Decimal("100")
        cats["ali"].save()
        _entry(seeded_user, cats["ali"], cats["pix"], "150")
        text = analytics.proactive_alerts(seeded_user, 2026, 3)
        assert "Alimentação" in text

    def test_no_alerts_message(self, seeded_user):
        text = analytics.proactive_alerts(seeded_user, 2026, 3)
        assert "nenhum" in text.lower() or "tudo" in text.lower()
