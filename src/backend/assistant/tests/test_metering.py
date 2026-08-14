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
