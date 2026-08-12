"""The suite-wide clock shift must actually shift the clock.

A harness that silently does nothing is worse than no harness: the suite would
report "passes a year from now" while testing today.
"""

import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import time_machine

from core.clock import parse_shift

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class TestParseShift:
    def test_days(self):
        assert parse_shift("+3d") == timedelta(days=3)

    def test_months_are_thirty_days(self):
        assert parse_shift("+1m") == timedelta(days=30)

    def test_years_are_three_hundred_sixty_five_days(self):
        assert parse_shift("+1y") == timedelta(days=365)

    def test_negative_shift(self):
        assert parse_shift("-6m") == timedelta(days=-180)

    def test_bare_number_is_rejected(self):
        with pytest.raises(ValueError, match="TEST_CLOCK_SHIFT"):
            parse_shift("7")

    def test_unknown_unit_is_rejected(self):
        with pytest.raises(ValueError, match="TEST_CLOCK_SHIFT"):
            parse_shift("+1w")


def test_shift_moves_date_today_in_a_real_pytest_run(tmp_path):
    """End-to-end: run a throwaway test under the shift and read what it saw.

    A subprocess, because the harness is an autouse fixture — it is already
    applied to the test you are reading, and asserting on it from inside itself
    proves nothing.
    """
    probe = BACKEND_DIR / "core" / "tests" / "test_zz_clock_probe.py"
    probe.write_text(
        "from datetime import date\n"
        "def test_probe():\n"
        "    print('PROBE_TODAY', date.today().isoformat())\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, trusted input
            [sys.executable, "-m", "pytest", str(probe), "-q", "-s", "-p", "no:randomly"],
            cwd=BACKEND_DIR.parent.parent,
            env={**_clean_env(), "TEST_CLOCK_SHIFT": "+1y"},
            capture_output=True,
            text=True,
        )
    finally:
        probe.unlink(missing_ok=True)

    expected = (_real_utc_today() + timedelta(days=365)).isoformat()
    assert f"PROBE_TODAY {expected}" in result.stdout, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def _real_utc_today() -> date:
    """The actual system date **in UTC**, even when this test runs inside an
    ambient TEST_CLOCK_SHIFT (the audit does exactly that).

    UTC, not local: ``shifted_clock`` travels to a timezone-aware UTC instant,
    and ``time_machine`` activates the destination's timezone, so the probe's
    ``date.today()`` reads the UTC date. Comparing against the *local* date
    made this test fail for the three hours a night when UTC-3 and UTC are on
    different days — a time bomb in the very harness that exists to defuse them.

    ``shifted_clock`` is autouse and wraps this test too, so a plain
    ``datetime.now`` here would read the *outer* shift instead of the real
    clock the subprocess is measured against.
    """
    if time_machine.escape_hatch.is_travelling():
        return time_machine.escape_hatch.datetime.datetime.now(UTC).date()
    return datetime.now(UTC).date()


def _clean_env():
    import os

    env = dict(os.environ)
    env.setdefault("POSTGRES_PORT", "5433")
    env.pop("TEST_CLOCK_SHIFT", None)
    return env
