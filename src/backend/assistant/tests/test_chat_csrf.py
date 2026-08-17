"""CSRF must be enforced on the write-capable chat endpoint.

``chat_view`` can reach every mutating tool in ``assistant.views.MUTATING_TOOLS``.
It was ``@csrf_exempt`` because the React widget sends the token in a header
rather than a form field — but the middleware reads the header too, so the
exemption bought nothing and cost the protection.
"""

import json

import pytest
from django.test import Client
from pydantic_ai.models.test import TestModel

from assistant.agents.assistant import agents_override
from assistant.models import ChatMessage


@pytest.fixture
def csrf_client(user, household):
    """A client that enforces CSRF and already holds a csrftoken cookie.

    `household` is requested for its side effect: the middleware resolves
    `request.household` from a Membership, and a user without one gives the
    assistant a scope with no tenant — which, since phase 4 made the column NOT
    NULL, is an IntegrityError on the first usage event rather than a quiet
    empty read.
    """
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    client.get("/")  # any rendered page sets the cookie
    return client


@pytest.mark.django_db
class TestChatCsrf:
    def test_post_without_token_is_rejected(self, csrf_client, household):
        response = csrf_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        assert response.status_code == 403
        assert not ChatMessage.objects.for_household(household).exists()

    def test_post_with_invalid_token_is_rejected(self, csrf_client, household):
        response = csrf_client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
            headers={"x-csrftoken": "x" * 64},
        )
        assert response.status_code == 403
        assert not ChatMessage.objects.for_household(household).exists()

    def test_post_with_valid_token_succeeds(self, csrf_client, household, consented_user):
        token = csrf_client.cookies["csrftoken"].value
        with agents_override(TestModel()):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data=json.dumps({"message": "oi"}),
                content_type="application/json",
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"

    def test_multipart_image_with_valid_token_succeeds(
        self, csrf_client, household, consented_user
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from assistant.agents.assistant import assistant_agent
        from assistant.agents.extraction import extraction_agent

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        token = csrf_client.cookies["csrftoken"].value
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data={"image": image},
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200

    def test_multipart_audio_with_valid_token_succeeds(
        self, csrf_client, household, monkeypatch, consented_user
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        async def fake_transcribe(data, filename, content_type, *, client=None, scope=None):
            return "mercado 80 no pix"

        monkeypatch.setattr("assistant.views.transcribe_audio", fake_transcribe)

        token = csrf_client.cookies["csrftoken"].value
        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        with agents_override(TestModel()):
            response = csrf_client.post(
                "/api/assistant/chat/",
                data={"audio": audio},
                headers={"x-csrftoken": token},
            )
        assert response.status_code == 200


def test_no_csrf_exempt_remains_in_the_assistant_app():
    """A regression guard: the exemption must not come back by copy-paste."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent
    offenders = [
        path.name
        for path in app_dir.rglob("*.py")
        if "tests" not in path.parts and "csrf_exempt" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
