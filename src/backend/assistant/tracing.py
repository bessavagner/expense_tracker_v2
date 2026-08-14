"""Logfire configuration and PydanticAI instrumentation.

Split deliberately in two: ``instrumentation_settings`` is the *policy* (what
is captured) and ``configure_tracing`` is the *transport* (where it goes). The
split is what lets the policy be asserted in tests without a network call.

Traces cover every agent, not only the chat one: ``Agent.instrument_all``
applies globally, so the receipt extraction agent is instrumented by the same
call. Each span carries the model name, which is what makes E09's future
routing decisions visible in production.
"""

import logging

from django.conf import settings
from pydantic_ai import Agent, InstrumentationSettings

logger = logging.getLogger(__name__)


def instrumentation_settings() -> InstrumentationSettings:
    """What the traces capture.

    ``include_content`` is on by explicit operator decision (E06 open question
    2, decided 2026-08-14): full prompts and completions, so a bad extraction
    can be read rather than reproduced.

    ``include_binary_content`` is a separate flag and defaults off. That
    decision was about text; this one governs whether every receipt photograph
    is uploaded to a third party.
    """
    return InstrumentationSettings(
        include_content=settings.LOGFIRE_CAPTURE_CONTENT,
        include_binary_content=settings.LOGFIRE_CAPTURE_BINARY,
    )


def configure_tracing() -> bool:
    """Wire Logfire, if a token is configured. Returns whether it happened.

    Never raises. Tracing is diagnostic infrastructure; a misconfigured
    observability vendor must not be able to prevent the application from
    starting.
    """
    if not settings.LOGFIRE_TOKEN:
        return False

    try:
        import logfire

        logfire.configure(
            token=settings.LOGFIRE_TOKEN,
            environment=settings.LOGFIRE_ENVIRONMENT,
            service_name="ledger",
        )
        Agent.instrument_all(instrumentation_settings())
    except Exception:
        logger.exception("Logfire configuration failed; continuing without agent tracing.")
        return False

    return True
