"""Replaying a task that gave up.

Cloud Tasks has no replay: once it has exhausted a task, the task is gone. The
record that survives is the TaskRun row, so replaying means enqueuing the same
work again — as a NEW run, so the failure it replaces stays on the record.
"""

import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import TaskRun, TaskStatus
from core.tasks.registry import task_handler

REPLAYED: list[dict] = []


@task_handler("test.replay.records", max_attempts=3)
def _records(payload):
    REPLAYED.append(payload)


@pytest.fixture(autouse=True)
def _clear():
    REPLAYED.clear()
    yield
    REPLAYED.clear()


def _dead(**extra):
    return TaskRun.objects.create(
        name="test.replay.records",
        idempotency_key=f"test.replay.records:{uuid.uuid4()}",
        payload={"value": 9},
        status=TaskStatus.DEAD,
        attempts=3,
        max_attempts=3,
        **extra,
    )


@pytest.mark.django_db
class TestReplayTask:
    def test_it_re_enqueues_a_dead_lettered_task(self):
        dead = _dead()

        call_command("replay_task", str(dead.pk))

        assert REPLAYED == [{"value": 9}]
        assert TaskRun.objects.count() == 2

    def test_the_original_failure_stays_on_the_record(self):
        """Replaying must not overwrite the evidence of what went wrong."""
        dead = _dead()

        call_command("replay_task", str(dead.pk))

        dead.refresh_from_db()
        assert dead.status == TaskStatus.DEAD
        assert dead.attempts == 3

    def test_it_refuses_a_task_that_has_not_given_up(self):
        run = TaskRun.objects.create(
            name="test.replay.records",
            idempotency_key="test.replay.records:pending",
            payload={},
            max_attempts=3,
        )

        with pytest.raises(CommandError, match="not dead-lettered"):
            call_command("replay_task", str(run.pk))

        assert REPLAYED == []

    def test_force_replays_a_task_that_has_not_given_up(self):
        run = TaskRun.objects.create(
            name="test.replay.records",
            idempotency_key="test.replay.records:forced",
            payload={"value": 10},
            max_attempts=3,
        )

        call_command("replay_task", str(run.pk), "--force")

        assert REPLAYED == [{"value": 10}]

    def test_an_unknown_id_is_a_clear_error(self):
        with pytest.raises(CommandError, match="No TaskRun"):
            call_command("replay_task", str(uuid.uuid4()))

    def test_a_malformed_id_is_a_clear_error(self):
        with pytest.raises(CommandError, match="No TaskRun"):
            call_command("replay_task", "banana")

    def test_a_double_typed_command_replays_once(self):
        """The replay key is (task_run, attempts), so running the command twice
        for the same failure is deduplicated — while a task that failed *again*
        later replays as a genuinely new run."""
        dead = _dead()

        call_command("replay_task", str(dead.pk))
        call_command("replay_task", str(dead.pk))

        # Two rows total: the original dead one, and one replay.
        assert TaskRun.objects.count() == 2
        assert REPLAYED == [{"value": 9}]
