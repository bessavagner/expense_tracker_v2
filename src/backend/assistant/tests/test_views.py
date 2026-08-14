import json

import pytest
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from model_bakery import baker
from pydantic_ai.models.test import TestModel

from accounts.resolution import household_for_user
from assistant.agents.assistant import agents_override, assistant_agent
from assistant.models import ChatMessage
from assistant.tests.fakes import FakeAgent, FakeStream


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
    def test_post_creates_user_message(self, logged_client, user, household):

        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        assert ChatMessage.objects.for_household(household).filter(role="user").exists()

    def test_post_returns_sse_content_type(self, logged_client, user):

        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert response["Content-Type"] == "text/event-stream"

    def test_post_creates_assistant_message(self, logged_client, user, household):

        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            # Consume the streaming response (may be async generator in Django 6)
            consume_streaming(response)
        assert ChatMessage.objects.for_household(household).filter(role="assistant").exists()

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
        self, logged_client, user, monkeypatch, household
    ):

        async def fake_transcribe(data, filename, content_type, *, client=None, scope=None):
            return "mercado 80 no pix"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        with agents_override(TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"audio": audio})
            body = consume_streaming(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert '"type": "user_text"' in body
        assert "mercado 80 no pix" in body
        assert (
            ChatMessage.objects.for_household(household)
            .filter(role="user", content__icontains="mercado 80")
            .exists()
        )
        assert ChatMessage.objects.for_household(household).filter(role="assistant").exists()

    def test_multipart_image_routes_to_assistant(self, logged_client, user, household):

        # 1x1 PNG válido (bytes mínimos)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        from assistant.agents.extraction import extraction_agent

        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            response = logged_client.post("/api/assistant/chat/", data={"image": image})
            body = consume_streaming(response)

        assert response.status_code == 200
        assert '"type": "user_text"' in body
        assert "📷" in body
        assert (
            ChatMessage.objects.for_household(household)
            .filter(role="user", content__icontains="foto")
            .exists()
        )

    def test_image_creates_receipt_draft(self, logged_client, user, household):
        """Fase 1: a foto gera um ReceiptDraft persistido com a extração."""
        from assistant.agents.extraction import extraction_agent
        from assistant.models import ReceiptDraft

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            response = logged_client.post("/api/assistant/chat/", data={"image": image})
            consume_streaming(response)

        assert response.status_code == 200
        # TestModel calls all tools including discard_receipt, so the draft may
        # transition pending → discarded; assert creation happened (any status).
        assert ReceiptDraft.objects.for_household(household).exists()

    def test_resent_registered_receipt_does_not_reregister(
        self, logged_client, user, monkeypatch, household
    ):
        """Reenviar a MESMA nota (já registrada) NÃO abre um novo fluxo de recibo
        — não cria draft para re-commit. Evita a duplicata do incidente PAGUE
        MENOS (o 'sim' seguinte deixa de ser sequestrado para commit_receipt)."""
        from decimal import Decimal

        from assistant.agents.extraction import ReceiptExtraction, ReceiptItem
        from assistant.models import ReceiptDraft, ReceiptDraftStatus

        ReceiptDraft.objects.create(
            household=household,
            payload={
                "store": "EMPREENDIMENTOS PAGUE MENOS S/A",
                "date": "2026-07-04",
                "amount_paid": "155.90",
                "items": [
                    {"description": "lemont", "line_total": "135.98"},
                    {"description": "barra", "line_total": "19.92"},
                ],
            },
            status=ReceiptDraftStatus.REGISTERED,
        )
        before = ReceiptDraft.objects.for_household(household).count()

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):

            return ReceiptExtraction(
                store="EMPREENDIMENTOS PAGUE MENOS S/A",
                amount_paid=Decimal("155.90"),
                items=[
                    ReceiptItem(description="lemont", line_total=Decimal("135.98")),
                    ReceiptItem(description="barra", line_total=Decimal("19.92")),
                ],
            )

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data={"image": image, "message": "corrige a data"},
            )
            consume_streaming(response)

        assert response.status_code == 200
        # nenhum draft novo criado → não há recibo pendente para re-commit
        assert ReceiptDraft.objects.for_household(household).count() == before

    def test_multipart_rejects_two_files(self, logged_client, user):

        a = SimpleUploadedFile("n.webm", b"\x00", content_type="audio/webm")
        i = SimpleUploadedFile("r.png", b"\x00", content_type="image/png")
        response = logged_client.post("/api/assistant/chat/", data={"audio": a, "image": i})
        assert response.status_code == 400

    def test_multipart_rejects_bad_audio_type(self, logged_client, user):

        bad = SimpleUploadedFile("x.txt", b"\x00", content_type="text/plain")
        response = logged_client.post("/api/assistant/chat/", data={"audio": bad})
        assert response.status_code == 400

    def test_multipart_accepts_audio_with_codecs_param(self, logged_client, user, monkeypatch):
        """MediaRecorder envia content_type 'audio/webm;codecs=opus' — o
        parâmetro de codec não pode fazer a validação rejeitar (era 400 →
        'Erro de conexão' no widget)."""

        async def fake_transcribe(data, filename, content_type, *, client=None, scope=None):

            return "mercado 80 no pix"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        audio = SimpleUploadedFile(
            "nota.webm", b"\x00\x01\x02", content_type="audio/webm;codecs=opus"
        )
        with agents_override(TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"audio": audio})
            consume_streaming(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"

    def test_multipart_rejects_oversized_image(self, logged_client, user, settings):

        settings.ASSISTANT_MAX_IMAGE_MB = 0  # tudo é grande demais
        big = SimpleUploadedFile("r.png", b"\x00" * 1024, content_type="image/png")
        response = logged_client.post("/api/assistant/chat/", data={"image": big})
        assert response.status_code == 400

    def test_image_fallback_uses_vision_model(self, logged_client, user, monkeypatch, settings):
        """Quando a extração inicial falha, o fallback tenta com LLM_VISION_MODEL."""
        settings.LLM_VISION_MODEL = "openai:vision-sentinel"
        captured = {}

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):

            captured.setdefault("calls", []).append(model)
            if model is None:
                raise RuntimeError("primeira extração falha")
            # segunda chamada com vision model tem sucesso
            from assistant.agents.extraction import ReceiptExtraction

            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"image": image})
            consume_streaming(response)

        assert captured["calls"][0] is None, "primeira chamada sem model override"
        assert captured["calls"][1] == "openai:vision-sentinel", "segunda usa LLM_VISION_MODEL"

    def test_image_is_preprocessed_before_send(self, logged_client, user, monkeypatch):
        """_handle_image deve passar a imagem por prepare_receipt_image."""
        calls = {}

        def fake_prepare(data, media_type):

            calls["called"] = True
            calls["media_type"] = media_type
            return b"PREPPED", "image/jpeg"

        monkeypatch.setattr("assistant.views.prepare_receipt_image", fake_prepare)

        from assistant.agents.extraction import ReceiptExtraction

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):

            calls["extract_images"] = images
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with assistant_agent.override(model=TestModel()):
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

    def test_multiple_images_one_extraction(self, logged_client, user, monkeypatch, household):
        """N fotos => UMA chamada a extract_receipt com N imagens (mesmo recibo)."""
        from assistant.agents.extraction import ReceiptExtraction

        captured = {}

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):

            captured["images"] = images
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data={"image": [img1, img2], "message": "isso é mercado"},
            )
            consume_streaming(response)

        assert response.status_code == 200
        assert len(captured["images"]) == 2
        # legenda vira rótulo do usuário com contagem de fotos
        assert (
            ChatMessage.objects.for_household(household)
            .filter(role="user", content__icontains="2 fotos")
            .exists()
        )

    def test_rejects_too_many_images(self, logged_client, user, settings):

        settings.ASSISTANT_MAX_IMAGES = 1
        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        response = logged_client.post("/api/assistant/chat/", data={"image": [img1, img2]})
        assert response.status_code == 400

    def test_rejects_bad_type_among_images(self, logged_client, user):

        good = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        bad = SimpleUploadedFile("x.txt", b"\x00", content_type="text/plain")
        response = logged_client.post("/api/assistant/chat/", data={"image": [good, bad]})
        assert response.status_code == 400

    def test_image_proposes_without_writing(self, logged_client, seeded_user):
        """Turno de imagem NUNCA cria Entry — apenas propõe via assistant_agent."""
        from assistant.agents.extraction import extraction_agent
        from finances.models import Entry

        image = SimpleUploadedFile("recibo.png", self._PNG, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            resp = logged_client.post("/api/assistant/chat/", {"image": image})
            consume_streaming(resp)

        # The image turn must PROPOSE, never write: zero entries created at all.
        assert Entry.objects.count() == 0

    def test_pending_receipt_routes_confirm_and_commits_once(
        self, logged_client, seeded_user, seeded_scope, household
    ):
        from assistant.agents.tools import propose_receipt
        from assistant.models import ReceiptDraft, ReceiptDraftStatus
        from finances.models import Entry

        draft = ReceiptDraft.objects.create(
            household=household,
            status=ReceiptDraftStatus.PENDING,
            payload={
                "store": "MATEUS",
                "date": "2026-06-22",
                "discount": "0",
                "payment_hint": "Pix",
                "items": [
                    {"description": "arroz", "line_total": "60.00"},
                    {"description": "refri", "line_total": "40.00"},
                ],
            },
        )
        propose_receipt(seeded_scope, {"Alimentação": [0], "Lanche": [1]}, "Pix")

        # A TestModel that calls only commit_receipt simulates the user's "sim".
        tm = TestModel(call_tools=["commit_receipt"])
        with assistant_agent.override(model=tm):
            resp = logged_client.post(
                "/api/assistant/chat/",
                {"message": "sim"},
                content_type="application/json",
            )
            consume_streaming(resp)
        assert Entry.objects.for_household(household).count() == 2
        draft.refresh_from_db()
        assert draft.status == ReceiptDraftStatus.REGISTERED

        # A second "sim" must NOT duplicate (draft no longer PENDING -> commit no-op).
        with assistant_agent.override(model=TestModel(call_tools=["commit_receipt"])):
            resp2 = logged_client.post(
                "/api/assistant/chat/",
                {"message": "sim"},
                content_type="application/json",
            )
            consume_streaming(resp2)
        assert Entry.objects.for_household(household).count() == 2

    def test_pending_receipt_audio_routes_confirm_and_commits_once(
        self, logged_client, seeded_user, seeded_scope, monkeypatch, household
    ):
        """Voice confirmation of a pending receipt must route to assistant_agent —
        regression guard for the audio path (single-agent mode)."""
        from assistant.agents.tools import propose_receipt
        from assistant.models import ReceiptDraft, ReceiptDraftStatus
        from finances.models import Entry

        draft = ReceiptDraft.objects.create(
            household=household,
            status=ReceiptDraftStatus.PENDING,
            payload={
                "store": "MATEUS",
                "date": "2026-06-22",
                "discount": "0",
                "payment_hint": "Pix",
                "items": [
                    {"description": "arroz", "line_total": "60.00"},
                    {"description": "refri", "line_total": "40.00"},
                ],
            },
        )
        propose_receipt(seeded_scope, {"Alimentação": [0], "Lanche": [1]}, "Pix")

        async def fake_transcribe(data, filename, content_type, *, client=None, scope=None):

            return "sim"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        audio = SimpleUploadedFile("confirm.webm", b"\x00\x01\x02", content_type="audio/webm")
        tm = TestModel(call_tools=["commit_receipt"])
        with assistant_agent.override(model=tm):
            resp = logged_client.post("/api/assistant/chat/", data={"audio": audio})
            consume_streaming(resp)

        assert Entry.objects.for_household(household).count() == 2
        draft.refresh_from_db()
        assert draft.status == ReceiptDraftStatus.REGISTERED

    def test_images_pass_user_taxonomy_to_extraction(
        self, logged_client, user, monkeypatch, household
    ):

        from assistant.agents.extraction import ReceiptExtraction

        baker.make("finances.Category", household=household, name="Alimentação")
        baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")

        captured = {}

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):

            captured["categories"] = categories
            captured["payment_methods"] = payment_methods
            return ReceiptExtraction(amount_paid=None)

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)
        img = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        with assistant_agent.override(model=TestModel()):
            response = logged_client.post("/api/assistant/chat/", data={"image": img})
            consume_streaming(response)

        assert "Alimentação" in (captured["categories"] or [])
        assert "Pix" in (captured["payment_methods"] or [])


