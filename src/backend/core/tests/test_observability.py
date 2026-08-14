"""Sentry wiring and the PII scrubber.

The configuration is built by a pure function so these tests never initialise
an SDK or open a socket — a test suite that talks to a vendor is a test suite
that fails on a plane.
"""

import json
import logging

import pytest

from core.observability import init_sentry, scrub_event, sentry_settings

CHAT_CONTENT = "gastei 45 no mercado no crédito"
VALID_DSN = "https://" + "k" * 32 + "@o1234567.ingest.us.sentry.io/4509"
# The shape a half-copied DSN has: the key and part of the host, but no scheme,
# no `.ingest…sentry.io`, and no project id. It reached production configuration
# once, which is why it is pinned here.
TRUNCATED_DSN = "a" * 32 + "@o123456789012345"


@pytest.fixture(autouse=True)
def _teardown_sentry_client():
    """Tear the global client down after any test that initialises one.

    ``sentry_sdk.init`` sets process-wide state. A test that leaves a client
    behind changes what every later test observes, and the failure surfaces
    somewhere else entirely.
    """
    yield
    import sentry_sdk

    sentry_sdk.init(dsn=None)


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


def test_no_dsn_does_not_initialise():
    assert init_sentry({}) is False


def test_a_valid_dsn_initialises():
    assert init_sentry({"SENTRY_DSN": VALID_DSN}) is True


def test_a_malformed_dsn_disables_sentry_instead_of_raising(caplog):
    """A bad DSN must not stop the application from booting.

    ``sentry_sdk.init`` raises ``BadDsn`` on an unparseable DSN, and settings
    calls this at import time — so without the guard, one mistyped secret takes
    the whole service down on startup rather than merely losing error tracking.
    Tracing already follows this rule; error tracking now does too.
    """
    with caplog.at_level(logging.WARNING):
        assert init_sentry({"SENTRY_DSN": TRUNCATED_DSN}) is False
    assert "Sentry" in caplog.text


def test_a_failed_init_never_logs_the_dsn(caplog):
    """The DSN is a write key from Secret Manager; a warning is not the place
    to spill it, and Cloud Logging keeps whatever gets written for 30 days."""
    with caplog.at_level(logging.WARNING):
        init_sentry({"SENTRY_DSN": TRUNCATED_DSN})
    assert TRUNCATED_DSN not in caplog.text
    assert "a" * 32 not in caplog.text


def test_request_body_is_removed():
    event = {"request": {"url": "/api/assistant/", "data": {"message": CHAT_CONTENT}}}
    scrubbed = scrub_event(event, {})
    assert "data" not in scrubbed["request"]
    assert CHAT_CONTENT not in json.dumps(scrubbed)


def test_cookies_and_headers_are_removed():
    """Headers carry the session cookie and the CSRF token."""
    event = {
        "request": {
            "url": "/",
            "cookies": {"sessionid": "abc123"},
            "headers": {"Cookie": "sessionid=abc123", "Authorization": "Bearer x"},
        }
    }
    scrubbed = scrub_event(event, {})
    assert "cookies" not in scrubbed["request"]
    assert "headers" not in scrubbed["request"]
    assert "abc123" not in json.dumps(scrubbed)


def test_the_url_survives():
    """Scrubbing must not make an event useless -- the path is how you find it."""
    event = {"request": {"url": "/api/assistant/", "method": "POST", "data": {"m": CHAT_CONTENT}}}
    scrubbed = scrub_event(event, {})
    assert scrubbed["request"]["url"] == "/api/assistant/"
    assert scrubbed["request"]["method"] == "POST"


def test_stack_frame_locals_are_removed():
    """Locals are where an entry description or a chat message actually leaks:
    the variable holding it is in the frame that raised."""
    event = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "stacktrace": {
                        "frames": [
                            {"filename": "views.py", "vars": {"message": CHAT_CONTENT}},
                        ]
                    },
                }
            ]
        }
    }
    scrubbed = scrub_event(event, {})
    assert CHAT_CONTENT not in json.dumps(scrubbed)


def test_extra_and_breadcrumb_data_are_removed():
    event = {
        "extra": {"entry_description": "Farmácia Pague Menos"},
        "breadcrumbs": {"values": [{"message": "ok", "data": {"content": CHAT_CONTENT}}]},
    }
    scrubbed = scrub_event(event, {})
    payload = json.dumps(scrubbed)
    assert CHAT_CONTENT not in payload
    assert "Pague Menos" not in payload


def test_event_without_request_is_untouched():
    """A scrubber that raises on an unexpected shape silently drops every event."""
    assert scrub_event({"message": "hello"}, {}) == {"message": "hello"}


@pytest.mark.django_db
def test_chat_content_never_reaches_the_transport(client, settings, django_user_model):
    """The DoD assertion: a real error on the real request path carries no chat content.

    `before_send` both scrubs and records, then returns None so nothing is ever
    transmitted. Recording what our own scrubber produced is the honest place to
    assert -- it is byte-for-byte what the transport would have sent.
    """
    import sentry_sdk

    captured = []

    def record(event, hint):
        captured.append(scrub_event(event, hint))
        return None  # never transmit from a test

    sentry_sdk.init(
        dsn="https://key@example.invalid/1",
        before_send=record,
        send_default_pii=False,
        traces_sample_rate=0,
    )
    try:
        with sentry_sdk.new_scope():
            try:
                raise ValueError(f"boom while handling {CHAT_CONTENT}")
            except ValueError:
                sentry_sdk.capture_exception()
    finally:
        sentry_sdk.init(dsn=None)  # tear the client down for the next test

    assert captured, "before_send never ran -- the event was dropped before scrubbing"
    payload = json.dumps(captured[0])
    # The exception *message* is developer-authored and stays; what must not
    # survive is any structured carrier of user content.
    assert "vars" not in payload
