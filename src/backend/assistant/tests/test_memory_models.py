import pytest
from django.db import IntegrityError
from django.utils import timezone
from model_bakery import baker


@pytest.mark.django_db
class TestMemoryRule:
    def test_create_memory_rule(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=1.0,
            source="user_correction",
        )
        assert rule.trigger == "cosmos"
        assert rule.field == "category"
        assert rule.value == "Alimentação"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert rule.id is not None
        assert rule.created_at is not None
        assert rule.last_used_at is not None

    def test_unique_constraint_user_trigger_field(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        with pytest.raises(IntegrityError):
            baker.make(
                "assistant.MemoryRule",
                user=user,
                trigger="cosmos",
                field="category",
                value="Lanche",
            )

    def test_same_trigger_different_fields_allowed(self, user):
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rule2 = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="description",
            value="Supermercado Cosmos",
        )
        assert rule2.id is not None

    def test_same_trigger_different_users_allowed(self, user):
        other = baker.make("core.CustomUser")
        baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        rule2 = baker.make(
            "assistant.MemoryRule",
            user=other,
            trigger="cosmos",
            field="category",
            value="Lanche",
        )
        assert rule2.id is not None

    def test_upsert_via_update_or_create(self, user):
        from assistant.models import MemoryRule

        MemoryRule.objects.create(
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            confidence=0.8,
            source="inferred",
        )
        rule, created = MemoryRule.objects.update_or_create(
            user=user,
            trigger="cosmos",
            field="category",
            defaults={"value": "Lanche", "confidence": 1.0, "source": "user_correction"},
        )
        assert not created
        assert rule.value == "Lanche"
        assert rule.confidence == 1.0
        assert rule.source == "user_correction"
        assert MemoryRule.objects.filter(user=user, trigger="cosmos", field="category").count() == 1

    def test_str_representation(self, user):
        rule = baker.make(
            "assistant.MemoryRule",
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
        )
        result = str(rule)
        assert "cosmos" in result
        assert "category" in result
        assert "Alimentação" in result

    def test_default_confidence_is_one(self, user):
        from assistant.models import MemoryRule

        rule = MemoryRule.objects.create(
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source="user_correction",
        )
        assert rule.confidence == 1.0

    def test_last_used_at_can_be_updated(self, user):
        from assistant.models import MemoryRule

        rule = MemoryRule.objects.create(
            user=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source="user_correction",
        )
        original = rule.last_used_at
        new_time = timezone.now()
        rule.last_used_at = new_time
        rule.save(update_fields=["last_used_at"])
        rule.refresh_from_db()
        assert rule.last_used_at >= original
