from django.test import TestCase


class HealthCheckTest(TestCase):
    def test_healthz_returns_200(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)

    def test_healthz_returns_json(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual(data["status"], "ok")

    def test_healthz_includes_db_check(self):
        response = self.client.get("/healthz/")
        data = response.json()
        self.assertIn("database", data)
        self.assertEqual(data["database"], "ok")

    def test_healthz_allows_unauthenticated_access(self):
        """Health check must work without login (Cloud Run probes are unauthenticated)."""
        self.client.logout()
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
