import pytest
from model_bakery import baker

from assistant.agents.memory import AUTO_APPLY, CONFIRM_APPLY, find_matching_rules


@pytest.mark.django_db
class TestConfidenceConstants:
    def test_auto_apply_threshold(self):
        assert AUTO_APPLY == 0.9

    def test_confirm_apply_threshold(self):
        assert CONFIRM_APPLY == 0.7


@pytest.mark.django_db
class TestFindMatchingRules:
    def test_matches_case_insensitive(self, user, household, scope):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(scope, "Gastei 50 no COSMOS")
        assert len(rules) == 1
        assert rules[0].value == "Alimentação"

    def test_matches_substring(self, user, household, scope):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(scope, "fui no supermercado cosmos comprar coisas")
        assert len(rules) == 1

    def test_no_match_returns_empty(self, user, household, scope):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(scope, "almocei no restaurante")
        assert len(rules) == 0

    def test_multiple_rules_match(self, user, household, scope):
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
            trigger="cosmos",
            field="description",
            value="Supermercado Cosmos",
        )
        rules = find_matching_rules(scope, "gastei 80 no cosmos")
        assert len(rules) == 2
        fields = {r.field for r in rules}
        assert fields == {"category", "description"}

    def test_updates_last_used_at(self, user, household, scope):
        rule = baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        original_last_used = rule.last_used_at
        find_matching_rules(scope, "gastei 50 no cosmos")
        rule.refresh_from_db()
        assert rule.last_used_at >= original_last_used

    def test_does_not_leak_other_households_rules(
        self, user, household, scope, other_user, other_household
    ):
        baker.make(
            "assistant.MemoryRule",
            household=other_household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rules = find_matching_rules(scope, "gastei 50 no cosmos")
        assert len(rules) == 0

    def test_unmatched_rules_not_updated(self, user, household, scope):
        rule = baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        original_last_used = rule.last_used_at
        find_matching_rules(scope, "almocei no restaurante")
        rule.refresh_from_db()
        assert rule.last_used_at == original_last_used
