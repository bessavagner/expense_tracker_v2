"""A new household lands in the guided setup; everything else is left alone.

The redirect is the one piece of this epic that can take the whole product
down — an over-broad rule loops, and a rule that catches the API breaks the
chat widget with no visible error. Hence the exemption tests.
"""

import pytest
from django.urls import reverse

from accounts.models import OnboardingState, OnboardingStep


@pytest.mark.django_db
class TestRedirect:
    def test_an_unonboarded_household_is_sent_to_the_guided_setup(self, logged_client, household):
        # The shared `household` fixture arrives onboarded (see conftest), so a
        # test about the NEW-household path has to say so explicitly.
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.get("/")

        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")

    def test_a_completed_household_is_left_alone(self, logged_client, household):
        state = OnboardingState.for_household(household)
        for step in OnboardingStep:
            state.mark(step)

        assert logged_client.get("/").status_code == 200

    def test_an_anonymous_visitor_is_not_redirected(self, client):
        """They get the login redirect, which is a different destination."""
        response = client.get("/")

        assert reverse("onboarding") not in response.get("Location", "")


@pytest.mark.django_db
class TestExemptions:
    @pytest.mark.parametrize(
        "path",
        [
            "/casa/comecar/",
            "/api/assistant/history/",
            "/api/dashboard/summary/",
            "/healthz/",
            "/manifest.webmanifest",
            "/sw.js",
            "/accounts/logout/",
        ],
    )
    def test_these_paths_are_never_redirected(self, logged_client, path):
        response = logged_client.get(path)

        assert response.get("Location", "") != reverse("onboarding")

    def test_an_htmx_request_is_not_redirected(self, logged_client):
        """HTMX swaps a redirect's body into a fragment slot, which would paint
        the whole setup page inside a table cell."""
        response = logged_client.get("/", HTTP_HX_REQUEST="true")

        assert response.get("Location", "") != reverse("onboarding")
