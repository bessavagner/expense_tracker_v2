"""Tests for current-date context injection (fix: agente gravava ano errado).

Root cause: os prompts mandavam "use hoje" mas nenhum agente recebia a data
atual, então o modelo barato (gpt-4o-mini, cutoff ~2023) chutava o ano 2023 e
o lançamento ia para um billing_month invisível no mês corrente.
"""

from django.utils import timezone

from assistant.agents.analyst import analyst_agent
from assistant.agents.orchestrator import orchestrator_agent
from assistant.agents.planner import planner_agent
from assistant.agents.prompts import build_date_instructions
from assistant.agents.registrar import registrar_agent


class TestBuildDateInstructions:
    def test_contains_today_iso(self):
        today = timezone.localdate()
        text = build_date_instructions()
        assert today.isoformat() in text

    def test_contains_current_year(self):
        today = timezone.localdate()
        text = build_date_instructions()
        assert str(today.year) in text

    def test_guides_use_of_current_year(self):
        text = build_date_instructions().lower()
        assert "ano" in text


class TestAgentsHaveDateInstructions:
    def test_orchestrator_has_dynamic_instructions(self):
        assert len(orchestrator_agent._instructions) >= 1

    def test_registrar_has_dynamic_instructions(self):
        assert len(registrar_agent._instructions) >= 1

    def test_analyst_has_dynamic_instructions(self):
        assert len(analyst_agent._instructions) >= 1

    def test_planner_has_dynamic_instructions(self):
        assert len(planner_agent._instructions) >= 1
