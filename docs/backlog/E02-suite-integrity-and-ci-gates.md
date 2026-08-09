---
id: E02
title: Suite integrity & CI gates
release: R0
status: review
depends_on: []
blocks: [E04, E08]
wedge_critical: false
---

# E02 · Suite integrity & CI gates

## Outcome

The test suite is green, cannot rot with the passage of wall-clock time, and CI catches the classes of mistake that the two largest upcoming epics (E04 household tenancy, E08 evaluation harness) will otherwise let through silently.

## Why now

Review finding **H6**: CI on `main` is red today, and the cause is a category of bug — tests that read the wall clock — that will keep recurring in a product built entirely around monthly billing cycles.

This epic blocks E04 and E08 for a specific reason: **E04 rewrites ~200 query sites and every cross-user isolation test.** The suite is the only thing standing between that refactor and a cross-tenant data leak. A suite you don't trust cannot play that role. Fix the suite before you lean on it.

## Evidence in the codebase

| What | Where |
|---|---|
| The failing test | `src/backend/finances/tests/test_views_projection.py::TestEstimateToggle::test_teto_param_uses_ceiling` |
| Its hardcoded month (now in the past — today is 2026-08-07) | same file, `?estimate=teto&start=2026-07&months=1` |
| Two sibling tests sharing the same hardcoded month | `TestEstimateToggle::test_default_is_median`, `::test_estimate_persists_in_session` |
| The injectable seam that makes the fix clean | `finances/views/projection.py:31` — `_parse_start(request, today)` already takes `today` |
| CI definition — no `makemigrations --check`, no frontend step | `.github/workflows/ci.yml` |
| Frontend build artifacts committed, able to drift from source | `src/backend/static/frontend/mount.js`, `src/backend/static/css/tailwind.css` |
| `isort` first-party list omits `assistant` | `pyproject.toml`, `[tool.ruff.lint.isort]` |

Current actual state, measured at `3bbc5ca`:

```
1 failed, 818 passed, 2 skipped
```

The README claims "818 tests … 817 passing, 1 skipped" — also wrong, and worth correcting in this epic.

## Stories

### S02-1 · Freeze the clock in date-sensitive tests

- **Given** a test whose outcome depends on the current date
- **When** the suite runs on any calendar day
- **Then** it produces the same result
- **And** `test_teto_param_uses_ceiling` passes
- **And** its two sibling tests in `TestEstimateToggle` are converted the same way, not left as latent failures
- **And** a time-freezing utility (`time-machine` or `freezegun`, added as a dev dependency) or explicit `today` injection is used consistently
- **And** a short convention note is added wherever the project records test conventions, so the next date-dependent test is written correctly

> The fix is *not* to change the assertion to match today's behaviour. The test encodes a real requirement — the ceiling estimator applies to future months. Freeze time so that requirement stays tested.

### S02-2 · Audit the whole suite for wall-clock dependence

- **Given** the full test suite
- **When** it is run with the system clock set forward by one year, and again by one month
- **Then** the same tests pass in all three runs
- **And** any test that fails under time shift is either frozen or documented as intentionally current-date-relative

### S02-3 · Add the missing CI gates

- **Given** a push or pull request
- **When** CI runs
- **Then** it additionally fails on: a missing migration (`makemigrations --check --dry-run`), a `check --deploy` regression under production-like settings, and a frontend type error or lint failure
- **And** the frontend job runs `tsc` and builds, so a broken island is caught in CI rather than in the Docker build
- **And** a scheduled nightly run of the full suite exists, so time-related rot surfaces on its own schedule instead of during a release

### S02-4 · Close the committed-artifact drift gap

- **Given** `mount.js` and `tailwind.css` are tracked in git and rebuilt manually
- **When** a change lands that modifies frontend source or introduces new Tailwind classes
- **Then** CI fails if the committed artifacts do not match a fresh build of the source
- **And** the rebuild command (including Tailwind's `--force` requirement) is documented where a developer will find it

### S02-5 · Correct the README's test claims

- **Given** the README badge and Quality section
- **When** the suite count or status changes
- **Then** the README matches reality
- **And** the numbers are stated in a way that does not require editing on every test added, or a CI step keeps them honest

## Definition of Done

```bash
# Green, three times, under different clocks
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
faketime '+1 year'  env POSTGRES_PORT=5433 uv run pytest src/backend/ -q   # or the chosen time-shift mechanism
faketime '+1 month' env POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# All gates
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com uv run python src/backend/manage.py check --deploy

# Frontend
cd src/backend/frontend && pnpm install --frozen-lockfile && pnpm build
```

Observable assertions:

- [ ] Zero failing tests; skip count is explained (the `RUN_LLM_TESTS` gated tests are the legitimate skips)
- [ ] The suite passes with the clock shifted forward by a year
- [ ] CI has jobs for migrations check, deploy check, frontend build, and a nightly schedule
- [ ] CI fails on a deliberately stale committed artifact (prove it by committing a stale one on a scratch branch)
- [ ] README test claims match `pytest` output

## Out of scope

- Adding *new* feature tests — this epic makes the existing suite trustworthy, it does not grow coverage
- The AI evaluation harness → **E08**
- Automated deploy pipeline → **E16** (this epic only adds *checks*, not deployment)
- Refactoring the projection feature itself

## Open questions

1. **`time-machine` or `freezegun`?** `time-machine` is faster and Python-3.12-friendly; `freezegun` is more widely known. Either is fine — pick one and use it consistently.
2. **How should CI verify committed artifacts?** Rebuild and `git diff --exit-code` is simplest but requires deterministic builds. If Vite output is not byte-stable, compare a hash of the source tree instead and document the approach.
3. **Should the frontend artifacts stay committed at all?** They exist so local dev works without a Node toolchain. Alternative: stop tracking them and require the build. Note the tradeoff in the plan; changing it is allowed but must be deliberate.

## Out-of-scope reminder for the agent

`test_teto_param_uses_ceiling` currently fails. It is **tempting and wrong** to delete it or relax the assertion. The requirement it encodes is real.

## Skill pipeline

1. `superpowers:writing-plans` — the epic is the spec; open questions are tool choices resolvable inside the plan
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development` — here the "test" is the meta-property: prove the suite is time-stable by shifting the clock
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `superpowers:verification-before-completion`
7. `superpowers:finishing-a-development-branch`
