# E02 · Suite Integrity & CI Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The test suite is green, cannot rot with the passage of wall-clock time, and CI catches the classes of mistake that E04 (household tenancy) and E08 (evaluation harness) would otherwise let through silently.

**Architecture:** Three layers. (1) A time-freezing dependency (`time-machine`) and a fixture on the three projection tests that encode a "future month" requirement, so the requirement stays tested instead of expiring. (2) A suite-wide opt-in clock shift driven by a `TEST_CLOCK_SHIFT` env var and a new root `conftest.py`, so "does this suite still pass next year" becomes a command anyone can run rather than a discovery made during a release. (3) CI gates for the failure modes CI does not currently see — a missing migration, a `check --deploy` regression, a frontend type error, and committed build artifacts that have drifted from their source — plus a nightly scheduled run that exercises the shifted clock.

**Tech Stack:** pytest + pytest-django + pytest-bdd + model-bakery, `time-machine` (new dev dependency), Django 6.0, GitHub Actions, `uv`, Ruff, pnpm + Vite + TypeScript for the React islands, `django-tailwind-cli` for the CSS.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7. Violating any of these fails review even if every task's tests pass.

- **TDD.** Test first, always. In this epic the "test" is often a meta-property: prove the suite is time-stable by shifting the clock and watching it fail before the fix.
- **Worktrees.** Feature work happens in an isolated worktree.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean. Line length 100, double quotes, `target-version = "py312"`.
- **pt-BR in the product UI, English in code, comments, and docs.**
- **Migrations are reversible.** (No migrations in this epic — but the new CI gate enforces that none are *missing*.)
- **No time-bomb tests.** This epic is where that constraint gets its teeth.
- **Tests run against the local pgvector container on port 5433**: prefix every pytest invocation with `POSTGRES_PORT=5433`.

### Out of scope — do not drag these in

- Adding *new* feature tests. This epic makes the existing suite trustworthy; it does not grow coverage.
- The AI evaluation harness → **E08**
- An automated deploy pipeline → **E16**. This epic adds *checks*, not deployment.
- Refactoring the projection feature itself.

### The one thing an agent will be tempted to do wrong

`finances/tests/test_views_projection.py::TestEstimateToggle::test_teto_param_uses_ceiling` fails today. It is **tempting and wrong** to delete it, relax the assertion, or change `2026-07` to whatever month is currently in the future. The requirement it encodes — *the ceiling estimator applies to future months* — is real. Freeze time so it stays tested.

---

## The bug, precisely

Verified at `HEAD` on 2026-08-08:

```
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_views_projection.py -q
→ 1 failed, 16 passed

>       assert resp.context["rows"][0]["diverse_estimated"] == Decimal("9999")
E       AssertionError: assert Decimal('0') == Decimal('9999')
```

Whole suite at `HEAD`, same day — the single failure is this one:

```
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
→ 1 failed, 820 passed, 2 skipped, 284 warnings in 42.98s
```

(The epic records `1 failed, 818 passed, 2 skipped` at its baseline commit
`3bbc5ca`; two tests have landed since. The failure is the same one.)

The mechanism, in `src/backend/finances/services/projection.py:163-170`:

```python
if m < current_month:
    diverse_estimated = diverse          # posted reality
elif m == current_month:
    diverse_estimated = max(diverse, est_typical_diverse)
else:
    diverse_estimated = est_typical_diverse   # the estimator under test
```

`current_month` comes from `today` (`projection.py:69-71`), which `build_projection_context` fills with a live `date.today()` (`finances/views/projection.py:111`). The test requests `start=2026-07`. On 2026-08-08, `2026-07 < 2026-08`, so the branch under test is never reached and `diverse_estimated` is the posted `Decimal("0")`. The test passed every day up to 2026-07-31 and has failed every day since.

Its two siblings, `test_default_is_median` and `test_estimate_persists_in_session`, use the same `start=2026-07` and only assert on `context["estimate"]`, which does not depend on the date. They pass today by luck and are latent failures — the epic requires converting them the same way rather than leaving them.

---

## Decisions this plan locks in

**Open question 1 — `time-machine` or `freezegun`?** `time-machine`. It patches at the C level, so it is roughly an order of magnitude faster per test, it correctly intercepts `datetime.date.today()` (which is what this codebase calls), and it ships a `time_machine` pytest fixture that composes with pytest classes without the decorator gymnastics `freezegun` needs. Use it consistently — a second time library is a bug generator.

**Open question 2 — how should CI verify committed artifacts?** Decided by measurement in Task 4, Step 1, not by assumption. Rebuild-and-`git diff --exit-code` if the Vite and Tailwind builds prove byte-stable across two runs; a committed source-hash sentinel if they do not. Both branches are written out in full — run the probe, take the branch, delete the other from your notes.

