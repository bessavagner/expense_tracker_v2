"""ASGI-layer enforcement of the request-body ceiling.

``django.test.Client`` cannot exercise this: it builds a ``WSGIRequest`` (or,
for ``AsyncClient``, pre-wraps the body in a ``LimitedStream``), never Django's
real ``ASGIHandler.read_body``. Production runs
``gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker``
(see ``Dockerfile``), where ``read_body`` reads the whole body into a
``SpooledTemporaryFile`` before any Django middleware runs and before Django's
own ``DATA_UPLOAD_MAX_MEMORY_SIZE`` check (which never trips for a request with
no ``Content-Length`` -- an absent header reads as ``0``). So this module drives
``core.asgi_body_limit.request_body_ceiling_asgi`` directly against a fake ASGI
app and fake ``receive``/``send`` channels, the way the real ASGI server would
call it.
"""

import asyncio
import tracemalloc

import pytest

from core.asgi_body_limit import request_body_ceiling_asgi


class FakeASGIApp:
    """Records what it was called with; stands in for Django's ASGIHandler.

    Mirrors the real ``ASGIHandler.read_body`` / ``handle`` contract: a
    disconnect message aborts the whole request with no response sent at all
    -- exactly like Django's own ``read_body`` raising ``RequestAborted``,
    which ``ASGIHandler.handle`` catches and returns from without ever
    reaching ``send_response``. Only a normal ``more_body: False`` completes
    the body and gets a response.
    """

    def __init__(self):
        self.called_with_scope = None
        self.received_messages = []
        self.aborted = False

    async def __call__(self, scope, receive, send):
        self.called_with_scope = scope
        while True:
            message = await receive()
            self.received_messages.append(message)
            if message["type"] == "http.disconnect":
                self.aborted = True
                return
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send_response(self, response, send):
        """Stands in for ASGIHandler.send_response's encoding of an HttpResponse."""
        await send({"type": "http.response.start", "status": response.status_code, "headers": []})
        await send({"type": "http.response.body", "body": response.content})


def _scope(path="/api/assistant/chat/", content_length=None):
    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return {"type": "http", "path": path, "headers": headers}


def _chunks_receive(chunks):
    """A fake ``receive`` that yields ``chunks``, then a final ``more_body:
    False`` message -- a normal, successfully completed body. (Not a
    disconnect: a disconnect signals premature termination, not completion,
    and ``FakeASGIApp`` treats the two very differently.)
    """
    it = iter(chunks)

    async def receive():
        try:
            body = next(it)
            return {"type": "http.request", "body": body, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    return receive


@pytest.mark.django_db(transaction=False)
class TestDeclaredLengthPath:
    def test_oversized_declared_length_rejected_without_calling_receive(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        receive_calls = 0

        async def receive():
            nonlocal receive_calls
            receive_calls += 1
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=4096)
        asyncio.run(middleware(scope, receive, send))

        assert receive_calls == 0, "receive() must never be awaited for a declared-oversized body"
        assert app.called_with_scope is None, "the wrapped app must never be invoked"
        assert sent[0]["status"] == 413
        assert "grande demais" in sent[1]["body"].decode()

    def test_content_length_exactly_at_limit_passes_through(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)
        receive = _chunks_receive([b"x" * 1024])
        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=1024)
        asyncio.run(middleware(scope, receive, send))

        assert app.called_with_scope is scope
        assert sent[0]["status"] == 200

    def test_content_length_one_over_limit_is_rejected(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        async def receive():
            raise AssertionError("receive() must not be called")

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=1025)
        asyncio.run(middleware(scope, receive, send))

        assert app.called_with_scope is None
        assert sent[0]["status"] == 413


