"""Admin holds every household's money and every user's raw chat.

Three properties, and the first one is why the other two matter: the service
is deployed --allow-unauthenticated because the product needs to be, so
"admin is on the internet" is not a deployment mistake to fix later, it is the
default this middleware exists to override.

404 rather than 403 throughout. A 403 confirms the path is admin; a 404 says
nothing, and an admin path nobody can confirm is one nobody can enumerate.
"""

import pytest
from django.conf import settings
from django.test import Client
from model_bakery import baker

from core.models import AdminAccessLog


def _admin_url(suffix=""):
    return "/" + settings.ADMIN_URL_PATH.lstrip("/") + suffix


def _with_totp(user):
    """Give ``user`` a real, activated TOTP authenticator."""
    from allauth.mfa.totp.internal import auth as totp_auth

    secret = totp_auth.generate_totp_secret()
    return totp_auth.TOTP.activate(user, secret)


@pytest.fixture
def staff(db):
    return baker.make(
        "core.CustomUser", email="operador@example.com", is_staff=True, is_superuser=True
    )


@pytest.mark.django_db
class TestTheOldPathIsGone:
    def test_slash_admin_no_longer_routes(self):
        """The path every scanner tries first must not be the real one."""
        assert settings.ADMIN_URL_PATH != "admin/"
        assert Client().get("/admin/").status_code == 404

    def test_slash_admin_login_no_longer_routes(self):
        assert Client().get("/admin/login/").status_code == 404


@pytest.mark.django_db
class TestThePathCannotBeConfirmedFromOutside:
    """The secret path must answer like any other nonexistent URL.

    `CommonMiddleware`'s APPEND_SLASH turns a 404 into a 301 whenever the
    slashed version of the URL *would* resolve — so `/gestao-dev` (no trailing
    slash) answered 301 while `/qualquer-coisa` answered 404. That difference
    is an oracle: it confirms a guessed path exists, which is the one thing
    moving the path was supposed to prevent. Access was never granted — the
    slashed path still 404s — but half the control was.
    """

    def test_the_unslashed_path_answers_exactly_like_a_nonexistent_one(self):
        client = Client()
        unslashed = "/" + settings.ADMIN_URL_PATH.strip("/")
        assert client.get(unslashed).status_code == client.get("/nao-existe-mesmo").status_code

    def test_the_refusal_is_byte_for_byte_a_routing_404(self):
        """Not just the status code — the headers too.

        The gate answers by raising, and a middleware's response only travels
        back out through the middleware listed *above* it. Registered above
        `XFrameOptionsMiddleware`, the gate's 404 came back without
        `X-Frame-Options: DENY` while every genuine 404 carried it, so one
        `curl -sI` separated the real admin path from every wrong guess. This
        compares the whole header set rather than one header, so the next
        middleware someone adds cannot reopen the same oracle quietly.
        """
        client = Client()
        real = client.get(_admin_url())
        missing = client.get("/nao-existe-mesmo/")
        assert real.status_code == missing.status_code == 404

        ignored = {"Content-Length", "Date", "Server", "Vary"}
        assert {k for k in real.headers if k not in ignored} == {
            k for k in missing.headers if k not in ignored
        }

    def test_the_unslashed_path_does_not_redirect(self):
        unslashed = "/" + settings.ADMIN_URL_PATH.strip("/")
        assert Client().get(unslashed).status_code == 404

    def test_a_staff_member_may_still_use_the_unslashed_path(self, staff):
        """Closing the oracle must not cost the operator the convenience of
        typing the path without its trailing slash."""
        _with_totp(staff)
        client = Client()
        client.force_login(staff)
        response = client.get("/" + settings.ADMIN_URL_PATH.strip("/"))
        assert response.status_code in (200, 301, 302)


@pytest.mark.django_db
class TestOnlyStaffReachAdmin:
    def test_an_anonymous_request_gets_404_not_a_login_page(self):
        """The epic's sixth observable assertion, anonymous half."""
        assert Client().get(_admin_url()).status_code == 404

    def test_an_authenticated_non_staff_user_gets_404(self, user):
        """The epic's sixth observable assertion, verbatim."""
        client = Client()
        client.force_login(user)
        assert client.get(_admin_url()).status_code == 404

    def test_a_non_staff_user_cannot_reach_a_model_page_either(self, user):
        client = Client()
        client.force_login(user)
        assert client.get(_admin_url("core/customuser/")).status_code == 404

    def test_staff_with_a_second_factor_get_in(self, staff):
        _with_totp(staff)
        client = Client()
        client.force_login(staff)
        assert client.get(_admin_url()).status_code == 200


@pytest.mark.django_db
class TestStaffWithoutASecondFactor:
    def test_they_are_sent_to_enrol_rather_than_stonewalled(self, staff):
        """404ing the only operator out of their own admin, with no
        explanation, is how this feature gets reverted at 2am."""
        client = Client()
        client.force_login(staff)
        response = client.get(_admin_url())
        assert response.status_code == 302
        assert "2fa" in response["Location"] or "totp" in response["Location"]


@pytest.mark.django_db
class TestStaffAccessIsLogged:
    def test_a_staff_request_writes_a_row_with_actor_target_and_time(self, staff):
        _with_totp(staff)
        client = Client()
        client.force_login(staff)
        client.get(_admin_url("core/customuser/"))

        entry = AdminAccessLog.objects.latest("created_at")
        assert entry.actor == staff
        assert "core/customuser" in entry.path
        assert entry.created_at is not None

    def test_a_refused_request_is_not_logged_as_access(self, user):
        client = Client()
        client.force_login(user)
        client.get(_admin_url())
        assert not AdminAccessLog.objects.filter(actor=user).exists()

    def test_the_log_cannot_be_edited_or_deleted_from_admin(self):
        """An audit log a staff member can delete is not an audit log."""
        from django.contrib import admin

        options = admin.site._registry[AdminAccessLog]
        assert options.has_add_permission(None) is False
        assert options.has_change_permission(None) is False
        assert options.has_delete_permission(None) is False


@pytest.mark.django_db
class TestChatIsNotInAdmin:
    def test_chatmessage_is_not_registered(self):
        """S05-5: raw conversation content is not an admin list column."""
        from django.contrib import admin

        from assistant.models import ChatMessage

        assert ChatMessage not in admin.site._registry


@pytest.mark.django_db
class TestTheServiceWorkerDoesNotPublishThePath:
    """`sw.js` is served to anyone who asks, so anything in it is public.

    An earlier version of this task templated `ADMIN_URL_PATH` into the
    worker's bypass list, reasoning that a hardcoded `/admin/` would be
    protecting a path that no longer exists. Both halves were true and the
    conclusion was still wrong: it published the secret to every anonymous
    visitor, which is precisely what the env var exists to withhold. Nothing
    was lost by removing it — `networkFirstNav` never writes to the cache, so
    an admin navigation is a plain fetch either way.
    """

    def test_sw_js_is_readable_by_anyone(self):
        """Stated so the test below is understood as being about a public file."""
        assert Client().get("/sw.js").status_code == 200

    def test_sw_js_does_not_contain_the_admin_path(self):
        body = Client().get("/sw.js").content.decode()
        assert settings.ADMIN_URL_PATH not in body
        assert settings.ADMIN_URL_PATH.strip("/") not in body
