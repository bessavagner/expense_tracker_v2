"""Item #5: o evento ``done`` do SSE sinaliza quando dados foram alterados."""

import json

import pytest
from asgiref.sync import async_to_sync
from pydantic_ai.models.test import TestModel

from assistant.agents.assistant import agents_override
from assistant.views import _run_mutated_data


class _Part:
    def __init__(self, part_kind, tool_name=None):
        self.part_kind = part_kind
        self.tool_name = tool_name


class _Msg:
    def __init__(self, parts):
        self.parts = parts


class TestRunMutatedData:
    def test_detects_mutating_tool(self):
        messages = [_Msg([_Part("tool-call", "register_entry")])]
        assert _run_mutated_data(messages) is True

    def test_detects_commit_receipt(self):
        messages = [_Msg([_Part("tool-call", "commit_receipt")])]
        assert _run_mutated_data(messages) is True

    def test_ignores_read_only_tools(self):
        messages = [
            _Msg([_Part("tool-call", "get_balance")]),
            _Msg([_Part("text")]),
        ]
        assert _run_mutated_data(messages) is False

    def test_empty(self):
        assert _run_mutated_data([]) is False

    def test_mutating_tools_are_real_writes(self):
        from assistant.views import MUTATING_TOOLS
        assert "register_entry" in MUTATING_TOOLS
        assert "commit_receipt" in MUTATING_TOOLS
        assert "update_entry" in MUTATING_TOOLS
        assert "delete_entry" in MUTATING_TOOLS
        assert "delegate_registro" not in MUTATING_TOOLS
        assert "propose_receipt" not in MUTATING_TOOLS
        assert "get_balance" not in MUTATING_TOOLS


def _consume(response):
    async def collect():
        return b"".join([c async for c in response.streaming_content]).decode()

    return async_to_sync(collect)()


@pytest.mark.django_db
class TestDoneEventDataChanged:
    def test_done_event_includes_data_changed_flag(self, logged_client, user):
        # TestModel calls every tool on the single assistant_agent, including register_entry.
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "registra um gasto"}),
                content_type="application/json",
            )
            body = _consume(response)

        done_lines = [
            json.loads(line)
            for line in body.splitlines()
            if line.strip() and json.loads(line).get("type") == "done"
        ]
        assert done_lines, "stream deve emitir um evento done"
        assert done_lines[-1]["data_changed"] is True
