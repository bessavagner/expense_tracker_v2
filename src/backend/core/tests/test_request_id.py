"""Request correlation: one ID in the header, the log line and the Sentry tag.

The point of the ID is that a user can report "it broke" and the operator can
find the exact request. That only works if the same value reaches all three.
"""

import json
import logging

import pytest

from core.log_formatting import JsonFormatter
from core.request_id import (
    get_log_context,
    get_request_id,
    new_request_id,
    set_log_context,
    set_request_id,
)


@pytest.fixture(autouse=True)
def _clean_context():
    """Reset the contextvars before every test in this module.

    Contextvars live for the whole task, and pytest runs a sync test module in
    the same task as every module before it -- any earlier test that drove a
    request through the middleware leaves its ID behind. Without this, the
    "starts empty" assertion passes alone and fails in a full-suite run, which
    is the worst kind of failure to debug.
    """
    set_request_id(None)
    set_log_context(user_id=None, household_id=None)


def test_new_request_id_is_unique_and_short():
    first, second = new_request_id(), new_request_id()
    assert first != second
    assert len(first) == 32  # uuid4 hex, no dashes — cheap to paste into a log filter


def test_context_starts_empty():
    assert get_request_id() is None
    assert get_log_context() == {"request_id": None, "user_id": None, "household_id": None}


def test_set_and_read_back():
    set_request_id("abc")
    set_log_context(user_id="u1", household_id="h1")
    assert get_request_id() == "abc"
    assert get_log_context() == {"request_id": "abc", "user_id": "u1", "household_id": "h1"}


def test_formatter_emits_single_line_json_with_severity():
    """Cloud Logging parses a JSON line and promotes `severity` to the log level."""
    set_request_id("req-1")
    set_log_context(user_id="u1", household_id="h1")
    record = logging.LogRecord("app", logging.WARNING, "f.py", 1, "algo quebrou", None, None)

    line = JsonFormatter().format(record)

    assert "\n" not in line
    payload = json.loads(line)
    assert payload["severity"] == "WARNING"
    assert payload["message"] == "algo quebrou"
    assert payload["request_id"] == "req-1"
    assert payload["user_id"] == "u1"
    assert payload["household_id"] == "h1"
    assert payload["logger"] == "app"


def test_formatter_includes_the_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("app", logging.ERROR, "f.py", 1, "falhou", None, sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_formatter_survives_unserialisable_arguments():
    """A formatter that raises takes down the log line AND the request."""

    class Opaque:
        def __repr__(self):
            return "<opaque>"

    record = logging.LogRecord("app", logging.INFO, "f.py", 1, "got %s", (Opaque(),), None)
    payload = json.loads(JsonFormatter().format(record))
    assert "<opaque>" in payload["message"]


@pytest.mark.django_db
def test_response_carries_the_request_id_header(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_each_request_gets_a_different_id(client):
    first = client.get("/healthz/").headers["X-Request-ID"]
    second = client.get("/healthz/").headers["X-Request-ID"]
    assert first != second


@pytest.mark.django_db
def test_an_inbound_request_id_is_honoured(client):
    """Cloud Run and load balancers set X-Request-ID; adopting it keeps one ID
    across the whole hop rather than minting a competing one."""
    response = client.get("/healthz/", headers={"X-Request-ID": "a" * 32})
    assert response.headers["X-Request-ID"] == "a" * 32


@pytest.mark.django_db
def test_an_absurd_inbound_id_is_replaced(client):
    """An attacker-supplied header must not become an unbounded log field."""
    response = client.get("/healthz/", headers={"X-Request-ID": "x" * 500})
    assert response.headers["X-Request-ID"] != "x" * 500
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_log_context_carries_user_and_household(logged_client, user, household):
    """The household field is what makes a log line answerable to a tenant.

    The contextvars are per-task and the sync test client runs the request in
    this task, so what the middleware set during the request is still readable
    here -- and, more to the point, still lands in a rendered log line.
    """
    logged_client.get("/healthz/")

    assert get_log_context() == {
        "request_id": get_request_id(),
        "user_id": str(user.pk),
        "household_id": str(household.pk),
    }

    record = logging.LogRecord("app", logging.INFO, "f.py", 1, "ok", None, None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["household_id"] == str(household.pk)
    assert payload["user_id"] == str(user.pk)
