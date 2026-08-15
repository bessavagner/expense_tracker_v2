"""Where the product's front door is, and what still answers at the old one.

`/login/` is not merely a legacy path: it is compiled into the installed
Android TWA and into the PWA manifest. Breaking it logs out every phone that
has the app, with no way to push a fix to them.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from model_bakery import baker


class TestLoginUrlPointsAtAllauth:
    def test_login_url_setting(self):
        assert settings.LOGIN_URL == "/accounts/login/"

    def test_account_login_resolves_to_the_app_view(self):
        from core.views import AppLoginView

        assert reverse("account_login") == "/accounts/login/"
        assert AppLoginView.__name__ == "AppLoginView"


@pytest.mark.django_db
class TestOldPathsStillAnswer:
    def test_slash_login_redirects_to_allauth(self):
        response = Client().get("/login/")
        assert response.status_code == 301
        assert response["Location"] == "/accounts/login/"

    def test_slash_login_preserves_the_next_parameter(self):
        response = Client().get("/login/?next=/entries/")
        assert response.status_code == 301
        assert "next=/entries/" in response["Location"]

    def test_slash_logout_redirects_to_allauth(self):
        """A redirect, not a logout.

        `/logout/` is kept for anything that still points at it, but a 301
        cannot carry a POST body and allauth logs out on POST — so the old path
        lands on allauth's confirmation page rather than ending the session
        itself. The navbar therefore posts to `account_logout` directly; the
        test below is what holds it to that.
        """
        user = baker.make("core.CustomUser", email="sai@example.com")
        client = Client()
        client.force_login(user)
        response = client.post("/logout/")
        assert response.status_code == 301
        assert response["Location"] == "/accounts/logout/"

    def test_the_navbar_posts_to_a_url_that_really_ends_the_session(self):
        from accounts.resolution import household_for_user
        from conftest import complete_onboarding

        user = baker.make("core.CustomUser", email="sai@example.com")
        complete_onboarding(household_for_user(user))
        client = Client()
        client.force_login(user)
        body = client.get("/").content.decode()
        assert "/accounts/logout/" in body, "the navbar still posts at the redirect"

        response = client.post(reverse("account_logout"))
        assert response.status_code == 302
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
class TestProtectedPagesBounceToTheNewDoor:
    def test_an_anonymous_request_is_sent_to_allauth_login(self):
        response = Client().get("/entries/")
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
class TestTheLockoutExplanationSurvived:
    def test_the_login_page_still_knows_the_lockout_window(self):
        response = Client().get(reverse("account_login"))
        assert response.context["lockout_minutes"] == settings.LOGIN_FAILURE_WINDOW_MINUTES
        assert response.context["locked_out"] is False
