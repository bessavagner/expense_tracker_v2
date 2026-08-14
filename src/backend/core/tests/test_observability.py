"""Sentry wiring and the PII scrubber.

The configuration is built by a pure function so these tests never initialise
an SDK or open a socket — a test suite that talks to a vendor is a test suite
that fails on a plane.
"""

from core.observability import sentry_settings


def test_no_dsn_means_no_sentry():
    """Absent DSN disables Sentry entirely rather than initialising a no-op.

    This is the local-development and CI path: neither should transmit.
    """
    assert sentry_settings({}) is None
    assert sentry_settings({"SENTRY_DSN": ""}) is None


def test_dsn_produces_configuration():
    config = sentry_settings({"SENTRY_DSN": "https://k@example.invalid/1"})
    assert config["dsn"] == "https://k@example.invalid/1"


def test_pii_is_off_by_default():
    """send_default_pii=True would attach request bodies and user data."""
    config = sentry_settings({"SENTRY_DSN": "https://k@example.invalid/1"})
    assert config["send_default_pii"] is False


def test_release_comes_from_the_cloud_run_revision():
    """Cloud Run injects K_REVISION; it is exactly the deployed-revision tag
    the DoD asks errors to be attributable to."""
    config = sentry_settings(
        {"SENTRY_DSN": "https://k@example.invalid/1", "K_REVISION": "expense-tracker-00044-2kq"}
    )
    assert config["release"] == "expense-tracker-00044-2kq"


def test_release_falls_back_to_explicit_then_unknown():
    base = {"SENTRY_DSN": "https://k@example.invalid/1"}
    assert sentry_settings({**base, "SENTRY_RELEASE": "local"})["release"] == "local"
    assert sentry_settings(base)["release"] == "unknown"


def test_environment_defaults_to_development():
    base = {"SENTRY_DSN": "https://k@example.invalid/1"}
    assert sentry_settings(base)["environment"] == "development"
    assert (
        sentry_settings({**base, "SENTRY_ENVIRONMENT": "production"})["environment"] == "production"
    )