**Open question 3 — should the frontend artifacts stay committed?** Yes, they stay. They exist so local dev and the Docker build work without a Node toolchain, and `whitenoise` serves them straight from `STATICFILES_DIRS`. Removing them would make every backend-only contributor install pnpm to see a page render, in exchange for a drift risk that Task 4 closes directly. Revisit only when the deploy pipeline builds assets itself (E16).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` (modify) | Add `time-machine` to the dev group; add `assistant` to the isort first-party list |
| `src/backend/core/clock.py` (create) | `parse_shift` — the pure parser, in an importable module rather than in a conftest |
| `src/backend/conftest.py` (create) | The suite-wide `TEST_CLOCK_SHIFT` fixture. Root-level so it applies to every app |
| `src/backend/finances/tests/test_views_projection.py` (modify) | Freeze the clock for `TestEstimateToggle` |
| `docs/testing-conventions.md` (create) | Where the project records how to write a date-sensitive test |
| `README.md` (modify) | Point at the conventions doc; stop asserting a test count that goes stale |
| `.github/workflows/ci.yml` (modify) | Migration check, deploy check, frontend job, artifact-drift gate, nightly schedule |
| `src/backend/core/tests/test_clock_harness.py` (create) | Proves the shift harness actually shifts |

---

### Task 1: Freeze the clock in the projection estimate tests

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups] dev`)
- Modify: `src/backend/finances/tests/test_views_projection.py:127-148`

**Interfaces:**
- Consumes: nothing.
- Produces: `time-machine` available to every test module, and its `time_machine` pytest fixture (`time_machine.move_to(destination, tick: bool)`) usable from any test. Task 2 depends on the dependency being present.

- [ ] **Step 1: Reproduce the failure, so you know what green means**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_views_projection.py::TestEstimateToggle -v
```

Expected: `test_teto_param_uses_ceiling` FAILS with `AssertionError: assert Decimal('0') == Decimal('9999')`; the other two PASS.

- [ ] **Step 2: Add the dependency**

In `pyproject.toml`, add to the `dev` list in `[dependency-groups]`:

```toml
dev = [
    "coverage>=7.13.4",
    "pre-commit>=4.5.1",
    "pytest>=9.0.2",
    "pytest-django>=4.12.0",
    "pytest-bdd>=8.0",
    "model-bakery>=1.20",
    "ruff>=0.15.4",
    "anyio>=4.13.0",
    "pytest-anyio>=0.0.0",
    "time-machine>=2.16",
]
```

Then:

```bash
uv sync
uv run python -c "import time_machine; print(time_machine.__version__)"
```

Expected: a version at or above `2.16`.

- [ ] **Step 3: Write the frozen version of the tests**

Replace the whole `TestEstimateToggle` class in `src/backend/finances/tests/test_views_projection.py` (lines 127-148) with:

```python
@pytest.mark.django_db
class TestEstimateToggle:
    """The estimator toggle, pinned to a fixed "today".

    ``start=2026-07`` has to be a FUTURE month for the ceiling estimator to
    apply at all — ``build_projection`` uses posted reality for past months and
    the estimator only for months after the current one
    (``finances/services/projection.py:163-170``). Reading the real clock made
    that true until 2026-07-31 and false every day after, so the requirement
    stopped being tested exactly when it started to matter.

    Frozen at midday UTC so the date is unambiguous whether the runner is on
    UTC (CI) or America/Sao_Paulo (dev) — ``date.today()`` reads the system
    timezone, not Django's ``TIME_ZONE``.
    """

    FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(self.FROZEN_NOW, tick=False)

    def test_teto_param_uses_ceiling(self, logged_client, user):
        baker.make("finances.Budget", user=user, name="Casa", amount=Decimal("9999"))
        resp = logged_client.get("/projection/?estimate=teto&start=2026-07&months=1")
        assert resp.status_code == 200
        assert resp.context["estimate"] == "teto"
        assert resp.context["rows"][0]["diverse_estimated"] == Decimal("9999")

    def test_default_is_median(self, logged_client, user):
        resp = logged_client.get("/projection/?start=2026-07&months=1")
        assert resp.context["estimate"] == "median"

    def test_estimate_persists_in_session(self, logged_client, user):
        logged_client.get("/projection/?estimate=teto&start=2026-07&months=1")
        # subsequent request without the param keeps the choice
        resp = logged_client.get("/projection/?start=2026-07&months=1")
        assert resp.context["estimate"] == "teto"
```

Note the local `from decimal import Decimal` and `from model_bakery import baker` imports inside `test_teto_param_uses_ceiling` are now redundant — the module already imports both at the top (lines 2 and 7). They are removed above; do not put them back.

Add `UTC` and `datetime` to the module's imports. The first line of the file becomes:

```python
from datetime import UTC, date, datetime
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_views_projection.py -v
```

Expected: `17 passed`.

- [ ] **Step 5: Prove the freeze is load-bearing, not decorative**

Temporarily change `FROZEN_NOW` to `datetime(2026, 9, 15, 12, 0, tzinfo=UTC)` — a date *after* the month under test — and re-run:

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_views_projection.py::TestEstimateToggle -v
```

