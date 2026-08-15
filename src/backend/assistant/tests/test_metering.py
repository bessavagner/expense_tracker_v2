"""The cost ledger. Its cardinal rule: metering never breaks a user's request.

Every test here is a SYNC test that drives the async writer through
``async_to_sync``. That is the suite's established shape (see
``test_views.py::consume_streaming``) and it is load-bearing, not stylistic:
an ``async def`` test under ``django_db`` runs its ORM calls on a *different*
connection from the one holding pytest-django's uncommitted fixture
transaction, so the household and user fixtures are invisible to it and every
insert dies on a foreign-key violation. ``async_to_sync`` runs the coroutine on
the calling thread, which is what routes Django's ``thread_sensitive`` ORM work
back to the connection that can see them.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync

from assistant.metering import Timer, record_usage
from assistant.models import ModelPrice, UsageKind, UsageRecord

pytestmark = pytest.mark.django_db


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest.fixture
def priced():
    from assistant.pricing import clear_price_cache

    clear_price_cache()
    ModelPrice.objects.create(
        model_name="openai:test",
        input_per_mtok=Decimal("1.00"),
        output_per_mtok=Decimal("10.00"),
        effective_from=date(2020, 1, 1),
        source_url="https://example.test/pricing",
        checked_on=date(2020, 1, 1),
    )
    yield
    clear_price_cache()


def test_a_record_captures_tokens_and_cost(household, user, priced):
    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.CHAT,
        model="openai:test",
        usage=FakeUsage(1_000_000, 100_000),
        latency_ms=1234,
        ok=True,
    )
    rec = UsageRecord.objects.get()
    assert rec.input_tokens == 1_000_000
    assert rec.output_tokens == 100_000
    assert rec.cost_usd == Decimal("2.000000")
    assert rec.latency_ms == 1234
    assert rec.ok is True


def test_a_failed_call_is_still_recorded(household, user, priced):
    """A failed vision call costs money. S07-2."""
    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.EXTRACTION,
        model="openai:test",
        usage=None,
        latency_ms=900,
        ok=False,
    )
    rec = UsageRecord.objects.get()
    assert rec.ok is False
    assert rec.input_tokens is None
    assert rec.cost_usd is None


def test_records_sharing_one_action_are_correlated(household, user, interaction, priced):
    """S07-1: a receipt costing three calls is analysable as one event."""
    for kind in (UsageKind.EXTRACTION, UsageKind.EXTRACTION, UsageKind.CHAT):
        async_to_sync(record_usage)(
            interaction=interaction,
            household=household,
            user=user,
            kind=kind,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=10,
            ok=True,
        )
    assert UsageRecord.objects.filter(interaction=interaction).count() == 3


def test_a_metering_failure_never_reaches_the_caller(household, user, priced):
    """S07-1: writing a usage record must never fail the user's request."""
    with patch(
        "assistant.models.UsageRecord.objects.acreate",
        side_effect=RuntimeError("database on fire"),
    ):
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.CHAT,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=1,
            ok=True,
        )  # must not raise
    assert UsageRecord.objects.count() == 0


def test_a_metering_failure_is_reported_not_swallowed(household, user, priced):
    """Silent is worse than loud: E06 S06-4 exists because of exactly this."""
    with (
        patch(
            "assistant.models.UsageRecord.objects.acreate",
            side_effect=RuntimeError("database on fire"),
        ),
        patch("assistant.metering.sentry_sdk.capture_exception") as capture,
    ):
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.CHAT,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=1,
            ok=True,
        )
    assert capture.called


def test_a_successful_write_reports_nothing(household, user, priced):
    """The counterpart to the two tests above, and not redundant with them.

    `record_usage` reports instead of raising, so a *programming* error inside
    it — the original version called the synchronous `cost_usd_for` from a
    coroutine, which raises SynchronousOnlyOperation — presents as a cost
    ledger that quietly stays empty rather than as a failure. Asserting the
    happy path is silent is what turns that back into a red test.
    """
    with patch("assistant.metering.sentry_sdk.capture_exception") as capture:
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.CHAT,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=1,
            ok=True,
        )
    assert not capture.called
    assert UsageRecord.objects.count() == 1


