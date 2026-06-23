"""Tests for the single strong assistant_agent (Task 3 — collapse to one agent).

The assistant_agent owns ALL tools from the union of registrar + analyst + planner
+ receipt_confirm, plus the four new edit/receipt helpers. No delegation tools.
"""

import pytest
from pydantic_ai.models.test import TestModel

from assistant.agents.assistant import agents_override, assistant_agent


def _tools(agent):
    return set(agent._function_toolset.tools.keys())


def test_agent_exposes_full_toolset():
    t = _tools(assistant_agent)
    expected = {
        # write
        "register_entry", "add_category", "set_category_budget", "add_payment_method",
        "set_income", "set_systemic_amount", "update_entry", "delete_entry",
        # receipt
        "propose_receipt", "commit_receipt", "discard_receipt", "add_receipt_item",
        # read
        "get_categories", "get_payment_methods", "get_systemic_expenses", "get_expenses",
        "get_balance", "get_budget_status", "get_installments", "get_category_breakdown",
        "compare_with_previous_month", "export_monthly_report", "find_anomalies",
        "get_category_averages", "list_recent_entries",
        # plan
        "project_month_end", "get_proactive_alerts", "get_upcoming_obligations",
        "simulate_projection",
        # memory
        "check_memory", "save_memory_rule", "get_memory_rules",
    }
    missing = expected - t
    assert not missing, f"missing tools: {missing}"


def test_no_delegation_tools():
    t = _tools(assistant_agent)
    assert not any(name.startswith("delegate_") for name in t)


@pytest.mark.django_db
class TestRuns:
    @pytest.mark.anyio
    async def test_runs_under_testmodel(self, seeded_user):
        with agents_override(TestModel()):
            result = await assistant_agent.run("gastei 50 no cosmos", deps=seeded_user)
            assert result.output


@pytest.mark.django_db
class TestPendingReceiptDirective:
    """Directive must reference real receipt tools (not delegate_registro).

    Relocated from test_orchestrator.py with corrected assertions after
    build_pending_receipt_directive was updated to instruct the single agent.
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
        assert "commit_receipt" in out
        assert "MATEUS SUPERMERCADOS" in out
        assert "NUNCA diga que registrou" in out
        assert "delegate_registro" not in out

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
