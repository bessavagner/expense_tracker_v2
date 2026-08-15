"""Deferred work: how it is scheduled, and how it comes back.

The public surface is deliberately two names. Everything else in this package
is internal, so that the payload ceiling, the idempotency key and the backend
choice cannot be bypassed by importing something one layer down.
"""

from core.tasks.enqueue import enqueue
from core.tasks.registry import task_handler

__all__ = ["enqueue", "task_handler"]
