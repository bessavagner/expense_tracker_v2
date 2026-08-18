from unittest.mock import patch

from django.db.utils import OperationalError
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


class HealthCheckMigrationDriftTest(TestCase):
    """A drifted revision is already broken for its users; say so out loud.

    Cloud Run's uptime check polls this endpoint every five minutes, so a 503
    here is the difference between "an operator notices within five minutes" and
    "a day passes at ~100% authenticated failure" — which is what 2026-08-15
    actually cost, because the count-based 5xx alert never reached its
    threshold at family-scale traffic.
    """

    def test_a_synced_database_reports_migrations_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["migrations"], "ok")
        self.assertEqual(data["unapplied"], [])

    def test_drift_degrades_the_endpoint_to_503(self):
        with patch(
            "core.views.unapplied_migrations",
            return_value=["accounts.0005_household_plan"],
        ):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["migrations"], "drift")

    def test_drift_names_the_missing_migrations(self):
        """`migrate accounts` is the fix. Anything less sends you investigating."""
        with patch(
            "core.views.unapplied_migrations",
            return_value=["accounts.0005_household_plan", "core.0010_thing"],
        ):
            response = self.client.get("/healthz/")
        self.assertEqual(
            response.json()["unapplied"],
            ["accounts.0005_household_plan", "core.0010_thing"],
        )

    def test_an_unreachable_database_is_reported_as_a_database_error_not_as_drift(self):
        """Two different outages. Conflating them sends the operator to the wrong runbook."""
        with patch("core.views.connection.ensure_connection", side_effect=OperationalError("nope")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["database"], "error")
        self.assertEqual(data["migrations"], "unknown")

    def test_a_drift_check_that_itself_raises_does_not_500_the_probe(self):
        """The probe must answer even when the drift question cannot be asked.

        A health endpoint that raises is indistinguishable from a dead
        container, and the operator loses the one signal that was still working.
        """
        with patch("core.views.unapplied_migrations", side_effect=RuntimeError("boom")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["migrations"], "unknown")
