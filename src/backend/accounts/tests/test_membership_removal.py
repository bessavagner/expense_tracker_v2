"""Revoking a pending invitation, and removing someone who already joined.

The second one is the assertion the epic singles out: removal has to take
effect on the *next request*, not at the next login. E04 put the scoping in
the middleware and the managers precisely so that deleting one row is enough —
this test is what proves that claim rather than assuming it.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.invitations import create_invitation
from accounts.models import Membership, Role


@pytest.fixture
def joined_member(household, user, db):
    """Someone who accepted an invitation and is looking at the ledger."""
    member = baker.make("core.CustomUser", email="socia@example.com")
    Membership.objects.create(user=member, household=household, role=Role.MEMBER)
    client = Client()
    client.force_login(member)
    return member, client


@pytest.mark.django_db
class TestRevokingAPendingInvitation:
    def test_an_owner_can_revoke(self, logged_client, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="desistiu@example.com"
        )
        response = logged_client.post(reverse("invite_revoke", args=[invitation.pk]))
        assert response.status_code in (200, 302)
        invitation.refresh_from_db()
        assert invitation.revoked_at is not None

    def test_a_revoked_token_no_longer_redeems(self, logged_client, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="desistiu@example.com"
        )
        logged_client.post(reverse("invite_revoke", args=[invitation.pk]))

        latecomer = baker.make("core.CustomUser", email="desistiu@example.com")
        client = Client()
        client.force_login(latecomer)
        client.post(reverse("invite_accept", args=[raw]))
        assert not Membership.objects.filter(user=latecomer, household=household).exists()

    def test_an_owner_of_another_household_cannot_revoke_this_ones_invitation(
        self, household, user, other_user, other_household
    ):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="alvo@example.com"
        )
        intruder = Client()
        intruder.force_login(other_user)
        response = intruder.post(reverse("invite_revoke", args=[invitation.pk]))
        assert response.status_code == 404
        invitation.refresh_from_db()
        assert invitation.revoked_at is None


@pytest.mark.django_db
class TestRemovingAMember:
    def test_an_owner_can_remove_a_member(self, logged_client, household, joined_member):
        member, _ = joined_member
        membership = Membership.objects.get(user=member, household=household)
        logged_client.post(reverse("member_remove", args=[membership.pk]))
        assert not Membership.objects.filter(pk=membership.pk).exists()

    def test_a_removed_member_loses_data_access_on_the_very_next_request(
        self, logged_client, household, user, joined_member
    ):
        """The epic's third observable assertion, stated as bluntly as it reads."""
        member, member_client = joined_member
        baker.make("finances.Entry", household=household, created_by=user, description="Feira")

        before = member_client.get("/entries/", follow=True).content.decode()
        assert "Feira" in before, "the fixture never had access, so removal proves nothing"

        membership = Membership.objects.get(user=member, household=household)
        logged_client.post(reverse("member_remove", args=[membership.pk]))

        after = member_client.get("/entries/", follow=True).content.decode()
        assert "Feira" not in after

    def test_a_member_may_not_remove_anyone(self, household, joined_member, user):
        member, member_client = joined_member
        owners = Membership.objects.get(user=user, household=household)
        response = member_client.post(reverse("member_remove", args=[owners.pk]))
        assert response.status_code == 403
        assert Membership.objects.filter(pk=owners.pk).exists()

    def test_the_last_owner_cannot_be_removed(self, logged_client, household, user):
        """E04's open question 3 and E13 own what *should* happen when the last
        owner leaves. Until they do, refusing is the answer that cannot corrupt
        a household."""
        membership = Membership.objects.get(user=user, household=household)
        response = logged_client.post(reverse("member_remove", args=[membership.pk]))
        assert response.status_code == 400
        assert Membership.objects.filter(pk=membership.pk).exists()

    def test_a_membership_in_another_household_is_invisible(
        self, logged_client, other_user, other_household
    ):
        foreign = Membership.objects.get(user=other_user, household=other_household)
        response = logged_client.post(reverse("member_remove", args=[foreign.pk]))
        assert response.status_code == 404
        assert Membership.objects.filter(pk=foreign.pk).exists()

    def test_removal_leaves_the_household_ledger_intact(
        self, logged_client, household, joined_member
    ):
        """created_by is SET_NULL for exactly this reason: a person leaving must
        not take the family's financial history with them."""
        from finances.models import Entry

        member, _ = joined_member
        baker.make("finances.Entry", household=household, created_by=member, description="Padaria")

        membership = Membership.objects.get(user=member, household=household)
        logged_client.post(reverse("member_remove", args=[membership.pk]))

        assert Entry.objects.filter(household=household, description="Padaria").exists()


@pytest.mark.django_db
class TestMembersPage:
    def test_it_lists_members_and_pending_invitations(
        self, logged_client, household, user, joined_member
    ):
        create_invitation(household=household, invited_by=user, email="pendente@example.com")
        body = logged_client.get(reverse("members")).content.decode()
        assert "socia@example.com" in body
        assert "pendente@example.com" in body

    def test_it_does_not_leak_another_households_members(
        self, logged_client, other_user, other_household
    ):
        body = logged_client.get(reverse("members")).content.decode()
        assert other_user.email not in body

    def test_a_member_sees_the_page_without_the_owner_controls(self, joined_member):
        _, member_client = joined_member
        body = member_client.get(reverse("members")).content.decode()
        assert "Convidar" not in body

    def test_the_owner_cannot_be_offered_a_button_that_removes_themselves(
        self, logged_client, household, user
    ):
        """The last-owner rule is enforced in the view, but offering the button
        and then refusing it is a worse experience than not offering it."""
        membership = Membership.objects.get(user=user, household=household)
        body = logged_client.get(reverse("members")).content.decode()
        assert reverse("member_remove", args=[membership.pk]) not in body

    def test_the_page_is_reachable_from_the_app_chrome(self, logged_client):
        """A members page nobody can find is not a feature."""
        body = logged_client.get("/", follow=True).content.decode()
        assert reverse("members") in body