Expected: `test_teto_param_uses_ceiling` FAILS again with `assert Decimal('0') == Decimal('9999')`. That failure is the proof that the fixture, not luck, is what makes the test pass. Restore `FROZEN_NOW` to `datetime(2026, 6, 15, 12, 0, tzinfo=UTC)` and re-run to green.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/backend/finances/tests/test_views_projection.py && \
  uv run ruff format --check src/backend/finances/tests/test_views_projection.py
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/backend/finances/tests/test_views_projection.py
git commit -m "test(projection): freeze the clock so the ceiling estimator stays tested"
```

---

### Task 2: Suite-wide clock-shift harness, audit, and the convention note

**Files:**
- Create: `src/backend/core/clock.py`
- Create: `src/backend/conftest.py`
- Create: `src/backend/core/tests/test_clock_harness.py`
- Create: `docs/testing-conventions.md`
- Modify: `README.md` (one-line pointer, in the Quality section)
- Modify: whatever tests the audit in Step 5 breaks

**Interfaces:**
- Consumes from Task 1: the `time-machine` dependency.
- Produces:
  - `core.clock.parse_shift(raw: str) -> timedelta` — raises `ValueError` on anything not matching `^[+-]?\d+[dmy]$`
  - `TEST_CLOCK_SHIFT` env var, accepting `+1d`, `+1m`, `+1y`, `-6m` and the like
  - an autouse `shifted_clock` fixture in `src/backend/conftest.py`, applied to every test in the suite
  - `docs/testing-conventions.md`, referenced by README and by future epics

**Why `parse_shift` lives in `core/clock.py` and not in the conftest:** pytest
loads `conftest.py` as a plugin under its own internal module name. A test doing
`from conftest import parse_shift` would import the same file a *second* time,
under a different name, giving two module objects for one file — a subtle trap
that only bites later. The conftest keeps the fixture; the pure function it calls
lives somewhere importable.

**Why an env var and not `faketime`:** `libfaketime` is not installed on this machine or on the GitHub Actions runner, needs `LD_PRELOAD`, and does not work under every Python build. An env var read by a `conftest.py` fixture is portable, works identically in CI, and is one `uv run pytest` away for anyone.

- [ ] **Step 1: Write the failing test for the harness itself**

Create `src/backend/core/tests/test_clock_harness.py`:

```python
"""The suite-wide clock shift must actually shift the clock.

A harness that silently does nothing is worse than no harness: the suite would
report "passes a year from now" while testing today.
"""

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

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

    expected = (date.today() + timedelta(days=365)).isoformat()
    assert f"PROBE_TODAY {expected}" in result.stdout, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def _clean_env():
    import os

    env = dict(os.environ)
    env.setdefault("POSTGRES_PORT", "5433")
    env.pop("TEST_CLOCK_SHIFT", None)
    return env
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_clock_harness.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'core.clock'`.

- [ ] **Step 3: Write the parser**

Create `src/backend/core/clock.py`:

```python
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
        raise ValueError(
            f"TEST_CLOCK_SHIFT must look like +1d, +1m, +1y or -6m; got {raw!r}"
        )
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(days=amount * _UNIT_DAYS[unit])
```

- [ ] **Step 4: Write the harness**

Create `src/backend/conftest.py`:

```python
"""Suite-wide fixtures.

``TEST_CLOCK_SHIFT`` moves the whole suite's clock so that wall-clock dependence
surfaces on demand — in a nightly job, or in one command before a release —
instead of on a random future morning. See ``docs/testing-conventions.md``.

    TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q
"""

import os
from datetime import UTC, datetime

import pytest
import time_machine

from core.clock import parse_shift


@pytest.fixture(autouse=True)
def shifted_clock():
    """Shift the clock for every test when TEST_CLOCK_SHIFT is set.

    ``tick=True`` so time still advances inside a test — freezing the whole
    suite would break anything that relies on two timestamps differing.
    Per-test ``time_machine.move_to`` calls nest inside this and win, which is
    what a test that pins its own date expects.
    """
    raw = os.environ.get("TEST_CLOCK_SHIFT")
    if not raw:
        yield
        return
    destination = datetime.now(UTC) + parse_shift(raw)
    with time_machine.travel(destination, tick=True):
        yield
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_clock_harness.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run the audit — the suite under three clocks**

