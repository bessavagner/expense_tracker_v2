"""Admin still works — for staff who have earned it.

E05 moved admin off `/admin/` to an env-var path and put
`core.admin_gate.admin_staff_only_middleware` in front of it, so "a superuser
can open a model page" now has two more preconditions: the right path, and a
second factor. This file asserts the happy path; `test_admin_isolation.py`
asserts every way in that must fail.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _admin_url(suffix=""):
    return "/" + settings.ADMIN_URL_PATH.lstrip("/") + suffix


class AdminSiteTest(TestCase):
    def setUp(self):
        from allauth.mfa.totp.internal import auth as totp_auth

        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )
        # Not decoration: without an activated authenticator the gate redirects
        # to enrolment instead of answering, which is the point of Task 15.
        totp_auth.TOTP.activate(self.admin_user, totp_auth.generate_totp_secret())
        self.client.force_login(self.admin_user)

    def test_admin_users_list(self):
        response = self.client.get(_admin_url("core/customuser/"))
        self.assertEqual(response.status_code, 200)

    def test_admin_user_detail(self):
        response = self.client.get(_admin_url(f"core/customuser/{self.admin_user.pk}/change/"))
        self.assertEqual(response.status_code, 200)
