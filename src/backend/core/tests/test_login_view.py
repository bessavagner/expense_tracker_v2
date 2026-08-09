"""The app's own login page.

Until now the family signed in through ``/admin/login/``: ``LOGIN_URL`` pointed
at it, ``LogoutView`` sent people back to it, and there was no app login view at
all — ``GET /login`` returned 404 in production. That is why the app opened on a
Django admin screen, and why signing in landed on ``/admin/`` instead of the
dashboard.

This is the E05 login page the lockout backend was written in anticipation of
(see ``core/auth_backends.py``). ``/admin/login/`` still exists and still works;
it is just no longer the family's front door.
"""

import pytest
from django.test import Client
from model_bakery import baker

from core.models import LoginAttempt

SENHA = "senha-correta-longa-o-suficiente"


@pytest.fixture
def account(db):
    user = baker.make("core.CustomUser", username="vagner")
    user.set_password(SENHA)
    user.save()
    return user


@pytest.mark.django_db
class TestLoginPageRenders:
    def test_get_renders_the_app_login_page(self):
        response = Client().get("/login/")
        assert response.status_code == 200
        assert "registration/login.html" in [t.name for t in response.templates]

    def test_page_is_in_portuguese_and_not_the_django_admin(self):
        body = Client().get("/login/").content.decode()
        assert "Entrar" in body
        assert "Django" not in body

    def test_page_carries_the_double_submit_guard(self):
        """The reported CSRF 403 was a double-tapped login form.

        ``auth.login()`` rotates the CSRF token, so the second tap posts a stale
        one and Django answers 403 — over an app that had already loaded. The
        guard is what stops the second tap being sent.
        """
        body = Client().get("/login/").content.decode()
        assert "addEventListener('submit'" in body, "the guard script is missing"
        assert '<form method="post"' in body
        assert "data-no-submit-guard" not in body.split("<script>")[0], (
            "the login form opted out of the guard"
        )
        assert 'data-pending="Entrando…"' in body

    def test_page_advertises_the_pwa(self):
        """It is the unauthenticated landing, so install must be offered here."""
        body = Client().get("/login/").content.decode()
        assert 'rel="manifest"' in body
        assert "/manifest.webmanifest" in body
        assert "serviceWorker" in body
        assert "#147874" in body


@pytest.mark.django_db
class TestSigningIn:
    def test_correct_credentials_land_on_the_dashboard(self, account):
        response = Client().post("/login/", {"username": "vagner", "password": SENHA})
        assert response.status_code == 302
        assert response["Location"] == "/"

    def test_next_is_honoured(self, account):
        response = Client().post(
            "/login/?next=/entries/", {"username": "vagner", "password": SENHA}
        )
        assert response.status_code == 302
        assert response["Location"] == "/entries/"

    def test_wrong_password_re_renders_with_a_portuguese_error(self, account):
        client = Client()
        response = client.post("/login/", {"username": "vagner", "password": "errada"})
        assert response.status_code == 200
        assert "Usuário ou senha incorretos." in response.content.decode()
        assert not client.session.get("_auth_user_id")

    def test_an_authenticated_visitor_is_sent_on_rather_than_shown_the_form(self, account):
        client = Client()
        client.force_login(account)
        response = client.get("/login/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestLockoutIsVisible:
    """E01's lockout was enforced but never explained.

    Through the admin form a locked-out user saw the stock "please enter a
    correct username and password" — indistinguishable from a typo, so the
    natural response was to keep trying and keep extending nothing. Saying so
    leaks nothing: a failed attempt is recorded for any username, existing or
    not, so a lockout message does not reveal that an account exists.
    """

    def test_locked_out_user_is_told_so(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(3):
            client.post("/login/", {"username": "vagner", "password": "errada"})

        response = client.post("/login/", {"username": "vagner", "password": SENHA})
        body = response.content.decode()
        assert response.status_code == 200
        assert "Muitas tentativas" in body
        assert "Usuário ou senha incorretos." not in body
        assert not client.session.get("_auth_user_id"), "the lockout let them in"

    def test_a_locked_out_attempt_does_not_extend_the_lockout(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(5):
            client.post("/login/", {"username": "vagner", "password": "errada"})
        assert LoginAttempt.objects.filter(username="vagner").count() == 3


@pytest.mark.django_db
class TestTheFrontDoorMoved:
    def test_a_protected_page_bounces_to_the_app_login(self):
        response = Client().get("/entries/")
        assert response.status_code == 302
        assert response["Location"].startswith("/login/")
        assert "next=/entries/" in response["Location"]

    def test_logging_out_returns_to_the_app_login_page(self, account):
        client = Client()
        client.force_login(account)
        response = client.post("/logout/")
        assert response.status_code == 302
        assert response["Location"] == "/login/"

    def test_the_admin_login_still_works_for_the_admin(self, account):
        """Moving the family's door must not lock the maintainer out of /admin/."""
        account.is_staff = True
        account.is_superuser = True
        account.save()
        client = Client()
        response = client.post(
            "/admin/login/",
            {"username": "vagner", "password": SENHA, "next": "/admin/"},
        )
        assert response.status_code == 302
        assert client.session.get("_auth_user_id")
