from datetime import date

from finances.forms import CockpitIncomeForm, IncomeForm


def test_income_form_normalizes_month_to_first_day():
    form = IncomeForm(
        data={"name": "Salário", "amount": "8655.00", "month": "2026-06-18", "is_recurring": False}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["month"] == date(2026, 6, 1)


def test_income_form_month_widget_renders_iso_value():
    form = IncomeForm(initial={"month": date(2026, 7, 1)})
    assert 'type="date"' in str(form["month"])
    # ISO value so <input type=date> prefills (pt-BR localizado viria como 01/07/2026)
    assert "2026-07-01" in str(form["month"])


def test_cockpit_income_form_month_widget_renders_iso_value():
    form = CockpitIncomeForm(initial={"month": date(2026, 7, 1)})
    assert "2026-07-01" in str(form["month"])
