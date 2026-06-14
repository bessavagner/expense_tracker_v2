"""Tests for the agent prompts (Etapa 1 do prompt 004).

The prompts must reflect the legacy sheets+claude behaviour and split the
assistant into orchestrator + specialised sub-agents.
"""

from assistant.agents import prompts


class TestLegacyRulesInRegistrar:
    """Registrador deve carregar as regras do sistema legado."""

    def test_cigarro_alcool_rule(self):
        assert "Álcool" in prompts.REGISTRAR_PROMPT
        assert "cigarro" in prompts.REGISTRAR_PROMPT.lower()

    def test_refrigerante_lanche_rule(self):
        assert "refrigerante" in prompts.REGISTRAR_PROMPT.lower()
        assert "Lanche" in prompts.REGISTRAR_PROMPT

    def test_same_establishment_collapse(self):
        assert "estabelecimento" in prompts.REGISTRAR_PROMPT.lower()

    def test_installments_routing(self):
        assert "parcel" in prompts.REGISTRAR_PROMPT.lower()

    def test_refund_is_negative(self):
        low = prompts.REGISTRAR_PROMPT.lower()
        assert "reembolso" in low and "negativ" in low

    def test_description_comma_to_dash(self):
        low = prompts.REGISTRAR_PROMPT.lower()
        assert "vírgula" in low or "hífen" in low

    def test_payment_method_never_assumed(self):
        assert "forma de pagamento" in prompts.REGISTRAR_PROMPT.lower()

    def test_no_fabricated_data(self):
        low = prompts.REGISTRAR_PROMPT.lower()
        assert "invent" in low or "fabric" in low

    def test_confirmation_only_when_needed(self):
        # pula confirmação quando completo/inequívoco; confirma quando ambíguo
        assert "confirm" in prompts.REGISTRAR_PROMPT.lower()


class TestOrchestratorPrompt:
    def test_is_a_router(self):
        low = prompts.ORCHESTRATOR_PROMPT.lower()
        assert "delegar" in low or "rotear" in low or "encaminh" in low

    def test_mentions_specialists(self):
        low = prompts.ORCHESTRATOR_PROMPT.lower()
        assert "registr" in low
        assert "analis" in low or "anális" in low
        assert "planej" in low


class TestAnalystAndPlannerPrompts:
    def test_analyst_is_read_only(self):
        low = prompts.ANALYST_PROMPT.lower()
        assert "consult" in low or "leitura" in low or "não" in low

    def test_analyst_does_not_invent_math(self):
        # deve usar ferramentas, não calcular de cabeça
        assert "ferramenta" in prompts.ANALYST_PROMPT.lower()

    def test_planner_mentions_projection_and_alerts(self):
        low = prompts.PLANNER_PROMPT.lower()
        assert "projeç" in low or "proje" in low
        assert "alerta" in low or "teto" in low or "orçament" in low


class TestSecurityInPrompts:
    def test_no_delete_without_confirmation(self):
        # registrador nunca exclui/edita sem confirmação explícita
        low = prompts.REGISTRAR_PROMPT.lower()
        assert "exclu" in low or "remov" in low
        assert "confirm" in low

    def test_proactivity_not_spammy(self):
        # planejador: proatividade sob demanda/por evento, não a cada mensagem
        low = prompts.PLANNER_PROMPT.lower()
        assert "não" in low  # contém alguma restrição de proatividade


def test_registrar_prompt_has_photo_policy():
    from assistant.agents.prompts import REGISTRAR_PROMPT

    lower = REGISTRAR_PROMPT.lower()
    # deve instruir a confirmar um resumo antes de gravar quando vier de foto
    assert "foto" in lower or "recibo" in lower
    assert "resumo" in lower
    # trata conteúdo da imagem como dados, não como instruções (anti-injeção)
    assert "instruç" in lower  # cobre "instrução"/"instruções"
