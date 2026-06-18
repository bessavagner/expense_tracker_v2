"""Regression: HTMX mutations (e.g. excluir renda) need a CSRF token.

`hx-delete`/`hx-post` buttons that are not inside a `{% csrf_token %}` form
carry no token, so `CsrfViewMiddleware` rejected them with 403 — the cause of
"excluir renda não funciona". The fix sets a global `hx-headers` X-CSRFToken on
`<body>` in base.html, so every HTMX request is authenticated.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestHtmxCsrfWiring:
    def test_base_template_sets_global_csrf_header(self, logged_client):
        """Every page must advertise the X-CSRFToken header for HTMX."""
        response = logged_client.get("/entries/2026/3/")
        content = response.content.decode()
        assert "hx-headers=" in content
        assert "X-CSRFToken" in content
        # Token must be interpolated, not the literal template tag.
        assert "{{ csrf_token }}" not in content

    def test_income_delete_succeeds_with_csrf_header(self, user):
        """Browser sends X-CSRFToken (via base.html) → delete works."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get("/entries/2026/3/")  # sets the csrftoken cookie
        token = client.cookies["csrftoken"].value
        inc = baker.make(
            "finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("100")
        )
        response = client.delete(
            f"/cockpit/2026/3/income/{inc.id}/delete/",
            HTTP_HX_REQUEST="true",
            HTTP_X_CSRFTOKEN=token,
        )
        assert response.status_code == 200
        from finances.models import Income

        assert not Income.objects.filter(pk=inc.pk).exists()

    def test_income_delete_rejected_without_csrf(self, user):
        """Documents the bug: no token → 403 (what was happening before)."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        inc = baker.make(
            "finances.Income", user=user, month=date(2026, 3, 1), amount=Decimal("100")
        )
        response = client.delete(
            f"/cockpit/2026/3/income/{inc.id}/delete/", HTTP_HX_REQUEST="true"
        )
        assert response.status_code == 403
