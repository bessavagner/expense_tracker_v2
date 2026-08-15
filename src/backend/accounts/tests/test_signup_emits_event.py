"""Signup is the funnel's anchor: time-to-activation is measured from it."""

import pytest
from django.urls import reverse

from core.events import EventName
from core.models import ProductEvent


@pytest.mark.django_db
def test_signing_up_emits_a_signup_event(client):
    client.post(
        reverse("account_signup"),
        {
            "email": "novo@example.com",
            "email2": "novo@example.com",
            "password1": "uma-senha-bem-comprida",
            "password2": "uma-senha-bem-comprida",
        },
    )

    event = ProductEvent.objects.get(name=EventName.SIGNUP)
    assert event.user.email == "novo@example.com"
    assert event.household == event.user.memberships.get().household
