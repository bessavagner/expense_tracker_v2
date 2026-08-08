"""Oversized request bodies are rejected before Django parses them.

Checked from Content-Length, not from the parsed body, because Cloud Run backs
the container's filesystem with its 1Gi of RAM — an upload "written to disk" is
an upload held in memory.
"""

import pytest
from asgiref.sync import iscoroutinefunction
from django.test import Client
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestGlobalBodyCeiling:
    def test_oversized_body_is_rejected_with_413(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert response.status_code == 413

    def test_body_under_the_ceiling_reaches_the_view(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 4096
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b'{"message": ""}',
            content_type="application/json",
        )
        # 400 from the view's own validation — it got there, which is the point.
        assert response.status_code == 400

    def test_rejection_message_is_pt_br(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = logged_client.post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert "grande demais" in response.content.decode()

    def test_get_requests_are_unaffected(self, logged_client, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1
        assert logged_client.get("/").status_code == 200

    def test_unauthenticated_oversized_request_is_rejected_too(self, db, settings):
        """The ceiling runs before authentication — that is the whole point."""
        settings.MAX_REQUEST_BODY_BYTES = 1024
        response = Client().post(
            "/api/assistant/chat/",
            data=b"x" * 4096,
            content_type="application/octet-stream",
        )
        assert response.status_code == 413


@pytest.mark.django_db
class TestImporterCeiling:
    def test_importer_has_a_tighter_ceiling_than_chat(self, settings):
        assert settings.MAX_CSV_UPLOAD_BYTES < settings.MAX_REQUEST_BODY_BYTES

    def test_oversized_csv_is_rejected(self, logged_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.MAX_CSV_UPLOAD_BYTES = 1024
        settings.MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
        big = SimpleUploadedFile("big.csv", b"a,b,c\n" * 2000, content_type="text/csv")
        response = logged_client.post(
            "/import/", {"file": big, "import_type": "regular"}
        )
        assert response.status_code == 413

    def test_small_csv_still_uploads(self, logged_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.MAX_CSV_UPLOAD_BYTES = 1024 * 1024
        small = SimpleUploadedFile(
            "small.csv",
            b"date,description,amount,category,payment_method\n",
            content_type="text/csv",
        )
        response = logged_client.post(
            "/import/", {"file": small, "import_type": "regular"}
        )
        # ImportUploadView is POST-redirect-GET: success is a redirect to the
        # mapping step, not a 200 — the point here is "not 413".
        assert response.status_code == 302
        assert response.url == "/import/map/"


class TestUploadDefaults:
    def test_number_of_files_per_request_is_capped(self, settings):
        assert settings.DATA_UPLOAD_MAX_NUMBER_FILES <= 10


# Beyond the spec's own test list: the middleware ordering (before WhiteNoise,
# which is sync-only) means every request in this app currently exercises the
# sync branch of the factory, never the async one — the chat-streaming tests
# prove behaviour end-to-end but never actually cover the coroutine path. These
# unit-test the factory and the Content-Length parsing directly so both
# branches, and the lying/malformed header case, have real coverage.
class TestMiddlewareFactoryBranches:
    def test_malformed_content_length_is_treated_as_oversized(self, rf, settings):
        # Fix round 1: a garbled header must fail closed, not read as absent.
        # See core.middleware.declared_content_length's docstring.
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 1024
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "not-a-number"
        blocked = _too_large(request)
        assert blocked is not None
        assert blocked.status_code == 413

    def test_negative_content_length_is_treated_as_oversized(self, rf, settings):
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 1024
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "-1"
        blocked = _too_large(request)
        assert blocked is not None
        assert blocked.status_code == 413

    def test_duplicate_content_length_headers_use_the_larger_value(self, rf, settings):
        # ASGI folds repeated headers into one comma-joined META value (see
        # ASGIRequest.__init__ in django/core/handlers/asgi.py) — a request
        # declaring conflicting lengths is read as the larger of them.
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 150
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "100,200"
        blocked = _too_large(request)
        assert blocked is not None
        assert blocked.status_code == 413

    def test_duplicate_content_length_headers_both_under_limit_pass(self, rf, settings):
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 250
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "100,200"
        assert _too_large(request) is None

    def test_missing_content_length_is_not_treated_as_oversized(self, rf, settings):
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 1024
        request = rf.get("/x")
        request.META.pop("CONTENT_LENGTH", None)
        assert _too_large(request) is None

    def test_content_length_exactly_at_limit_passes(self, rf, settings):
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 1024
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "1024"
        assert _too_large(request) is None

    def test_content_length_one_over_limit_is_rejected(self, rf, settings):
        from core.middleware import _too_large

        settings.MAX_REQUEST_BODY_BYTES = 1024
        request = rf.post("/x")
        request.META["CONTENT_LENGTH"] = "1025"
        blocked = _too_large(request)
        assert blocked is not None
        assert blocked.status_code == 413

    def test_sync_get_response_stays_sync(self, rf, settings):
        from django.http import HttpResponse

        from core.middleware import max_request_body_middleware

        settings.MAX_REQUEST_BODY_BYTES = 1024

        def get_response(request):
            return HttpResponse("ok")

        middleware = max_request_body_middleware(get_response)
        assert not iscoroutinefunction(middleware)

        request = rf.post("/x", data=b"x" * 4096, content_type="application/octet-stream")
        response = middleware(request)
        assert response.status_code == 413

    def test_async_get_response_stays_async(self, rf, settings):
        # No async test runner plugin (pytest-asyncio, anyio's pytest mode) is
        # configured in this project, so the coroutine is driven with
        # asyncio.run rather than an `async def test_...`.
        import asyncio

        from django.http import HttpResponse

        from core.middleware import max_request_body_middleware

        settings.MAX_REQUEST_BODY_BYTES = 1024

        async def get_response(request):
            return HttpResponse("ok")

        middleware = max_request_body_middleware(get_response)
        assert iscoroutinefunction(middleware)

        request = rf.post("/x", data=b"x" * 4096, content_type="application/octet-stream")
        response = asyncio.run(middleware(request))
        assert response.status_code == 413