This is the actual work of story S02-2. Run all three and capture the failure lists.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -5
TEST_CLOCK_SHIFT=+1m POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -20
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -20
```

Expected after Task 1: the unshifted run is green. The shifted runs are where new failures appear — that is the point of the step, not a problem with it.

For **each** failure the shifted runs produce, decide between exactly two outcomes and record which:

- **Freeze it.** The test encodes a requirement that is date-relative (like `TestEstimateToggle`). Add a `_frozen_clock` autouse fixture to the class, or `time_machine.move_to(...)` to the function, using the same "midday UTC on a fixed date" pattern from Task 1. Pick the frozen date so the *requirement* holds, and say in the docstring which requirement that is.
- **Document it as intentionally current-date-relative.** A test that asserts "the default month is this month" is correct to read the clock. Add a comment naming why, and add `@pytest.mark.current_date` so the marker makes them greppable.

Register the marker in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "current_date: test deliberately reads the real clock; excluded from clock-shift runs",
]
```

and exclude them from the shifted runs by appending `-m "not current_date"` to the shifted commands.

**Known starting points** — do not treat this list as exhaustive, run the audit:

| File | Why it is a candidate |
|---|---|
| `src/backend/finances/tests/test_entries_live_summary.py` | calls `date.today()` / `timezone.now()` directly |
| `src/backend/assistant/tests/test_memory_models.py` | same |
| `src/backend/finances/tests/test_category_stats.py` | pins `AS_OF = date(2026, 6, 20)` and mixes it with data at `date(2026, 6, 1)` |
| `src/backend/assistant/tests/test_simulate_projection.py` | passes an explicit `today=date(2026, 6, 20)` — already correct, use it as the model for others |

- [ ] **Step 7: Re-run all three clocks until they agree**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -3
TEST_CLOCK_SHIFT=+1m POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date" 2>&1 | tail -3
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date" 2>&1 | tail -3
```

Expected: zero failures in all three. The skip count in the unshifted run must be explainable — the legitimate skips are the `RUN_LLM_TESTS`-gated tests in `src/backend/assistant/tests/` (see `assistant/tests/conftest.py:10`). Record the exact numbers; Task 5 needs them.

- [ ] **Step 8: Write the convention note**

Create `docs/testing-conventions.md`:

````markdown
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

All three must produce the same result. CI runs the shifted pair nightly, so rot
surfaces on its own schedule rather than during a release.

Accepted values: `+1d`, `+1m`, `+1y`, `-6m` — a signed integer and one of `d`,
`m`, `y`. Months are 30 days and years are 365; the goal is crossing a boundary,
not modelling a calendar.

**Common failure:** a test passes shifted and fails unshifted. That usually means
it depends on the *current* month having no data, and the shift moved it into an
empty month. Pin the date rather than the data.
````

- [ ] **Step 9: Point at it from the README**

In `README.md`, in the `## ✅ Quality & Testing` section, add after the code block (currently line 176):

```markdown
- **Time-stable by construction.** Date-sensitive tests freeze the clock rather
  than read it; `TEST_CLOCK_SHIFT=+1y` re-runs the suite a year from now. The
  rules are in **[`docs/testing-conventions.md`](docs/testing-conventions.md)**.
```

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/conftest.py src/backend/core/clock.py \
        src/backend/core/tests/test_clock_harness.py \
        docs/testing-conventions.md README.md pyproject.toml
git add -u src/backend/   # whatever the audit in step 5 changed
git commit -m "test: suite-wide clock-shift harness and time-stability audit"
```

---

### Task 3: The missing CI gates

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml` (`[tool.ruff.lint.isort]` — add `assistant`)

**Interfaces:**
- Consumes from Task 2: the `TEST_CLOCK_SHIFT` env var and the `current_date` marker, used by the nightly job.
- Produces: a `test` job, a `frontend` job, and a `clock-shift` job. Task 4 adds artifact-drift steps to `test` and `frontend`.

**What CI misses today** (`.github/workflows/ci.yml`): a missing migration, a `check --deploy` regression, any frontend error at all, and time rot. It runs `manage.py check` but not `check --deploy`, so the settings that only exist under `if not DEBUG:` are never exercised in CI even though `core/tests/test_deploy_settings.py` exercises them in a subprocess.

- [ ] **Step 1: Fix the isort first-party list first — it is a one-line lint gap**

In `pyproject.toml`:

```toml
[tool.ruff.lint.isort]
known-first-party = ["config", "core", "finances", "assistant"]
```

`assistant` was missing, so Ruff sorted `from assistant.models import ...` as a third-party import. Verify it changes something:

```bash
uv run ruff check --select I --diff src/backend/
```

Expected: a diff reordering imports in the assistant app's modules. Apply it:

```bash
uv run ruff check --select I --fix src/backend/ && uv run ruff format src/backend/
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: `All checks passed!`

- [ ] **Step 2: Re-measure the suite runtime, so the CI matrix stays a decision and not a guess**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -1
```

