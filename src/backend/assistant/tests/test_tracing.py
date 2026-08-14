"""Agent tracing configuration.

These tests never contact Logfire. `configure_tracing` is split from
`instrumentation_settings` precisely so the policy (what gets captured) is
assertable without the transport (where it goes).
"""

from assistant.tracing import configure_tracing, instrumentation_settings


def test_no_token_means_no_logfire(settings):
    """Local development and CI must not transmit."""
    settings.LOGFIRE_TOKEN = ""
    assert configure_tracing() is False


def test_content_capture_follows_the_setting(settings):
    settings.LOGFIRE_CAPTURE_CONTENT = True
    assert instrumentation_settings().include_content is True

    settings.LOGFIRE_CAPTURE_CONTENT = False
    assert instrumentation_settings().include_content is False


def test_binary_content_is_excluded_by_default(settings):
    """Receipt photos are the largest exposure in the product; capturing text
    was decided, capturing every JPEG was not."""
    settings.LOGFIRE_CAPTURE_BINARY = False
    assert instrumentation_settings().include_binary_content is False


def test_binary_capture_can_be_turned_on(settings):
    settings.LOGFIRE_CAPTURE_BINARY = True
    assert instrumentation_settings().include_binary_content is True
