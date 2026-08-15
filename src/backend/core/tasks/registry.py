"""Which names are runnable, and what runs them.

A task's *name* travels through Cloud Tasks as a URL segment, so it is the one
piece of the contract that outlives the process. Keeping the mapping in one
place is what makes a typo fail at enqueue time — inside the request that made
it — rather than as a 404 in a dispatch nobody is watching.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.utils.module_loading import autodiscover_modules


class UnknownTask(LookupError):
    """No handler is registered under this name."""


class DuplicateTask(RuntimeError):
    """Two different handlers claimed the same name."""


@dataclass(frozen=True)
class TaskDefinition:
    """A runnable name.

    ``max_attempts`` lives here rather than only on the Cloud Tasks queue
    because the queue's ceiling is shared by every task in it, and because
    Cloud Tasks has no dead-letter queue — an exhausted task is simply dropped.
    The application has to own the ceiling to be able to record the giving-up.
    """

    name: str
    handler: Callable[[dict], None]
    max_attempts: int


_REGISTRY: dict[str, TaskDefinition] = {}


def task_handler(name: str, *, max_attempts: int = 5):
    """Register ``name`` as runnable, and return the function unchanged.

    Unchanged on purpose: the handler stays an ordinary function, so a test can
    call it directly without going anywhere near HTTP or a queue.
    """

    def decorator(func):
        existing = _REGISTRY.get(name)
        if existing is not None and existing.handler is not func:
            raise DuplicateTask(
                f"Task '{name}' is already registered to "
                f"{existing.handler.__module__}.{existing.handler.__qualname__}."
            )
        _REGISTRY[name] = TaskDefinition(name=name, handler=func, max_attempts=max_attempts)
        return func

    return decorator


def get_task(name: str) -> TaskDefinition:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownTask(name) from None


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


def autodiscover() -> None:
    """Import every app's ``tasks`` module, so decorators have run.

    Same mechanism Django's admin uses, and for the same reason: registration
    by import side effect only works if something guarantees the import.
    """
    autodiscover_modules("tasks")
