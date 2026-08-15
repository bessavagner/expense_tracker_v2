"""The shape of the request we hand to Cloud Tasks.

Asserted against an injected client rather than the real API: this is about
what we ask for, and getting the OIDC audience or the target URL wrong is a
403 in production that no amount of local running would surface.
"""

import json
import uuid
from unittest import mock

import pytest

from core.models import TaskRun
from core.tasks.cloud import CloudTasksBackend

SERVICE_ACCOUNT = "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"


@pytest.fixture(autouse=True)
def _cloud(settings):
    """The deployed configuration, as a fixture.

    Not `override_settings` on the class: Django's decorator only understands
    SimpleTestCase subclasses, and these are plain pytest classes.
    """
    settings.CLOUD_TASKS_ENABLED = True
    settings.CLOUD_TASKS_PROJECT = "expense-tracker-482807"
    settings.CLOUD_TASKS_LOCATION = "southamerica-east1"
    settings.CLOUD_TASKS_QUEUE = "ledger-default"
    settings.CLOUD_TASKS_TARGET_BASE_URL = "https://ledger.example.com/"
    settings.CLOUD_TASKS_AUDIENCE = "https://ledger.example.com"
    settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT = SERVICE_ACCOUNT


@pytest.fixture
def fake_client():
    client = mock.Mock()
    client.queue_path.side_effect = lambda p, loc, q: f"projects/{p}/locations/{loc}/queues/{q}"
    return client


def _run(**extra):
    return TaskRun(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        name="assistant.embed_memory_rule",
        idempotency_key="k",
        payload={"rule_id": "abc"},
        max_attempts=4,
        **extra,
    )


def _sent_task(fake_client):
    return fake_client.create_task.call_args.args[0].task


class TestCloudTasksBackend:
    def test_it_targets_the_handler_url_for_the_task_name(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        http = _sent_task(fake_client).http_request
        assert http.url == "https://ledger.example.com/tasks/assistant.embed_memory_rule/"

    def test_it_sends_only_the_task_run_id(self, fake_client):
        """The payload lives on the row. Keeping the wire format to one id is
        what makes the fixed 1 MiB task ceiling a non-issue for transport."""
        CloudTasksBackend(client=fake_client).dispatch(_run())

        body = json.loads(_sent_task(fake_client).http_request.body)
        assert body == {"task_run_id": "11111111-2222-3333-4444-555555555555"}

    def test_it_attaches_an_oidc_token_for_the_configured_service_account(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        token = _sent_task(fake_client).http_request.oidc_token
        assert token.service_account_email == SERVICE_ACCOUNT
        assert token.audience == "https://ledger.example.com"

    def test_it_forwards_the_originating_request_id(self, fake_client):
        """The DoD box: a task execution's trace links back to its originating
        request ID. No new plumbing — `request_id_middleware` already adopts a
        well-formed inbound X-Request-ID, so the task's own log lines inherit
        the value under one Cloud Logging filter."""
        CloudTasksBackend(client=fake_client).dispatch(_run(request_id="ab" * 16))

        headers = _sent_task(fake_client).http_request.headers
        assert headers["X-Request-ID"] == "ab" * 16

    def test_it_omits_the_header_when_there_was_no_request(self, fake_client):
        """Work scheduled from a management command has no originating request,
        and an empty header would be adopted as garbage rather than ignored."""
        CloudTasksBackend(client=fake_client).dispatch(_run(request_id=""))

        assert "X-Request-ID" not in _sent_task(fake_client).http_request.headers

    def test_it_enqueues_onto_the_configured_queue(self, fake_client):
        CloudTasksBackend(client=fake_client).dispatch(_run())

        request = fake_client.create_task.call_args.args[0]
        assert request.parent == (
            "projects/expense-tracker-482807/locations/southamerica-east1/queues/ledger-default"
        )


def test_backend_for_settings_picks_cloud_tasks_when_enabled():
    from core.tasks.backends import backend_for_settings

    assert isinstance(backend_for_settings(), CloudTasksBackend)
