import pytest
from model_bakery import baker

from assistant.agents.tools import create_memory_rule, list_memory_rules, lookup_memory
from assistant.models import MemoryRule


@pytest.mark.django_db
class TestLookupMemory:
    def test_returns_matching_rules_formatted(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        result = lookup_memory(user, "gastei 50 no cosmos")
        assert "category" in result
        assert "Alimentação" in result
        assert "auto-aplicar" in result

    def test_returns_confirm_tier(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="posto",
            field="category",
            value="Transporte",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(user, "fui no posto")
        assert "sugerir" in result

    def test_returns_ask_tier(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="loja",
            field="category",
            value="Compras",
            confidence=0.5,
            source="inferred",
        )
        result = lookup_memory(user, "comprei na loja")
        assert "perguntar" in result

    def test_no_matches_returns_message(self, user):
        result = lookup_memory(user, "almocei no restaurante")
        assert "nenhuma" in result.lower()

    def test_multiple_rules_all_listed(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="payment_method",
            value="Pix",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(user, "gastei no cosmos")
        assert "category" in result
        assert "payment_method" in result


@pytest.mark.django_db
class TestCreateMemoryRule:
    def test_creates_new_rule(self, user):
        result = create_memory_rule(user, "cosmos", "category", "Alimentação")
        assert "criada" in result.lower() or "salva" in result.lower()
        rule = MemoryRule.objects.get(user=user, trigger="cosmos", field="category")
        assert rule.value == "Alimentação"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"

    def test_upserts_existing_rule(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=0.5,
            source="inferred",
        )
        result = create_memory_rule(user, "cosmos", "category", "Lanche")
        assert "atualizada" in result.lower()
        rule = MemoryRule.objects.get(user=user, trigger="cosmos", field="category")
        assert rule.value == "Lanche"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert MemoryRule.objects.filter(user=user, trigger="cosmos", field="category").count() == 1

    def test_invalid_field_returns_error(self, user):
        result = create_memory_rule(user, "cosmos", "invalid_field", "value")
        assert "erro" in result.lower()


@pytest.mark.django_db
class TestListMemoryRules:
    def test_lists_user_rules(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="posto",
            field="category",
            value="Transporte",
        )
        result = list_memory_rules(user)
        assert "cosmos" in result
        assert "posto" in result

    def test_empty_returns_message(self, user):
        result = list_memory_rules(user)
        assert "nenhuma" in result.lower()

    def test_excludes_other_users(self, user):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            user=other,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        result = list_memory_rules(user)
        assert "nenhuma" in result.lower()
