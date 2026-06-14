import json

import pytest
from asgiref.sync import async_to_sync
from django.test import Client
from model_bakery import baker
from pydantic_ai.models.test import TestModel

from assistant.agents.orchestrator import agents_override
from assistant.models import ChatMessage


def consume_streaming(response):
    """Consume a StreamingHttpResponse that may have an async generator."""
    content = response.streaming_content
    if hasattr(content, "__anext__"):
        # async generator — use async_to_sync to stay within the same thread/DB context

        async def collect():
            chunks = []
            async for chunk in content:
                chunks.append(chunk)
            return b"".join(chunks)

        return async_to_sync(collect)().decode()
    else:
        return b"".join(content).decode()


@pytest.mark.django_db
class TestChatEndpoint:
    def test_post_creates_user_message(self, logged_client, user):
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        assert ChatMessage.objects.filter(user=user, role="user").exists()

    def test_post_returns_sse_content_type(self, logged_client, user):
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response["Content-Type"] == "text/event-stream"

    def test_post_creates_assistant_message(self, logged_client, user):
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            # Consume the streaming response (may be async generator in Django 6)
            consume_streaming(response)
        assert ChatMessage.objects.filter(user=user, role="assistant").exists()

    def test_post_unauthenticated(self):
        client = Client()
        response = client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_post_empty_message(self, logged_client, user):
        response = logged_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": ""}),
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestHistoryEndpoint:
    def test_returns_messages(self, logged_client, user):
        baker.make("assistant.ChatMessage", user=user, role="user", content="oi")
        baker.make("assistant.ChatMessage", user=user, role="assistant", content="olá!")
        response = logged_client.get("/api/assistant/history/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_filters_by_user(self, logged_client, user):
        other = baker.make("core.CustomUser")
        baker.make("assistant.ChatMessage", user=user, content="mine")
        baker.make("assistant.ChatMessage", user=other, content="theirs")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "mine"

    def test_limits_to_50(self, logged_client, user):
        for i in range(60):
            baker.make("assistant.ChatMessage", user=user, content=f"msg {i}")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 50

    def test_unauthenticated(self):
        client = Client()
        response = client.get("/api/assistant/history/")
        assert response.status_code == 403
