import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestChatMessage:
    def test_create_user_message(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="user",
            content="gastei 50 no cosmos",
        )
        assert msg.role == "user"
        assert msg.content == "gastei 50 no cosmos"
        assert msg.user == user
        assert msg.id is not None

    def test_create_assistant_message(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="assistant",
            content="Vou registrar...",
        )
        assert msg.role == "assistant"

    def test_str_representation(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            role="user",
            content="gastei 50 no cosmos pix",
        )
        result = str(msg)
        assert "user" in result
        assert "gastei 50" in result

    def test_ordering_by_created_at(self, user):
        baker.make("assistant.ChatMessage", user=user, content="first")
        baker.make("assistant.ChatMessage", user=user, content="second")
        from assistant.models import ChatMessage

        messages = list(ChatMessage.objects.filter(user=user))
        assert messages[0].content == "first"
        assert messages[1].content == "second"

    def test_metadata_nullable(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            metadata=None,
        )
        assert msg.metadata is None

    def test_metadata_stores_json(self, user):
        msg = baker.make(
            "assistant.ChatMessage",
            user=user,
            metadata={"agent": "entry", "entry_id": "abc-123"},
        )
        assert msg.metadata["agent"] == "entry"


@pytest.mark.django_db
class TestReceiptDraft:
    def test_stores_payload_and_defaults_pending(self, user):
        from assistant.models import ReceiptDraft

        chat = baker.make("assistant.ChatMessage", user=user, role="user")
        payload = {
            "store": "Lojas Americanas",
            "items": [{"description": "Soutien", "line_total": "9.99"}],
            "amount_paid": "42.16",
        }
        draft = ReceiptDraft.objects.create(user=user, chat_message=chat, payload=payload)
        draft.refresh_from_db()
        assert draft.status == "pending"
        assert draft.payload["store"] == "Lojas Americanas"
        assert draft.payload["items"][0]["line_total"] == "9.99"

    def test_can_be_marked_registered(self, user):
        from assistant.models import ReceiptDraft

        draft = ReceiptDraft.objects.create(user=user, payload={})
        draft.status = "registered"
        draft.save(update_fields=["status"])
        draft.refresh_from_db()
        assert draft.status == "registered"
