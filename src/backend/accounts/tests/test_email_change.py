"""Changing the address you log in with.

allauth's single-address flow (`ACCOUNT_CHANGE_EMAIL`): adding an address adds
a temporary *second* one, and it only replaces the primary once it is
verified. What that buys is the property this file exists to assert — there is
never a window in which the user cannot log in.
"""

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.core import mail
from django.test import Client
from django.urls import reverse
from model_bakery import baker


@pytest.fixture
def verified_user(user, db):
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    return user


@pytest.mark.django_db
class TestTheSetting:
    def test_single_address_change_is_on(self):
        from allauth.account import app_settings

        assert app_settings.CHANGE_EMAIL is True

    def test_enumeration_prevention_is_still_on(self):
        """The epic forbids weakening this for a friendlier collision message."""
        from allauth.account import app_settings

        assert app_settings.PREVENT_ENUMERATION is True
        assert app_settings.UNIQUE_EMAIL is True


@pytest.mark.django_db
class TestChangingTheAddress:
    def test_the_page_is_the_single_address_one_and_is_in_pt_br(self, logged_client, verified_user):
        response = logged_client.get(reverse("account_email"))
        assert response.status_code == 200
        body = response.content.decode()
        # The override is in place, not allauth's stock English page.
        assert "Seu e-mail" in body
        assert "Email Address" not in body
        assert "Change Email" not in body
        # allauth's multi-address manager offers these; the single-address
        # flow must not.
        assert "Make Primary" not in body
        assert "Remove" not in body

    def test_the_old_address_stays_primary_until_the_new_one_is_confirmed(
        self, logged_client, verified_user
    ):
        logged_client.post(
            reverse("account_email"), {"email": "novo@example.com", "action_add": ""}
        )

        verified_user.refresh_from_db()
        primary = EmailAddress.objects.get_primary(verified_user)
        assert primary.email == "vagner@example.com"
        assert primary.verified is True

        pending = EmailAddress.objects.get_new(verified_user)
        assert pending.email == "novo@example.com"
        assert pending.verified is False

    def test_the_user_can_still_log_in_with_the_old_address_while_it_is_pending(
        self, logged_client, verified_user
    ):
        verified_user.set_password("uma-senha-bem-comprida")
        verified_user.save(update_fields=["password"])
        logged_client.post(
            reverse("account_email"), {"email": "novo@example.com", "action_add": ""}
        )

        fresh = Client()
        ok = fresh.login(username="vagner@example.com", password="uma-senha-bem-comprida")
        assert ok is True

    def test_confirming_makes_the_new_address_the_only_one(self, logged_client, verified_user):
        mail.outbox.clear()
        logged_client.post(
            reverse("account_email"), {"email": "novo@example.com", "action_add": ""}
        )
        pending = EmailAddress.objects.get_new(verified_user)
        key = EmailConfirmationHMAC(pending).key

        logged_client.post(reverse("account_confirm_email", args=[key]))

        verified_user.refresh_from_db()
        addresses = list(EmailAddress.objects.filter(user=verified_user))
        assert len(addresses) == 1
        assert addresses[0].email == "novo@example.com"
        assert addresses[0].verified is True
        assert addresses[0].primary is True
        assert verified_user.email == "novo@example.com"


@pytest.mark.django_db
class TestACollisionWithAnotherAccount:
    """Enumeration prevention is the requirement, not a friendly error.

    With `ACCOUNT_PREVENT_ENUMERATION = True` allauth deliberately accepts the
    request rather than saying "that address is taken" — saying so is exactly
    the leak the setting exists to stop. The change then fails silently at
    confirmation, because a verified address can only belong to one account.
    Asserting "the form shows an error" here would be asserting the leak.
    """

    def test_the_response_does_not_say_the_address_is_registered(
        self, logged_client, verified_user
    ):
        other = baker.make("core.CustomUser", email="ocupado@example.com")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)

        response = logged_client.post(
            reverse("account_email"),
            {"email": "ocupado@example.com", "action_add": ""},
            follow=True,
        )
        body = response.content.decode().lower()
        assert "já está em uso" not in body
        assert "already" not in body
        assert "cadastrad" not in body

    def test_the_login_address_is_unchanged(self, logged_client, verified_user):
        other = baker.make("core.CustomUser", email="ocupado@example.com")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)

        logged_client.post(
            reverse("account_email"), {"email": "ocupado@example.com", "action_add": ""}
        )

        verified_user.refresh_from_db()
        assert verified_user.email == "vagner@example.com"
        assert EmailAddress.objects.get_primary(verified_user).email == "vagner@example.com"

    def test_confirming_cannot_steal_the_other_accounts_address(self, logged_client, verified_user):
        other = baker.make("core.CustomUser", email="ocupado@example.com")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)

        logged_client.post(
            reverse("account_email"), {"email": "ocupado@example.com", "action_add": ""}
        )
        pending = EmailAddress.objects.filter(
            user=verified_user, email="ocupado@example.com"
        ).first()
        if pending is not None:
            logged_client.post(
                reverse("account_confirm_email", args=[EmailConfirmationHMAC(pending).key])
            )

        other.refresh_from_db()
        verified_user.refresh_from_db()
        assert other.email == "ocupado@example.com"
        assert verified_user.email == "vagner@example.com"
        assert EmailAddress.objects.filter(email="ocupado@example.com", verified=True).count() == 1
