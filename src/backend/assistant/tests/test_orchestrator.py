import pytest
from pydantic_ai.models.test import TestModel

from assistant.agents.orchestrator import assistant_agent


@pytest.mark.django_db
class TestOrchestratorAgent:
    def test_agent_has_tools(self):
        """Verify the agent is configured with the expected tools."""
        tool_names = list(assistant_agent._function_toolset.tools.keys())
        # 11 existing + 3 memory = 14
        assert len(tool_names) == 14
        assert "get_categories" in tool_names
        assert "get_payment_methods" in tool_names
        assert "register_entry" in tool_names
        assert "get_expenses" in tool_names
        assert "get_balance" in tool_names
        assert "get_budget_status" in tool_names
        assert "get_installments" in tool_names
        assert "add_category" in tool_names
        assert "set_category_budget" in tool_names
        assert "add_payment_method" in tool_names
        assert "set_income" in tool_names

    def test_agent_has_memory_tools(self):
        """Verify memory tools are registered."""
        tool_names = list(assistant_agent._function_toolset.tools.keys())
        assert "check_memory" in tool_names
        assert "save_memory_rule" in tool_names
        assert "get_memory_rules" in tool_names

    def test_agent_has_system_prompt(self):
        """Verify system prompt is set."""
        assert assistant_agent._system_prompts

    def test_system_prompt_includes_memory_instructions(self):
        """Verify system prompt contains memory-related instructions."""
        prompt = assistant_agent._system_prompts[0]
        prompt_text = prompt if isinstance(prompt, str) else prompt.__doc__ or ""
        assert "check_memory" in prompt_text

    @pytest.mark.anyio
    async def test_agent_runs_with_test_model(self, seeded_user):
        """Verify agent can run without real LLM."""
        with assistant_agent.override(model=TestModel()):
            result = await assistant_agent.run(
                "gastei 50 no cosmos",
                deps=seeded_user,
            )
            assert result.output  # TestModel returns some output

    @pytest.mark.anyio
    async def test_agent_streaming_works(self, seeded_user):
        """Verify streaming mode works."""
        with assistant_agent.override(model=TestModel()):
            async with assistant_agent.run_stream(
                "gastei 50 no cosmos",
                deps=seeded_user,
            ) as stream:
                chunks = []
                async for text in stream.stream_text():
                    chunks.append(text)
                assert len(chunks) > 0