Measured at `HEAD` on 2026-08-08: **42.98s** for 823 tests. That is cheap enough
that the clock-shift matrix runs on every pull request, not only nightly — the
workflow in Step 3 is written that way.

Re-measure anyway: if the suite has grown past **3 minutes** since this plan was
written, restore `if: github.event_name == 'schedule'` on the `clock-shift` job
and update the comment with the new number. A future reader should not have to
re-measure to understand the choice.

- [ ] **Step 3: Rewrite the workflow**

Replace `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    # 06:00 UTC = 03:00 America/Sao_Paulo. Nightly so time-related rot surfaces
    # on its own schedule instead of during a release.
    - cron: "0 6 * * *"

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: expense_tracker_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      POSTGRES_DB: expense_tracker_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      SECRET_KEY: test-secret-key
      DEBUG: "true"

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync

      - name: Lint
        run: uv run ruff check src/backend/

      - name: Format check
        run: uv run ruff format --check src/backend/

      - name: Run tests with coverage
        run: |
          uv run coverage run -m pytest src/backend/ -v
          uv run coverage report --fail-under=80

      - name: Django system check
        run: uv run python src/backend/manage.py check

      # A model change without its migration is invisible until deploy, where it
      # surfaces as a 500 on a column that does not exist.
      - name: No missing migrations
        run: uv run python src/backend/manage.py makemigrations --check --dry-run

      # The production-only settings live inside `if not DEBUG:`, so the plain
      # `check` above never sees them. This is the only place CI does.
      - name: Deploy check under production-like settings
        env:
          DEBUG: "False"
          ALLOWED_HOSTS: example.com
          CSRF_TRUSTED_ORIGINS: https://example.com
        run: |
          SECRET_KEY=$(uv run python -c \
            "from django.core.management.utils import get_random_secret_key as g; print(g())") \
            uv run python src/backend/manage.py check --deploy

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: src/backend/frontend

    steps:
      - uses: actions/checkout@v4

      - uses: pnpm/action-setup@v4
        with:
          version: 11

      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: src/backend/frontend/pnpm-lock.yaml

      - name: Install dependencies
        run: pnpm install --frozen-lockfile

      # Explicit, so a type error reads as a type error rather than as a build
      # failure. `pnpm build` runs tsc again — that redundancy is the point.
      - name: Type check
        run: pnpm exec tsc --noEmit

      - name: Build the React islands
        run: pnpm build

  clock-shift:
    # The suite is time-sensitive by domain (billing months), so "does it still
    # pass next year" is a real question. Measured at 43s for 823 tests on
    # 2026-08-08, so it runs on every PR as well as nightly. If the suite ever
    # passes ~3 minutes, add `if: github.event_name == 'schedule'` here.
    runs-on: ubuntu-latest

    strategy:
      fail-fast: false
      matrix:
        shift: ["+1m", "+1y"]

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: expense_tracker_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      POSTGRES_DB: expense_tracker_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      SECRET_KEY: test-secret-key
      DEBUG: "true"
      TEST_CLOCK_SHIFT: ${{ matrix.shift }}

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.12
      - run: uv sync
      - name: Suite under a shifted clock
        run: uv run pytest src/backend/ -q -m "not current_date"
```

Update the runtime in the `clock-shift` comment with the number from Step 2.

- [ ] **Step 4: Validate the workflow file parses**

```bash
uv run python -c "
import yaml, pathlib
doc = yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())
print('jobs:', sorted(doc['jobs']))
print('triggers:', sorted(doc[True] if True in doc else doc['on']))
"
```

Expected: `jobs: ['clock-shift', 'frontend', 'test']` and the three triggers. (YAML parses the bare key `on` as the boolean `True`; that is a YAML quirk, not a bug in the workflow.)

If `pyyaml` is not installed, use `uvx --from pyyaml python -c ...` or skip to Step 5 — the real validation is CI running.

- [ ] **Step 5: Run every new gate locally before pushing**

```bash
uv run python src/backend/manage.py makemigrations --check --dry-run

DEBUG=False \
SECRET_KEY=$(uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
ALLOWED_HOSTS=example.com CSRF_TRUSTED_ORIGINS=https://example.com \
  uv run python src/backend/manage.py check --deploy
```

Expected: `No changes detected`, then `System check identified no issues (0 silenced).`

Then the frontend gate. **Note:** `pnpm build` currently fails on a fresh checkout of this machine's working tree with `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY` — `node_modules` has drifted from the lockfile, and pnpm refuses to purge it non-interactively. That is exactly what CI would hit. Fix it locally with a clean install:

```bash
cd src/backend/frontend
CI=true pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm build
cd -
```

Expected: install succeeds, `tsc` prints nothing, and the build writes `src/backend/static/frontend/mount.js`.

