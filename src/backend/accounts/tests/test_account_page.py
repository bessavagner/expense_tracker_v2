"""The Conta page and the Membros tab that E18 absorbs into it.

E05's own membership tests still live in `test_membership_removal.py` and are
the guard that absorbing this page did not relax a permission check. What is
asserted here is the *surface*: the tab renders, it renders standalone, and it
names people by name rather than by raw email address.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.invitations import create_invitation
from accounts.models import Membership, Role


@pytest.fixture
def joined_member(household, user, db):
    member = baker.make("core.CustomUser", email="socia@example.com")
    Membership.objects.create(user=member, household=household, role=Role.MEMBER)
    client = Client()
    client.force_login(member)
    return member, client


@pytest.mark.django_db
class TestMembersTab:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_members_tab"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_the_fragment_url_renders_standalone(self, logged_client, household):
        response = logged_client.get(reverse("account_members_tab"))
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.content.decode()

    def test_as_an_htmx_fragment_it_is_not_a_whole_page(self, logged_client, household):
        response = logged_client.get(reverse("account_members_tab"), headers={"HX-Request": "true"})
        assert "<!DOCTYPE html>" not in response.content.decode()

    def test_it_lists_members_and_pending_invitations(
        self, logged_client, household, user, joined_member
    ):
        create_invitation(household=household, invited_by=user, email="pendente@example.com")
        body = logged_client.get(reverse("account_members_tab")).content.decode()
        assert "socia@example.com" in body
        assert "pendente@example.com" in body

    def test_it_does_not_leak_another_households_members(
        self, logged_client, other_user, other_household
    ):
        body = logged_client.get(reverse("account_members_tab")).content.decode()
        assert other_user.email not in body

    def test_a_member_does_not_see_the_owner_controls(self, joined_member):
        _, member_client = joined_member
        body = member_client.get(reverse("account_members_tab")).content.decode()
        assert "Convidar" not in body


@pytest.mark.django_db
class TestPeopleAreNamedByName:
    def test_a_member_with_a_name_is_shown_by_it(self, logged_client, household, joined_member):
        member, _ = joined_member
        member.first_name = "Sócia"
        member.save(update_fields=["first_name"])
        body = logged_client.get(reverse("account_members_tab")).content.decode()
        assert "Sócia" in body

    def test_a_member_without_a_name_is_shown_by_their_email(
        self, logged_client, household, joined_member
    ):
        """The normal case on day one — every existing account has a blank name."""
        member, _ = joined_member
        assert member.first_name == ""
        body = logged_client.get(reverse("account_members_tab")).content.decode()
        assert "socia@example.com" in body
