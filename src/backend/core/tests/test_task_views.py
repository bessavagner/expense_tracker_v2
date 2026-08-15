"""The dispatch view, where at-least-once delivery meets a real database.

The response code is the whole protocol between this app and Cloud Tasks, so
each test here is really asserting "and therefore Cloud Tasks will / will not
try again".
"""

import json
import uuid
from unittest import mock

import pytest
from django.test import Client
from django.urls import reverse

from core.models import TaskRun, TaskStatus
from core.tasks import auth
from core.tasks.registry import task_handler

SERVICE_ACCOUNT = "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"
AUDIENCE = "https://ledger.example.com"

CALLS: list[dict] = []
FAILURES: list[dict] = []


@task_handler("test.view.records", max_attempts=3)
def _records(payload):
    CALLS.append(payload)


@task_handler("test.view.always-fails", max_attempts=2)
def _always_fails(payload):
    FAILURES.append(payload)
    raise RuntimeError("handler exploded")


@pytest.fixture(autouse=True)
def _configured(settings):
    """Every test in this module needs the OIDC check switched on.

    Applied as a fixture rather than `override_settings` on the class:
    Django's decorator only understands SimpleTestCase subclasses, and these
    are plain pytest classes.
    """
    settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT = SERVICE_ACCOUNT
    settings.CLOUD_TASKS_AUDIENCE = AUDIENCE


@pytest.fixture(autouse=True)
def _clear():
    CALLS.clear()
    FAILURES.clear()
    yield
    CALLS.clear()
    FAILURES.clear()


@pytest.fixture
def accepted():
    """Make the OIDC check pass, so a test can be about anything else."""
    claims = {"email": SERVICE_ACCOUNT, "email_verified": True}
    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        yield


def _post(name, task_run_id):
    return Client().post(
        reverse("tasks:dispatch", args=[name]),
        data=json.dumps({"task_run_id": str(task_run_id)}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer a-token",
    )


def _run(name="test.view.records", payload=None, max_attempts=3):
    return TaskRun.objects.create(
        name=name,
        idempotency_key=f"{name}:{uuid.uuid4()}",
        payload=payload if payload is not None else {},
        max_attempts=max_attempts,
    )


@pytest.mark.django_db
class TestAuthentication:
    def test_a_request_with_no_token_is_refused(self):
        """The DoD box: handlers reject requests not carrying a valid OIDC token."""
        run = _run()

        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": str(run.pk)}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert CALLS == []

    def test_a_request_with_a_bad_token_is_refused(self):
        run = _run()

        with mock.patch.object(auth, "verify_id_token", side_effect=ValueError("bad")):
            response = _post("test.view.records", run.pk)

        assert response.status_code == 403
        assert CALLS == []

    def test_the_reason_is_not_disclosed_to_the_caller(self):
        run = _run()

        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": str(run.pk)}),
            content_type="application/json",
        )

        assert response.json() == {"error": "forbidden"}


@pytest.mark.django_db
class TestDispatch:
    def test_get_is_not_allowed(self, accepted):
        response = Client().get(reverse("tasks:dispatch", args=["test.view.records"]))

        assert response.status_code == 405

    def test_an_unregistered_name_is_a_404(self, accepted):
        """404 rather than 500: an unknown name will never become known by
        retrying, and Cloud Tasks stops on a 4xx."""
        run = _run()

        response = _post("test.view.no-such-handler", run.pk)

        assert response.status_code == 404

    def test_a_malformed_body_is_a_400(self, accepted):
        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data="not json",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer a-token",
        )

        assert response.status_code == 400

    def test_a_task_run_id_that_is_not_a_uuid_is_a_400(self, accepted):
        response = Client().post(
            reverse("tasks:dispatch", args=["test.view.records"]),
            data=json.dumps({"task_run_id": "banana"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer a-token",
        )

        assert response.status_code == 400

    def test_an_unknown_task_run_is_a_404(self, accepted):
        response = _post("test.view.records", uuid.uuid4())

        assert response.status_code == 404

    def test_a_valid_dispatch_runs_the_handler_and_returns_200(self, accepted):
        run = _run(payload={"value": 1})

        response = _post("test.view.records", run.pk)

        run.refresh_from_db()
        assert response.status_code == 200
        assert response.json() == {"status": "done"}
        assert CALLS == [{"value": 1}]
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1


@pytest.mark.django_db
class TestIdempotency:
    def test_the_same_task_delivered_twice_produces_one_result(self, accepted):
        """The DoD box: a handler invoked twice with the same payload produces
        one result. Cloud Tasks delivers at least once, so this is the normal
        case, not the exceptional one."""
        run = _run(payload={"value": 2})

        first = _post("test.view.records", run.pk)
        second = _post("test.view.records", run.pk)

        run.refresh_from_db()
        assert first.status_code == 200
        assert second.status_code == 200
        assert CALLS == [{"value": 2}]
        assert run.attempts == 1

    def test_a_run_belonging_to_another_name_is_a_404(self, accepted):
        """The name in the URL and the name on the row must agree, or a
        mis-routed task would run the wrong handler's code on this payload."""
        run = _run(name="test.view.always-fails")

        response = _post("test.view.records", run.pk)

        assert response.status_code == 404
        assert FAILURES == []


@pytest.mark.django_db
class TestRetryAndDeadLetter:
    def test_a_failure_below_the_ceiling_asks_for_a_retry(self, accepted):
        run = _run(name="test.view.always-fails", max_attempts=2)

        response = _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert response.status_code == 500
        assert run.status == TaskStatus.PENDING
        assert run.attempts == 1

    def test_the_final_failure_dead_letters_and_stops_the_retries(self, accepted):
        """The DoD box: a deliberately failed task lands in the dead-letter
        path and is visible.

        200 on the last failure is deliberate. The app owns the attempt
        ceiling; letting Cloud Tasks keep retrying past it would spend money
        re-running work we have already recorded as given up on.
        """
        run = _run(name="test.view.always-fails", max_attempts=2)

        _post("test.view.always-fails", run.pk)
        response = _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert response.status_code == 200
        assert response.json() == {"status": "dead"}
        assert run.status == TaskStatus.DEAD
        assert run.attempts == 2
        assert "RuntimeError: handler exploded" in run.last_error
        assert TaskRun.objects.filter(status=TaskStatus.DEAD).count() == 1

    def test_a_dead_lettered_task_is_not_run_again(self, accepted):
        run = _run(name="test.view.always-fails", max_attempts=2)

        _post("test.view.always-fails", run.pk)
        _post("test.view.always-fails", run.pk)
        _post("test.view.always-fails", run.pk)

        run.refresh_from_db()
        assert run.attempts == 2
        assert len(FAILURES) == 2
