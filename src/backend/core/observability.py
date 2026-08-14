"""Sentry configuration and the payload scrubber.

Built as pure functions taking an environment mapping rather than reading
``os.environ`` directly, so the whole configuration is testable without
initialising an SDK or opening a socket.

The scrubber is not optional decoration. This application handles financial
descriptions, chat content and receipt data; Sentry's defaults capture request
bodies, and shipping those to a third party would itself be a privacy incident
(ADR-005).
"""

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


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


def init_sentry(environ: Mapping[str, str]) -> bool:
    """Initialise Sentry if a DSN is configured. Returns whether it happened.

    Never raises. Settings calls this at import time, so an exception here does
    not merely lose error tracking — it stops Django from starting, and one
    mistyped secret takes the whole service down. ``sentry_sdk.init`` raises
    ``BadDsn`` on an unparseable DSN, which is exactly the mistake a
    half-copied value from a vendor console produces.

    Error tracking is diagnostic infrastructure, and the same rule applies to
    it as to tracing (``assistant.tracing.configure_tracing``): a misconfigured
    observability vendor must not be able to prevent the application from
    running.
    """
    config = sentry_settings(environ)
    if config is None:
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(**config)
    except Exception as exc:
        # The exception *type* only. A DSN is a write key out of Secret
        # Manager, and BadDsn's message can quote the value it rejected —
        # which would then sit in Cloud Logging for thirty days.
        logger.warning(
            "Sentry disabled: the DSN was rejected (%s). Error tracking is off; "
            "the application continues.",
            type(exc).__name__,
        )
        return False

    return True


# Request sub-keys that carry user content or credentials wholesale. `url`,
# `method` and `query_string` deliberately survive: a scrubbed event still has
# to be findable, and an event nobody can locate is as useless as no event.
_REQUEST_KEYS_TO_DROP = ("data", "cookies", "headers", "env")


def scrub_event(event: dict, hint: dict) -> dict:
    """Sentry ``before_send``: remove every structured carrier of user content.

    Runs on every event, so it must never raise — an exception here drops the
    event silently and the failure it described is lost twice over. Hence the
    defensive ``isinstance`` checks against event shapes that vary by SDK
    version and integration.
    """
    if not isinstance(event, dict):
        return event

    request = event.get("request")
    if isinstance(request, dict):
        for key in _REQUEST_KEYS_TO_DROP:
            request.pop(key, None)

    # Stack-frame locals are the real leak path: the variable holding a chat
    # message or an entry description lives in the frame that raised.
    for value in _exception_values(event):
        stacktrace = value.get("stacktrace")
        if not isinstance(stacktrace, dict):
            continue
        for frame in stacktrace.get("frames") or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)

    # `extra` is where application code attaches context, and breadcrumb `data`
    # is where integrations do. Neither is worth auditing call site by call site.
    event.pop("extra", None)
    breadcrumbs = event.get("breadcrumbs")
    crumb_values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    for crumb in crumb_values or []:
        if isinstance(crumb, dict):
            crumb.pop("data", None)

    return event


def _exception_values(event: dict):
    """The exception entries, tolerating both shapes the SDK emits."""
    exception = event.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values") or []
    elif isinstance(exception, list):
        values = exception
    else:
        values = []
    return [v for v in values if isinstance(v, dict)]
