import pytest
from model_bakery import baker

from accounts.resolution import household_for_user
from assistant.agents.tools import create_memory_rule, list_memory_rules, lookup_memory
from assistant.models import MemoryRule


@pytest.mark.django_db
class TestLookupMemory:
    def test_returns_matching_rules_formatted(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        result = lookup_memory(scope, "gastei 50 no cosmos")
        assert "category" in result
        assert "Alimentação" in result
        assert "auto-aplicar" in result

    def test_returns_confirm_tier(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="posto",
            field="category",
            value="Transporte",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(scope, "fui no posto")
        assert "sugerir" in result

    def test_returns_ask_tier(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="loja",
            field="category",
            value="Compras",
            confidence=0.5,
            source="inferred",
        )
        result = lookup_memory(scope, "comprei na loja")
        assert "perguntar" in result

    def test_no_matches_returns_message(self, user, scope):
        result = lookup_memory(scope, "almocei no restaurante")
        assert "nenhuma" in result.lower()

    def test_multiple_rules_all_listed(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="payment_method",
            value="Pix",
            confidence=0.8,
            source="inferred",
        )
        result = lookup_memory(scope, "gastei no cosmos")
        assert "category" in result
        assert "payment_method" in result


@pytest.mark.django_db
class TestCreateMemoryRule:
    def test_creates_new_rule(self, user, scope, household):
        result = create_memory_rule(scope, "cosmos", "category", "Alimentação")
        assert "criada" in result.lower() or "salva" in result.lower()
        rule = MemoryRule.objects.for_household(household).get(trigger="cosmos", field="category")
        assert rule.value == "Alimentação"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"

    def test_upserts_existing_rule(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=0.5,
            source="inferred",
        )
        result = create_memory_rule(scope, "cosmos", "category", "Lanche")
        assert "atualizada" in result.lower()
        rule = MemoryRule.objects.for_household(household).get(trigger="cosmos", field="category")
        assert rule.value == "Lanche"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert (
            MemoryRule.objects.for_household(household)
            .filter(trigger="cosmos", field="category")
            .count()
            == 1
        )

    def test_invalid_field_returns_error(self, user, scope):
        result = create_memory_rule(scope, "cosmos", "invalid_field", "value")
        assert "erro" in result.lower()


@pytest.mark.django_db
class TestListMemoryRules:
    def test_lists_user_rules(self, user, scope, household):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="posto",
            field="category",
            value="Transporte",
        )
        result = list_memory_rules(scope)
        assert "cosmos" in result
        assert "posto" in result

    def test_empty_returns_message(self, user, scope):
        result = list_memory_rules(scope)
        assert "nenhuma" in result.lower()

    def test_excludes_other_users(self, user, scope):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            household=household_for_user(other),
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        result = list_memory_rules(scope)
        assert "nenhuma" in result.lower()
