import json
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser


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

    def test_sw_precaches_offline_page_and_stylesheet(self):
        # The offline fallback must render styled even on the first offline hit,
        # so the SW precaches /offline/ and the (hashed) tailwind stylesheet.
        body = self.client.get("/sw.js").content.decode()
        self.assertIn("/offline/", body)
        self.assertIn("tailwind", body)
        self.assertIn("css/tailwind", body)


class TestOffline(TestCase):
    def test_offline_returns_200_without_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/offline/").status_code, 200)

    def test_offline_page_has_retry(self):
        body = self.client.get("/offline/").content.decode()
        self.assertIn("Tentar novamente", body)
        self.assertIn("Sem conex", body)  # "Sem conexão"


class TestIconFiles(TestCase):
    def test_pwa_icons_exist(self):
        static_dir = Path(settings.STATICFILES_DIRS[0])
        for name in (
            "icon-192.png",
            "icon-512.png",
            "icon-maskable-512.png",
            "apple-touch-icon.png",
        ):
            path = static_dir / "images" / "pwa" / name
            self.assertTrue(path.exists(), f"missing icon: {path}")


class TestBaseHeadTags(TestCase):
    def setUp(self):
        self.client.force_login(baker.make(CustomUser))

    def test_page_links_manifest(self):
        body = self.client.get("/").content.decode()
        self.assertIn('rel="manifest"', body)
        self.assertIn("/manifest.webmanifest", body)

    def test_page_has_theme_color(self):
        body = self.client.get("/").content.decode()
        self.assertIn('name="theme-color"', body)
        self.assertIn("#f5f3ef", body)  # light theme-color

    def test_page_has_brand_tile_color(self):
        body = self.client.get("/").content.decode()
        self.assertIn("#147874", body)  # msapplication-TileColor (brand teal)

    def test_page_registers_service_worker(self):
        body = self.client.get("/").content.decode()
        self.assertIn("serviceWorker", body)
        self.assertIn("/sw.js", body)
