"""Clicking a link sent to an address proves you control that address.

Asking an invitee to then verify the same address is a round trip through an
email client for no security gain — and it is where the invite flow loses
people. The proof is narrow on purpose: only the address the invitation was
sent to, and only while the invitation is still pending.
"""

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.invitations import create_invitation
from accounts.models import Membership

SENHA = "senha-da-convidada-99"


@pytest.mark.django_db
class TestInvitedSignupSkipsVerification:
    def _signup_via_invitation(self, household, user, email, invited_email=None):
        _, raw = create_invitation(
            household=household, invited_by=user, email=invited_email or email
        )
        accept_path = reverse("invite_accept", args=[raw])
        client = Client()
        client.get(accept_path)  # stashes the token in the session
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {"email": email, "email2": email, "password1": SENHA, "password2": SENHA},
        )
        return client, accept_path

    def test_the_invited_address_is_verified_without_an_email(self, household, user):
        mail.outbox.clear()
        client, _ = self._signup_via_invitation(household, user, "nova@example.com")

        address = EmailAddress.objects.get(email="nova@example.com")
        assert address.verified is True
        assert "_auth_user_id" in client.session, "invited signup did not log in"

    def test_no_verification_email_is_sent_to_an_invited_address(self, household, user):
        mail.outbox.clear()
        self._signup_via_invitation(household, user, "nova@example.com")
        subjects = [m.subject for m in mail.outbox]
        assert not any("Confirme" in s for s in subjects), subjects

    def test_signing_up_with_a_different_address_still_verifies_normally(self, household, user):
        """The proof covers the invited address only. Anything else is a
        stranger typing a stranger's address and must not be trusted."""
        mail.outbox.clear()
        client, _ = self._signup_via_invitation(
            household, user, email="outra@example.com", invited_email="convidada@example.com"
        )
        address = EmailAddress.objects.get(email="outra@example.com")
        assert address.verified is False
        assert "_auth_user_id" not in client.session

    def test_an_ordinary_signup_is_untouched(self):
        mail.outbox.clear()
        client = Client()
        client.post(
            reverse("account_signup"),
            {
                "email": "sozinha@example.com",
                "email2": "sozinha@example.com",
                "password1": SENHA,
                "password2": SENHA,
            },
        )
        assert EmailAddress.objects.get(email="sozinha@example.com").verified is False
        assert len(mail.outbox) == 1

    def test_a_revoked_invitation_proves_nothing(self, household, user):
        """The exemption is scoped to a *pending* invitation. A token whose
        owner changed their mind must not still be a free pass."""
        from accounts.invitations import revoke_invitation

        invitation, raw = create_invitation(
            household=household, invited_by=user, email="tarde@example.com"
        )
        accept_path = reverse("invite_accept", args=[raw])
        client = Client()
        client.get(accept_path)
        revoke_invitation(invitation)

        mail.outbox.clear()
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {
                "email": "tarde@example.com",
                "email2": "tarde@example.com",
                "password1": SENHA,
                "password2": SENHA,
            },
        )
        assert EmailAddress.objects.get(email="tarde@example.com").verified is False


@pytest.mark.django_db
class TestTheInviteeLandsInTheHousehold:
    def test_signup_then_accept_produces_the_membership(self, household, user):
        _, raw = create_invitation(household=household, invited_by=user, email="nova@example.com")
        accept_path = reverse("invite_accept", args=[raw])
        client = Client()
        client.get(accept_path)
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {
                "email": "nova@example.com",
                "email2": "nova@example.com",
                "password1": SENHA,
                "password2": SENHA,
            },
        )
        client.post(accept_path)

        joined = Membership.objects.filter(household=household).exclude(user=user)
        assert joined.count() == 1
        assert joined.first().user.email == "nova@example.com"
