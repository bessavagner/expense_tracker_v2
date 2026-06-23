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

    def test_multipart_image_routes_to_receipt_confirm(self, logged_client, user):
        # 1x1 PNG válido (bytes mínimos)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        from assistant.agents.extraction import extraction_agent
        from assistant.agents.receipt_confirm import receipt_confirm_agent

        with (
            extraction_agent.override(model=TestModel()),
            receipt_confirm_agent.override(model=TestModel()),
        ):
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

    def test_image_creates_receipt_draft(self, logged_client, user):
        """Fase 1: a foto gera um ReceiptDraft persistido com a extração."""
        from assistant.agents.extraction import extraction_agent
        from assistant.agents.receipt_confirm import receipt_confirm_agent
        from assistant.models import ReceiptDraft

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            receipt_confirm_agent.override(model=TestModel()),
        ):
            response = logged_client.post(
                "/api/assistant/chat/", data={"image": image}
            )
            consume_streaming(response)

        assert response.status_code == 200
        # TestModel calls all tools including discard_receipt, so the draft may
        # transition pending → discarded; assert creation happened (any status).
        assert ReceiptDraft.objects.filter(user=user).exists()

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

    def test_multipart_accepts_audio_with_codecs_param(
        self, logged_client, user, monkeypatch
    ):
        """MediaRecorder envia content_type 'audio/webm;codecs=opus' — o
        parâmetro de codec não pode fazer a validação rejeitar (era 400 →
        'Erro de conexão' no widget)."""

        async def fake_transcribe(data, filename, content_type, *, client=None):
            return "mercado 80 no pix"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        audio = SimpleUploadedFile(
            "nota.webm", b"\x00\x01\x02", content_type="audio/webm;codecs=opus"
        )
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/", data={"audio": audio}
            )
            consume_streaming(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"

    def test_multipart_rejects_oversized_image(self, logged_client, user, settings):
        settings.ASSISTANT_MAX_IMAGE_MB = 0  # tudo é grande demais
        big = SimpleUploadedFile("r.png", b"\x00" * 1024, content_type="image/png")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": big}
        )
        assert response.status_code == 400

    def test_image_fallback_uses_vision_model(
        self, logged_client, user, monkeypatch, settings
    ):
        """Quando a extração inicial falha, o fallback tenta com LLM_VISION_MODEL."""
        settings.LLM_VISION_MODEL = "openai:vision-sentinel"
        captured = {}

        async def fake_extract(images, model=None):
            captured.setdefault("calls", []).append(model)
            if model is None:
                raise RuntimeError("primeira extração falha")
            # segunda chamada com vision model tem sucesso
            from assistant.agents.extraction import ReceiptExtraction
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        from assistant.agents.receipt_confirm import receipt_confirm_agent
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with receipt_confirm_agent.override(model=TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"image": image})
            consume_streaming(response)

        assert captured["calls"][0] is None, "primeira chamada sem model override"
        assert captured["calls"][1] == "openai:vision-sentinel", "segunda usa LLM_VISION_MODEL"

    def test_image_is_preprocessed_before_send(
        self, logged_client, user, monkeypatch
    ):
        """_handle_image deve passar a imagem por prepare_receipt_image."""
        calls = {}

        def fake_prepare(data, media_type):
            calls["called"] = True
            calls["media_type"] = media_type
            return b"PREPPED", "image/jpeg"

        monkeypatch.setattr("assistant.views.prepare_receipt_image", fake_prepare)

        from assistant.agents.extraction import ReceiptExtraction

        async def fake_extract(images, model=None):
            calls["extract_images"] = images
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        from assistant.agents.receipt_confirm import receipt_confirm_agent
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with receipt_confirm_agent.override(model=TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"image": image})
            consume_streaming(response)

        assert calls.get("called") is True
        # os bytes pré-processados chegam ao extract_receipt
        assert calls["extract_images"][0][0] == b"PREPPED"
        assert calls["extract_images"][0][1] == "image/jpeg"

    _PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
        b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def test_multiple_images_one_extraction(self, logged_client, user, monkeypatch):
        """N fotos => UMA chamada a extract_receipt com N imagens (mesmo recibo)."""
        from assistant.agents.extraction import ReceiptExtraction
        from assistant.agents.receipt_confirm import receipt_confirm_agent

        captured = {}

        async def fake_extract(images, model=None):
            captured["images"] = images
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        with receipt_confirm_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data={"image": [img1, img2], "message": "isso é mercado"},
            )
            consume_streaming(response)

        assert response.status_code == 200
        assert len(captured["images"]) == 2
        # legenda vira rótulo do usuário com contagem de fotos
        assert ChatMessage.objects.filter(
            user=user, role="user", content__icontains="2 fotos"
        ).exists()

    def test_rejects_too_many_images(self, logged_client, user, settings):
        settings.ASSISTANT_MAX_IMAGES = 1
        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": [img1, img2]}
        )
        assert response.status_code == 400

    def test_rejects_bad_type_among_images(self, logged_client, user):
        good = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        bad = SimpleUploadedFile("x.txt", b"\x00", content_type="text/plain")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": [good, bad]}
        )
        assert response.status_code == 400

    def test_image_proposes_without_writing(self, logged_client, seeded_user):
        """Turno de imagem NUNCA cria Entry — apenas propõe via receipt_confirm_agent."""
        from assistant.agents.extraction import extraction_agent
        from assistant.agents.receipt_confirm import receipt_confirm_agent
        from finances.models import Entry

        image = SimpleUploadedFile("recibo.png", self._PNG, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            receipt_confirm_agent.override(model=TestModel()),
        ):
            resp = logged_client.post(
                "/api/assistant/chat/", {"image": image}
            )
            consume_streaming(resp)

        # The image turn must PROPOSE, never write: zero entries created at all.
        assert Entry.objects.count() == 0


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
