"""The registry is the contract between an enqueue call and the code that runs.

A name travels through Cloud Tasks as a URL segment, so it outlives the
process. These tests pin the two failures that matter: a typo must be loud, and
two handlers must never quietly share a name.
"""

import pytest

from core.tasks.registry import (
    DuplicateTask,
    UnknownTask,
    get_task,
    registered_names,
    task_handler,
)


def test_registered_handler_is_retrievable_by_name():
    @task_handler("test.retrievable", max_attempts=3)
    def handler(payload):
        return payload

    definition = get_task("test.retrievable")

    assert definition.name == "test.retrievable"
    assert definition.handler is handler
    assert definition.max_attempts == 3


def test_decorator_returns_the_function_unchanged():
    """The handler stays directly callable, so a test can invoke it plainly."""

    @task_handler("test.unchanged")
    def handler(payload):
        return payload["x"]

    assert handler({"x": 7}) == 7


def test_default_max_attempts_is_five():
    @task_handler("test.default-attempts")
    def handler(payload):
        pass

    assert get_task("test.default-attempts").max_attempts == 5


def test_unknown_name_raises():
    with pytest.raises(UnknownTask):
        get_task("test.never-registered")


def test_two_handlers_cannot_claim_one_name():
    @task_handler("test.contested")
    def first(payload):
        pass

    with pytest.raises(DuplicateTask):

        @task_handler("test.contested")
        def second(payload):
            pass


def test_registered_names_are_sorted():
    @task_handler("test.zzz")
    def last(payload):
        pass

    @task_handler("test.aaa")
    def first(payload):
        pass

    names = registered_names()

    assert names.index("test.aaa") < names.index("test.zzz")


@pytest.mark.django_db
class TestTaskRun:
    """The durable record. Everything an operator needs is on this row."""

    def test_a_new_run_starts_pending_with_no_attempts(self):
        from core.models import TaskRun, TaskStatus

        run = TaskRun.objects.create(
            name="test.model",
            idempotency_key="test.model:1",
            payload={"a": 1},
            max_attempts=4,
        )

        assert run.status == TaskStatus.PENDING
        assert run.attempts == 0
        assert run.last_error == ""
        assert run.request_id == ""

    def test_the_idempotency_key_is_unique(self):
        from django.db import IntegrityError

        from core.models import TaskRun

        TaskRun.objects.create(
            name="test.model", idempotency_key="test.model:dup", payload={}, max_attempts=4
        )

        with pytest.raises(IntegrityError):
            TaskRun.objects.create(
                name="test.model", idempotency_key="test.model:dup", payload={}, max_attempts=4
            )

    def test_str_shows_the_attempt_budget(self):
        from core.models import TaskRun

        run = TaskRun.objects.create(
            name="test.model",
            idempotency_key="test.model:str",
            payload={},
            max_attempts=4,
            attempts=2,
        )

        assert str(run) == "test.model (pending, 2/4)"
