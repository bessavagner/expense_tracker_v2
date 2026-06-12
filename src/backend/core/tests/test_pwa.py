import json

from django.test import TestCase


class TestManifest(TestCase):
    def test_manifest_returns_200(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)

    def test_manifest_content_type(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp["Content-Type"], "application/manifest+json")

    def test_manifest_is_valid_json_with_required_keys(self):
        resp = self.client.get("/manifest.webmanifest")
        data = json.loads(resp.content)
        for key in ("name", "short_name", "start_url", "display", "icons"):
            self.assertIn(key, data)
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["display"], "standalone")

    def test_manifest_lists_icons(self):
        resp = self.client.get("/manifest.webmanifest")
        data = json.loads(resp.content)
        self.assertGreaterEqual(len(data["icons"]), 2)
        for icon in data["icons"]:
            self.assertIn("src", icon)
            self.assertIn("sizes", icon)
        purposes = [i.get("purpose") for i in data["icons"]]
        self.assertIn("maskable", purposes)

    def test_manifest_served_without_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 200)
