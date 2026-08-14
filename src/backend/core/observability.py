"""Sentry configuration and the payload scrubber.

Built as pure functions taking an environment mapping rather than reading
``os.environ`` directly, so the whole configuration is testable without
initialising an SDK or opening a socket.

The scrubber is not optional decoration. This application handles financial
descriptions, chat content and receipt data; Sentry's defaults capture request
bodies, and shipping those to a third party would itself be a privacy incident
(ADR-005).
"""

from collections.abc import Mapping


def sentry_settings(environ: Mapping[str, str]) -> dict | None:
    """The kwargs for ``sentry_sdk.init()``, or ``None`` to stay disabled.

    No DSN means no Sentry at all — the local-development and CI path. Both
    must transmit nothing.
    """
    dsn = environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None

    # Cloud Run injects K_REVISION with the serving revision's name, which is
    # exactly the granularity the DoD wants an error attributed to. SENTRY_RELEASE
    # is the manual override for anywhere that is not Cloud Run.
    release = environ.get("K_REVISION") or environ.get("SENTRY_RELEASE") or "unknown"

    return {
        "dsn": dsn,
        "environment": environ.get("SENTRY_ENVIRONMENT", "development"),
        "release": release,
        # Never flip this to True. It attaches request bodies, cookies and user
        # identifiers wholesale, which is the incident the scrubber below exists
        # to prevent.
        "send_default_pii": False,
        "traces_sample_rate": float(environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        "before_send": scrub_event,
    }


def scrub_event(event, hint):  # replaced in Task 2
    return event
