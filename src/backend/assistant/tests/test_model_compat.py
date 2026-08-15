"""Provider quirks that would otherwise 400 a tool-calling request.

Every expectation here was measured against the live provider on 2026-08-14,
not inferred from documentation — see `docs/eval-dataset.md` § Provider quirks.
A wrong entry does not degrade gracefully: it 400s every receipt read.
"""

import pytest

from assistant.agents.model_compat import settings_for


class TestOpenAIChatCompletions:
    """gpt-5.6 rejects `reasoning_effort` alongside function tools on /v1/chat."""

    def test_gpt_5_6_disables_reasoning_effort(self):
        assert settings_for("openai:gpt-5.6-terra") == {"openai_reasoning_effort": "none"}

    def test_every_gpt_5_6_sibling_is_covered(self):
        for name in ("openai:gpt-5.6-luna", "openai:gpt-5.6-sol"):
            assert settings_for(name) == {"openai_reasoning_effort": "none"}, name

    def test_gpt_5_4_is_left_alone(self):
        """It accepts the combination today and scores 0.97. Do not touch it."""
        assert settings_for("openai:gpt-5.4") is None

    def test_the_responses_api_needs_no_quirk(self):
        """/v1/responses accepts function tools with reasoning left ON."""
        assert settings_for("openai-responses:gpt-5.6-terra") is None


class TestOpenRouter:
    """Alibaba refuses `tool_choice: required` while the model is in thinking mode."""

    def test_qwen_reasoning_is_disabled(self):
        assert settings_for("openrouter:qwen/qwen3.7-flash") == {
            "openrouter_reasoning": {"enabled": False}
        }

    def test_other_openrouter_models_are_left_alone(self):
        assert settings_for("openrouter:nvidia/nemotron-3-super-120b-a12b:free") is None


class TestTheQuirkReachesTheProvider:
    """A correct table nobody consults is worth nothing — assert the wiring."""

    @pytest.mark.anyio
    async def test_extract_receipt_passes_the_settings_through(self, monkeypatch):
        from assistant.agents import extraction

        seen = {}

        class _Result:
            output = "extraction"

            def usage(self):
                return None

        async def fake_run(prompt, **kwargs):
            seen.update(kwargs)
            return _Result()

        monkeypatch.setattr(extraction.extraction_agent, "run", fake_run)
        await extraction.extract_receipt([(b"x", "image/jpeg")], model="openai:gpt-5.6-terra")

        assert seen["model_settings"] == {"openai_reasoning_effort": "none"}

    @pytest.mark.anyio
    async def test_the_configured_vision_model_is_what_gets_matched(self, monkeypatch, settings):
        """`model=None` means "run LLM_VISION_MODEL" — match on that, not None."""
        from assistant.agents import extraction

        seen = {}

        class _Result:
            output = "extraction"

            def usage(self):
                return None

        async def fake_run(prompt, **kwargs):
            seen.update(kwargs)
            return _Result()

        settings.LLM_VISION_MODEL = "openai:gpt-5.6-terra"
        monkeypatch.setattr(extraction.extraction_agent, "run", fake_run)
        await extraction.extract_receipt([(b"x", "image/jpeg")])

        assert seen["model_settings"] == {"openai_reasoning_effort": "none"}


class TestTheFallbackGetsItsOwnQuirks:
    """The Essential tier falls back across providers, so quirks differ per attempt."""

    def test_each_attempt_is_matched_on_its_own_model(self, scope):
        from assistant.tests.fakes import FakeAgent, FakeStream
        from assistant.tests.test_views import consume_streaming
        from assistant.views import _sse_response

        agent = FakeAgent(
            {
                "openai:gpt-5.6-terra": FakeStream(["nope"], fail_after=0),
                "openrouter:qwen/qwen3.7-flash": FakeStream(["ok"]),
            }
        )
        consume_streaming(
            _sse_response(
                scope,
                agent,
                "oi",
                message_history=None,
                model="openai:gpt-5.6-terra",
                fallback_model="openrouter:qwen/qwen3.7-flash",
            )
        )

        assert agent.settings == [
            {"openai_reasoning_effort": "none"},
            {"openrouter_reasoning": {"enabled": False}},
        ]


class TestFallback:
    def test_an_unknown_model_gets_no_settings(self):
        assert settings_for("anthropic:claude-sonnet-5") is None

    def test_a_model_instance_is_not_a_string_and_is_ignored(self):
        """The harness passes a TestModel object through the same seam."""

        class Fake:
            pass

        assert settings_for(Fake()) is None

    def test_none_is_tolerated(self):
        """`extract_receipt(model=None)` means 'run the configured model'."""
        assert settings_for(None) is None
