import json

from django.test import TestCase


class TestManifest(TestCase):
    def test_manifest_returns_200(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)

    def test_manifest_content_type(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertIn("application/manifest+json", resp["Content-Type"])

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


class TestServiceWorker(TestCase):
    def test_sw_returns_200(self):
        self.assertEqual(self.client.get("/sw.js").status_code, 200)

    def test_sw_javascript_content_type(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp["Content-Type"], "application/javascript")

    def test_sw_allowed_at_root_scope(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp["Service-Worker-Allowed"], "/")

    def test_sw_not_cached(self):
        resp = self.client.get("/sw.js")
        self.assertIn("no-cache", resp["Cache-Control"])

    def test_sw_served_without_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/sw.js").status_code, 200)


class TestOffline(TestCase):
    def test_offline_returns_200_without_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/offline/").status_code, 200)

    def test_offline_page_has_retry(self):
        body = self.client.get("/offline/").content.decode()
        self.assertIn("Tentar novamente", body)
        self.assertIn("Sem conex", body)  # "Sem conexão"
