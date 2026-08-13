"""The app's own login page.

E01 built this page to replace ``/admin/login/`` — before it, the app opened on
a Django admin screen and signing in landed on ``/admin/``. E05 moved it again,
from ``/login/`` to allauth's ``/accounts/login/``, because allauth now owns
signup, verification and password reset and the login form has to be the one
that shares their form classes and their session flow.

What did *not* move is the reason this view exists rather than allauth's stock
one: E01's lockout, and the page that explains it. ``/login/`` survives as a
301 for the installed TWA — see ``test_front_door.py``.
"""

import pytest
from django.test import Client
from model_bakery import baker

from core.models import LoginAttempt

SENHA = "senha-correta-longa-o-suficiente"
# From E05 the identifier is the address. allauth's form field is `login`.
IDENTIFIER = "vagner@example.com"
LOGIN_URL = "/accounts/login/"


@pytest.fixture
def account(db):
    """An account that can actually sign in.

    The verified `EmailAddress` is not decoration: with
    `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` allauth checks that table, not
    `CustomUser.email`, so a user built without one is bounced to
    "confirme seu e-mail" no matter how right the password is. Production's
    pre-E05 accounts get theirs from `core/0004_seed_email_addresses`; a row
    made inside a test has to say so itself.
    """
    from allauth.account.models import EmailAddress

    user = baker.make("core.CustomUser", username="vagner", email=IDENTIFIER)
    user.set_password(SENHA)
    user.save()
    EmailAddress.objects.update_or_create(
        user=user, email=IDENTIFIER, defaults={"verified": True, "primary": True}
    )
    return user


@pytest.mark.django_db
class TestLoginPageRenders:
    def test_get_renders_the_app_login_page(self):
        response = Client().get(LOGIN_URL)
        assert response.status_code == 200
        assert "account/login.html" in [t.name for t in response.templates]

    def test_page_is_in_portuguese_and_not_the_django_admin(self):
        body = Client().get(LOGIN_URL).content.decode()
        assert "Entrar" in body
        assert "Django" not in body

    def test_page_carries_the_double_submit_guard(self):
        """The reported CSRF 403 was a double-tapped login form.

        ``auth.login()`` rotates the CSRF token, so the second tap posts a stale
        one and Django answers 403 — over an app that had already loaded. The
        guard is what stops the second tap being sent.
        """
        body = Client().get(LOGIN_URL).content.decode()
        assert "addEventListener('submit'" in body, "the guard script is missing"
        assert '<form method="post"' in body
        assert "data-no-submit-guard" not in body.split("<script>")[0], (
            "the login form opted out of the guard"
        )
        assert 'data-pending="Entrando…"' in body

    def test_page_advertises_the_pwa(self):
        """It is the unauthenticated landing, so install must be offered here."""
        body = Client().get(LOGIN_URL).content.decode()
        assert 'rel="manifest"' in body
        assert "/manifest.webmanifest" in body
        assert "serviceWorker" in body
        assert "#147874" in body

    def test_page_offers_the_two_ways_out_of_a_dead_end(self):
        """A door with no bell and no spare key is the problem E05 exists for."""
        body = Client().get(LOGIN_URL).content.decode()
        assert "/accounts/signup/" in body
        assert "/accounts/password/reset/" in body


@pytest.mark.django_db
class TestSigningIn:
    def test_correct_credentials_land_on_the_dashboard(self, account):
        response = Client().post(LOGIN_URL, {"login": IDENTIFIER, "password": SENHA})
        assert response.status_code == 302
        assert response["Location"] == "/"

    def test_next_is_honoured(self, account):
        response = Client().post(
            f"{LOGIN_URL}?next=/entries/", {"login": IDENTIFIER, "password": SENHA}
        )
        assert response.status_code == 302
        assert response["Location"] == "/entries/"

    def test_wrong_password_re_renders_with_a_portuguese_error(self, account):
        client = Client()
        response = client.post(LOGIN_URL, {"login": IDENTIFIER, "password": "errada"})
        assert response.status_code == 200
        assert "E-mail ou senha incorretos." in response.content.decode()
        assert not client.session.get("_auth_user_id")

    def test_an_authenticated_visitor_is_sent_on_rather_than_shown_the_form(self, account):
        client = Client()
        client.force_login(account)
        response = client.get(LOGIN_URL)
        assert response.status_code == 302


@pytest.mark.django_db
class TestLockoutIsVisible:
    """E01's lockout was enforced but never explained.

    Through the admin form a locked-out user saw the stock "please enter a
    correct username and password" — indistinguishable from a typo, so the
    natural response was to keep trying and keep extending nothing. Saying so
    leaks nothing: a failed attempt is recorded for any identifier, existing or
    not, so a lockout message does not reveal that an account exists.
    """

    def test_locked_out_user_is_told_so(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(3):
            client.post(LOGIN_URL, {"login": IDENTIFIER, "password": "errada"})

        response = client.post(LOGIN_URL, {"login": IDENTIFIER, "password": SENHA})
        body = response.content.decode()
        assert response.status_code == 200
        assert "Muitas tentativas" in body
        assert "E-mail ou senha incorretos." not in body
        assert not client.session.get("_auth_user_id"), "the lockout let them in"

    def test_a_locked_out_attempt_does_not_extend_the_lockout(self, account, settings):
        settings.LOGIN_FAILURE_LIMIT = 3
        client = Client()
        for _ in range(5):
            client.post(LOGIN_URL, {"login": IDENTIFIER, "password": "errada"})
        assert LoginAttempt.objects.filter(username=IDENTIFIER).count() == 3


@pytest.mark.django_db
class TestTheFrontDoorMoved:
    def test_a_protected_page_bounces_to_the_app_login(self):
        response = Client().get("/entries/")
        assert response.status_code == 302
        assert response["Location"].startswith(LOGIN_URL)
        assert "next=/entries/" in response["Location"]

    def test_logging_out_returns_to_the_app_login_page(self, account):
        client = Client()
        client.force_login(account)
        response = client.post("/accounts/logout/")
        assert response.status_code == 302
        assert response["Location"] == LOGIN_URL

    def test_the_maintainer_reaches_admin_through_this_same_door(self, account):
        """Moving the family's door must not lock the maintainer out of admin.

        E05 also closed `/admin/login/` — the gate 404s anonymous requests —
        so staff sign in here, like everyone else. What is different for them
        is what happens next: with an authenticator enrolled, allauth answers
        the correct password with the 2FA challenge rather than a session. The
        admin path therefore sits behind password *and* second factor, and this
        test is what says the second half is really enforced at login and not
        only checked by the gate afterwards.
        """
        from allauth.mfa.totp.internal import auth as totp_auth

        account.is_staff = True
        account.is_superuser = True
        account.save()
        totp_auth.TOTP.activate(account, totp_auth.generate_totp_secret())

        client = Client()
        response = client.post(LOGIN_URL, {"login": IDENTIFIER, "password": SENHA})
        assert response.status_code == 302
        assert "2fa" in response["Location"], response["Location"]
        assert not client.session.get("_auth_user_id"), "the password alone signed them in"

    def test_a_maintainer_without_a_second_factor_signs_in_normally(self, account):
        """Enrolment is demanded by the admin gate, not by the login page.

        Staff who have not enrolled yet still get into the *app* — they are
        redirected to enrol only when they reach for admin. Otherwise the first
        operator could never enrol at all.
        """
        account.is_staff = True
        account.save()
        client = Client()
        response = client.post(LOGIN_URL, {"login": IDENTIFIER, "password": SENHA})
        assert response.status_code == 302
        assert client.session.get("_auth_user_id")
