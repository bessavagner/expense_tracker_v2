import json

import pytest
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_multipart_audio_transcribes_and_streams(
        self, logged_client, user, monkeypatch
    ):
        async def fake_transcribe(data, filename, content_type, *, client=None):
            return "mercado 80 no pix"

        monkeypatch.setattr(
            "assistant.views.transcribe_audio", fake_transcribe
        )

        audio = SimpleUploadedFile(
            "nota.webm", b"\x00\x01\x02", content_type="audio/webm"
        )
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/", data={"audio": audio}
            )
            body = consume_streaming(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert '"type": "user_text"' in body
        assert "mercado 80 no pix" in body
        assert ChatMessage.objects.filter(
            user=user, role="user", content__icontains="mercado 80"
        ).exists()
        assert ChatMessage.objects.filter(user=user, role="assistant").exists()

    def test_multipart_image_routes_to_registrar(self, logged_client, user):
        # 1x1 PNG válido (bytes mínimos)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        from assistant.agents.registrar import registrar_agent

        with registrar_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/", data={"image": image}
            )
            body = consume_streaming(response)

        assert response.status_code == 200
        assert '"type": "user_text"' in body
        assert "📷" in body
        assert ChatMessage.objects.filter(
            user=user, role="user", content__icontains="foto"
        ).exists()

    def test_multipart_rejects_two_files(self, logged_client, user):
        a = SimpleUploadedFile("n.webm", b"\x00", content_type="audio/webm")
        i = SimpleUploadedFile("r.png", b"\x00", content_type="image/png")
        response = logged_client.post(
            "/api/assistant/chat/", data={"audio": a, "image": i}
        )
        assert response.status_code == 400

    def test_multipart_rejects_bad_audio_type(self, logged_client, user):
        bad = SimpleUploadedFile("x.txt", b"\x00", content_type="text/plain")
        response = logged_client.post(
            "/api/assistant/chat/", data={"audio": bad}
        )
        assert response.status_code == 400

    def test_multipart_rejects_oversized_image(self, logged_client, user, settings):
        settings.ASSISTANT_MAX_IMAGE_MB = 0  # tudo é grande demais
        big = SimpleUploadedFile("r.png", b"\x00" * 1024, content_type="image/png")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": big}
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
