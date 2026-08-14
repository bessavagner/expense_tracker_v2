"""Per-request correlation context.

Contextvars rather than thread-locals: the assistant streams over ASGI, where
one thread serves many concurrent requests and a thread-local would hand a log
line the wrong request's ID. Contextvars are per-task, which is the unit that
actually corresponds to a request here.
"""

import uuid
from contextvars import ContextVar

# 32 hex chars. Long enough not to collide, short enough to paste into a Cloud
# Logging filter by hand.
REQUEST_ID_LENGTH = 32

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("log_user_id", default=None)
_household_id: ContextVar[str | None] = ContextVar("log_household_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(value: str | None):
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_log_context(user_id=None, household_id=None) -> None:
    _user_id.set(str(user_id) if user_id is not None else None)
    _household_id.set(str(household_id) if household_id is not None else None)


def get_log_context() -> dict:
    return {
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "household_id": _household_id.get(),
    }


def sanitise_inbound(raw: str | None) -> str:
    """Adopt a caller-supplied request ID, or mint one.

    Adopting the inbound header keeps one ID across a load-balancer hop. But the
    value reaches a log field, so an unbounded or non-hex string supplied by a
    caller is replaced rather than trusted — a log field is not a place to let a
    stranger write 500 arbitrary bytes.
    """
    if not raw:
        return new_request_id()
    candidate = raw.strip()
    if len(candidate) != REQUEST_ID_LENGTH or not all(
        c in "0123456789abcdef" for c in candidate.lower()
    ):
        return new_request_id()
    return candidate.lower()