@pytest.mark.django_db
class TestChokepointWiring:
    """E07 S07-3: chat_view decides quota BEFORE any model call, and every
    branch carries the chosen tier's model plus the degrade notice down to the
    stream.

    Written sync + `consume_streaming` rather than `async def`: an async test
    body runs its ORM calls on a different connection from the one holding
    pytest-django's uncommitted fixture transaction, so `household` and `user`
    are invisible to it. See the module docstring of `test_metering.py`.
    """

    def test_an_abuse_refusal_makes_zero_model_calls(self, logged_client, user, settings):
        """DoD: a ceiling-refused request produces zero model calls and no row.

        No `agents_override` here on purpose — `ALLOW_MODEL_REQUESTS` is False
        in this suite, so reaching a model at all raises rather than costing
        money.
        """
        from assistant.models import UsageInteraction

        settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 0
        response = logged_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert response.status_code == 429
        # Refused before `open_interaction`, so the turn is not charged either.
        assert UsageInteraction.objects.count() == 0

    def test_a_household_out_of_credits_still_gets_an_answer(
        self, logged_client, user, household, plan
    ):
        """DoD: zero credits degrades to ESSENTIAL, it does NOT refuse."""
        from assistant.models import InteractionKind, UsageInteraction
        from core.tiers import Tier

        UsageInteraction.objects.create(
            household=household,
            user=user,
            kind=InteractionKind.TEXT,
            tier=Tier.ADVANCED,
            credits_charged=plan.monthly_credits,
        )
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            body = consume_streaming(response)

        assert response.status_code == 200
        assert '"type": "notice"' in body
        assert "Essencial" in body

        opened = UsageInteraction.objects.get(tier=Tier.ESSENTIAL)
        assert opened.credits_charged == 0

    def test_the_degrade_notice_arrives_before_any_token(
        self, logged_client, user, household, plan
    ):
        """A notice after the answer is a footnote nobody reads."""
        from assistant.models import InteractionKind, UsageInteraction
        from core.tiers import Tier

        UsageInteraction.objects.create(
            household=household,
            user=user,
            kind=InteractionKind.TEXT,
            tier=Tier.ADVANCED,
            credits_charged=plan.monthly_credits,
        )
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            body = consume_streaming(response)

        assert body.index('"notice"') < body.index('"token"')

    def test_a_household_with_credits_gets_no_notice(self, logged_client, user, household, plan):
        """The notice is for a degrade. Emitting it always would train the user
        to ignore it."""
        with agents_override(TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            body = consume_streaming(response)

        assert '"type": "notice"' not in body

    def test_the_interaction_is_opened_before_any_model_call(
        self, logged_client, user, household, monkeypatch
    ):
        """A stream that dies mid-flight must still have counted against budget."""
        from assistant.models import UsageInteraction

        def exploding_sse(*args, **kwargs):
            raise AssertionError("must not be reached")

        # The interaction is written by `chat_view` itself, so it exists even
        # when everything downstream of it fails.
        monkeypatch.setattr("assistant.views._sse_response", exploding_sse)
        with pytest.raises(AssertionError):
            logged_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
            )
        assert UsageInteraction.objects.count() == 1

    @pytest.mark.parametrize("field", ["model", "notice"])
    def test_the_text_path_threads_the_decision(
        self, logged_client, user, household, monkeypatch, settings, field
    ):
        from django.http import JsonResponse

        captured = {}

        def fake_sse(scope, agent, prompt, **kwargs):
            captured.update(kwargs)
            return JsonResponse({})

        monkeypatch.setattr("assistant.views._sse_response", fake_sse)
        logged_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert field in captured
        if field == "model":
            assert captured["model"] == settings.LLM_TIER_ADVANCED

    def test_the_audio_path_threads_the_decision(
        self, logged_client, user, household, monkeypatch, settings
    ):
        from django.http import JsonResponse

        captured = {}

        async def fake_transcribe(data, filename, content_type, *, client=None, scope=None):
            return "mercado 80 no pix"

        def fake_sse(scope, agent, prompt, **kwargs):
            captured.update(kwargs)
            return JsonResponse({})

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)
        monkeypatch.setattr("assistant.views._sse_response", fake_sse)

        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        logged_client.post("/api/assistant/chat/", data={"audio": audio})
        assert captured["model"] == settings.LLM_TIER_ADVANCED
        assert "notice" in captured

    def test_the_image_path_threads_the_decision(
        self, logged_client, user, household, monkeypatch, settings
    ):
        from django.http import JsonResponse

        from assistant.agents.extraction import ReceiptExtraction

        captured = {}

        async def fake_extract(
            images, categories=None, payment_methods=None, model=None, *, scope=None
        ):
            return ReceiptExtraction()

        def fake_sse(scope, agent, prompt, **kwargs):
            captured.update(kwargs)
            return JsonResponse({})

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)
        monkeypatch.setattr("assistant.views._sse_response", fake_sse)

        image = SimpleUploadedFile("recibo.png", self._PNG, content_type="image/png")
        logged_client.post("/api/assistant/chat/", data={"image": image})
        assert captured["model"] == settings.LLM_TIER_ADVANCED
        assert "notice" in captured

    _PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
        b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.mark.django_db
