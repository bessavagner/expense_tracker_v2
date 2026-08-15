"""A new household lands in the guided setup; everything else is left alone.

The redirect is the one piece of this epic that can take the whole product
down — an over-broad rule loops, and a rule that catches the API breaks the
chat widget with no visible error. Hence the exemption tests.
"""

import pytest
from django.conf import settings
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
    """`logged_client`'s household arrives onboarded (see conftest), which
    means the middleware never redirects *anything* for it — every exemption
    assertion below would pass identically with `_ONBOARDING_EXEMPT_PREFIXES`
    emptied out. So every test here logs in against `new_household` instead,
    and `test_a_non_exempt_path_is_the_control` proves that client can
    actually be redirected, which is what makes the exemption tests capable
    of failing.
    """

    @pytest.fixture
    def unonboarded_client(self, client, user, new_household):
        client.force_login(user)
        return client

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
    def test_these_paths_are_never_redirected(self, unonboarded_client, path):
        response = unonboarded_client.get(path)

        assert response.get("Location", "") != reverse("onboarding")

    def test_a_non_exempt_path_is_the_control(self, unonboarded_client):
        """Same client, same unonboarded household, a path with no exemption:
        this one MUST redirect, or the exemption tests above are vacuous."""
        response = unonboarded_client.get("/entries/")

        assert response.status_code == 302
        assert response["Location"] == reverse("onboarding")

    def test_an_htmx_request_is_not_redirected(self, unonboarded_client):
        """HTMX swaps a redirect's body into a fragment slot, which would paint
        the whole setup page inside a table cell."""
        response = unonboarded_client.get("/", HTTP_HX_REQUEST="true")

        assert response.get("Location", "") != reverse("onboarding")


@pytest.mark.django_db
class TestStaffBypassAdminWithoutReopeningTheSecretPathOracle:
    """`core.admin_gate` hides `settings.ADMIN_URL_PATH` by making the real
    path answer exactly like a wrong guess for anyone it refuses — see the
    prior-incident note on `ADMIN_URL_PATH` in `config/settings.py`. Exempting
    the admin path here by prefix would reopen that: the real path would 404
    (exempt, gate answers) while a wrong guess 302'd to onboarding (not
    exempt, this middleware answers) for any authenticated, unonboarded
    visitor — a class that includes every new signup. Staff are exempted by
    `request.user.is_staff` instead, which sidesteps the path entirely.
    """

    def test_an_unonboarded_non_staff_user_cannot_tell_the_real_path_from_a_guess(
        self, client, user, new_household
    ):
        client.force_login(user)

        real = client.get("/" + settings.ADMIN_URL_PATH)
        guess = client.get("/nao-existe-mesmo/")

        assert real.status_code == guess.status_code == 302
        assert real["Location"] == guess["Location"] == reverse("onboarding")

    def test_an_unonboarded_staff_user_reaches_the_admin_gate_instead_of_onboarding(
        self, client, django_user_model
    ):
        # No `Membership` at all: `resolve_active_household`'s fallback mints
        # one on the spot, unonboarded — exactly the `createsuperuser` case
        # this middleware must not route into a setup flow for a household
        # the operator never meant to create.
        staff = django_user_model.objects.create_user(
            username="staff-unonboarded",
            email="staff-unonboarded@example.com",
            is_staff=True,
        )
        client.force_login(staff)

        response = client.get("/" + settings.ADMIN_URL_PATH)

        # No second factor enrolled, so the gate itself still refuses — the
        # point is only that it is the GATE answering, not this middleware.
        assert response.get("Location", "") != reverse("onboarding")
