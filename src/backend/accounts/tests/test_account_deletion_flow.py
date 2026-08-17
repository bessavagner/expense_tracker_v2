"""Deleting an account from the UI, the way a person actually does it.

The service is tested in `core/tests/test_privacy_deletion.py`. What is tested
here is the path to it: that an export is offered before an irreversible act,
that a mis-tap cannot trigger it, and that nobody can trigger it for somebody
else.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.models import Membership, Role
from core.models import CustomUser
from finances.models import ExportJob, ExportStatus

pytestmark = pytest.mark.django_db


class TestTheConfirmationPage:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_delete"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_it_offers_an_export_when_there_is_none(self, logged_client, household):
        """S13-1: 'they are offered an export first, because deletion is
        irreversible and their financial history is not recoverable'."""
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert reverse("finances:export_page") in body
        assert "Baixar" in body

    def test_it_says_when_the_last_export_was_made(self, logged_client, household, user):
        baker.make(
            ExportJob,
            household=household,
            created_by=user,
            status=ExportStatus.DONE,
            storage_key="exports/x.zip",
        )
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "Você já baixou" in body

    def test_it_tells_a_lone_member_the_household_goes_too(self, logged_client, household):
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "toda a casa" in body

    def test_it_tells_a_shared_household_what_the_other_person_keeps(
        self, logged_client, household
    ):
        socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
        Membership.objects.create(user=socia, household=household, role=Role.MEMBER)
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "socia@example.com" in body
        assert "continua" in body


class TestTheConfirmation:
    def test_the_wrong_address_deletes_nothing(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_delete"), {"confirm_email": "outra@example.com"}
        )
        assert response.status_code == 200
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_an_empty_confirmation_deletes_nothing(self, logged_client, household, user):
        logged_client.post(reverse("account_delete"), {})
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_the_address_match_ignores_case_and_whitespace(self, logged_client, household, user):
        """A person copying their own address out of the page should not be
        defeated by a trailing space."""
        logged_client.post(reverse("account_delete"), {"confirm_email": "  VAGNER@example.com "})
        assert not CustomUser.objects.filter(pk=user.pk).exists()

    def test_a_get_never_deletes(self, logged_client, household, user):
        logged_client.get(reverse("account_delete"))
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_the_right_address_deletes_the_account(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_delete"), {"confirm_email": "vagner@example.com"}
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("account_deleted")
        assert not CustomUser.objects.filter(pk=user.pk).exists()

    def test_it_signs_you_out(self, logged_client, household, user):
        logged_client.post(reverse("account_delete"), {"confirm_email": user.email})
        response = logged_client.get(reverse("account"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_it_cannot_be_pointed_at_somebody_else(self, logged_client, household, other_user):
        """The view reads `request.user` and the form carries no id. This is the
        assertion that stays true if anyone ever adds one."""
        logged_client.post(
            reverse("account_delete"),
            {
                "confirm_email": other_user.email,
                "user": other_user.pk,
                "id": other_user.pk,
            },
        )
        assert CustomUser.objects.filter(pk=other_user.pk).exists()

    def test_it_requires_csrf(self, user, household):
        """Deleting an account on a forged cross-site POST is the worst possible
        CSRF outcome, so this is asserted rather than assumed from middleware."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.post(reverse("account_delete"), {"confirm_email": user.email})
        assert response.status_code == 403
        assert CustomUser.objects.filter(pk=user.pk).exists()


class TestTheGoodbyePage:
    def test_it_renders_to_somebody_who_is_not_signed_in(self):
        """It has to: by the time anyone reaches it their account is gone."""
        response = Client().get(reverse("account_deleted"))
        assert response.status_code == 200
        assert "excluída" in response.content.decode()

    def test_it_does_not_redirect_to_login(self):
        assert Client().get(reverse("account_deleted")).status_code == 200
