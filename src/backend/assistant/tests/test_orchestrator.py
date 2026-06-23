"""Tests for the multi-agent system (Etapa 3 do prompt 004).

Architecture: orchestrator (router) delegates to specialised sub-agents
(Registrador = write, Analista/Planejador = read-only).
"""

import pytest
from pydantic_ai.models.test import TestModel

from assistant.agents.analyst import analyst_agent
from assistant.agents.orchestrator import (
    agents_override,
    assistant_agent,
    orchestrator_agent,
)
from assistant.agents.planner import planner_agent
from assistant.agents.registrar import registrar_agent

WRITE_TOOLS = {
    "register_entry",
    "add_category",
    "set_category_budget",
    "add_payment_method",
    "set_income",
    "set_systemic_amount",
    "save_memory_rule",
}


def _tools(agent):
    return set(agent._function_toolset.tools.keys())


class TestOrchestratorRouter:
    def test_assistant_agent_is_orchestrator(self):
        assert assistant_agent is orchestrator_agent

    def test_has_only_delegation_tools(self):
        tools = _tools(orchestrator_agent)
        assert tools == {"delegate_registro", "delegate_analise", "delegate_planejamento"}

    def test_system_prompt_is_router(self):
        prompt = orchestrator_agent._system_prompts[0]
        text = prompt if isinstance(prompt, str) else prompt.__doc__ or ""
        assert "delegar" in text.lower() or "delegate" in text.lower()


class TestRegistrarAgent:
    def test_has_write_tools(self):
        tools = _tools(registrar_agent)
        assert WRITE_TOOLS.issubset(tools)
        assert "register_entry" in tools

    def test_has_memory_tools(self):
        tools = _tools(registrar_agent)
        assert {"check_memory", "save_memory_rule", "get_memory_rules"}.issubset(tools)

    def test_system_prompt_has_legacy_rules(self):
        prompt = registrar_agent._system_prompts[0]
        text = prompt if isinstance(prompt, str) else prompt.__doc__ or ""
        assert "sistemático" in text
        assert "Álcool" in text  # cigarro -> Álcool legacy rule
        assert "NÃO crie" in text or "não crie" in text.lower()


class TestAnalystAgent:
    def test_has_read_tools(self):
        tools = _tools(analyst_agent)
        assert "get_expenses" in tools
        assert "get_category_breakdown" in tools
        assert "compare_with_previous_month" in tools
        assert "export_monthly_report" in tools
        assert "find_anomalies" in tools

    def test_is_read_only_no_write_tools(self):
        assert not (_tools(analyst_agent) & WRITE_TOOLS)


class TestPlannerAgent:
    def test_has_planning_tools(self):
        tools = _tools(planner_agent)
        assert "project_month_end" in tools
        assert "get_proactive_alerts" in tools
        assert "get_upcoming_obligations" in tools

    def test_is_read_only_no_write_tools(self):
        assert not (_tools(planner_agent) & WRITE_TOOLS)


@pytest.mark.django_db
class TestRunsWithTestModel:
    @pytest.mark.anyio
    async def test_orchestrator_runs(self, seeded_user):
        with agents_override(TestModel()):
            result = await assistant_agent.run("gastei 50 no cosmos", deps=seeded_user)
            assert result.output

    @pytest.mark.anyio
    async def test_streaming_works(self, seeded_user):
        with agents_override(TestModel()):
            async with assistant_agent.run_stream(
                "quanto gastei esse mês?", deps=seeded_user
            ) as stream:
                chunks = [text async for text in stream.stream_text()]
                assert len(chunks) > 0


@pytest.mark.django_db
class TestPendingReceiptDirective:
    """Confirmação de recibo de foto ('sim') volta pelo orquestrador; sem aviso
    de pendência ele não delega o registro e ainda afirma sucesso (bug do
    recibo MATEUS: draft pendente, 0 lançamentos). A diretiva força a delegação.
    """

    def _make_pending(self, user):
        from assistant.models import ReceiptDraft, ReceiptDraftStatus

        return ReceiptDraft.objects.create(
            user=user,
            payload={
                "store": "MATEUS SUPERMERCADOS",
                "amount_paid": "745.85",
                "items": [{"description": "arroz", "line_total": "10.00"}],
            },
            status=ReceiptDraftStatus.PENDING,
        )

    def test_directive_present_when_draft_pending(self, user):
        from assistant.agents.tools import build_pending_receipt_directive

        self._make_pending(user)
        out = build_pending_receipt_directive(user)
        assert "delegate_registro" in out
        assert "MATEUS SUPERMERCADOS" in out
        assert "NUNCA diga que registrou" in out

    def test_directive_empty_when_no_pending(self, user):
        from assistant.agents.tools import build_pending_receipt_directive

        assert build_pending_receipt_directive(user) == ""

    def test_directive_empty_when_already_registered(self, user):
        from assistant.agents.tools import build_pending_receipt_directive
        from assistant.models import ReceiptDraft, ReceiptDraftStatus

        ReceiptDraft.objects.create(
            user=user,
            payload={"store": "X", "items": []},
            status=ReceiptDraftStatus.REGISTERED,
        )
        assert build_pending_receipt_directive(user) == ""