If `pnpm install --frozen-lockfile` fails with a lockfile mismatch, the lockfile is stale relative to `package.json`. Regenerate it (`pnpm install`), commit the result, and say so in the commit message — do not switch CI to a non-frozen install to paper over it.

- [ ] **Step 6: Push and watch CI**

```bash
git add .github/workflows/ci.yml pyproject.toml
git add -u src/backend/   # the isort reordering from step 1
git commit -m "ci: gate on missing migrations, deploy check, frontend build and a nightly clock shift"
git push
gh run watch
```

Expected: `test`, `frontend`, and both `clock-shift` matrix legs (`+1m`, `+1y`) green.

If a `clock-shift` leg fails in CI but passed locally, the difference is almost
always the runner's timezone: CI is UTC, the dev machine is America/Sao_Paulo,
and `date.today()` reads the system timezone rather than Django's `TIME_ZONE`.
Reproduce it locally with `TZ=UTC TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run
pytest src/backend/ -q -m "not current_date"` before changing anything.

---

### Task 4: Close the committed-artifact drift gap

`src/backend/static/frontend/mount.js` and `src/backend/static/css/tailwind.css` are tracked in git and rebuilt by hand. A frontend change that lands without a rebuild ships stale JavaScript; a new Tailwind class that lands without `--force` ships CSS missing that class. Both have bitten this project before.

**Files:**
- Modify: `.github/workflows/ci.yml` (add drift steps to `test` and `frontend`)
- Modify: `docs/runbook.md` (the rebuild procedure, including `--force`)
- Modify: `README.md` (§4 "Build frontend assets" — make the React build command real)
- Possibly create: `src/backend/static/frontend/.source-hash` and `scripts/frontend-source-hash.sh` (branch B only)

**Interfaces:**
- Consumes from Task 3: the `test` and `frontend` jobs.
- Produces: a CI failure when a committed artifact does not match its source.

- [ ] **Step 1: Decide the mechanism by measuring build determinism**

Rebuild-and-diff is the simplest gate, but it only works if the builds are byte-stable. Measure, do not assume:

```bash
cd src/backend/frontend
CI=true pnpm install --frozen-lockfile
pnpm build && H1=$(sha256sum ../static/frontend/mount.js | cut -d' ' -f1)
pnpm build && H2=$(sha256sum ../static/frontend/mount.js | cut -d' ' -f1)
echo "vite: $H1"; echo "vite: $H2"
cd -

uv run python src/backend/manage.py tailwind build --force
T1=$(sha256sum src/backend/static/css/tailwind.css | cut -d' ' -f1)
uv run python src/backend/manage.py tailwind build --force
T2=$(sha256sum src/backend/static/css/tailwind.css | cut -d' ' -f1)
echo "tailwind: $T1"; echo "tailwind: $T2"

git checkout -- src/backend/static/   # discard the probe's output
```

**If both pairs match → take Branch A** (Step 2). **If either pair differs → take Branch B** (Step 3). Record which branch you took and the four hashes; a reviewer needs to see the measurement, not the conclusion.

- [ ] **Step 2: Branch A — rebuild and diff**

Add to the `frontend` job in `.github/workflows/ci.yml`, after `Build the React islands`:

```yaml
      # The artifact is committed so local dev and the Docker build work without
      # a Node toolchain. That only stays safe if CI proves it matches its source.
      - name: Committed React bundle matches a fresh build
        run: |
          git diff --exit-code -- ../static/frontend/mount.js \
            || { echo "::error::mount.js is stale. Run 'pnpm build' in src/backend/frontend and commit the result."; exit 1; }
```

Add to the `test` job, after `Django system check`:

```yaml
      # Tailwind v4 scans templates for class names, so a new class in a template
      # needs a rebuild. --force is required: without it the CLI trusts its cache
      # and emits CSS that is missing the new class.
      - name: Committed Tailwind CSS matches a fresh build
        run: |
          uv run python src/backend/manage.py tailwind build --force
          git diff --exit-code -- src/backend/static/css/tailwind.css \
            || { echo "::error::tailwind.css is stale. Run 'uv run python src/backend/manage.py tailwind build --force' and commit the result."; exit 1; }
```

Skip Step 3 entirely.

- [ ] **Step 3: Branch B — a committed source hash**

Only if Step 1 showed a non-deterministic build. The gate then checks "was the artifact rebuilt after the source changed" rather than "does the artifact match byte for byte".

Create `scripts/frontend-source-hash.sh`:

```bash
#!/usr/bin/env bash
# Hash of every input to the frontend build. Committed alongside the artifacts so
# CI can tell "source changed, artifact not rebuilt" from "build is not byte
# stable" — the builds are not byte stable, so a plain diff would flap.
set -euo pipefail
cd "$(dirname "$0")/.."
{
  git ls-files -z src/backend/frontend/src \
                  src/backend/frontend/package.json \
                  src/backend/frontend/pnpm-lock.yaml \
                  src/backend/frontend/vite.config.ts \
                  src/backend/frontend/tsconfig.json \
                  src/backend/static/css/input.css \
                  src/backend/templates \
    | xargs -0 sha256sum
} | sort | sha256sum | cut -d' ' -f1
```

