"""Clock-shift parsing for the test harness. See docs/testing-conventions.md."""

import re
from datetime import timedelta

_SHIFT_PATTERN = re.compile(r"^([+-]?\d+)([dmy])$")
# Approximate on purpose: the point is to cross a month or year boundary, not to
# model a calendar. A test that cares about the difference between 30 days and a
# real month is a test that should be pinning its own date anyway.
_UNIT_DAYS = {"d": 1, "m": 30, "y": 365}


def parse_shift(raw: str) -> timedelta:
    """``'+1y'`` -> ``timedelta(days=365)``. Raises ``ValueError`` on anything else."""
    match = _SHIFT_PATTERN.match(raw.strip())
    if match is None:
        raise ValueError(f"TEST_CLOCK_SHIFT must look like +1d, +1m, +1y or -6m; got {raw!r}")
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(days=amount * _UNIT_DAYS[unit])
