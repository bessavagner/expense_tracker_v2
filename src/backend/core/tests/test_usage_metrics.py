"""The daily aggregate line Cloud Logging turns into dashboard tiles."""

import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _run(*args):
    out = StringIO()
    call_command("emit_usage_metrics", *args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def _yesterday():
    return (timezone.localtime() - timedelta(days=1)).date()


def _turn(household, user, when=None):
    from assistant.models import InteractionKind, UsageInteraction

    row = UsageInteraction.objects.create(household=household, user=user, kind=InteractionKind.TEXT)
    if when is not None:
        # `auto_now_add` ignores an assigned value, so the timestamp is moved
        # with an UPDATE after the insert.
        UsageInteraction.objects.filter(pk=row.pk).update(created_at=when)
    return row


def _record(household, cost, when=None):
    from assistant.models import UsageRecord

    row = UsageRecord.objects.create(
        household=household, kind="chat", model="openai:test", cost_usd=Decimal(cost)
    )
    if when is not None:
        UsageRecord.objects.filter(pk=row.pk).update(created_at=when)
    return row


def test_it_emits_one_parseable_json_line(household, user):
    day = _yesterday()
    noon = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
    noon += timedelta(hours=12)
    _turn(household, user, noon)
    _record(household, "1.50", noon)

    payload = _run()
    assert payload["metric"] == "assistant_usage_daily"
    assert payload["day"] == day.isoformat()
    assert payload["turns"] == 1
    assert Decimal(payload["cost_usd"]) == Decimal("1.50")


def test_a_quiet_day_still_emits_zeroes():
    """A missing line is indistinguishable from a broken job. Emit zeroes."""
    payload = _run()
    assert payload["turns"] == 0
    assert Decimal(payload["cost_usd"]) == Decimal("0")


def test_today_is_not_counted_yet(household, user):
    """The default window is YESTERDAY, whole and closed. Counting a partial
    today would make the newest point on the dashboard always dip."""
    _turn(household, user)  # created now
    _record(household, "9.99")
    assert _run()["turns"] == 0


def test_an_explicit_day_selects_that_window(household, user):
    when = timezone.make_aware(
        timezone.datetime.combine(date(2026, 3, 14), timezone.datetime.min.time())
    ) + timedelta(hours=9)
    _turn(household, user, when)
    _record(household, "2.25", when)

    payload = _run("--day", "2026-03-14")
    assert payload["day"] == "2026-03-14"
    assert payload["turns"] == 1
    assert Decimal(payload["cost_usd"]) == Decimal("2.25")


def test_an_unpriced_record_does_not_break_the_sum(household, user):
    """Transcription records carry cost_usd=NULL. Sum() skips them; the line
    must still be emitted rather than crashing or printing 'None'."""
    from assistant.models import UsageRecord

    day = _yesterday()
    when = timezone.make_aware(
        timezone.datetime.combine(day, timezone.datetime.min.time())
    ) + timedelta(hours=3)
    row = UsageRecord.objects.create(
        household=household, kind="transcription", model="whisper-1", cost_usd=None
    )
    UsageRecord.objects.filter(pk=row.pk).update(created_at=when)

    payload = _run()
    assert Decimal(payload["cost_usd"]) == Decimal("0")


def test_the_line_carries_every_field_the_metric_extracts(household):
    """The log-based metrics in the runbook EXTRACT these exact keys. Renaming
    one silently flatlines a dashboard tile instead of failing."""
    assert set(_run()) == {"metric", "day", "turns", "cost_usd"}