def test_an_interactionless_call_is_still_metered(household, priced):
    """An embedding can be triggered outside a chat turn. FK is nullable."""
    async_to_sync(record_usage)(
        household=household,
        kind=UsageKind.EMBEDDING,
        model="openai:test",
        usage=FakeUsage(500, 0),
        latency_ms=42,
        ok=True,
    )
    rec = UsageRecord.objects.get()
    assert rec.interaction_id is None
    assert rec.user_id is None


def test_an_unpriced_model_records_tokens_but_no_cost(household, user):
    """Tokens are still worth having when the price is not. S07-5 counts these
    separately rather than summing them as zero."""
    async_to_sync(record_usage)(
        household=household,
        user=user,
        kind=UsageKind.TRANSCRIPTION,
        model="whisper-1",
        usage=FakeUsage(300, 0),
        latency_ms=5,
        ok=True,
    )
    rec = UsageRecord.objects.get()
    assert rec.input_tokens == 300
    assert rec.cost_usd is None


def test_timer_reports_elapsed_milliseconds():
    with Timer() as t:
        pass
    assert isinstance(t.ms, int)
    assert t.ms >= 0


class TestTheChatRunIsMetered:
    """S07-2 for the largest call site: every agent run leaves a cost row.

    The two endpoint tests prove the wiring; the rest drive `_sse_response`
    directly with a scripted agent, because `agent.override(model=...)` cannot
    express "die after the first token" or "answer differently on the second
    attempt".
    """

    def _stream(self, scope, agent, **kwargs):
        from assistant.tests.test_views import consume_streaming
        from assistant.views import _sse_response

        return consume_streaming(_sse_response(scope, agent, "oi", message_history=None, **kwargs))

    def _scope_with(self, household, user, interaction):
        from assistant.agents.scope import AgentScope

        return AgentScope(household=household, user=user, interaction=interaction)

    def test_a_chat_turn_produces_one_usage_record(self, logged_client, user, household, settings):
        import json as _json

        from pydantic_ai.models.test import TestModel

        from assistant.agents.assistant import agents_override
        from assistant.tests.test_views import consume_streaming

        with agents_override(TestModel()):
            resp = logged_client.post(
                "/api/assistant/chat/",
                data=_json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            consume_streaming(resp)

        # Filtered by kind rather than `.get()`: `TestModel` calls every tool,
        # and `check_memory` reaches the embedding service, which is metered too.
        rec = UsageRecord.objects.get(kind=UsageKind.CHAT)
        assert rec.ok is True
        # Correlated back to the action that authorised it (S07-1), and stamped
        # with the tier the chokepoint picked, not with whatever the agent was
        # constructed with.
        assert rec.interaction_id is not None
        assert rec.model == settings.LLM_TIER_ADVANCED
        assert rec.latency_ms is not None

    def test_the_record_belongs_to_the_household_that_asked(
        self, logged_client, user, household, other_household
    ):
        import json as _json

        from pydantic_ai.models.test import TestModel

        from assistant.agents.assistant import agents_override
        from assistant.tests.test_views import consume_streaming

        with agents_override(TestModel()):
            resp = logged_client.post(
                "/api/assistant/chat/",
                data=_json.dumps({"message": "oi"}),
                content_type="application/json",
            )
            consume_streaming(resp)

        assert {r.household_id for r in UsageRecord.objects.all()} == {household.id}

    def test_a_failed_chat_run_is_still_recorded(self, household, user, interaction, priced):
        """The provider consumed tokens before dying. Those are billed."""
        from assistant.tests.fakes import FakeAgent, FakeStream

        agent = FakeAgent({"openai:test": FakeStream(["nada"], fail_after=0)})
        body = self._stream(
            self._scope_with(household, user, interaction), agent, model="openai:test"
        )

        assert '"type": "error"' in body
        rec = UsageRecord.objects.get()
        assert rec.ok is False
        assert rec.cost_usd is None
        assert rec.interaction_id == interaction.id

    def test_a_fallback_retry_records_both_attempts(self, household, user, interaction, priced):
        """Otherwise the free tier looks cheaper than it is: the failed first
        attempt is a real provider call with a real bill."""
        from assistant.tests.fakes import FakeAgent, FakeStream

        agent = FakeAgent(
            {
                "openai:test": FakeStream(["nada"], fail_after=0),
                "openai:cheap": FakeStream(["ok"]),
            }
        )
        self._stream(
            self._scope_with(household, user, interaction),
            agent,
            model="openai:test",
            fallback_model="openai:cheap",
        )

        assert UsageRecord.objects.filter(interaction=interaction).count() == 2
        assert UsageRecord.objects.get(model="openai:test").ok is False
        assert UsageRecord.objects.get(model="openai:cheap").ok is True

    def test_the_recorded_cost_uses_the_model_that_actually_ran(
        self, household, user, interaction, priced
    ):
        from assistant.tests.fakes import FakeAgent, FakeStream, FakeUsage

        agent = FakeAgent({"openai:test": FakeStream(["ok"], usage=FakeUsage(1_000_000, 100_000))})
        self._stream(self._scope_with(household, user, interaction), agent, model="openai:test")

        rec = UsageRecord.objects.get()
        assert rec.input_tokens == 1_000_000
        assert rec.cost_usd == Decimal("2.000000")

    def test_a_metering_failure_does_not_break_the_stream(
        self, household, user, interaction, priced
    ):
        """The module's cardinal rule, asserted end-to-end rather than on the
        writer alone: the user still gets their answer."""
        from assistant.tests.fakes import FakeAgent, FakeStream

        agent = FakeAgent({"openai:test": FakeStream(["tudo certo"])})
        with patch(
            "assistant.models.UsageRecord.objects.acreate",
            side_effect=RuntimeError("database on fire"),
        ):
            body = self._stream(
                self._scope_with(household, user, interaction), agent, model="openai:test"
            )

        assert "tudo certo" in body
        assert '"type": "error"' not in body


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
    b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestExtractionIsMetered:
    def _post_image(self, logged_client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from assistant.tests.test_views import consume_streaming

        image = SimpleUploadedFile("recibo.png", _PNG, content_type="image/png")
        resp = logged_client.post("/api/assistant/chat/", data={"image": image})
        consume_streaming(resp)
        return resp

    def test_a_receipt_photo_correlates_extraction_and_chat(
        self, logged_client, user, household, priced
    ):
        """DoD: one photo, several provider calls, all analysable as one event."""
        from pydantic_ai.models.test import TestModel

        from assistant.agents.assistant import assistant_agent
        from assistant.agents.extraction import extraction_agent
        from assistant.models import UsageInteraction

        with (
            extraction_agent.override(model=TestModel()),
            assistant_agent.override(model=TestModel()),
        ):
            self._post_image(logged_client)

        interaction = UsageInteraction.objects.get()
        kinds = set(
            UsageRecord.objects.filter(interaction=interaction).values_list("kind", flat=True)
        )
        assert UsageKind.EXTRACTION in kinds
        assert UsageKind.CHAT in kinds

    def test_the_vision_retry_produces_a_second_extraction_record(
        self, logged_client, user, household, monkeypatch, priced
    ):
        """The expensive retry is a separate billable call, and the attempt that
        failed is billable too — the provider read the image either way."""
        from pydantic_ai.models.test import TestModel

        from assistant.agents import extraction as extraction_module
        from assistant.agents.assistant import assistant_agent
        from assistant.agents.extraction import ReceiptExtraction
        from assistant.tests.fakes import FakeRunResult

        async def flaky_run(prompt, model=None, model_settings=None):
            if model is None:
                raise RuntimeError("primeira extração falha")
            return FakeRunResult(ReceiptExtraction())

        monkeypatch.setattr(extraction_module.extraction_agent, "run", flaky_run)
        with assistant_agent.override(model=TestModel()):
            self._post_image(logged_client)

        extractions = UsageRecord.objects.filter(kind=UsageKind.EXTRACTION)
        assert extractions.count() == 2
        assert sorted(extractions.values_list("ok", flat=True)) == [False, True]

    def test_extraction_outside_a_request_is_not_metered(self):
        """`extract_receipt` is called by eval harnesses with no household. A
        record with no tenant is worse than no record — it cannot be scoped,
        reported, or billed to anyone."""
        from asgiref.sync import async_to_sync
        from pydantic_ai.models.test import TestModel

        from assistant.agents.extraction import extract_receipt, extraction_agent

        with extraction_agent.override(model=TestModel()):
            async_to_sync(extract_receipt)([(_PNG, "image/png")])

        assert UsageRecord.objects.count() == 0


class TestTranscriptionIsMetered:
    def test_the_transcription_fallback_bills_twice(self, household, user, settings):
        """DoD: the fallback loop bills twice when the primary rejects the audio.

        The failed attempt is a real request the provider processed and charged
        for; counting only the success makes the browser's webm/opus problem
        look free.
        """
        from types import SimpleNamespace

        from assistant.agents.scope import AgentScope
        from assistant.services.transcription import transcribe_audio

        settings.LLM_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
        settings.LLM_TRANSCRIBE_FALLBACK_MODEL = "whisper-1"

        class FallbackTranscriptions:
            async def create(self, **kwargs):
                if kwargs["model"] == "gpt-4o-mini-transcribe":
                    raise RuntimeError("Audio file might be corrupted or unsupported")
                return SimpleNamespace(text="mercado 80 no pix")

        client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FallbackTranscriptions()))
        async_to_sync(transcribe_audio)(
            b"\x00",
            "nota.webm",
            "audio/webm",
            client=client,
            scope=AgentScope(household=household, user=user),
        )

        assert UsageRecord.objects.filter(kind=UsageKind.TRANSCRIPTION).count() == 2
        assert UsageRecord.objects.get(model="gpt-4o-mini-transcribe").ok is False
        assert UsageRecord.objects.get(model="whisper-1").ok is True

    def test_transcription_cost_is_null_not_zero(self, household, user):
        """Providers price transcription per MINUTE of audio; ModelPrice models
        tokens. The gap is declared (see `test_pricing_gaps_are_declared`), and
        a zero here would look like a measurement instead of a hole."""
        from types import SimpleNamespace

        from assistant.agents.scope import AgentScope
        from assistant.services.transcription import transcribe_audio

        class Transcriptions:
            async def create(self, **kwargs):
                return SimpleNamespace(text="oi")

        client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
        async_to_sync(transcribe_audio)(
            b"\x00",
            "nota.webm",
            "audio/webm",
            client=client,
            scope=AgentScope(household=household, user=user),
        )

        assert UsageRecord.objects.get().cost_usd is None

    def test_transcription_without_a_scope_is_not_metered(self, household, user):
        from types import SimpleNamespace

        from assistant.services.transcription import transcribe_audio

        class Transcriptions:
            async def create(self, **kwargs):
                return SimpleNamespace(text="oi")

        client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
        async_to_sync(transcribe_audio)(b"\x00", "nota.webm", "audio/webm", client=client)
        assert UsageRecord.objects.count() == 0

    def test_the_audio_turn_meters_its_transcription(
        self, logged_client, user, household, monkeypatch
    ):
        """The wiring: `chat_view` must hand the scope down, or every real
        transcription in production goes unbilled while the unit test passes."""
        from types import SimpleNamespace

        from django.core.files.uploadedfile import SimpleUploadedFile
        from pydantic_ai.models.test import TestModel

        from assistant.agents.assistant import agents_override
        from assistant.tests.test_views import consume_streaming

        class Transcriptions:
            async def create(self, **kwargs):
                return SimpleNamespace(text="mercado 80 no pix")

        monkeypatch.setattr(
            "assistant.services.transcription._get_client",
            lambda: SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions())),
        )

        audio = SimpleUploadedFile("nota.webm", b"\x00\x01", content_type="audio/webm")
        with agents_override(TestModel()):
            resp = logged_client.post("/api/assistant/chat/", data={"audio": audio})
            consume_streaming(resp)

        rec = UsageRecord.objects.get(kind=UsageKind.TRANSCRIPTION)
        assert rec.interaction_id is not None