```bash
chmod +x scripts/frontend-source-hash.sh
./scripts/frontend-source-hash.sh > src/backend/static/frontend/.source-hash
```

Add to the `frontend` job, replacing Branch A's step:

```yaml
      - name: Committed artifacts were rebuilt for the current source
        working-directory: .
        run: |
          expected=$(cat src/backend/static/frontend/.source-hash)
          actual=$(./scripts/frontend-source-hash.sh)
          if [ "$expected" != "$actual" ]; then
            echo "::error::Frontend source changed without a rebuild. Run:"
            echo "  cd src/backend/frontend && pnpm build && cd -"
            echo "  uv run python src/backend/manage.py tailwind build --force"
            echo "  ./scripts/frontend-source-hash.sh > src/backend/static/frontend/.source-hash"
            exit 1
          fi
```

- [ ] **Step 4: Prove the gate fails on a stale artifact**

The epic requires proving this, not assuming it. On a scratch branch:

```bash
git checkout -b scratch/prove-artifact-gate
printf '\n/* deliberate drift */\n' >> src/backend/static/css/tailwind.css
git add src/backend/static/css/tailwind.css
git commit -m "test: deliberately stale artifact, do not merge"
git push -u origin scratch/prove-artifact-gate
gh pr create --title "DO NOT MERGE: prove the artifact gate fails" --body "Scratch branch for E02 Task 4 Step 4." --draft
gh run watch
```

Expected: the artifact step FAILS with the `::error::` message. Then:

```bash
gh pr close --delete-branch
git checkout -   # back to the working branch
```

If it passes, the gate is not wired to the file you edited. Fix it and repeat — an untested gate is not a gate.

- [ ] **Step 5: Document the rebuild in the runbook**

Add to `docs/runbook.md`:

````markdown
## Rebuilding the committed frontend artifacts

`src/backend/static/frontend/mount.js` and `src/backend/static/css/tailwind.css`
are **tracked in git**. They are committed so local dev and the Docker build work
without a Node toolchain. CI fails if they drift from their source, so rebuild
and commit both whenever you touch `src/backend/frontend/src/**`,
`src/backend/templates/**`, or `src/backend/static/css/input.css`.

```bash
# React islands
cd src/backend/frontend
CI=true pnpm install --frozen-lockfile
pnpm build            # runs tsc, then vite build -> ../static/frontend/mount.js
cd -

# Tailwind — --force is NOT optional
uv run python src/backend/manage.py tailwind build --force

git add src/backend/static/frontend/mount.js src/backend/static/css/tailwind.css
```

**Common failure #1:** dropping `--force`. Tailwind v4 trusts its cache and emits
CSS that is missing any class you just added to a template. The page renders
unstyled in exactly one place and looks like a template bug.

**Common failure #2:** `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY` from
`pnpm build`. `node_modules` has drifted from the lockfile and pnpm will not
purge it without a TTY. `CI=true pnpm install --frozen-lockfile` first.

**Common failure #3:** a local `vite build --watch` service (systemd `--user`)
rewriting `mount.js` under you mid-commit. Stop it before rebuilding by hand.
````

- [ ] **Step 6: Fix the README's frontend build step**

`README.md` §4 currently says:

```bash
# React islands (Vite) + Tailwind CSS
uv run python src/backend/manage.py tailwind build --force
# build the React bundle per the frontend toolchain (mount.js)
```

That comment is not a command. Replace the whole block with:

```bash
# React islands (Vite)
cd src/backend/frontend && CI=true pnpm install --frozen-lockfile && pnpm build && cd -

# Tailwind CSS — --force is required, see docs/runbook.md
uv run python src/backend/manage.py tailwind build --force
```

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml docs/runbook.md README.md
git add scripts/frontend-source-hash.sh src/backend/static/frontend/.source-hash 2>/dev/null || true
git commit -m "ci: fail when committed frontend artifacts drift from their source"
```

---

### Task 5: Make the README's test claims true and keep them true

**Files:**
- Modify: `README.md:14` (the badge) and `README.md:171,178` (the Quality section)

**Interfaces:**
- Consumes from Task 2, Step 6: the real pass/skip numbers.
- Produces: nothing other tasks use.

The README claims a static `tests-817 passing` badge and "**818 tests** … 817 passing, 1 skipped". Measured at `3bbc5ca`: `1 failed, 818 passed, 2 skipped`. Both the count and the status were wrong, and they were wrong because a hand-maintained number goes stale the moment anyone adds a test.

- [ ] **Step 1: Get the real numbers**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q 2>&1 | tail -1
```

