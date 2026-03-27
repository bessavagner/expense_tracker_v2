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