@pytest.mark.django_db(transaction=False)
class TestChunkedBodyPath:
    """No declared ``Content-Length`` -- the chunked-transfer case."""

    def test_chunked_body_over_ceiling_is_aborted_not_fully_consumed(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 10
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        # 3 chunks of 6 bytes = 18 bytes total, over the 10-byte ceiling. The
        # running total crosses 10 after the 2nd chunk (12 > 10), so the 3rd
        # chunk must never be read.
        chunks = [b"x" * 6, b"x" * 6, b"x" * 6]
        calls = 0
        it = iter(chunks)

        async def receive():
            nonlocal calls
            calls += 1
            try:
                body = next(it)
            except StopIteration:
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": body, "more_body": True}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, receive, send))

        assert calls == 2, "must abort as soon as the running total crosses the ceiling"
        # Pass-through, not pre-buffering: the wrapped app *is* invoked from
        # the start (no way to know a length-less body is oversized without
        # reading some of it) -- but it must never see the chunk that tipped
        # the total over the ceiling. That chunk is replaced with a synthetic
        # disconnect, which the app's own read loop (mirroring Django's
        # read_body) treats as an abort with no response of its own.
        assert app.called_with_scope is scope
        assert app.aborted, "the app's read loop must see the synthetic disconnect, not a 3rd chunk"
        assert app.received_messages == [
            {"type": "http.request", "body": b"x" * 6, "more_body": True},
            {"type": "http.disconnect"},
        ]
        assert sent[0]["status"] == 413
        assert "grande demais" in sent[1]["body"].decode()
        # Exactly one response -- the app must not respond again after the abort.
        assert len(sent) == 2

    def test_chunked_body_under_ceiling_passes_through_untouched(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 1024
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        chunks = [b"a" * 100, b"b" * 100]
        it = iter(chunks)

        async def receive():
            try:
                body = next(it)
                return {"type": "http.request", "body": body, "more_body": True}
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, receive, send))

        assert app.called_with_scope is scope
        assert app.received_messages == [
            {"type": "http.request", "body": b"a" * 100, "more_body": True},
            {"type": "http.request", "body": b"b" * 100, "more_body": True},
            {"type": "http.request", "body": b"", "more_body": False},
        ]
        assert sent[0]["status"] == 200

    def test_chunked_body_disconnects_before_completing(self, settings):
        """A client disconnect mid-stream, under the ceiling, must not hang or
        raise -- the disconnect message is buffered and replayed like any
        other, exactly as Django's own read_body would see it directly."""
        settings.MAX_REQUEST_BODY_BYTES = 1024
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        messages = [
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ]
        it = iter(messages)

        async def receive():
            return next(it)

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, receive, send))

        assert app.called_with_scope is scope
        assert app.received_messages == messages

    def test_counting_receive_stays_defensive_if_called_again_after_abort(self, settings):
        """Regression test for counting_receive's defensive early-return: if
        some consumer calls it again after the wrapper has already sent the
        413 and reported one synthetic disconnect, it must keep reporting
        disconnect -- never resume reading, never call the real receive()
        again, never raise. (Real Django never does this: ASGIHandler.handle
        returns immediately once read_body raises RequestAborted. This
        exercises the guard directly rather than leaving it unverified.)
        """
        settings.MAX_REQUEST_BODY_BYTES = 5

        class CallsReceiveTwiceRegardless:
            def __init__(self):
                self.messages = []

            async def __call__(self, scope, receive, send):
                self.messages.append(await receive())  # over the ceiling -> abort
                self.messages.append(await receive())  # calls again anyway

            async def send_response(self, response, send):
                await send(
                    {"type": "http.response.start", "status": response.status_code, "headers": []}
                )
                await send({"type": "http.response.body", "body": response.content})

        app = CallsReceiveTwiceRegardless()
        middleware = request_body_ceiling_asgi(app)

        real_receive_calls = 0

        async def receive():
            nonlocal real_receive_calls
            real_receive_calls += 1
            return {"type": "http.request", "body": b"x" * 10, "more_body": True}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, receive, send))

        assert real_receive_calls == 1, "must not call the real receive() again once aborted"
        assert app.messages == [
            {"type": "http.disconnect"},
            {"type": "http.disconnect"},
        ]
        assert sent[0]["status"] == 413
        assert len(sent) == 2, "the wrapper itself must still send exactly one response"

    def test_counting_receive_is_reentrant_after_the_body_completes(self, settings):
        """Mirrors ASGIHandler.handle's own usage: it passes the *same*
        receive to read_body and to the later, independent
        listen_for_disconnect task (django/core/handlers/asgi.py:175,205) --
        so a second, later call to our wrapped receive, after the body has
        already completed normally, must reach the real underlying receive
        rather than replaying something stale or raising."""
        settings.MAX_REQUEST_BODY_BYTES = 1024

        class TwoPhaseApp:
            def __init__(self):
                self.extra_message = None

            async def __call__(self, scope, receive, send):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect" or not message.get("more_body", False):
                        break
                # A second, independent call -- as listen_for_disconnect makes.
                self.extra_message = await receive()
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

        app = TwoPhaseApp()
        middleware = request_body_ceiling_asgi(app)

        real_messages = [
            {"type": "http.request", "body": b"hi", "more_body": False},
            {"type": "http.disconnect"},
        ]
        it = iter(real_messages)

        async def receive():
            return next(it)

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, receive, send))

        assert app.extra_message == {"type": "http.disconnect"}
        assert sent[0]["status"] == 200

    def test_chunked_body_exactly_at_limit_passes(self, settings):
        settings.MAX_REQUEST_BODY_BYTES = 10
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        chunks = [b"x" * 10, b""]
        it = iter(chunks)

        async def _receive():
            try:
                body = next(it)
            except StopIteration:
                body = b""
            more = body != b""
            return {"type": "http.request", "body": body, "more_body": more}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)
        asyncio.run(middleware(scope, _receive, send))

        assert app.called_with_scope is scope
        assert sent[0]["status"] == 200


