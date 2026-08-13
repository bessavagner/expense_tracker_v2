"""allauth is installed and mounted, and it is configured for email-only login.

Deliberately asserts settings rather than behaviour: this task installs the
library without handing it the door, so there is no behaviour to assert yet.
The behavioural tests arrive with Task 6.
"""

from django.conf import settings
from django.test import Client
from django.urls import reverse


class TestAllauthIsInstalled:
    def test_apps_are_installed(self):
        for app in ("allauth", "allauth.account", "allauth.mfa"):
            assert app in settings.INSTALLED_APPS

    def test_account_middleware_is_installed(self):
        assert "allauth.account.middleware.AccountMiddleware" in settings.MIDDLEWARE

    def test_login_is_by_email_only(self):
        assert settings.ACCOUNT_LOGIN_METHODS == {"email"}

    def test_username_is_not_a_signup_field(self):
        """The user model keeps `username`, but nobody is ever asked for one."""
        assert "username" not in settings.ACCOUNT_SIGNUP_FIELDS
        assert "username*" not in settings.ACCOUNT_SIGNUP_FIELDS
        assert "email*" in settings.ACCOUNT_SIGNUP_FIELDS

    def test_verification_is_mandatory(self):
        assert settings.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


class TestAllauthIsMounted:
    def test_signup_page_is_reachable(self, db):
        response = Client().get(reverse("account_signup"))
        assert response.status_code == 200

    def test_password_reset_page_is_reachable(self, db):
        response = Client().get(reverse("account_reset_password"))
        assert response.status_code == 200
