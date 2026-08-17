"""Owner invites, invitee joins, both see one ledger.

The epic's second observable assertion. The interesting case is the invitee
with no account: they arrive at a link, have to sign up, have to verify, and
must still land inside the right household afterwards — a round trip through
three redirects and an email client, which is exactly where a session-only
design loses the token.
"""

import re

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.invitations import create_invitation
from accounts.models import Membership, Role

SENHA = "senha-da-convidada-99"


def _link_from(message, fragment):
    urls = re.findall(r"https?://\S+", message.body)
    matches = [u for u in urls if fragment in u]
    assert matches, f"no {fragment!r} link in:\n{message.body}"
    return matches[0].split("testserver")[-1]


@pytest.mark.django_db
class TestOwnerSendsAnInvitation:
    def test_an_owner_can_invite_by_email(self, logged_client, household):
        response = logged_client.post(reverse("invite_create"), {"email": "parceira@example.com"})
        assert response.status_code in (200, 302)
        assert household.accounts_invitation.filter(email="parceira@example.com").exists()

    def test_the_invitation_email_carries_a_link(self, logged_client):
        logged_client.post(reverse("invite_create"), {"email": "parceira@example.com"})
        assert len(mail.outbox) == 1
        assert "/casa/convite/" in mail.outbox[0].body

    def test_the_email_does_not_contain_the_stored_hash(self, logged_client, household):
        logged_client.post(reverse("invite_create"), {"email": "parceira@example.com"})
        invitation = household.accounts_invitation.get()
        assert invitation.token_hash not in mail.outbox[0].body

    def test_a_plain_member_may_not_invite(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        client = Client()
        client.force_login(member)
        response = client.post(reverse("invite_create"), {"email": "x@example.com"})
        assert response.status_code == 403

    def test_an_anonymous_visitor_may_not_invite(self):
        response = Client().post(reverse("invite_create"), {"email": "x@example.com"})
        assert response.status_code in (302, 403)
        assert not mail.outbox


@pytest.mark.django_db
class TestAcceptingWithAnExistingAccount:
    def test_an_authenticated_invitee_joins_the_household(self, household, user):
        invitee = baker.make("core.CustomUser", email="ja-tem@example.com")
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        client = Client()
        client.force_login(invitee)
        response = client.post(reverse("invite_accept", args=[raw]))
        assert response.status_code == 302
        assert Membership.objects.filter(user=invitee, household=household).exists()

    def test_an_anonymous_visitor_sees_the_household_name_and_a_way_in(self, household, user):
        _, raw = create_invitation(household=household, invited_by=user, email="quem@example.com")
        response = Client().get(reverse("invite_accept", args=[raw]))
        assert response.status_code == 200
        body = response.content.decode()
        assert household.name in body
        assert "/accounts/signup/" in body
        assert "/accounts/login/" in body

    def test_a_bad_token_says_so_without_a_traceback(self):
        response = Client().get(reverse("invite_accept", args=["nao-existe"]))
        assert response.status_code == 404

    def test_a_spent_token_is_refused_on_the_second_use(self, household, user):
        first = baker.make("core.CustomUser", email="primeira@example.com")
        second = baker.make("core.CustomUser", email="segunda@example.com")
        _, raw = create_invitation(household=household, invited_by=user, email=first.email)

        one = Client()
        one.force_login(first)
        one.post(reverse("invite_accept", args=[raw]))

        two = Client()
        two.force_login(second)
        two.post(reverse("invite_accept", args=[raw]))
        assert not Membership.objects.filter(user=second, household=household).exists()

    def test_a_get_does_not_spend_the_token(self, household, user):
        """An email client or link scanner fetches every URL in a message before
        a human sees it. A scanner that can accept an invitation is a scanner
        that can burn one."""
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="quem@example.com"
        )
        Client().get(reverse("invite_accept", args=[raw]))
        invitation.refresh_from_db()
        assert invitation.accepted_at is None
        assert invitation.is_pending is True


@pytest.mark.django_db
class TestAcceptingWithoutAnAccount:
    def test_an_invitee_signs_up_then_lands_in_the_household(self, household, user):
        _, raw = create_invitation(household=household, invited_by=user, email="nova@example.com")
        accept_path = reverse("invite_accept", args=[raw])

        client = Client()
        # 1. Lands on the invitation, is anonymous, follows "criar conta".
        assert client.get(accept_path).status_code == 200

        # 2. Signs up with the invited address. `next` carries the way back.
        mail.outbox.clear()
        client.post(
            f"{reverse('account_signup')}?next={accept_path}",
            {
                "email": "nova@example.com",
                "email2": "nova@example.com",
                "password1": SENHA,
                "password2": SENHA,
                # E13: the signup form now carries a required acceptance checkbox.
                "accept_terms": "on",
            },
        )

        # 3. Verifies. (Task 13 removes this step for invited addresses; until
        #    then the round trip has to work the long way.)
        if mail.outbox:
            client.post(_link_from(mail.outbox[0], "confirm"))

        client.post(reverse("account_login"), {"login": "nova@example.com", "password": SENHA})

        # 4. Back to the invitation, now signed in.
        client.post(accept_path)

        invitee = Membership.objects.filter(household=household).exclude(user=user).first()
        assert invitee is not None
        assert invitee.user.email == "nova@example.com"


@pytest.mark.django_db
class TestBothSeeOneLedger:
    def test_the_invitee_reads_the_inviters_entries(self, household, user):
        """The whole point of an invitation: E04's scoping does the rest."""
        baker.make("finances.Entry", household=household, created_by=user, description="Feira")
        invitee = baker.make("core.CustomUser", email="socia@example.com")
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)

        client = Client()
        client.force_login(invitee)
        client.post(reverse("invite_accept", args=[raw]))

        # `/entries/` 302s to the current month's URL, so follow it — asserting
        # against the redirect body would pass on an empty string.
        body = client.get("/entries/", follow=True).content.decode()
        assert "Feira" in body
