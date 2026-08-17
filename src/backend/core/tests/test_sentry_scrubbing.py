"""What the error tracker actually receives, checked against what we claim.

`docs/architecture/data-inventory.md` and the privacy notice both say Sentry
gets the shape of a failure and never its contents. `core.observability` was
built to make that true (ADR-005). This file is the difference between "was
built to" and "does".

The events below are hand-built in the shape the SDK emits, so no network and
no `sentry_sdk.init` are involved: `scrub_event` is a pure function, which is
exactly why it was written that way.
"""

import json

from core.observability import scrub_event, sentry_settings
from core.privacy.subprocessors import SUBPROCESSORS

#: The things this test hunts for in a scrubbed payload. Each one is a real
#: category of content from this product, written the way it would actually
#: appear — a chat message, an entry description, a receipt total, a session
#: cookie, an API key.
SECRETS = [
    "Comprei remédio na Pague Menos e paguei 87,43",
    "Salário da Amanda",
    "sessionid=abc123",
    "sk-proj-realkeydonotship",
    "vagner@example.com",
]


def an_event_carrying_everything() -> dict:
    """An event in the shape sentry-sdk builds for a Django request failure."""
    return {
        "level": "error",
        "request": {
            "url": "https://ledger.example.com/entries/",
            "method": "POST",
            "query_string": "month=2026-08",
            "data": {"description": SECRETS[0], "amount": "87.43"},
            "cookies": {"sessionid": "abc123"},
            "headers": {"Authorization": "Bearer sk-proj-realkeydonotship"},
            "env": {"REMOTE_ADDR": "203.0.113.7"},
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "invalid literal",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "finances/views/entries.py",
                                "lineno": 361,
                                "function": "post",
                                "vars": {
                                    "description": SECRETS[0],
                                    "income_name": SECRETS[1],
                                    "cookie": SECRETS[2],
                                    "api_key": SECRETS[3],
                                    "user": SECRETS[4],
                                },
                            }
                        ]
                    },
                }
            ]
        },
        "extra": {"chat_message": SECRETS[0], "user_email": SECRETS[4]},
        "breadcrumbs": {
            "values": [
                {
                    "category": "query",
                    "message": "SELECT",
                    # Not a query — a string in the shape sentry-sdk's SQL
                    # breadcrumb carries, which is precisely how a description
                    # reaches the error tracker if the scrubber misses it.
                    "data": {
                        "sql": f"INSERT INTO entry (description) VALUES ('{SECRETS[0]}')"  # noqa: S608
                    },
                }
            ]
        },
    }


class TestNothingWeCallPrivateSurvives:
    def test_no_piece_of_user_content_is_anywhere_in_the_scrubbed_event(self):
        """One assertion over the whole serialized payload rather than one per
        key. A scrubber that misses a nesting level fails here even if every
        individual key it knows about is clean."""
        scrubbed = json.dumps(scrub_event(an_event_carrying_everything(), {}))
        leaked = [secret for secret in SECRETS if secret in scrubbed]
        assert not leaked, f"these reached the error tracker: {leaked}"

    def test_the_request_body_cookies_headers_and_env_are_gone(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        request = scrubbed["request"]
        for key in ("data", "cookies", "headers", "env"):
            assert key not in request

    def test_stack_frame_locals_are_gone(self):
        """The real leak path: the variable holding a chat message lives in the
        frame that raised."""
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert "vars" not in frame

    def test_extra_and_breadcrumb_data_are_gone(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        assert "extra" not in scrubbed
        assert "data" not in scrubbed["breadcrumbs"]["values"][0]


class TestTheEventIsStillUseful:
    def test_the_url_the_method_and_the_query_string_survive(self):
        """A scrubbed event nobody can locate is as useless as no event."""
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        assert scrubbed["request"]["url"].endswith("/entries/")
        assert scrubbed["request"]["method"] == "POST"
        assert scrubbed["request"]["query_string"] == "month=2026-08"

    def test_the_exception_type_the_file_and_the_line_survive(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
        assert frame["filename"] == "finances/views/entries.py"
        assert frame["lineno"] == 361


class TestTheConfigurationItself:
    def test_default_pii_is_off(self):
        """`send_default_pii=True` attaches request bodies, cookies and user
        identifiers wholesale — it would defeat the scrubber upstream of it."""
        config = sentry_settings({"SENTRY_DSN": "https://k@o0.ingest.sentry.io/1"})
        assert config["send_default_pii"] is False

    def test_the_scrubber_is_actually_wired_as_before_send(self):
        config = sentry_settings({"SENTRY_DSN": "https://k@o0.ingest.sentry.io/1"})
        assert config["before_send"] is scrub_event

    def test_no_dsn_means_nothing_is_transmitted_at_all(self):
        """The local-development and CI path, and it must transmit nothing."""
        assert sentry_settings({}) is None
        assert sentry_settings({"SENTRY_DSN": "   "}) is None

    def test_the_scrubber_never_raises_on_a_malformed_event(self):
        """It runs on every event. An exception here drops the event silently
        and the failure it described is lost twice over."""
        for weird in ({}, {"request": "not-a-dict"}, {"exception": []}, {"breadcrumbs": None}):
            scrub_event(weird, {})


class TestTheInventoryDocumentIsAContract:
    def test_it_exists(self):
        from pathlib import Path

        doc = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "data-inventory.md"
        assert doc.is_file()

    def test_every_sub_processor_is_documented(self):
        """Same mechanism as `core/tests/test_metrics_doc.py`: the document is
        only a contract if something forces it to keep up."""
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[4] / "docs" / "architecture" / "data-inventory.md"
        ).read_text(encoding="utf-8")
        missing = [p.name for p in SUBPROCESSORS if p.name not in doc]
        assert not missing, f"undocumented sub-processors: {missing}"

    def test_the_document_records_what_sentry_is_verified_not_to_receive(self):
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[4] / "docs" / "architecture" / "data-inventory.md"
        ).read_text(encoding="utf-8")
        assert "test_sentry_scrubbing.py" in doc