class TestEmbeddingIsMetered:
    def _fake_response(self, prompt_tokens=5):
        from types import SimpleNamespace

        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1] * 1536)],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
        )

    def test_an_embedding_is_metered(self, household, user):
        from unittest.mock import AsyncMock

        from assistant.agents.scope import AgentScope
        from assistant.services.embedding import get_embedding

        with patch("assistant.services.embedding.async_client") as client:
            client.embeddings.create = AsyncMock(return_value=self._fake_response())
            async_to_sync(get_embedding)("oi", scope=AgentScope(household=household, user=user))

        rec = UsageRecord.objects.get(kind=UsageKind.EMBEDDING)
        assert rec.model == "text-embedding-3-small"

    def test_the_embedding_token_count_is_not_silently_zero(self, household, user):
        """OpenAI's embeddings endpoint names them `prompt_tokens`, not
        `input_tokens`. Reading the wrong attribute records a real call as zero
        tokens, which is indistinguishable from a free one."""
        from unittest.mock import AsyncMock

        from assistant.agents.scope import AgentScope
        from assistant.services.embedding import get_embedding

        with patch("assistant.services.embedding.async_client") as client:
            client.embeddings.create = AsyncMock(return_value=self._fake_response(742))
            async_to_sync(get_embedding)("oi", scope=AgentScope(household=household, user=user))

        assert UsageRecord.objects.get().input_tokens == 742

    def test_a_failed_embedding_is_recorded(self, household, user):
        from unittest.mock import AsyncMock

        from assistant.agents.scope import AgentScope
        from assistant.services.embedding import get_embedding

        with patch("assistant.services.embedding.async_client") as client:
            client.embeddings.create = AsyncMock(side_effect=Exception("API error"))
            result = async_to_sync(get_embedding)(
                "oi", scope=AgentScope(household=household, user=user)
            )

        assert result is None  # the contract callers rely on is unchanged
        assert UsageRecord.objects.get().ok is False

    def test_an_embedding_without_a_scope_is_not_metered(self):
        from unittest.mock import AsyncMock

        from assistant.services.embedding import get_embedding

        with patch("assistant.services.embedding.async_client") as client:
            client.embeddings.create = AsyncMock(return_value=self._fake_response())
            async_to_sync(get_embedding)("oi")

        assert UsageRecord.objects.count() == 0


