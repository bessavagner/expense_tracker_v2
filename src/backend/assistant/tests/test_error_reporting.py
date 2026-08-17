"""Failures reach the error tracker without changing what the user sees.

E06 S06-4 is explicit that this story improves observability, not UX. Every
test here asserts both halves: the report happened AND the message is the same.
"""

import json
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync


def _consume(response):
    """Drain an async streaming response from a sync test.

    The chat view is async, so `streaming_content` is an async generator --
    the same helper `test_data_changed` needs, for the same reason.
    """

    async def collect():
        return b"".join([chunk async for chunk in response.streaming_content]).decode()

    return async_to_sync(collect)()


@pytest.mark.django_db(transaction=True)
def test_stream_failure_is_reported_and_the_message_is_unchanged(logged_client, consented_user):
    """The generic 'Erro ao processar mensagem' path was fully silent.

    It is the single most important site in the epic: every unhandled agent
    failure in production landed here and vanished.
    """
    from assistant.agents.assistant import assistant_agent

    def _explode(*args, **kwargs):
        raise RuntimeError("model exploded")

    with patch.object(assistant_agent, "run_stream", side_effect=_explode):
        with patch("sentry_sdk.capture_exception") as capture:
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            body = _consume(response)

    assert capture.called, "the agent failure was swallowed without reporting"
    assert "Erro ao processar mensagem" in body, "the user-facing message changed"


@pytest.mark.django_db
def test_import_row_failures_are_reported_once_not_per_row(monkeypatch):
    """A 1000-row file with 1000 bad rows must not create 1000 events.

    Aggregating is not merely tidier -- a per-row report would exhaust the
    Sentry quota that ADR-005 assumed was adequate, in a single upload.
    """
    # Moved from finances.views.importer to the runner in E12: the reporting
    # belongs with the loop that counts the failures, not with the HTTP layer.
    from finances.services import import_runner

    captured = []
    monkeypatch.setattr(
        import_runner.sentry_sdk, "capture_message", lambda *a, **kw: captured.append((a, kw))
    )
    # Drive `report_import_failures` directly: it is the unit under test, and
    # building a 1000-row import fixture to assert a counter is disproportionate.
    import_runner.report_import_failures(error_count=1000, kinds={"ValueError"})

    assert len(captured) == 1


@pytest.mark.django_db
def test_no_import_failures_reports_nothing(monkeypatch):
    from finances.services import import_runner

    captured = []
    monkeypatch.setattr(
        import_runner.sentry_sdk, "capture_message", lambda *a, **kw: captured.append(a)
    )
    import_runner.report_import_failures(error_count=0, kinds=set())

    assert captured == []
