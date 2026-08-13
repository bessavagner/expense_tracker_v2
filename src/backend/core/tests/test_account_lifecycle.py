"""Sign up, verify, log in, forget the password, reset it, log in again.

The epic's first observable assertion, written as one road rather than six
unit tests, because the failure this catches is always at a seam: a signal
that fires too late, a redirect that drops `next`, a verification that lets an
unverified account through.

Reads links out of `mail.outbox` rather than constructing them, so a change to
allauth's URL shapes fails here loudly instead of passing against a URL the
product never sends.
"""

import re

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import Membership, Role

EMAIL = "estranho@example.com"
FIRST_PASSWORD = "primeira-senha-longa-7"
SECOND_PASSWORD = "segunda-senha-longa-42"


def _link_from(message, fragment):
    """The first URL in the message body containing `fragment`."""
    urls = re.findall(r"https?://\S+", message.body)
    matches = [u for u in urls if fragment in u]
    assert matches, f"no {fragment!r} link in:\n{message.body}"
    return matches[0]


@pytest.mark.django_db
class TestAccountLifecycle:
    def test_a_stranger_can_sign_up_verify_log_in_and_reset(self):
        client = Client()

        # --- sign up ---------------------------------------------------
        response = client.post(
            reverse("account_signup"),
            {
                "email": EMAIL,
                "email2": EMAIL,
                "password1": FIRST_PASSWORD,
                "password2": FIRST_PASSWORD,
            },
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1

        # --- verification is mandatory ---------------------------------
        fresh = Client()
        fresh.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" not in fresh.session, "unverified account logged in"

        # --- verify ----------------------------------------------------
        confirm_url = _link_from(mail.outbox[0], "confirm")
        path = confirm_url.split("testserver")[-1]
        assert fresh.post(path).status_code in (302, 200)

        # --- log in ----------------------------------------------------
        fresh.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" in fresh.session

        # --- the signup owns a household -------------------------------
        membership = Membership.objects.get(user_id=fresh.session["_auth_user_id"])
        assert membership.role == Role.OWNER

        # --- forget the password ---------------------------------------
        mail.outbox.clear()
        anonymous = Client()
        anonymous.post(reverse("account_reset_password"), {"email": EMAIL})
        assert len(mail.outbox) == 1

        reset_url = _link_from(mail.outbox[0], "password/reset")
        reset_path = reset_url.split("testserver")[-1]

        # allauth redirects the key URL to a `set-password` URL before showing
        # the form; follow it, then post to wherever it landed.
        landed = anonymous.get(reset_path, follow=True)
        assert landed.status_code == 200
        form_path = landed.request["PATH_INFO"]
        anonymous.post(form_path, {"password1": SECOND_PASSWORD, "password2": SECOND_PASSWORD})

        # --- the old password is dead, the new one works ---------------
        stale = Client()
        stale.post(reverse("account_login"), {"login": EMAIL, "password": FIRST_PASSWORD})
        assert "_auth_user_id" not in stale.session

        final = Client()
        final.post(reverse("account_login"), {"login": EMAIL, "password": SECOND_PASSWORD})
        assert "_auth_user_id" in final.session


@pytest.mark.django_db
class TestPasswordValidatorsStillApply:
    """settings.AUTH_PASSWORD_VALIDATORS must survive the move to allauth."""

    def test_a_short_password_is_rejected_at_signup(self):
        response = Client().post(
            reverse("account_signup"),
            {
                "email": "curta@example.com",
                "email2": "curta@example.com",
                "password1": "abc",
                "password2": "abc",
            },
        )
        assert response.status_code == 200  # re-rendered with errors
        assert not mail.outbox

    def test_a_common_password_is_rejected_at_signup(self):
        response = Client().post(
            reverse("account_signup"),
            {
                "email": "comum@example.com",
                "email2": "comum@example.com",
                "password1": "password123",
                "password2": "password123",
            },
        )
        assert response.status_code == 200
        assert not mail.outbox
