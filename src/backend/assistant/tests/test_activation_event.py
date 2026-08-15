"""Activation is the first confirmed receipt — see docs/architecture/activation-event.md."""

import pytest
from model_bakery import baker

from assistant.agents.scope import AgentScope
from assistant.agents.tools import commit_receipt, create_entry
from assistant.models import ReceiptDraftStatus
from core.events import EventName
from core.models import ProductEvent


@pytest.fixture
def scope(household, user):
    return AgentScope(household=household, user=user)


@pytest.fixture
def category(household, user):
    return baker.make("finances.Category", household=household, name="Alimentação", created_by=user)


@pytest.fixture
def payment_method(household, user):
    return baker.make(
        "finances.PaymentMethod", household=household, name="Pix", type="pix", created_by=user
    )


def _pending_draft(household, user, category, payment_method):
    """A draft whose plan is already resolved, so commit_receipt can be called alone."""
    return baker.make(
        "assistant.ReceiptDraft",
        household=household,
        created_by=user,
        status=ReceiptDraftStatus.PENDING,
        payload={
            "store": "Mercadinho",
            "plan": {
                "date": "2026-08-15",
                "store": "Mercadinho",
                "payment_method_id": str(payment_method.id),
                "payment_method_name": payment_method.name,
                "table": "-",
                "lines": [
                    {
                        "category_id": str(category.id),
                        "category_name": category.name,
                        "description": "compras",
                        "amount": "42.00",
                    }
                ],
            },
        },
    )


@pytest.mark.django_db
class TestActivation:
    def test_the_first_confirmed_receipt_activates_the_household(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)

        commit_receipt(scope)

        assert (
            ProductEvent.objects.for_household(household).filter(name=EventName.ACTIVATED).count()
            == 1
        )

    def test_a_second_receipt_does_not_activate_again(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)
        commit_receipt(scope)
        _pending_draft(household, user, category, payment_method)
        commit_receipt(scope)

        assert (
            ProductEvent.objects.for_household(household).filter(name=EventName.ACTIVATED).count()
            == 1
        )

    def test_a_receipt_with_no_plan_does_not_activate(self, scope, household, user):
        baker.make(
            "assistant.ReceiptDraft",
            household=household,
            created_by=user,
            status=ReceiptDraftStatus.PENDING,
            payload={"store": "X"},
        )

        commit_receipt(scope)

        assert (
            not ProductEvent.objects.for_household(household)
            .filter(name=EventName.ACTIVATED)
            .exists()
        )

    def test_confirming_a_receipt_also_counts_as_the_first_ai_entry(
        self, scope, household, user, category, payment_method
    ):
        _pending_draft(household, user, category, payment_method)

        commit_receipt(scope)

        assert (
            ProductEvent.objects.for_household(household)
            .filter(name=EventName.FIRST_AI_ENTRY)
            .count()
            == 1
        )


@pytest.mark.django_db
class TestFirstAiEntry:
    def test_a_chat_captured_entry_emits_first_ai_entry(
        self, scope, household, category, payment_method
    ):
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")

        assert (
            ProductEvent.objects.for_household(household)
            .filter(name=EventName.FIRST_AI_ENTRY)
            .count()
            == 1
        )

    def test_a_chat_captured_entry_does_not_activate(
        self, scope, household, category, payment_method
    ):
        """Activation is the wedge, not any entry. E11 S11-1 is explicit about this."""
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")

        assert (
            not ProductEvent.objects.for_household(household)
            .filter(name=EventName.ACTIVATED)
            .exists()
        )

    def test_a_rejected_entry_emits_nothing(self, scope, household, payment_method):
        result = create_entry(scope, "2026-08-15", "45.00", "x", "Inexistente", "Pix")

        assert result.startswith("Erro:")
        assert ProductEvent.objects.for_household(household).count() == 0

    def test_the_second_ai_entry_does_not_re_emit(self, scope, household, category, payment_method):
        create_entry(scope, "2026-08-15", "45.00", "mercado", "Alimentação", "Pix")
        create_entry(scope, "2026-08-16", "12.00", "pão", "Alimentação", "Pix")

        assert (
            ProductEvent.objects.for_household(household)
            .filter(name=EventName.FIRST_AI_ENTRY)
            .count()
            == 1
        )

    def test_the_event_carries_no_user_content(self, scope, household, category, payment_method):
        """Constraint 11: metadata holds counts and enum values, never descriptions."""
        create_entry(scope, "2026-08-15", "45.00", "farmácia do bairro", "Alimentação", "Pix")

        event = ProductEvent.objects.for_household(household).get(name=EventName.FIRST_AI_ENTRY)
        assert "farmácia" not in str(event.metadata)
        assert event.metadata == {"source": "chat"}
