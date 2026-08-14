"""The E01 lockout has to follow the credential check to its new URL.

E01 put the lockout in an authentication backend precisely so it would not be
tied to a view. That only holds if the backend the *new* login form uses is
the one carrying the lockout — allauth ships its own, and inheriting from
Django's ModelBackend is not enough once email is the identifier.

allauth's own `login_failed` rate limit is not a substitute: its documentation
states it protects the allauth login view and not Django's admin login, and
this product needs both doors covered.
"""

import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from core.models import LoginAttempt

SENHA = "senha-correta-longa-o-suficiente"


@pytest.fixture
def account(db):
    user = baker.make("core.CustomUser", username="alvo", email="alvo@example.com")
    user.set_password(SENHA)
    user.save()
    return user


def _fail_n_times(username, ip, count):
    for _ in range(count):
        LoginAttempt.objects.create(username=username, ip=ip)


@pytest.mark.django_db
class TestLockoutAppliesToEmailLogin:
    def test_a_locked_email_is_refused_even_with_the_right_password(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail_n_times("alvo@example.com", "203.0.113.9", 3)

        result = authenticate(request=None, username="alvo@example.com", password=SENHA)
        assert result is None

    def test_an_unlocked_email_still_authenticates(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        result = authenticate(request=None, username="alvo@example.com", password=SENHA)
        assert result == account


@pytest.mark.django_db
class TestCaseCannotBuyAFreshBudget:
    """One address is one account, so it must be one lockout budget.

    allauth resolves an address case-insensitively — `Alvo@example.com` signs
    in as `alvo@example.com`. Counted as submitted, each capitalisation would
    get its own budget, and an n-letter address offers 2^n of them: the lockout
    becomes arithmetic rather than a limit.
    """

    def test_a_locked_address_stays_locked_in_a_different_case(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail_n_times("alvo@example.com", "203.0.113.9", 3)

        assert authenticate(request=None, username="ALVO@example.com", password=SENHA) is None
        assert authenticate(request=None, username="Alvo@Example.COM", password=SENHA) is None

    def test_failures_in_mixed_case_count_against_the_same_budget(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        url = reverse("account_login")
        for identifier in ("alvo@example.com", "ALVO@example.com", "Alvo@Example.com"):
            client.post(url, {"login": identifier, "password": "errada"})

        assert LoginAttempt.objects.filter(username="alvo@example.com").count() == 3
        assert authenticate(request=None, username="alvo@example.com", password=SENHA) is None


@pytest.mark.django_db
class TestLockoutAppliesAtTheLoginView:
    def test_repeated_failures_at_the_login_page_lock_the_account(self, account, settings):
        """Drive the real form, because the point is that the *view* is covered."""
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        url = reverse("account_login")

        for _ in range(3):
            client.post(url, {"login": "alvo@example.com", "password": "errada"})

        response = client.post(url, {"login": "alvo@example.com", "password": SENHA})
        assert response.status_code == 200  # re-rendered form, not a redirect
        assert "_auth_user_id" not in client.session

    def test_a_failed_attempt_at_the_login_page_is_recorded(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 10
        Client().post(reverse("account_login"), {"login": "alvo@example.com", "password": "errada"})
        assert LoginAttempt.objects.filter(username="alvo@example.com").exists()


@pytest.mark.django_db
class TestOnlyOneBackendIsRegistered:
    def test_no_unlocked_backend_remains(self, settings):
        """A second, lockout-free backend would quietly undo the whole thing."""
        assert settings.AUTHENTICATION_BACKENDS == [
            "core.auth_backends.LockoutAuthenticationBackend"
        ]