class DrainingApp:
    """Reads every message to completion without retaining any of them.

    Deliberately does *not* keep a ``received_messages`` list like
    ``FakeASGIApp`` -- for the memory-amplification test below, the fake app
    itself must not be the thing allocating memory per message, or the
    measurement would say nothing about ``request_body_ceiling_asgi``.
    """

    def __init__(self):
        self.message_count = 0
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        while True:
            message = await receive()
            self.message_count += 1
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class TestChunkedBodyMemory:
    """Reproduces the amplification the fix-round-1 buffering caused.

    A client trickling a body in many tiny ASGI messages must not cost the
    server memory proportional to the *message count* -- only to the body it
    actually declared/received. A byte-sum assertion alone can't catch this
    (the old code summed bytes correctly; it just also kept every message
    dict alive in a list), so this measures actual traced memory.
    """

    def test_many_tiny_chunks_do_not_amplify_memory(self, settings):
        # Ceiling large enough that 100k tiny chunks stay well under it --
        # this must never trip the abort path; it's purely a memory bound on
        # the *legitimate*, still-streaming case.
        settings.MAX_REQUEST_BODY_BYTES = 10_000_000
        app = DrainingApp()
        middleware = request_body_ceiling_asgi(app)

        num_messages = 100_000
        chunk = b"xy"  # 2 bytes/message => ~200 KB of real payload total
        sent_count = 0

        async def receive():
            nonlocal sent_count
            sent_count += 1
            if sent_count > num_messages:
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.request", "body": chunk, "more_body": True}

        sent = []

        async def send(message):
            sent.append(message)

        scope = _scope(content_length=None)

        tracemalloc.start()
        asyncio.run(middleware(scope, receive, send))
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert app.called
        assert app.message_count == num_messages + 1
        assert sent[0]["status"] == 200
        # A per-message buffering implementation costs roughly 150-250 bytes
        # of Python object overhead *per message*, independent of chunk size
        # -- tens of MB for 100k messages (measured on the fix-round-1 code:
        # ~73 MiB for a comparable 400 KB body split into small chunks). A
        # true pass-through wrapper holds at most the one in-flight message,
        # so peak traced memory should stay a low single-digit MB at most.
        assert peak < 5 * 1024 * 1024, (
            f"peak traced memory {peak} bytes ({peak / 1024 / 1024:.1f} MiB) -- "
            "looks like the body is being buffered instead of streamed"
        )


class TestNonHttpScope:
    def test_non_http_scope_passes_straight_through(self, settings):
        """Lifespan/websocket scopes are untouched -- this module only checks HTTP."""
        app = FakeASGIApp()
        middleware = request_body_ceiling_asgi(app)

        async def receive():
            return {"type": "lifespan.startup"}

        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "lifespan"}
        asyncio.run(middleware(scope, receive, send))

        assert app.called_with_scope is scope
