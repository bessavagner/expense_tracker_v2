"""`enqueue` is the only door. These tests pin what it guarantees at that door.

The eager backend is not a test double — it is the local-development backend,
and it shares `run_task_run` with the HTTP path precisely so that "what happens
on the third failure" cannot differ between a laptop and production.
"""

import pytest
from django.test import override_settings

from core.models import TaskRun, TaskStatus
from core.tasks.enqueue import PayloadTooLarge, default_idempotency_key, enqueue
from core.tasks.registry import UnknownTask, task_handler

CALLS: list[dict] = []


@task_handler("test.enqueue.records", max_attempts=3)
def _records(payload):
    CALLS.append(payload)


@task_handler("test.enqueue.always-fails", max_attempts=2)
def _always_fails(payload):
    raise RuntimeError("nope")


@pytest.fixture(autouse=True)
def _clear_calls():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.mark.django_db
class TestEnqueue:
    def test_an_unknown_name_fails_at_enqueue_time(self):
        """A typo must die in the request that made it, not in the cloud."""
        with pytest.raises(UnknownTask):
            enqueue("test.enqueue.no-such-handler", {})

    def test_it_creates_a_run_and_executes_it_eagerly(self):
        run = enqueue("test.enqueue.records", {"value": 1})

        run.refresh_from_db()
        assert CALLS == [{"value": 1}]
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1
        assert run.max_attempts == 3

    def test_the_same_work_enqueued_twice_runs_once(self):
        first = enqueue("test.enqueue.records", {"value": 2})
        second = enqueue("test.enqueue.records", {"value": 2})

        assert first.pk == second.pk
        assert CALLS == [{"value": 2}]
        assert TaskRun.objects.filter(name="test.enqueue.records").count() == 1

    def test_a_caller_supplied_key_overrides_the_content_hash(self):
        """Lets a caller say 'this rule, this value' instead of 'these bytes'."""
        first = enqueue("test.enqueue.records", {"value": 3}, idempotency_key="rule:7")
        second = enqueue("test.enqueue.records", {"value": 4}, idempotency_key="rule:7")

        assert first.pk == second.pk
        assert CALLS == [{"value": 3}]

    def test_the_content_hash_is_insensitive_to_key_order(self):
        assert default_idempotency_key("n", {"a": 1, "b": 2}) == default_idempotency_key(
            "n", {"b": 2, "a": 1}
        )

    @override_settings(TASK_PAYLOAD_MAX_BYTES=64)
    def test_an_oversized_payload_is_refused_with_an_actionable_message(self):
        """Cloud Tasks caps a task at 1 MiB and the limit cannot be raised.

        Refusing here, with the reason, is what stops someone discovering it as
        a dispatch failure in production with no idea why.
        """
        with pytest.raises(PayloadTooLarge) as excinfo:
            enqueue("test.enqueue.records", {"blob": "x" * 500})

        assert "object storage" in str(excinfo.value)
        assert not TaskRun.objects.filter(name="test.enqueue.records").exists()

    def test_a_failing_handler_below_the_ceiling_stays_pending(self):
        run = enqueue("test.enqueue.always-fails", {"n": 1})

        run.refresh_from_db()
        assert run.status == TaskStatus.PENDING
        assert run.attempts == 1
        assert "RuntimeError: nope" in run.last_error

    def test_a_failing_handler_at_the_ceiling_is_dead_lettered(self):
        run = enqueue("test.enqueue.always-fails", {"n": 2})
        from core.tasks.execution import run_task_run

        run.refresh_from_db()
        run_task_run(run)  # second and final attempt

        run.refresh_from_db()
        assert run.status == TaskStatus.DEAD
        assert run.attempts == 2

    def test_a_handler_failure_never_reaches_the_caller(self):
        """Scheduling work must not be able to break the request that did it."""
        run = enqueue("test.enqueue.always-fails", {"n": 3})

        assert run.pk is not None

    def test_it_records_the_originating_request_id(self):
        from core.request_id import set_request_id

        set_request_id("ab" * 16)
        try:
            run = enqueue("test.enqueue.records", {"value": 5})
        finally:
            set_request_id(None)

        assert run.request_id == "ab" * 16

    def test_a_done_run_is_not_re_executed(self):
        from core.tasks.execution import run_task_run

        run = enqueue("test.enqueue.records", {"value": 6})
        run.refresh_from_db()

        assert run_task_run(run) == TaskStatus.DONE
        assert CALLS == [{"value": 6}]


class TestBackendSelection:
    @override_settings(CLOUD_TASKS_ENABLED=False)
    def test_it_is_eager_when_cloud_tasks_is_off(self):
        """The local answer to open question 4: a synchronous fallback, not an
        emulator. `CLOUD_TASKS_ENABLED=0` must be a complete setup."""
        from core.tasks.backends import EagerBackend, backend_for_settings

        assert isinstance(backend_for_settings(), EagerBackend)
