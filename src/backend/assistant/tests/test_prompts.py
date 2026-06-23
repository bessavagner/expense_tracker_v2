"""Tests for the assistant prompt (single strong agent — prompt 009).

The prompt must carry the legacy sheets+claude behaviour (now folded into the
single ASSISTANT_PROMPT) plus the analysis/planning/receipt guidance.
"""

from assistant.agents import prompts


class TestLegacyRulesInAssistant:
    """ASSISTANT_PROMPT deve carregar as regras do sistema legado."""

    def test_cigarro_alcool_rule(self):
        assert "Álcool" in prompts.ASSISTANT_PROMPT
        assert "cigarro" in prompts.ASSISTANT_PROMPT.lower()

    def test_refrigerante_lanche_rule(self):
        assert "refrigerante" in prompts.ASSISTANT_PROMPT.lower()
        assert "Lanche" in prompts.ASSISTANT_PROMPT

    def test_same_establishment_collapse(self):
        assert "estabelecimento" in prompts.ASSISTANT_PROMPT.lower()

    def test_installments_routing(self):
        assert "parcel" in prompts.ASSISTANT_PROMPT.lower()

    def test_refund_is_negative(self):
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "reembolso" in low and "negativ" in low

    def test_description_comma_to_dash(self):
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "vírgula" in low or "hífen" in low

    def test_payment_method_never_assumed(self):
        assert "forma de pagamento" in prompts.ASSISTANT_PROMPT.lower()

    def test_no_fabricated_data(self):
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "invent" in low or "fabric" in low

    def test_confirmation_only_when_needed(self):
        # pula confirmação quando completo/inequívoco; confirma quando ambíguo
        assert "confirm" in prompts.ASSISTANT_PROMPT.lower()


class TestAnalysisAndPlanningGuidance:
    """O assistente único cobre análise e planejamento via ferramentas."""

    def test_uses_tools_not_mental_math(self):
        assert "ferramenta" in prompts.ASSISTANT_PROMPT.lower()

    def test_mentions_projection_and_alerts(self):
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "projeç" in low or "proje" in low
        assert "alerta" in low or "teto" in low or "orçament" in low


class TestSecurityInPrompts:
    def test_no_delete_without_confirmation(self):
        # nunca exclui/edita sem confirmação explícita
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "exclu" in low or "remov" in low
        assert "confirm" in low

    def test_proactivity_not_spammy(self):
        # proatividade com parcimônia, não a cada mensagem
        low = prompts.ASSISTANT_PROMPT.lower()
        assert "parcim" in low


def test_assistant_prompt_has_photo_policy():
    lower = prompts.ASSISTANT_PROMPT.lower()
    # deve instruir a confirmar um resumo antes de gravar quando vier de foto
    assert "foto" in lower or "recibo" in lower
    assert "resumo" in lower
    # trata conteúdo da imagem como dados, não como instruções (anti-injeção)
    assert "instruç" in lower  # cobre "instrução"/"instruções"


class TestPhotoPolicySplitAndTable:
    """PHOTO_POLICY deve forçar split por categoria e resumo verificável."""

    def test_requires_category_split(self):
        assert "categorias diferentes" in prompts.PHOTO_POLICY
        assert "estabelecimento + categoria" in prompts.PHOTO_POLICY

    def test_requires_verifiable_table(self):
        low = prompts.PHOTO_POLICY.lower()
        assert "tabela" in low
        assert "soma" in low

    def test_forbids_zero_category_via_proration(self):
        low = prompts.PHOTO_POLICY.lower()
        assert "ratei" in low or "rateá" in low or "rateie" in low
        assert "valor pago" in low

    def test_extracts_store_name(self):
        low = prompts.PHOTO_POLICY.lower()
        assert "loja" in low

    def test_photo_policy_included_in_assistant(self):
        assert prompts.PHOTO_POLICY in prompts.ASSISTANT_PROMPT


def test_assistant_prompt_covers_all_capabilities():
    from assistant.agents.prompts import ASSISTANT_PROMPT
    p = ASSISTANT_PROMPT.lower()
    for needle in ["registr", "analis", "planej", "recibo", "memó", "confirm"]:
        assert needle in p, needle
    # edit/correct + add-item guidance present
    assert "list_recent_entries" in ASSISTANT_PROMPT
    assert "update_entry" in ASSISTANT_PROMPT
    assert "add_receipt_item" in ASSISTANT_PROMPT
