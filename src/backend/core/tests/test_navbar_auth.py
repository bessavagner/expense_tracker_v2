from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser


class TestLogout(TestCase):
    def test_logout_logs_user_out(self):
        user = baker.make(CustomUser)
        self.client.force_login(user)
        resp = self.client.post("/logout/")
        self.assertEqual(resp.status_code, 302)
        # A protected page now bounces to the login screen.
        protected = self.client.get("/entries/")
        self.assertEqual(protected.status_code, 302)
        self.assertIn("/admin/login", protected["Location"])


class TestNavbarControls(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_navbar_has_theme_toggle_and_logout(self):
        body = self.client.get("/").content.decode()
        self.assertIn("Alternar tema", body)  # theme toggle button
        self.assertIn("/logout/", body)  # logout form action
