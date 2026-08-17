"""Signing up records *which* documents were accepted, and which version.

The DoD asks for "signup records acceptance of a specific policy version".
Specific is the whole requirement: a boolean would satisfy a checkbox on a
form and nothing a regulator would ask for.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from core.models import PolicyAcceptance, PolicyDocument

pytestmark = pytest.mark.django_db

GOOD = {
    "email": "nova@example.com",
    "email2": "nova@example.com",
    "password1": "uma-senha-bem-comprida-7",
    "password2": "uma-senha-bem-comprida-7",
}


def test_signing_up_records_both_documents_at_their_current_versions():
    response = Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})
    assert response.status_code in (200, 302)

    accepted = {
        (row.document, row.version)
        for row in PolicyAcceptance.objects.filter(user__email="nova@example.com")
    }
    assert accepted == {
        (PolicyDocument.PRIVACY, settings.PRIVACY_POLICY_VERSION),
        (PolicyDocument.TERMS, settings.TERMS_VERSION),
    }


def test_the_checkbox_is_required_and_no_account_is_created_without_it():
    from core.models import CustomUser

    response = Client().post(reverse("account_signup"), GOOD)

    assert response.status_code == 200  # re-rendered with an error, not a redirect
    assert not CustomUser.objects.filter(email="nova@example.com").exists()
    assert not PolicyAcceptance.objects.exists()


def test_the_error_is_in_portuguese():
    response = Client().post(reverse("account_signup"), GOOD)
    body = response.content.decode()
    assert "Termos de Uso" in body or "aceitar" in body.lower()


def test_the_signup_page_links_both_documents_so_they_can_be_read_first():
    """An acceptance of a document with no link to it is not informed consent."""
    body = Client().get(reverse("account_signup")).content.decode()
    assert reverse("privacy_notice") in body
    assert reverse("terms_of_service") in body


def test_the_ip_is_recorded():
    Client().post(
        reverse("account_signup"),
        {**GOOD, "accept_terms": "on"},
        REMOTE_ADDR="203.0.113.7",
    )
    rows = PolicyAcceptance.objects.filter(user__email="nova@example.com")
    assert {row.ip for row in rows} == {"203.0.113.7"}


def test_signing_up_does_not_grant_ai_consent():
    """Plan decision D3b: the AI ask happens in context, at first use. Bundling
    it into this checkbox would make it neither specific nor informed."""
    from core.models import CustomUser
    from core.privacy import has_ai_consent

    Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})
    person = CustomUser.objects.get(email="nova@example.com")
    assert has_ai_consent(person) is False


def test_the_existing_signup_side_effects_still_happen():
    """E04 seeds a household on signup and E14 emits the `signup` event. This
    form sits in the middle of that flow, so it is worth asserting it did not
    displace either."""
    from accounts.models import Membership
    from core.events import EventName
    from core.models import CustomUser, ProductEvent

    Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})

    person = CustomUser.objects.get(email="nova@example.com")
    assert Membership.objects.filter(user=person).exists()
    assert ProductEvent.objects.filter(name=EventName.SIGNUP).exists()