Record the exact line.

- [ ] **Step 2: Replace the static badge with a live one**

In `README.md`, replace line 14:

```markdown
[![Tests](https://img.shields.io/badge/tests-817%20passing-success)](#-quality--testing)
```

with:

```markdown
[![CI](https://github.com/bessavagner/expense_tracker_v2/actions/workflows/ci.yml/badge.svg)](https://github.com/bessavagner/expense_tracker_v2/actions/workflows/ci.yml)
```

A GitHub Actions status badge is generated from the last run, so it cannot go stale and cannot be wrong. That is the answer to "stated in a way that does not require editing on every test added".

- [ ] **Step 3: Drop the hardcoded counts from the prose**

Replace line 171:

```bash
uv run pytest src/backend/ -v              # run the full suite (818 tests)
```

with:

```bash
uv run pytest src/backend/ -v              # run the full suite
```

Replace line 178:

```markdown
- **818 tests** across unit, integration, and BDD scenarios (`pytest-bdd`) — 817 passing, 1 skipped.
```

with:

```markdown
- Unit, integration, and BDD scenarios (`pytest-bdd`). The only skipped tests are
  the real-LLM ones, gated behind `RUN_LLM_TESTS=1` because they cost money.
```

- [ ] **Step 4: Update the CI description to match what CI now does**

Replace line 179:

```markdown
- **GitHub Actions CI** runs lint, format check, the full suite with an ≥80% coverage gate, and `manage.py check` on every push and PR.
```

with:

```markdown
- **GitHub Actions CI** on every push and PR: lint, format check, the full suite
  with an ≥80% coverage gate, `manage.py check` and `check --deploy`, a missing
  migration check, a frontend type-check and build, and a committed-artifact
  drift gate. A nightly job re-runs the suite with the clock shifted forward.
```

- [ ] **Step 5: Verify no stale count survives anywhere**

```bash
grep -rn "81[0-9] tests\|817\|818" README.md docs/ || echo "clean"
```

Expected: `clean`. If `docs/backlog/E02-suite-integrity-and-ci-gates.md` shows up, leave it — the epic is a historical record of the measurement and is correct as written.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(readme): live CI badge instead of a test count that goes stale"
```

---

### Task 6: Full Definition of Done

**Files:**
- Modify: `docs/backlog/E02-suite-integrity-and-ci-gates.md`, `docs/backlog/INDEX.md` (status)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: the evidence block pasted into the review.

- [ ] **Step 1: Green under three clocks**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
TEST_CLOCK_SHIFT=+1m POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
```

Expected: zero failures in all three. Paste all three summary lines.

- [ ] **Step 2: All gates**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && \
  uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
DEBUG=False \
SECRET_KEY=$(uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
ALLOWED_HOSTS=example.com CSRF_TRUSTED_ORIGINS=https://example.com \
  uv run python src/backend/manage.py check --deploy
```

Expected: coverage `TOTAL` ≥ 80%, `All checks passed!`, `No changes detected`, `System check identified no issues`.

- [ ] **Step 3: Frontend**

```bash
cd src/backend/frontend && CI=true pnpm install --frozen-lockfile && \
  pnpm exec tsc --noEmit && pnpm build && cd -
git diff --stat -- src/backend/static/
```

Expected: install and build succeed, `tsc` silent. The `git diff --stat` output depends on which branch Task 4 took — under Branch A it must be empty; under Branch B a byte difference is expected and the `.source-hash` is what must match.

- [ ] **Step 4: Confirm each of the epic's observable assertions**

- [ ] Zero failing tests; the skip count is explained by the `RUN_LLM_TESTS` gate in `assistant/tests/conftest.py:10`
- [ ] The suite passes with the clock shifted forward by a year
- [ ] CI has jobs for the migration check, the deploy check, the frontend build, and a nightly schedule — confirm at `gh workflow view ci.yml`
- [ ] CI failed on a deliberately stale committed artifact — link the scratch PR from Task 4, Step 4
- [ ] README test claims match `pytest` output

- [ ] **Step 5: Update the epic's status**

Change `status: ready` to `status: review` in the frontmatter of `docs/backlog/E02-suite-integrity-and-ci-gates.md`, and update the E02 row in the §4 table of `docs/backlog/INDEX.md`.

E02 unblocks **E04** and **E08**. Once E02 is `done`, flip both of those rows from `blocked` to `ready` in the same table and in their own frontmatter.

```bash
git add docs/backlog/
git commit -m "chore(backlog): E02 to review — suite green under three clocks"
```

- [ ] **Step 6: Hand off for review**

Run `superpowers:requesting-code-review`, then `superpowers:verification-before-completion` with the pasted output from Steps 1-3, then `superpowers:finishing-a-development-branch`.