class TestEssentialFallbackRetry:
    def _run(self, scope, agent, **kwargs):
        from assistant.views import _sse_response

        return consume_streaming(_sse_response(scope, agent, "oi", message_history=None, **kwargs))

    def test_a_first_attempt_that_dies_before_any_token_retries_the_fallback(self, scope):
        agent = FakeAgent(
            {
                "primary": FakeStream(["nope"], fail_after=0),
                "fallback": FakeStream(["ok"]),
            }
        )
        body = self._run(scope, agent, model="primary", fallback_model="fallback")
        assert agent.calls == ["primary", "fallback"]
        assert "ok" in body
        assert '"type": "error"' not in body

    def test_a_failure_after_the_first_token_is_not_retried(self, scope):
        """The client already rendered those tokens; a replay would duplicate
        them, and there is no way to unsay them."""
        agent = FakeAgent(
            {
                "primary": FakeStream(["meio ", "caminho"], fail_after=1),
                "fallback": FakeStream(["ok"]),
            }
        )
        body = self._run(scope, agent, model="primary", fallback_model="fallback")
        assert agent.calls == ["primary"]
        assert '"type": "error"' in body

    def test_without_a_fallback_a_failure_stays_a_failure(self, scope):
        agent = FakeAgent({"primary": FakeStream(["nope"], fail_after=0)})
        body = self._run(scope, agent, model="primary")
        assert agent.calls == ["primary"]
        assert '"type": "error"' in body

    def test_a_fallback_that_also_dies_reports_the_error_once(self, scope):
        agent = FakeAgent(
            {
                "primary": FakeStream(["nope"], fail_after=0),
                "fallback": FakeStream(["nope"], fail_after=0),
            }
        )
        body = self._run(scope, agent, model="primary", fallback_model="fallback")
        assert agent.calls == ["primary", "fallback"]
        assert body.count('"type": "error"') == 1