def test_no_unmetered_provider_call_site_exists():
    """The ratchet. E07 DoD: fails if a new unmetered call site is added.

    Every module that reaches a provider must import `record_usage`. Coarse on
    purpose — a precise AST check would be brittle, and coarse-but-loud beats
    precise-but-skipped. If you are adding a legitimate new call site, meter it;
    if you genuinely cannot, add it to EXEMPT with a comment saying why.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    CALL = re.compile(
        r"\.(run_stream|run)\(|"
        r"client\.audio\.transcriptions\.create\(|"
        r"\.embeddings\.create\("
    )

    # The E08 evaluation harness (dev-only, gated on RUN_LLM_TESTS=1, never
    # reachable from a request). It must NOT meter: `UsageRecord` is scoped to a
    # household, and a harness run has no household — it invents a throwaway one
    # inside a transaction that is always rolled back. A cost row nobody can be
    # charged for would pollute the very ledger the pricing decisions are read
    # from. See `assistant/eval/costing.py`, which prices these runs separately.
    EXEMPT = {
        "assistant/eval/extraction_runner.py",
        "assistant/eval/behaviour_runner.py",
    }

    offenders = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        # Test modules make deliberate unmetered calls through doubles, and
        # migrations never reach a provider at all.
        if "/tests/" in f"/{rel}" or "/migrations/" in rel or rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        if CALL.search(text) and "record_usage" not in text:
            offenders.append(rel)

    assert not offenders, "Unmetered provider call sites (E07 S07-2):\n  " + "\n  ".join(offenders)

    # A stale exemption is a hole in the ratchet: rename or delete an exempt
    # module and the name silently stops matching anything, so the next call
    # site added under that path is never checked.
    for rel in EXEMPT:
        assert (root / rel).exists(), f"stale EXEMPT entry, no such file: {rel}"


class TestEscalationIsRecorded:
    """E09's DoD needs the escalation RATE and its causes, per attempt.

    A column rather than a derived count: two EXTRACTION records sharing one
    interaction could equally be a quality escalation or a retry after a
    transient 500, and counting cannot separate them.
    """

    def test_a_normal_call_records_no_reason(self, household, user, priced):
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.EXTRACTION,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=10,
            ok=True,
        )
        record = UsageRecord.objects.get()
        assert record.escalation_reason == ""

    def test_an_escalated_call_records_why(self, household, user, priced):
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.EXTRACTION,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=10,
            ok=True,
            escalation_reason="low_confidence",
        )
        record = UsageRecord.objects.get()
        assert record.escalation_reason == "low_confidence"

    def test_a_failed_escalation_is_still_recorded_as_an_escalation(self, household, user, priced):
        """A failed escalation still cost money and still counts against the rate."""
        async_to_sync(record_usage)(
            household=household,
            user=user,
            kind=UsageKind.EXTRACTION,
            model="openai:test",
            usage=None,
            latency_ms=10,
            ok=False,
            escalation_reason="inconsistent",
        )
        record = UsageRecord.objects.get()
        assert record.ok is False
        assert record.escalation_reason == "inconsistent"
