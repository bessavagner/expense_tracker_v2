# Testing conventions

English in tests, pt-BR only inside assertions about user-facing copy. Everything
else here is about time, because time is what breaks this suite.

## A test may not read the wall clock by accident

This product is built around monthly billing cycles, so most interesting
behaviour is "what happens for a month in the future" or "what happens after the
card closes". A test that hardcodes a month and reads `date.today()` passes until
that month goes past, then fails forever — and by then nobody remembers what the
assertion meant.

Three ways to write a date-sensitive test, in order of preference.

### 1. Inject the date

Best when the code under test already takes one. `build_projection`,
`_parse_start`, `monthly_diverse_total_median` and friends all accept `today`:

```python
rows = build_projection(user, date(2026, 7, 1), 1, today=date(2026, 6, 20))
```

No patching, no fixture, obvious at the call site.

### 2. Freeze the clock with `time-machine`

Use when the date is read somewhere you cannot reach — a view, a template tag, a
model default. `time-machine` ships a `time_machine` pytest fixture:

```python
from datetime import UTC, datetime


@pytest.mark.django_db
class TestSomething:
    FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(self.FROZEN_NOW, tick=False)
```

Freeze at **midday UTC**. `date.today()` reads the *system* timezone, not
Django's `TIME_ZONE`, so a midnight freeze lands on different dates on a UTC CI
runner and an America/Sao_Paulo laptop.

Say in the docstring *which requirement* the frozen date makes true. "Frozen to
2026-06-15" is not a reason; "2026-07 has to be a future month for the ceiling
estimator to apply" is.

### 3. Deliberately read the real clock

Legitimate for tests asserting things like "the default month is the current
month". Mark them so the clock-shift runs skip them:

```python
@pytest.mark.current_date
def test_default_month_is_this_month(logged_client):
    ...
```

## Proving the suite is time-stable

`TEST_CLOCK_SHIFT` moves the whole suite's clock (see `src/backend/conftest.py`):

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
TEST_CLOCK_SHIFT=+1m POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
```

All three must produce the same result. The shifted pair belongs on a schedule in
CI, so time rot surfaces on its own nightly cadence rather than during a release.

The `-m "not current_date"` filter exists for the tests described in point 3
above. Nothing carries the marker today — the audit that introduced this harness
(2026-08-09, 906 passed / 2 skipped under all three clocks) found no test that
needed it — but the shifted commands keep the filter so that adding one later
does not also require remembering to change the commands.

Accepted values: `+1d`, `+1m`, `+1y`, `-6m` — a signed integer and one of `d`,
`m`, `y`. Months are 30 days and years are 365; the goal is crossing a boundary,
not modelling a calendar.

**Common failure:** a test passes shifted and fails unshifted. That usually means
it depends on the *current* month having no data, and the shift moved it into an
empty month. Pin the date rather than the data.
