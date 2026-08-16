"""The operator dashboard: staff only, and honest about empty data."""

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db

URL = "/metricas/"


def test_an_anonymous_visitor_is_turned_away(client):
    response = client.get(URL)
    assert response.status_code in (302, 403, 404)


def test_an_ordinary_user_cannot_see_it(client, django_user_model):
    """Household metrics across ALL households. A beta user seeing this would be
    seeing other families' behaviour."""
    user = baker.make(django_user_model, username="familia", is_staff=False)
    client.force_login(user)

    assert client.get(URL).status_code in (302, 403, 404)


def test_staff_can_see_it(client, django_user_model):
    staff = baker.make(django_user_model, username="operador", is_staff=True)
    client.force_login(staff)

    response = client.get(URL)

    assert response.status_code == 200


def test_it_renders_with_no_data_at_all(client, django_user_model):
    """The first time this is opened there will be nothing. An operator dashboard
    that 500s on an empty database is one nobody opens twice."""
    staff = baker.make(django_user_model, username="operador", is_staff=True)
    client.force_login(staff)

    response = client.get(URL)

    assert response.status_code == 200
    assert "Ativação" in response.content.decode()


def test_the_login_redirect_does_not_leak_the_admin_path(client, settings):
    """`staff_member_required` sends people to the admin login by default, and
    `core.admin_gate` keeps that path secret — a 404 there must stay
    indistinguishable from a wrong guess."""
    response = client.get(URL)

    assert settings.ADMIN_URL_PATH.strip("/") not in response.get("Location", "")
