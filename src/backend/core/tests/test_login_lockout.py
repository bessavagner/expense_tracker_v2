"""Repeated failed logins must lock the account out for a window.

Enforced in an authentication backend rather than a view, because E05 replaces
``/admin/login/`` with a real login page and the protection has to follow the
credential check, not the URL.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import authenticate
from django.test import Client, RequestFactory
from django.utils import timezone
from model_bakery import baker

from core.models import LoginAttempt
from core.security import client_ip, is_locked

# Frozen so the boundary tests below compare against a fixed instant rather
# than the real clock — see TestIsLockedWindowEdges.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def account(db):
    user = baker.make("core.CustomUser", username="alvo")
    user.set_password("senha-correta-longa-o-suficiente")
    user.save()
    return user


def _fail(username, ip="203.0.113.9", count=1, age=timedelta(0)):
    stamp = timezone.now() - age
    for _ in range(count):
        attempt = LoginAttempt.objects.create(username=username, ip=ip)
        LoginAttempt.objects.filter(pk=attempt.pk).update(created_at=stamp)


@pytest.mark.django_db
class TestIsLocked:
    def test_clean_account_is_not_locked(self):
        assert is_locked("alvo", "203.0.113.9") is False

    def test_under_the_limit_is_not_locked(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", count=4)
        assert is_locked("alvo", "198.51.100.4") is False

    def test_at_the_limit_locks_by_username(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", count=5)
        # locked even from a fresh IP — the username arm is the real protection
        assert is_locked("alvo", "198.51.100.4") is True

    def test_at_the_limit_locks_by_ip(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        _fail("alvo", ip="203.0.113.9", count=5)
        assert is_locked("outro-usuario", "203.0.113.9") is True

    def test_failures_outside_the_window_are_forgotten(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 5
        settings.LOGIN_FAILURE_WINDOW_MINUTES = 15
        _fail("alvo", count=9, age=timedelta(minutes=20))
        assert is_locked("alvo", "203.0.113.9") is False

    def test_no_identifiers_is_never_locked(self):
        assert is_locked(None, None) is False


@pytest.mark.django_db
class TestIsLockedWindowEdges:
    """The rolling window boundary is inclusive: exactly ``window`` minutes old
    still counts, one second past it does not. Frozen rather than derived from
    the real clock, because a few milliseconds of drift between writing the
    attempt and calling ``is_locked`` would make a boundary assertion flaky.
    """

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)

    def test_attempt_exactly_at_the_window_boundary_still_locks(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 1
        settings.LOGIN_FAILURE_WINDOW_MINUTES = 15
        _fail("alvo", count=1, age=timedelta(minutes=15))
        assert is_locked("alvo", "203.0.113.9") is True

    def test_attempt_one_second_past_the_window_boundary_does_not_lock(self, settings):
        settings.LOGIN_FAILURE_LIMIT = 1
        settings.LOGIN_FAILURE_WINDOW_MINUTES = 15
        _fail("alvo", count=1, age=timedelta(minutes=15, seconds=1))
        assert is_locked("alvo", "203.0.113.9") is False


class TestClientIp:
    def test_falls_back_to_remote_addr_with_no_forwarded_header(self):
        request = RequestFactory().post("/", REMOTE_ADDR="198.51.100.4")
        assert client_ip(request) == "198.51.100.4"

    def test_single_entry_forwarded_header_is_the_real_client_ip(self):
        """Cloud Run's own front end appends the real client IP as the last
        (here, only) entry — there is no load balancer in front of this
        service to add a further hop."""
        request = RequestFactory().post(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.9", REMOTE_ADDR="10.0.0.1"
        )
        assert client_ip(request) == "203.0.113.9"

    def test_two_entry_header_picks_the_last_not_the_forged_leading_one(self):
        """``<forged-victim>, <real-client>`` — Cloud Run appends the real
        client IP after whatever the client supplied, so the last entry
        wins, not the leftmost."""
        request = RequestFactory().post(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.250, 198.51.100.9",
            REMOTE_ADDR="10.0.0.1",
        )
        assert client_ip(request) != "203.0.113.250"
        assert client_ip(request) == "198.51.100.9"

    def test_garbage_forwarded_header_falls_back_rather_than_crashing(self):
        """X-Forwarded-For is client-controlled — it can be anything at all."""
        request = RequestFactory().post(
            "/", HTTP_X_FORWARDED_FOR="'; DROP TABLE --", REMOTE_ADDR="198.51.100.4"
        )
        assert client_ip(request) == "198.51.100.4"

    def test_no_usable_address_returns_none(self):
        request = RequestFactory().post("/", REMOTE_ADDR="not-an-ip")
        assert client_ip(request) is None


@pytest.mark.django_db
class TestClientIpForgeryResistance:
    """The security property the last-entry rule protects: a forged leading
    XFF entry naming some other address must not be able to record or match
    a lockout against that address.
    """

    def test_forged_leading_entry_is_not_recorded_or_locked(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        victim_ip = "203.0.113.250"
        attacker_ip = "198.51.100.9"
        request = RequestFactory().post(
            "/",
            HTTP_X_FORWARDED_FOR=f"{victim_ip}, {attacker_ip}",
            REMOTE_ADDR="10.0.0.1",
        )
        for _ in range(3):
            authenticate(request=request, username="alvo", password="errada")
        assert not LoginAttempt.objects.filter(ip=victim_ip).exists()
        assert LoginAttempt.objects.filter(ip=attacker_ip).count() == 3
        assert is_locked(None, victim_ip) is False
        assert is_locked(None, attacker_ip) is True


@pytest.mark.django_db
class TestBackendEnforcement:
    def test_correct_password_works_when_not_locked(self, account):
        assert authenticate(username="alvo", password="senha-correta-longa-o-suficiente")

    def test_correct_password_is_refused_while_locked(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail("alvo", count=3)
        assert authenticate(username="alvo", password="senha-correta-longa-o-suficiente") is None

    def test_failed_authenticate_records_an_attempt(self, account):
        authenticate(username="alvo", password="errada")
        assert LoginAttempt.objects.filter(username="alvo").count() == 1

    def test_a_locked_out_attempt_does_not_extend_its_own_lockout(self, account, settings):
        """Otherwise the window slides forever and the lockout never expires."""
        settings.LOGIN_FAILURE_LIMIT = 3
        _fail("alvo", count=3)
        authenticate(username="alvo", password="errada")
        authenticate(username="alvo", password="errada")
        assert LoginAttempt.objects.filter(username="alvo").count() == 3

    def test_successful_login_clears_the_failures(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 10
        _fail("alvo", count=4)
        client = Client()
        assert client.login(username="alvo", password="senha-correta-longa-o-suficiente")
        assert LoginAttempt.objects.filter(username="alvo").count() == 0


@pytest.mark.django_db
class TestAdminLoginIsProtected:
    """The lockout must be live on whatever login view is wired today."""

    def test_repeated_admin_login_failures_lock_the_account(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(3):
            client.post(
                "/admin/login/",
                {"username": "alvo", "password": "errada", "next": "/admin/"},
            )
        response = client.post(
            "/admin/login/",
            {
                "username": "alvo",
                "password": "senha-correta-longa-o-suficiente",
                "next": "/admin/",
            },
        )
        # Still on the login form rather than redirected in — the correct
        # password was never checked.
        assert response.status_code == 200
        assert LoginAttempt.objects.filter(username="alvo").count() == 3