@pytest.mark.django_db
class TestUsageEndpoint:
    """S07-4: the allowance is visible, not silently applied."""

    def test_usage_endpoint_reports_balance_and_tier(self, logged_client, user, household, plan):
        response = logged_client.get("/api/assistant/usage/")
        assert response.status_code == 200
        body = response.json()
        assert body["granted"] == plan.monthly_credits
        assert body["remaining"] == plan.monthly_credits
        assert body["tier"] == "advanced"
        assert {t["value"] for t in body["tiers"]} == {"advanced", "standard", "essential"}
        assert {t["label"] for t in body["tiers"]} == {"Avançado", "Padrão", "Essencial"}

    def test_the_remaining_balance_drops_as_credits_are_charged(
        self, logged_client, user, household, plan
    ):
        from assistant.models import InteractionKind, UsageInteraction
        from core.tiers import Tier

        UsageInteraction.objects.create(
            household=household,
            user=user,
            kind=InteractionKind.TEXT,
            tier=Tier.ADVANCED,
            credits_charged=7,
        )
        body = logged_client.get("/api/assistant/usage/").json()
        assert body["remaining"] == plan.monthly_credits - 7

    def test_a_neighbours_spending_does_not_move_our_balance(
        self, logged_client, user, household, other_household, other_user, plan
    ):
        from assistant.models import InteractionKind, UsageInteraction
        from core.tiers import Tier

        UsageInteraction.objects.create(
            household=other_household,
            user=other_user,
            kind=InteractionKind.TEXT,
            tier=Tier.ADVANCED,
            credits_charged=500,
        )
        body = logged_client.get("/api/assistant/usage/").json()
        assert body["remaining"] == plan.monthly_credits

    def test_the_renewal_date_is_the_first_of_next_month(self, logged_client, user, household):
        from datetime import date

        import time_machine

        with time_machine.travel(date(2026, 8, 14), tick=False):
            body = logged_client.get("/api/assistant/usage/").json()
        assert body["renews_on"] == "2026-09-01"

    def test_usage_endpoint_requires_authentication(self):
        response = Client().get("/api/assistant/usage/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestTierEndpoint:
    def test_a_user_can_switch_tier(self, logged_client, user, household):
        response = logged_client.post(
            "/api/assistant/tier/",
            data=json.dumps({"tier": "standard"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        household.refresh_from_db()
        assert household.preferred_tier == "standard"

    def test_an_unknown_tier_is_rejected(self, logged_client, user, household):
        response = logged_client.post(
            "/api/assistant/tier/",
            data=json.dumps({"tier": "godmode"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        household.refresh_from_db()
        assert household.preferred_tier == "advanced"

    def test_the_chosen_tier_is_what_the_chokepoint_spends(
        self, logged_client, user, household, plan
    ):
        """The switch has to mean something. Standard costs fewer credits per
        turn than Advanced, so choosing it must change what a turn is billed."""
        from assistant.models import UsageInteraction

        logged_client.post(
            "/api/assistant/tier/",
            data=json.dumps({"tier": "standard"}),
            content_type="application/json",
        )
        with agents_override(TestModel()):
            consume_streaming(
                logged_client.post(
                    "/api/assistant/chat/",
                    data=json.dumps({"message": "oi"}),
                    content_type="application/json",
                )
            )

        opened = UsageInteraction.objects.get()
        assert opened.tier == "standard"
        assert opened.credits_charged == 1  # the seeded standard/text price

    def test_tier_endpoint_requires_authentication(self):
        response = Client().post(
            "/api/assistant/tier/",
            data=json.dumps({"tier": "standard"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_a_get_is_not_a_way_to_change_tier(self, logged_client, user, household):
        assert logged_client.get("/api/assistant/tier/").status_code == 405


@pytest.mark.django_db
class TestHistoryEndpoint:
    def test_returns_messages(self, logged_client, user, household):

        baker.make("assistant.ChatMessage", household=household, role="user", content="oi")
        baker.make("assistant.ChatMessage", household=household, role="assistant", content="olá!")
        response = logged_client.get("/api/assistant/history/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["role"] == "user"
        assert data[1]["role"] == "assistant"

    def test_filters_by_user(self, logged_client, user, household):

        other = baker.make("core.CustomUser")
        baker.make("assistant.ChatMessage", household=household, content="mine")
        baker.make("assistant.ChatMessage", household=household_for_user(other), content="theirs")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "mine"

    def test_limits_to_50(self, logged_client, user, household):

        for i in range(60):
            baker.make("assistant.ChatMessage", household=household, content=f"msg {i}")
        response = logged_client.get("/api/assistant/history/")
        data = response.json()
        assert len(data) == 50

    def test_unauthenticated(self):

        client = Client()
        response = client.get("/api/assistant/history/")
        assert response.status_code == 403
