"""Segurança: status, links out, and the one regression this must not cause.

D5 opens 2FA to every user. The thing that must survive it is E05's admin
gate: staff without a second factor still get bounced to enrolment. That is
asserted here as well as in `core/tests/test_admin_isolation.py`, because the
two would otherwise be one edit apart from silently disagreeing.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker


def activate_totp(user):
    """Give `user` a working authenticator, the way allauth's own tests do."""
    from allauth.mfa.totp.internal import auth as totp_auth

    return totp_auth.TOTP.activate(user, totp_auth.generate_totp_secret())


@pytest.mark.django_db
class TestSecurityTab:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_security_tab"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_the_fragment_url_renders_standalone(self, logged_client):
        response = logged_client.get(reverse("account_security_tab"))
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.content.decode()

    def test_it_links_out_rather_than_embedding_the_password_form(self, logged_client):
        body = logged_client.get(reverse("account_security_tab")).content.decode()
        assert reverse("account_change_password") in body
        assert 'name="oldpassword"' not in body

    def test_it_reports_two_factor_as_inactive_when_it_is(self, logged_client):
        body = logged_client.get(reverse("account_security_tab")).content.decode()
        assert "Inativa" in body
        assert reverse("mfa_activate_totp") in body

    def test_it_reports_two_factor_as_active_when_it_is(self, logged_client, user):
        activate_totp(user)
        body = logged_client.get(reverse("account_security_tab")).content.decode()
        assert "Ativa" in body
        assert reverse("mfa_index") in body


@pytest.mark.django_db
class TestTwoFactorIsForEveryone:
    def test_a_non_staff_user_can_reach_enrolment(self, logged_client, user):
        """D5. Before E18 this was reachable in principle and linked from nowhere."""
        assert not user.is_staff
        response = logged_client.get(reverse("mfa_activate_totp"))
        # allauth demands re-authentication before enrolment; either the form
        # or the reauth page is a pass. A 403/404 is not.
        assert response.status_code in (200, 302)
        if response.status_code == 302:
            assert "reauthenticate" in response["Location"]

    def test_a_non_staff_user_can_enrol_and_then_disable(self, logged_client, user):
        # `logged_client`, not a bare `Client()`: from E11 a user whose
        # household has not finished the guided setup is redirected out of
        # every page, so a hand-rolled client would assert against an empty
        # body and pass or fail for the wrong reason.
        activate_totp(user)

        from allauth.mfa.utils import is_mfa_enabled

        assert is_mfa_enabled(user)

        body = logged_client.get(reverse("account_security_tab")).content.decode()
        assert reverse("mfa_index") in body

        from allauth.mfa.models import Authenticator

        Authenticator.objects.filter(user=user).delete()
        assert not is_mfa_enabled(user)


@pytest.mark.django_db
class TestTheStaffAdminGateIsUnchanged:
    def test_staff_without_a_second_factor_are_still_sent_to_enrolment(self, settings):
        staff = baker.make(
            "core.CustomUser", email="operador@example.com", is_staff=True, is_superuser=True
        )
        client = Client()
        client.force_login(staff)
        response = client.get("/" + settings.ADMIN_URL_PATH)
        assert response.status_code == 302
        assert "2fa" in response["Location"] or "totp" in response["Location"]

    def test_staff_who_deactivate_lose_admin_until_they_re_enrol(self, settings):
        """Correct, and deliberately not special-cased (spec, Error handling)."""
        from allauth.mfa.models import Authenticator

        staff = baker.make(
            "core.CustomUser", email="operador2@example.com", is_staff=True, is_superuser=True
        )
        activate_totp(staff)
        client = Client()
        client.force_login(staff)

        Authenticator.objects.filter(user=staff).delete()
        response = client.get("/" + settings.ADMIN_URL_PATH)
        assert response.status_code == 302
        assert "2fa" in response["Location"] or "totp" in response["Location"]
