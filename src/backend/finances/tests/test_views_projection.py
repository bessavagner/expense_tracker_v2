from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestProjectionView:
    def test_requires_login(self):
        response = Client().get("/projection/")
        assert response.status_code in (302, 401, 403)

    def test_renders_page(self, logged_client):
        response = logged_client.get("/projection/")
        assert response.status_code == 200
        assert "projection/projection_page.html" in [t.name for t in response.templates]
        assert "rows" in response.context

    def test_htmx_returns_partial(self, logged_client):
        response = logged_client.get("/projection/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "projection/_projection_table.html" in [t.name for t in response.templates]

    def test_respects_start_and_months_params(self, logged_client):
        response = logged_client.get("/projection/?start=2026-03&months=4")
        rows = response.context["rows"]
        assert len(rows) == 4
        assert rows[0]["month"] == date(2026, 3, 1)
        assert rows[-1]["month"] == date(2026, 6, 1)

    def test_clamps_invalid_months(self, logged_client):
        # Too-large / non-positive months are clamped to a sane range, never crash.
        big = logged_client.get("/projection/?start=2026-01&months=999")
        assert big.status_code == 200
        assert 1 <= len(big.context["rows"]) <= 36

        zero = logged_client.get("/projection/?start=2026-01&months=0")
        assert zero.status_code == 200
        assert len(zero.context["rows"]) >= 1

    def test_bad_start_falls_back_to_default(self, logged_client):
        response = logged_client.get("/projection/?start=garbage")
        assert response.status_code == 200
        assert len(response.context["rows"]) >= 1

    def test_scoped_to_user(self, logged_client, other_user):
        cat = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            amount=Decimal("5000"),
            category=cat,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
            billing_month_override=True,
        )
        response = logged_client.get("/projection/?start=2026-03&months=1")
        assert response.context["rows"][0]["total"] == Decimal("0")


@pytest.mark.django_db
def test_start_control_is_year_and_month_selects(logged_client):
    html = logged_client.get(reverse("finances:projection")).content.decode()
    assert 'name="start_year"' in html
    assert 'name="start_month"' in html


@pytest.mark.django_db
def test_year_options_span_data_history(logged_client, user):
    cat = baker.make("finances.Category", user=user)
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make("finances.Entry", user=user, category=cat, payment_method=pm,
               amount=Decimal("10"), date=date(2024, 3, 1), billing_month=date(2024, 3, 1),
               billing_month_override=True)
    html = logged_client.get(reverse("finances:projection")).content.decode()
    assert '<option value="2024"' in html


@pytest.mark.django_db
def test_start_year_month_params_drive_window(logged_client):
    html = logged_client.get(
        reverse("finances:projection"), {"start_year": "2026", "start_month": "3", "months": "2"}
    ).content.decode()
    assert "mar/2026" in html.lower() or "Mar/2026" in html


@pytest.mark.django_db
def test_whatif_add_then_table_shows_simulado(logged_client):
    r = logged_client.post("/projection/whatif/add/", {
        "type": "income", "label": "bônus", "amount": "5000", "month": "2026-08",
    })
    assert r.status_code == 200
    assert b"Simula" in r.content  # simulated row label rendered


@pytest.mark.django_db
def test_whatif_clear_empties_session(logged_client):
    logged_client.post("/projection/whatif/add/", {
        "type": "expense_oneoff", "label": "x", "amount": "100", "month": "2026-08"})
    logged_client.post("/projection/whatif/clear/")
    sess = logged_client.session
    assert sess.get("projection_whatif", []) == []


@pytest.mark.django_db
def test_projection_shows_estimated_total_row_above_estimated_balance(logged_client):
    resp = logged_client.get("/projection/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Gastos totais estimados" in body
    # must sit immediately above the estimated saldo row
    assert body.index("Gastos totais estimados") < body.index("Saldo projetado estimado")
