"""A user with no Membership must still be able to write.

Phase 4 deleted `accounts/bridge.py`, whose `household_for_writer` minted a
user their own household on first write, and made `household` NOT NULL in the
same commit. Nothing on a request path calls `household_for_user` any more, so
`request.household` is None for such a user and every write raises
IntegrityError — an unhandled 500.

`manage.py createsuperuser` produces exactly such a user, and the runbook tells
the operator to run it after deploying. So does adding a user through the admin.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts.models import Membership
from finances.models import Income

pytestmark = pytest.mark.django_db


@pytest.fixture
def fresh_user():
    """A user created the way `createsuperuser` and the admin create one."""
    user = get_user_model().objects.create_user(username="novato", password="pw")
    assert not Membership.objects.filter(user=user).exists()
    return user


@pytest.fixture
def fresh_client(fresh_user):
    client = Client()
    client.force_login(fresh_user)
    return client


def test_a_user_with_no_membership_resolves_a_household(fresh_user):
    """The middleware must not hand a view `request.household = None`."""
    from accounts.middleware import resolve_active_household

    request = type("R", (), {"user": fresh_user, "session": {}})()

    assert resolve_active_household(request) is not None


def test_a_user_with_no_membership_can_create_an_income(fresh_client):
    """The runbook's own happy path: deploy, createsuperuser, log in, add income.

    Asserts the row lands, not merely that the response was not a 500 — an
    invalid form also returns 200 without ever reaching ``save()``, so a
    status-only assertion passes vacuously.
    """
    response = fresh_client.post(
        reverse("finances:settings_income_create"),
        {"name": "Salário", "amount": "1000.00", "month": "2026-08-01"},
    )

    assert response.status_code < 400, response.status_code
    assert Income.objects.count() == 1
