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


#: The password these tests set on the fixture user before signing back in.
#: Not a secret — nothing outside this module reads it, and it exists only so
#: `with_password` and the assertions cannot drift apart.
PASSWORD = "uma-senha-bem-comprida"  # noqa: S105


def with_password(client, user):
    """Give `user` a known password and keep `client` signed in.

    `set_password` rotates the session auth hash, which signs a `force_login`
    client straight back out — so every one of these tests would otherwise be
    asserting against the login page's 302 rather than the page it named.
    """
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    client.force_login(user)
    return user


def activate_recovery_codes(user):
    """Give `user` a set of recovery codes; without them the view 404s."""
    from allauth.mfa.recovery_codes.internal import auth as recovery_auth

    return recovery_auth.RecoveryCodes.activate(user)


def past_reauthentication(client, user, url_name):
    """Clear allauth's reauthentication gate and return the page behind it.

    Enrolment, deactivation and the recovery codes all sit behind it: allauth
    302s to `account_reauthenticate` first. A test that merely followed that
    redirect would assert against the reauth page while claiming to test the
    page beyond it — which is exactly what happened to three of these before
    the redirect chain was read.
    """
    with_password(client, user)
    return client.post(
        reverse("account_reauthenticate") + "?next=" + reverse(url_name),
        {"password": PASSWORD},
        follow=True,
    )


@pytest.mark.django_db
class TestTheStyledAllauthPages:
    """Every page a user can reach from Segurança renders in the ledger theme.

    Each test asserts on a string only this repo's override contains. Asserting
    merely that the English is gone would prove nothing: allauth ships its own
    pt-BR catalogue, so the stock templates are already translated. What was
    missing before E18 was the *styling*, and a copy string unique to the
    override is what distinguishes "our template rendered" from "allauth's
    template rendered in Portuguese".
    """

    def test_password_change_is_the_styled_override(self, logged_client):
        body = logged_client.get(reverse("account_change_password")).content.decode()
        assert "Repita a nova senha" in body
        assert "Você continua conectado nos aparelhos em que já entrou." in body
        assert "Change Password" not in body

    def test_password_change_still_posts_to_allauths_own_view(self, logged_client, user):
        """The form is re-skinned, never reimplemented (spec D3)."""
        with_password(logged_client, user)
        response = logged_client.post(
            reverse("account_change_password"),
            {
                "oldpassword": PASSWORD,
                "password1": "outra-senha-bem-comprida",
                "password2": "outra-senha-bem-comprida",
            },
        )
        assert response.status_code in (200, 302)
        user.refresh_from_db()
        assert user.check_password("outra-senha-bem-comprida")

    def test_reauthenticate_is_the_styled_override(self, logged_client, user):
        with_password(logged_client, user)
        body = logged_client.get(
            reverse("account_reauthenticate") + "?next=" + reverse("account")
        ).content.decode()
        assert "Confirme que é você" in body
        assert "Digite a sua senha para continuar." in body
        assert "Confirm Access" not in body

    def test_the_two_factor_overview_is_the_styled_override(self, logged_client):
        body = logged_client.get(reverse("mfa_index"), follow=True).content.decode()
        assert "Um código do seu celular, além da senha." in body
        assert "duas etapas" in body.lower()
        assert "Two-Factor Authentication" not in body

    def test_totp_enrolment_is_the_styled_override(self, logged_client, user):
        body = past_reauthentication(logged_client, user, "mfa_activate_totp").content.decode()
        assert "Ou digite este código" in body
        assert "Ativar duas etapas" in body
        assert "Activate Authenticator App" not in body

    def test_totp_deactivation_is_the_styled_override(self, logged_client, user):
        activate_totp(user)
        body = past_reauthentication(logged_client, user, "mfa_deactivate_totp").content.decode()
        assert "Desativar duas etapas" in body
        assert "A partir daí, só a senha protege a sua conta." in body
        assert "Deactivate Authenticator App" not in body

    def test_recovery_codes_are_the_styled_override(self, logged_client, user):
        activate_totp(user)
        activate_recovery_codes(user)
        body = past_reauthentication(
            logged_client, user, "mfa_view_recovery_codes"
        ).content.decode()
        assert "Use um deles se perder o acesso ao aplicativo autenticador." in body
        assert "vale uma vez só" in body
        assert "Recovery Codes" not in body

    def test_every_styled_page_carries_the_ledger_shell(self, logged_client):
        """They inherit `allauth/layouts/base.html`, which the repo overrides —
        this is the assertion that an override did not break the chain."""
        body = logged_client.get(reverse("account_change_password")).content.decode()
        assert 'lang="pt-BR"' in body
        assert "css/tailwind.css" in body
