from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser


class TestLogout(TestCase):
    def test_logout_logs_user_out(self):
        user = baker.make(CustomUser, email="sai@example.com")
        self.client.force_login(user)
        # `/accounts/logout/`, which is what the navbar posts to. `/logout/`
        # survives as a 301 for anything that still points at it, but a 301
        # cannot carry a POST body, so it cannot be the thing that logs out.
        resp = self.client.post("/accounts/logout/")
        self.assertEqual(resp.status_code, 302)
        # A protected page now bounces to the app's login screen.
        protected = self.client.get("/entries/")
        self.assertEqual(protected.status_code, 302)
        self.assertIn("/accounts/login/", protected["Location"])


class TestNavbarControls(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser, email="navbar@example.com")
        self.client.force_login(self.user)

    def test_navbar_has_theme_toggle_and_logout(self):
        body = self.client.get("/").content.decode()
        self.assertIn("Alternar tema", body)  # theme toggle button
        self.assertIn("/accounts/logout/", body)  # logout form action
