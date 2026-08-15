"""Every day-one surface renders against no data and must teach, not just shrug.

Server-rendered surfaces only. The React cards are covered by `pnpm build`
plus the visual-verdict pass, since this repo has no frontend test runner.
"""

from datetime import date

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestEmptySurfacesTeach:
    def test_the_entries_table_offers_the_camera(self, logged_client):
        body = logged_client.get(reverse("finances:entries_month", args=[2026, 8])).content.decode()

        assert "Nenhuma entrada neste mês" in body
        assert "cupom" in body

    def test_the_consolidated_view_explains_what_will_appear(self, logged_client):
        body = logged_client.get(reverse("finances:consolidated")).content.decode()

        assert "categoria" in body.lower()

    def test_the_categories_tab_says_what_a_category_is_for(self, logged_client):
        body = logged_client.get(reverse("finances:settings_categories")).content.decode()

        assert "como o app agrupa seus gastos" in body

    def test_the_payment_methods_tab_explains_the_closing_day(self, logged_client):
        body = logged_client.get(reverse("finances:settings_payment_methods")).content.decode()

        assert "fecha a fatura" in body

    def test_the_income_tab_says_why_income_matters(self, logged_client):
        body = logged_client.get(reverse("finances:settings_income")).content.decode()

        assert "quanto sobra" in body

    def test_the_projection_explains_itself_before_there_is_data(self, logged_client):
        """Keyed on the household having no data, NOT on `rows` being empty.

        `_default_start` returns last month, which is after the projection
        origin in every realistic case, so `build_projection` returns a full
        window of zero rows and the `{% if not rows %}` branch never fires for
        a new household. It stays as the pre-origin fallback it already was.
        """
        body = logged_client.get(reverse("finances:projection")).content.decode()

        assert "Nada para projetar ainda" in body
        assert "estimar os próximos meses" in body

    def test_the_projection_stops_teaching_once_there_is_data(self, logged_client, household, user):
        from model_bakery import baker

        baker.make(
            "finances.Income",
            household=household,
            created_by=user,
            month=date(2026, 8, 1),
            amount=1000,
        )

        body = logged_client.get(reverse("finances:projection")).content.decode()

        assert "Nada para projetar ainda" not in body


@pytest.mark.django_db
class TestTheCockpitSectionsTeach:
    """The cockpit is four HTMX fragments, each of which a new household hits empty."""

    def test_the_income_section_says_where_income_comes_from(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_income", args=[2026, 8])
        ).content.decode()

        assert "quanto sobra" in body

    def test_the_systemic_section_explains_what_a_systemic_expense_is(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_systemic", args=[2026, 8])
        ).content.decode()

        assert "todo mês" in body

    def test_the_parcelamentos_section_explains_itself(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_parcelamentos", args=[2026, 8])
        ).content.decode()

        assert "parcelada" in body

    def test_the_vencimentos_section_points_at_the_card_setup(self, logged_client):
        body = logged_client.get(
            reverse("finances:cockpit_vencimentos", args=[2026, 8])
        ).content.decode()

        assert reverse("finances:settings_payment_methods") in body
