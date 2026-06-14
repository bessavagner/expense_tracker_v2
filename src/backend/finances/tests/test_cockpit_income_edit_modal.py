from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from finances.models import Income

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="u", password="pw")


@pytest.fixture
def income(user):
    return Income.objects.create(
        user=user, name="Salário", amount=Decimal("5000"), month=date(2026, 6, 1)
    )


def test_get_returns_prefilled_form(client, user, income):
    client.force_login(user)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026, 6, income.id])
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Salário" in body
    assert "modal-edit-form" in body


def test_post_updates_and_rerenders_section(client, user, income):
    client.force_login(user)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026, 6, income.id])
    resp = client.post(
        url,
        {"name": "Salário", "amount": "5500", "month": "2026-06-01", "is_recurring": ""},
    )
    assert resp.status_code == 200
    income.refresh_from_db()
    assert income.amount == Decimal("5500")
    assert "cockpit-income" in resp.content.decode()
    assert "entry-saved" in resp.headers.get("HX-Trigger", "")


def test_post_invalid_returns_form(client, user, income):
    client.force_login(user)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026, 6, income.id])
    resp = client.post(url, {"name": "", "amount": "", "month": ""})
    assert resp.status_code == 200
    assert "modal-edit-form" in resp.content.decode()
    income.refresh_from_db()
    assert income.name == "Salário"


def test_cross_user_404(client, income):
    other = get_user_model().objects.create_user(username="o", password="pw")
    client.force_login(other)
    url = reverse("finances:cockpit_income_edit_modal", args=[2026, 6, income.id])
    assert client.get(url).status_code == 404


def test_income_row_is_clickable(client, user, income):
    client.force_login(user)
    resp = client.get(reverse("finances:cockpit_income", args=[2026, 6]))
    html = resp.content.decode()
    edit_url = reverse("finances:cockpit_income_edit_modal", args=[2026, 6, income.id])
    assert f'hx-get="{edit_url}"' in html
    assert "event.stopPropagation()" in html
