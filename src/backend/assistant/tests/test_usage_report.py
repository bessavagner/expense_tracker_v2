"""The operator report — the numbers a price has to clear."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _record(household, cost, kind="chat"):
    from assistant.models import UsageRecord

    return UsageRecord.objects.create(
        household=household,
        kind=kind,
        model="openai:test",
        cost_usd=None if cost is None else Decimal(cost),
    )


def _run(*args):
    out = StringIO()
    call_command("usage_report", *args, stdout=out)
    return out.getvalue()


def test_the_report_totals_cost_per_household(household):
    _record(household, "1.00")
    _record(household, "2.50")
    assert "3.50" in _run()


def test_the_report_shows_p50_p90_and_p99(household, other_household):
    """S07-5: the numbers a price must clear."""
    for _ in range(10):
        _record(household, "1.00")
    _record(other_household, "50.00")
    text = _run()
    assert "p50" in text and "p90" in text and "p99" in text


def test_the_percentiles_run_over_households_not_records(household, other_household):
    """One heavy house among many light ones must show up at p99, and the
    light house's ten cheap calls must not drag the percentile down with it."""
    for _ in range(10):
        _record(household, "1.00")
    _record(other_household, "50.00")
    text = _run()
    assert "p50          : 10.00" in text
    assert "p99          : 50.00" in text


def test_the_report_breaks_cost_down_by_kind(household):
    """S07-5: what does receipt OCR cost relative to text chat?"""
    _record(household, "0.10", kind="chat")
    _record(household, "4.00", kind="extraction")
    text = _run("--by-kind")
    assert "extraction" in text and "chat" in text


def test_the_kind_breakdown_is_off_by_default(household):
    _record(household, "4.00", kind="extraction")
    assert "por tipo" not in _run()


def test_the_report_counts_unpriced_records_instead_of_hiding_them(household):
    """A null cost is a KNOWN gap. Silently summing it as zero is a lie."""
    _record(household, None, kind="transcription")
    assert "sem preço" in _run()


def test_a_fully_priced_period_does_not_mention_the_gap(household):
    """The counterpart: the warning must mean something when it appears."""
    _record(household, "1.00")
    assert "sem preço" not in _run()


def test_the_report_respects_the_date_window(household):
    _record(household, "9.99")
    assert "9.99" not in _run("--since", "2099-01-01")


def test_an_empty_period_reports_zero_households_rather_than_crashing(household):
    """The percentile helper is handed an empty list on a quiet day."""
    text = _run("--since", "2099-01-01")
    assert "casas ativas : 0" in text
