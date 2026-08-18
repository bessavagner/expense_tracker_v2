# E16 · Operations: staging, deploy & recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Changes reach production through an automated, reversible pipeline with a staging environment in front of it, and a database restore has been *performed and timed* rather than assumed.

**Architecture:** `config/settings.py` becomes a package — `base.py` holds everything environment-neutral, `dev.py` and `prod.py` each state their own posture, and production hardening lives unconditionally in `prod.py` rather than behind `if not DEBUG`. A single `.github/workflows/deploy.yml` authenticates to GCP through Workload Identity Federation and carries two jobs: a merge to `main` migrates and deploys **staging**, a `v*` tag migrates and deploys **production**. Migrations always run as a separate step against the direct connection *before* the new revision is created, so a failed migration aborts the deploy instead of leaving a half-migrated database serving traffic. Schema drift — the 2026-08-15 failure, which no pipeline ordering can detect after the fact — is surfaced by one function, `core.migration_drift.unapplied_migrations()`, read from three places: `/healthz/`, a management command, and a nightly Cloud Scheduler job. Recovery stops being a vendor assumption: a nightly `ledger-backup` Cloud Run Job writes a logical dump to GCS with a lifecycle rule, and the restore is rehearsed end to end with `dump_ledger_totals` proving the money survived.

**Tech Stack:** Django 6, Python 3.12, uv, pytest + pytest-django, GitHub Actions, Google Cloud Run + Cloud Build + Cloud Scheduler + Cloud Monitoring, Workload Identity Federation, Supabase (PostgreSQL 17.6), `postgres:17` Docker image for client tools.

**Spec:** [`docs/backlog/E16-operations-staging-deploy-recovery.md`](../../backlog/E16-operations-staging-deploy-recovery.md) — this epic is self-contained by design (`INDEX.md` preamble) and is the spec this plan argues from.

**Epic:** E16 · Operations — R4, alongside E15 (billing) and E17 (trust surface). Its one dependency, **E06, closed 2026-08-14**. R4's gate names this epic directly: *"you can restore the database inside your stated RTO — rehearsed, not assumed."*

**Baseline commit:** `fef60a8`. Every file:line reference below was read at that commit.

> **Two of the spec's `Evidence in the codebase` rows are stale at this baseline and the plan corrects them rather than repeating them.** `docs/runbook.md` **does exist** — 2842 lines, twenty sections, written incrementally by E01/E06/E07/E09/E10/E12/E13 — so S16-6 is a *gap-filling and verification* task (Task 12), not a writing-from-scratch one. And `config/settings.py:108-110, 234-244` no longer points at the security block; it moved to **`config/settings.py:154-155` and `629-639`** as the file grew. Trust this plan's line numbers, and re-read before editing.

---

## Global Constraints

Copied verbatim from `docs/backlog/INDEX.md` §7. Every task's requirements implicitly include this section; violating any of these fails review regardless of whether the DoD passes.

1. **TDD.** Test first, always. Project convention, not a preference.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number.** *(This epic adds no LLM call. It does add the strongest existing check on that boundary — Task 11 compares the acumulado across a restore.)*
4. **Tenant scoping is centralized.** No `filter(user=...)` on a domain model; use `.for_household(...)` / `.for_request(...)`. *(This epic writes no domain query. `dump_ledger_totals` already uses the scoped manager.)*
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean. Line length 100, target py312.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated. **This epic is the one most likely to break this rule** — it handles two databases' credentials, a WIF provider, and a service-account identity. Task 5 states which of those are secrets and which are public identifiers, because treating a public identifier as a secret is how a runbook becomes unusable.
8. **pt-BR in the product UI, English in code, comments, and docs.** *(This epic writes no product UI. The runbook is operator documentation and stays in English, matching every existing section except the three E13 ones whose titles are pt-BR because their legal subject is.)*
9. **Migrations are reversible** or the epic states explicitly why not. *(This epic ships no migration.)*
10. **No time-bomb tests.** Any date-sensitive test freezes the clock. See `docs/testing-conventions.md`. *(Only Task 2's drift tests touch stored state, and they are date-independent.)*

### An additional constraint specific to this epic

**No task here may run against production until the same thing has been done on staging first.** That is the entire point of Task 4 existing before Tasks 5–9. The one exception is Task 10's backup provisioning, which is production-only by definition and is why it is ordered after the pipeline is proven.

**The daisyUI Blueprint chain does not apply to this epic.** No task writes or edits markup. `/healthz/` returns `JsonResponse`, not a template. If a task ends up touching a template, the chain in `docs/superpowers/plans/2026-08-17-E13-lgpd-compliance.md` applies verbatim.

---

## Decisions taken before this plan

D1–D3 answer three of the spec's four open questions and were **settled by the maintainer on 2026-08-18**. D4 is deliberately left to measurement. D5–D14 are decisions this plan makes, each verified against the repo at `fef60a8`.

| # | Decision | Why |
|---|---|---|
| **D1** | **Staging gets its own Supabase project**, not a second database inside the production project. | Answers spec open question 2. Strongest isolation: a wrong `DATABASE_URL` cannot reach production, and a restore rehearsal never touches production's project. Free tier allows two active projects, so the cost is R$0. The known cost is operational, not financial — Supabase pauses a free project after a week of inactivity, so Task 4 records how to unpause and the deploy workflow tolerates a cold start. |
| **D2** | **Schema drift degrades `/healthz/` to 503**, *and* a scheduled check runs nightly. | Answers spec open question implied by S16-9's own "consider `/healthz/`". Reuses uptime policy `17994738960177318338` and its notification channel — detection in ≤5 minutes with zero new alerting infrastructure. The spec names the trade-off and accepts it: a drifted revision is already broken for its users, so removing it from rotation is correct. **The consequence this plan must handle is in D6.** |
| **D3** | **Production deploys are triggered by a `v*` git tag.** Merges to `main` deploy staging. | Answers spec open question 4. Deliberate, recorded in git history rather than only in an Actions log, and needs no second human — correct for one maintainer. A GitHub Environment protection rule can be added later without touching the workflow, which is the "mechanism should exist before there is a second engineer" the spec asks for. |
| **D4** | **The RTO target is not set in this plan.** Task 11 measures it; the measured number becomes the RTO and is written into the architecture review's NFR table. | Answers spec open question 3 by refusing to answer it. The review proposed 4 hours; committing to a number before measuring is the exact failure mode S16-5 exists to end. |
| **D5** | `config/settings/__init__.py` is **empty**, and no module re-exports a default. | S16-1's point is that production cannot be loaded unhardened. If `__init__` re-exported `dev`, `DJANGO_SETTINGS_MODULE=config.settings` would keep working and silently give an unhardened instance — the H7 bug with extra steps. Empty means Django raises `ImproperlyConfigured: The SECRET_KEY setting must not be empty` on the old value: loud, immediate, unambiguous. |
| **D6** | The production deploy job **runs migrations before `gcloud run deploy`**, and this is now load-bearing rather than merely tidy. | With D2, a revision whose migrations are unapplied fails its Cloud Run **startup probe** and the deploy aborts, leaving the previous revision serving. That is the safe failure — but only if migrations run first. Deploy-then-migrate under D2 does not produce 500s; it produces a stuck deploy. Both are better than 2026-08-15; only one is intelligible. |
| **D7** | Staging runs **`config.settings.prod`**, not a third settings module. | Staging exists to exercise what production runs. A `staging.py` that relaxed anything would make staging a worse predictor of production than no staging at all. The differences — database, Sentry environment, `ALLOWED_HOSTS` — are all already env vars. |
| **D8** | The 5xx ratio alert is built on **two log-based counter metrics**, not on `run.googleapis.com/request_count`. | The built-in Cloud Run metric carries `response_code_class` but **no URL path label**, so `/healthz/` cannot be excluded from the denominator — and the uptime check's healthy pings to `/healthz/` are exactly the traffic that would have diluted the 2026-08-15 ratio below any sane threshold. Cloud Logging's request log has `httpRequest.requestUrl`, so log-based metrics can exclude it. E13's `ledger_purge_ran` established the pattern and the runbook documents it. |
| **D9** | The ratio policy uses `combiner: "AND"` across **two** conditions: ratio > 50% *and* at least 3 non-healthz 5xx, both over 30 minutes. | The spec asks for a threshold where "a single error on a quiet afternoon does not page". At family scale a quiet afternoon may hold two requests total, so a ratio alone would page on one stray 500. The count condition is the volume floor; the ratio is what makes a *total* failure at low volume page as loudly as a spike. The 2026-08-15 shape — a day at ~100% with several errors — trips both. |
| **D10** | The **count**-based policy `4509450462948742746` is kept, unchanged. | S16-8 says so explicitly, and the reason is real: a ratio is blind to a burst that is small relative to healthy traffic. Two policies, two shapes of failure. |
| **D11** | **We stop relying on Supabase's backups as the primary mechanism** and add a nightly `ledger-backup` Cloud Run Job writing `pg_dump -Fc` to GCS with a 30-day lifecycle rule. Supabase's own backups are verified and documented as a second line, not the first. | Spec open question 1 asks what the retention actually is. Whatever Task 10 finds, a backup whose retention is set by someone else's pricing page is not a backup you can state an RPO from. The job mirrors `ledger-purge` exactly — same image, same env, Scheduler trigger, log line, alert on silence — so it costs one already-understood pattern rather than a new one. |
| **D12** | Restore verification uses **`manage.py dump_ledger_totals --json`**, diffed before and after. | It already exists (`src/backend/finances/management/commands/dump_ledger_totals.py`), was built for exactly this, and its docstring records why: *"Row counts do not prove a migration was lossless — this project has a documented history of reconciliation issues where the counts matched and the balances did not."* S16-5's "balances and acumulado, not merely row counts" is this command's entire purpose. Its `FIXED_TODAY = date(2026, 8, 12)` pin must **not** be changed for the rehearsal: a drifting clock produces a spurious diff. |
| **D13** | The production deploy job **re-points `ledger-purge` at the new image** as its last step. | The runbook already warns that `--source` deploys push untagged digests, so the purge job keeps running its creation-time image, "and a stale sweep still exits 0 and still logs, so the alert will not catch this; nothing will." A manual step that nothing verifies is a step that will be skipped. Automating it is a two-line addition to a workflow that is already authenticated. |
| **D14** | Drift detection reads `MigrationExecutor.migration_plan()`, not `showmigrations` output. | It is the same code `migrate` itself uses to decide what to run, so the answer cannot disagree with reality. Parsing `showmigrations` text would be a second implementation of the question. |

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/backend/config/settings/__init__.py` | **Create.** Empty. Makes the package importable and nothing else — see D5. | 1 |
| `src/backend/config/settings/base.py` | **Create** from the current `settings.py`, minus every `if not DEBUG:` branch and minus the `DEBUG` definition itself. Everything environment-neutral. | 1 |
| `src/backend/config/settings/dev.py` | **Create.** `DEBUG = True`, plain log formatter, plain static storage, persistent DB connections. | 1 |
| `src/backend/config/settings/prod.py` | **Create.** `DEBUG = False` as a literal, and the security settings unconditionally. The module production and staging both load. | 1 |
| `src/backend/config/settings.py` | **Delete** (via `git mv` into `base.py`, so history follows). | 1 |
| `src/backend/config/wsgi.py:14`, `asgi.py:14` | **Modify.** Default to `config.settings.prod`. | 1 |
| `src/backend/manage.py:10` | **Modify.** Default to `config.settings.dev`. | 1 |
| `pyproject.toml:33` | **Modify.** `DJANGO_SETTINGS_MODULE = "config.settings.dev"`. | 1 |
| `Dockerfile:43` | **Modify.** `config.settings.prod` for the build-time `collectstatic`. | 1 |
| `src/backend/core/tests/test_deploy_settings.py` | **Modify.** Assert against `config.settings.prod` directly, and add the test that proves `DEBUG=True` in the environment cannot unharden it. | 1 |
| `src/backend/core/tests/test_email_config.py:16` | **Modify.** Reload `config.settings.base`. | 1 |
| `src/backend/core/migration_drift.py` | **Create.** `unapplied_migrations()` — the single source of the drift answer. | 2 |
| `src/backend/core/tests/test_migration_drift.py` | **Create.** Both directions, including a genuinely drifted database. | 2 |
| `src/backend/core/management/commands/check_migration_drift.py` | **Create.** Operator- and cron-facing wrapper; exit 1 on drift. | 2 |
| `src/backend/core/views.py:11-24` | **Modify.** `health_check` reports drift and degrades to 503. | 3 |
| `src/backend/core/tests/test_health.py` | **Modify.** Add the drift cases. | 3 |
| `.github/workflows/deploy.yml` | **Create.** Both jobs — staging on merge, production on tag. | 5, 6 |
| `deploy/README.md` | **Modify.** Index the new specs; state which identifiers are public. | 5, 8, 10 |
| `deploy/fivexx-ratio-alert-policy.json` | **Create.** The S16-8 policy. | 8 |
| `deploy/log-metrics/` | **Create.** The two log-based metric definitions the ratio policy reads. | 8 |
| `deploy/drift-alert-policy.json` | **Create.** Alert on the nightly drift check failing or going silent. | 7 |
| `.env.example` | **Modify.** Staging block; `SENTRY_ENVIRONMENT`; the backup bucket. | 4, 10 |
| `docs/runbook.md` | **Modify.** Five new sections, one corrected. | 4–12 |
| `docs/superpowers/evidence/e16-rollback/README.md` | **Create.** The rollback that was performed. | 9 |
| `docs/superpowers/evidence/e16-restore/README.md` | **Create.** The timed restore. The reason the epic exists. | 11 |
| `docs/operations/credentials.md` | **Create.** Where every operating credential lives — not the values. | 12 |
| `README.md:113-128` | **Modify.** Add the deploy/recovery pointer to the runbook block that already exists. | 12 |
| `docs/architecture/product-readiness-review.md` | **Modify.** Replace the estimated RTO with the measured one. | 11 |
| `docs/backlog/E16-operations-staging-deploy-recovery.md`, `docs/backlog/INDEX.md` | **Modify.** Tick the DoD; mark the epic done. | 13 |

---

## Task 1: Split the settings module

Closes **S16-1**. Pure code, no infrastructure, and everything downstream depends on it — a staging environment that loads a module whose hardening is conditional would inherit the bug this task removes.

**Files:**
- Create: `src/backend/config/settings/__init__.py`
- Create: `src/backend/config/settings/base.py` (from `src/backend/config/settings.py` via `git mv`)
- Create: `src/backend/config/settings/dev.py`
- Create: `src/backend/config/settings/prod.py`
- Modify: `src/backend/config/wsgi.py:14`, `src/backend/config/asgi.py:14`, `src/backend/manage.py:10`
- Modify: `pyproject.toml:33`, `Dockerfile:43`
- Test: `src/backend/core/tests/test_deploy_settings.py` (modify), `src/backend/core/tests/test_email_config.py:16` (modify)

**Interfaces:**
- Consumes: nothing.
- Produces: three importable settings modules — `config.settings.base`, `config.settings.dev`, `config.settings.prod`. Every later task that runs a Django command names one of them explicitly. `config.settings` is **not** a usable settings module after this task.

- [ ] **Step 1: Write the failing test — production hardening survives `DEBUG=True` in the environment**

This is the H7 assertion, and it is the one the current suite cannot make. Replace the whole `_run_deploy_check` helper and `TestDeploySecurityChecks` class in `src/backend/core/tests/test_deploy_settings.py` with:

```python
def _run_deploy_check(extra_env=None, settings_module="config.settings.prod"):
    """Run ``manage.py check --deploy`` in a subprocess against a named settings module."""
    env = dict(os.environ)
    # python-dotenv (load_dotenv) does NOT override existing env vars, so these win
    # over the dev .env.
    env.update(
        {
            # Long, varied key so security.W009 doesn't add noise to the output.
            "SECRET_KEY": "aZ9_kQ2w-pR7x!mN4tB6vC8yE0sG1hJ3lD5fH7uI9oP2qW4eR6tY8u0",
            "ALLOWED_HOSTS": "example.com",
            "CSRF_TRUSTED_ORIGINS": "https://example.com",
            "DJANGO_SETTINGS_MODULE": settings_module,
        }
    )
    env.update(extra_env or {})
    return subprocess.run(  # noqa: S603 — fixed argv, trusted input (sys.executable)
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class TestDeploySecurityChecks:
    """``check --deploy`` must not flag HSTS / cookie / SSL issues under prod settings."""

    def test_no_hsts_warnings(self):
        result = _run_deploy_check()
        output = result.stdout + result.stderr
        for code in ("security.W004", "security.W005", "security.W021"):
            assert code not in output, f"{code} present:\n{output}"

    def test_no_cookie_or_ssl_warnings(self):
        result = _run_deploy_check()
        output = result.stdout + result.stderr
        for code in ("security.W008", "security.W012", "security.W016"):
            assert code not in output, f"{code} present:\n{output}"


class TestProductionHardeningIsUnconditional:
    """Review finding H7: a stray ``DEBUG=True`` must not be able to unharden production.

    Before the settings split, every one of SSL redirect, secure cookies, HSTS and
    nosniff lived inside a single ``if not DEBUG:`` block, so one environment
    variable disabled all four at once and ``check --deploy`` went quiet about it.
    These assertions are the reason the split exists; they cannot pass against a
    settings module that decides its own posture from the environment.
    """

    def test_debug_env_var_cannot_turn_debug_on_in_prod(self):
        result = _run_deploy_check({"DEBUG": "True"})
        output = result.stdout + result.stderr
        # security.W018 is "DEBUG must not be True in deployment".
        assert "security.W018" not in output, f"DEBUG leaked into prod settings:\n{output}"

    def test_debug_env_var_cannot_disable_the_security_settings(self):
        result = _run_deploy_check({"DEBUG": "True"})
        output = result.stdout + result.stderr
        for code in ("security.W004", "security.W008", "security.W012", "security.W016"):
            assert code not in output, f"{code} returned under DEBUG=True:\n{output}"

    def test_prod_states_debug_as_a_literal_not_from_the_environment(self):
        """Source-level guard, for the same reason the SameSite one exists below.

        The two assertions above would keep passing if ``prod.py`` read DEBUG from
        the environment and the test environment happened to be clean. Only reading
        the module's own source distinguishes "stated" from "currently happens to be
        False".
        """
        prod_source = (BACKEND_DIR / "config" / "settings" / "prod.py").read_text(
            encoding="utf-8"
        )
        assert "DEBUG = False" in prod_source
        assert "os.environ" not in prod_source.split("DEBUG = False")[0].split("\n")[-1]


class TestDevIsNotProduction:
    """The dev module must not be silently hardened, or nobody could work locally."""

    def test_dev_settings_have_debug_on(self):
        result = subprocess.run(  # noqa: S603 — fixed argv, trusted input
            [sys.executable, "-c", "from django.conf import settings; print(settings.DEBUG)"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev"},
            capture_output=True,
            text=True,
        )
        assert "True" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
```

Also change the source-text assertion further down the file, which currently reads `config/settings.py`:

```python
        settings_source = (BACKEND_DIR / "config" / "settings" / "base.py").read_text(
            encoding="utf-8"
        )
```

…and the ASGI preload test's explicit module:

```python
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_deploy_settings.py -v
```

Expected: FAIL. `TestProductionHardeningIsUnconditional` errors because `config.settings.prod` does not exist — `ModuleNotFoundError: No module named 'config.settings.prod'; 'config.settings' is not a package`.

- [ ] **Step 3: Create the package and move the file, preserving history**

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
mkdir -p src/backend/config/settings
git mv src/backend/config/settings.py src/backend/config/settings/base.py
touch src/backend/config/settings/__init__.py
git add src/backend/config/settings/__init__.py
```

`base.py` now resolves `BASE_DIR` one directory too shallow — it computes `Path(__file__).resolve().parent.parent`, which was `src/backend/` and is now `src/backend/config/`. Fix line 9:

```python
# Two parents now that settings is a package: settings/base.py -> settings/ -> config/ -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
```

And line 12's `.env` walk, which counted from the old depth:

```python
# Load .env from project root (three levels above src/backend/config/settings/)
load_dotenv(BASE_DIR.parent.parent / ".env")
```

> `BASE_DIR` is `src/backend` in both the old and new code once corrected, so `BASE_DIR.parent.parent` is still the repo root. Getting this wrong is silent: `load_dotenv` on a missing path is a no-op, and every setting falls back to its default. Step 6 checks it explicitly.

- [ ] **Step 4: Strip the environment-conditional branches out of `base.py`**

Three edits, in this order.

**4a. Delete the `DEBUG` definition** at line 15 and replace it with a comment, so nothing in `base.py` can branch on it:

```python
# DEBUG is NOT defined here. It is stated by dev.py and prod.py, because review
# finding H7 was that one environment variable silently disabled SSL redirect,
# secure cookies, HSTS and nosniff together. A module that reads DEBUG from the
# environment is a module that can be deployed unhardened by accident.
```

**4b. Replace the connection block** at lines 154-156:

```python
# Connection settings for serverless (Cloud Run)
if not DEBUG:
    DATABASES["default"]["CONN_MAX_AGE"] = 0
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
```

with nothing — `prod.py` will set it. Delete those four lines.

**4c. Make the two remaining `DEBUG` reads take a neutral default.** Line 176's logging formatter and lines 218-227's `STORAGES` both branch on `DEBUG`. Set them to the *development* value in `base.py` and let `prod.py` override, so a module that forgets to override is loud in production (unminified static, readable logs) rather than insecure:

```python
        "console": {
            "class": "logging.StreamHandler",
            # dev default; prod.py swaps this for the JSON formatter that Cloud
            # Logging parses into queryable fields.
            "formatter": "plain",
        }
```

```python
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    # dev default; prod.py swaps in WhiteNoise's manifest storage.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
```

**4d. Delete the entire production security block** at lines 628-639 (`# Production security` through `SECURE_CONTENT_TYPE_NOSNIFF = True`). It moves to `prod.py` verbatim, minus the `if`.

- [ ] **Step 5: Write `dev.py` and `prod.py`**

`src/backend/config/settings/dev.py`:

```python
"""Local development settings.

Everything that is *only* safe on a laptop lives here, so the production module
never has to ask whether it is in production.
"""

from .base import *  # noqa: F403 — a settings module is a namespace, not an API

DEBUG = True

# Persistent connections: there is no serverless cold-start cost locally, and a
# reconnect per request makes the dev server noticeably slower.
DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
```

`src/backend/config/settings/prod.py`:

```python
"""Production settings — loaded by Cloud Run, in production and in staging alike.

Every hardening line below is unconditional. Review finding **H7** was that they
all sat inside a single ``if not DEBUG:``, so a stray ``DEBUG=True`` in the
environment disabled SSL redirect, secure cookies, HSTS and nosniff at once and
``check --deploy`` reported nothing. There is no environment variable in this
file. If you are reading it, you are hardened.

Staging loads this module too (E16 D7). Staging exists to exercise what
production runs, and a staging module that relaxed anything would make staging a
worse predictor of production than having no staging at all. The differences
between the two environments are all data — database, ``ALLOWED_HOSTS``,
``SENTRY_ENVIRONMENT`` — and all already environment variables read by base.py.
"""

from .base import *  # noqa: F403 — a settings module is a namespace, not an API

DEBUG = False

# --- Transport and cookies ----------------------------------------------
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# HTTP Strict Transport Security: tell browsers to only use HTTPS for a year,
# including subdomains, and allow preload-list inclusion.
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Serverless database behaviour --------------------------------------
# Cloud Run kills idle instances, so a pooled connection outlives nothing and a
# dead one is worse than none. Health-check before reuse.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# --- Static files -------------------------------------------------------
# WhiteNoise's manifest storage: hashed filenames, so a deploy cannot serve a
# stale cached asset. A missing manifest entry is a hard error at render time,
# which is why the Dockerfile's collectstatic must not be allowed to fail.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# --- Logging ------------------------------------------------------------
# Structured JSON on stdout: Cloud Run collects it and Cloud Logging parses each
# line into fields, which is what makes "every ERROR for this household" a query
# instead of a grep.
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405
```

- [ ] **Step 6: Point every entry point at the right module**

Four one-line edits. Run them and then read the diff — a missed one fails at a different time in a different place.

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
sed -i 's/"DJANGO_SETTINGS_MODULE", "config.settings"/"DJANGO_SETTINGS_MODULE", "config.settings.dev"/' src/backend/manage.py
sed -i 's/"DJANGO_SETTINGS_MODULE", "config.settings"/"DJANGO_SETTINGS_MODULE", "config.settings.prod"/' src/backend/config/wsgi.py src/backend/config/asgi.py
sed -i 's/^DJANGO_SETTINGS_MODULE = "config.settings"$/DJANGO_SETTINGS_MODULE = "config.settings.dev"/' pyproject.toml
sed -i 's/^ENV DJANGO_SETTINGS_MODULE=config.settings \\$/ENV DJANGO_SETTINGS_MODULE=config.settings.prod \\/' Dockerfile
git diff -- src/backend/manage.py src/backend/config/wsgi.py src/backend/config/asgi.py pyproject.toml Dockerfile
```

Expected diff: exactly five changed lines, `manage.py` to `.dev`, `wsgi.py`/`asgi.py` to `.prod`, `pyproject.toml` to `.dev`, `Dockerfile` to `.prod`.

Then fix the one test that reloads the settings module by name — `src/backend/core/tests/test_email_config.py:16`:

```python
    import config.settings.base as module
```

Its docstring line above it should follow: `"""Re-import config.settings.base under a patched environment."""`

And confirm `BASE_DIR` survived the move:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c \
  "from django.conf import settings; print(settings.BASE_DIR); print(settings.STATICFILES_DIRS)"
```

Expected: `/home/bessa/Documents/projetos/expense_tracker_v2/src/backend` and a `static` directory under it. Anything shorter means Step 3's parent count is wrong.

- [ ] **Step 7: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_deploy_settings.py src/backend/core/tests/test_email_config.py -v
```

Expected: PASS, including all three `TestProductionHardeningIsUnconditional` cases.

- [ ] **Step 8: Prove the new test can actually fail**

Project convention (`docs/superpowers/plans/` history; the E12 H5 lesson). Temporarily change `prod.py`'s first setting to read the environment:

```bash
sed -i 's/^DEBUG = False$/DEBUG = os.environ.get("DEBUG", "False").lower() == "true"/' src/backend/config/settings/prod.py
sed -i 's/^from .base import \*.*$/import os\n\nfrom .base import *  # noqa: F403/' src/backend/config/settings/prod.py
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_deploy_settings.py::TestProductionHardeningIsUnconditional -v
```

Expected: **FAIL** on all three cases — `security.W018` appears, the security warnings return, and the source-text assertion fails. Then restore:

```bash
git checkout src/backend/config/settings/prod.py
```

- [ ] **Step 9: Run the whole suite, the linter, and both deploy checks**

The split touches how every test loads settings, so a partial run proves nothing here.

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ -q && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
POSTGRES_PORT=5433 uv run python src/backend/manage.py check
POSTGRES_PORT=5433 uv run python src/backend/manage.py check --database default
DJANGO_SETTINGS_MODULE=config.settings.prod \
  SECRET_KEY="aZ9_kQ2w-pR7x!mN4tB6vC8yE0sG1hJ3lD5fH7uI9oP2qW4eR6tY8u0" \
  ALLOWED_HOSTS=example.com CSRF_TRUSTED_ORIGINS=https://example.com \
  uv run python src/backend/manage.py check --deploy
```

Expected: suite green, coverage ≥ 80, ruff clean, `check --deploy` reports `System check identified no issues`.

**Expected failure while doing this:** `ruff` will flag `F403`/`F405` on the star imports. The `# noqa` comments above cover the ones this plan writes; if ruff still complains, add `"F403", "F405"` to a per-file ignore for `src/backend/config/settings/*.py` in `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]` rather than restructuring the modules — star-importing a base settings module is the documented Django idiom.

- [ ] **Step 10: Update the two places that document the old shape**

`docs/runbook.md` line ~1 area and the `.env.example` `DEBUG` comment both imply one settings file. Add to `.env.example` under `DEBUG=True`:

```
# DEBUG is read only by config/settings/dev.py. config/settings/prod.py — what
# Cloud Run loads, in production and staging alike — states DEBUG = False as a
# literal and hardens unconditionally, so this variable cannot unharden a
# deployed instance. See E16 S16-1 / review finding H7.
```

- [ ] **Step 11: Commit**

```bash
git add -A src/backend/config/ src/backend/manage.py src/backend/core/tests/test_deploy_settings.py \
  src/backend/core/tests/test_email_config.py pyproject.toml Dockerfile .env.example
git commit -m "refactor(E16): split settings so production hardening cannot be turned off

Review finding H7: SSL redirect, secure cookies, HSTS and nosniff all sat in one
'if not DEBUG:' block, so a single stray environment variable disabled four
controls at once and check --deploy stayed quiet about it.

config/settings.py becomes a package. prod.py states DEBUG = False as a literal
and hardens unconditionally; there is no environment variable in it. Staging
loads the same module, because staging that relaxes anything predicts nothing.

Three new tests assert the property rather than the current value, including a
source-level one — the others would keep passing if prod.py read DEBUG from an
environment that happened to be clean."
```

---

## Task 2: The drift answer — one function, one command

Closes the first half of **S16-9**. This is the task that addresses the 2026-08-15 outage directly: revision `00046-l64` carried `accounts.0005`'s `Household.plan` while the database sat at `accounts.0004`, and `resolve_active_household` selects `plan_id` in middleware on every request, so every route 500'd for every logged-in user for about a day.

**Files:**
- Create: `src/backend/core/migration_drift.py`
- Create: `src/backend/core/management/commands/check_migration_drift.py`
- Test: `src/backend/core/tests/test_migration_drift.py`

**Interfaces:**
- Consumes: Task 1's settings package (the command is run with `DJANGO_SETTINGS_MODULE=config.settings.prod` in production).
- Produces:
  - `core.migration_drift.unapplied_migrations(alias: str = "default") -> list[str]` — labels like `"accounts.0005_household_plan"`, ordered as `migrate` would apply them. Empty list means in sync. Raises `django.db.utils.OperationalError` if the database is unreachable; **callers must decide what that means**, and Task 3 decides it means "database error", not "drift".
  - Management command `check_migration_drift`, exit code `0` in sync / `1` drifted / `2` unreachable, with `--json` for machine consumption.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_migration_drift.py`:

```python
"""Drift between the code's migrations and the database's applied set.

The failure this exists for is the 2026-08-15 outage: revision 00046-l64 shipped
`accounts.0005`'s `Household.plan` against a database still on `accounts.0004`,
and `resolve_active_household` selects `plan_id` in middleware on every request.
Every route 500'd for every logged-in user for a day. Anonymous requests mostly
passed, which is why it presented as "server error after login" rather than as
an outage — and why nothing noticed.

The drifted case is produced by un-recording a real migration in
`django_migrations`, which is byte-for-byte the state production was in. A mock
would only prove the mock agrees with itself.
"""

import pytest
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from core.migration_drift import unapplied_migrations

# A real, long-landed migration. Un-recording it puts the test database in
# exactly the shape a drifted production database has: the column is present,
# the row saying so is not.
A_REAL_MIGRATION = ("core", "0009_policy_acceptance_and_consent")


@pytest.mark.django_db
class TestUnappliedMigrations:
    def test_a_migrated_database_reports_no_drift(self):
        assert unapplied_migrations() == []

    def test_an_unrecorded_migration_is_reported(self):
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)

        drift = unapplied_migrations()

        assert "core.0009_policy_acceptance_and_consent" in drift

    def test_the_report_names_every_migration_that_would_run(self):
        """`migrate <app>` is the fix, so the answer must name the app and the file.

        A check that says "the database is behind" sends you on an investigation.
        One that says "core.0009_policy_acceptance_and_consent" is the fix.
        """
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)

        drift = unapplied_migrations()

        assert all("." in label for label in drift), drift
        app, _, name = drift[0].partition(".")
        assert app and name

    def test_it_asks_the_database_each_time_rather_than_caching(self):
        """Drift can appear *after* a process starts — a rollback is the usual way.

        A module-level cache would make the healthz check in Task 3 report the
        state at boot forever, which is precisely the day-long blind spot the
        2026-08-15 incident opened.
        """
        assert unapplied_migrations() == []
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)
        assert unapplied_migrations() != []
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_migration_drift.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.migration_drift'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/backend/core/migration_drift.py`:

```python
"""Is the database behind the code that is running against it?

Asked through `MigrationExecutor.migration_plan`, which is the same code
`migrate` itself uses to decide what to run — so this answer cannot disagree
with what `migrate` would do. Parsing `showmigrations` output would be a second
implementation of the same question, and two implementations of one question is
how they start to differ.

Deliberately *not* cached. Drift can appear after a process has started — a
rollback to a revision older than the applied migrations is the usual way — and
a value computed once at boot is exactly the blind spot that kept the
2026-08-15 outage open for a day after it opened.
"""

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


def unapplied_migrations(alias: str = "default") -> list[str]:
    """Return ``app.name`` labels for migrations the database has not applied.

    Empty list means in sync. The order is the order ``migrate`` would apply
    them, so the first entry is where a fix starts.

    Raises whatever the database driver raises when it cannot connect; a caller
    that cannot tell "unreachable" from "drifted" will report the wrong outage.
    """
    executor = MigrationExecutor(connections[alias])
    targets = executor.loader.graph.leaf_nodes()
    return [f"{migration.app_label}.{migration.name}" for migration, _backwards in executor.migration_plan(targets)]
```

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_migration_drift.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Write the failing test for the management command**

Append to `src/backend/core/tests/test_migration_drift.py`:

```python
import json
from io import StringIO

from django.core.management import call_command


@pytest.mark.django_db
class TestCheckMigrationDriftCommand:
    """The cron- and operator-facing wrapper. Its exit code is its contract."""

    def test_it_exits_zero_and_says_so_when_in_sync(self):
        out = StringIO()
        call_command("check_migration_drift", stdout=out)
        assert "no drift" in out.getvalue().lower()

    def test_it_raises_command_error_when_drifted(self):
        """CommandError is how a management command exits non-zero.

        The exit code is the whole point: Cloud Scheduler decides the job failed
        from the process's status, and a command that printed a warning and
        exited 0 would make the nightly check decorative.
        """
        from django.core.management.base import CommandError

        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)
        with pytest.raises(CommandError) as excinfo:
            call_command("check_migration_drift")
        assert "core.0009_policy_acceptance_and_consent" in str(excinfo.value)

    def test_json_output_is_machine_readable(self):
        out = StringIO()
        call_command("check_migration_drift", "--json", stdout=out)
        payload = json.loads(out.getvalue())
        assert payload == {"drift": False, "unapplied": []}
```

Run it:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_migration_drift.py::TestCheckMigrationDriftCommand -v
```

Expected: FAIL — `Unknown command: 'check_migration_drift'`.

- [ ] **Step 6: Write the command**

Create `src/backend/core/management/commands/check_migration_drift.py`:

```python
"""Fail loudly when the database is behind the code running against it.

Run after every production deploy and nightly thereafter (E16 S16-9). The
nightly part is not belt-and-braces: the 2026-08-15 window *opened* at a deploy
but stayed open for a day because nothing re-asked. Drift also arrives without a
deploy — a rollback, or a `migrate` pointed at the wrong database.

Operator procedure: `docs/runbook.md`, "Schema drift".
"""

import json

from django.core.management.base import BaseCommand, CommandError

from core.migration_drift import unapplied_migrations


class Command(BaseCommand):
    help = "Exit non-zero if the database has not applied every migration in the image."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")

    def handle(self, *args, **options):
        unapplied = unapplied_migrations()

        if options["json"]:
            self.stdout.write(json.dumps({"drift": bool(unapplied), "unapplied": unapplied}))
            if unapplied:
                raise CommandError(f"schema drift: {', '.join(unapplied)}")
            return

        if not unapplied:
            # Logged on every run, including the ones that find nothing — the
            # alert in Task 7 fires on *silence*, so a quiet success is data.
            self.stdout.write(self.style.SUCCESS("ledger_drift_check_ran: no drift"))
            return

        raise CommandError(
            "ledger_drift_check_ran: schema drift — the database has not applied "
            f"{len(unapplied)} migration(s): {', '.join(unapplied)}. "
            "Fix with: DATABASE_URL=<direct connection, port 5432> "
            "uv run python src/backend/manage.py migrate"
        )
```

- [ ] **Step 7: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_migration_drift.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 8: Prove the drifted test can fail**

```bash
sed -i 's/^    return \[f"{migration.app_label}.*$/    return []/' src/backend/core/migration_drift.py
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_migration_drift.py -v
```

Expected: **FAIL** on `test_an_unrecorded_migration_is_reported`, `test_the_report_names_every_migration_that_would_run`, `test_it_asks_the_database_each_time_rather_than_caching`, and `test_it_raises_command_error_when_drifted`. If any of those four still passes, that test is not testing anything. Restore:

```bash
git checkout src/backend/core/migration_drift.py 2>/dev/null || git stash pop
```

(If the file is not yet tracked, re-apply Step 3's content by hand.)

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/migration_drift.py \
  src/backend/core/management/commands/check_migration_drift.py \
  src/backend/core/tests/test_migration_drift.py
git commit -m "feat(E16): detect a database that is behind the image running against it

The 2026-08-15 outage: revision 00046-l64 shipped accounts.0005's
Household.plan against a database on accounts.0004, and the household resolver
selects plan_id in middleware on every request. Every route 500'd for every
logged-in user for a day, and nothing in the system noticed.

unapplied_migrations() asks MigrationExecutor.migration_plan — the same code
migrate uses — so the answer cannot disagree with reality. It names the missing
migrations, so the fix is a migrate command rather than an investigation.

Not cached: drift also arrives from a rollback, after boot."
```

---

## Task 3: `/healthz/` reports drift, and degrades

Closes the second half of **S16-9**. Decision **D2**: drift makes the health endpoint return 503, so the uptime check that already exists — policy `17994738960177318338`, notifying *Operator email* — catches it within five minutes with no new alerting infrastructure.

> **Read this before implementing.** Cloud Run's *startup probe* hits `/healthz/`. After this change, deploying an image whose migrations have not been applied means the new revision never becomes ready and the deploy **aborts**, leaving the previous revision serving. That is the correct failure, and it is why Task 6's production job runs migrations *before* `gcloud run deploy` (decision **D6**). Deploy-then-migrate under this change does not produce 500s; it produces a stuck deploy.
>
> **Before merging this task, confirm production is not already drifted**, or the first deploy after it will fail for a reason that looks like this task's fault:
> ```bash
> DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
>   uv run python src/backend/manage.py showmigrations --plan | grep -c '^\[ \]'
> ```
> Expect `0`. Anything else: apply the migrations first, per `docs/runbook.md` § *Applying a migration to Supabase*.

**Files:**
- Modify: `src/backend/core/views.py:11-24` (`health_check`)
- Test: `src/backend/core/tests/test_health.py`

**Interfaces:**
- Consumes: `core.migration_drift.unapplied_migrations()` from Task 2.
- Produces: `GET /healthz/` returns `{"status": ..., "database": ..., "migrations": ..., "unapplied": [...]}`. `status` is `"ok"` (200), or `"degraded"` (503) when either the database is unreachable or migrations are unapplied. `migrations` is `"ok"`, `"drift"`, or `"unknown"` — Task 7's scheduled check and Task 12's runbook section both read these exact strings.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/core/tests/test_health.py`:

```python
from unittest.mock import patch

from django.db.utils import OperationalError


class HealthCheckMigrationDriftTest(TestCase):
    """A drifted revision is already broken for its users; say so out loud.

    Cloud Run's uptime check polls this endpoint every five minutes, so a 503
    here is the difference between "an operator notices within five minutes" and
    "a day passes at ~100% authenticated failure" — which is what 2026-08-15
    actually cost, because the count-based 5xx alert never reached its
    threshold at family-scale traffic.
    """

    def test_a_synced_database_reports_migrations_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["migrations"], "ok")
        self.assertEqual(data["unapplied"], [])

    def test_drift_degrades_the_endpoint_to_503(self):
        with patch(
            "core.views.unapplied_migrations",
            return_value=["accounts.0005_household_plan"],
        ):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["migrations"], "drift")

    def test_drift_names_the_missing_migrations(self):
        """`migrate accounts` is the fix. Anything less sends you investigating."""
        with patch(
            "core.views.unapplied_migrations",
            return_value=["accounts.0005_household_plan", "core.0010_thing"],
        ):
            response = self.client.get("/healthz/")
        self.assertEqual(
            response.json()["unapplied"],
            ["accounts.0005_household_plan", "core.0010_thing"],
        )

    def test_an_unreachable_database_is_reported_as_a_database_error_not_as_drift(self):
        """Two different outages. Conflating them sends the operator to the wrong runbook."""
        with patch("core.views.connection.ensure_connection", side_effect=OperationalError("nope")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["database"], "error")
        self.assertEqual(data["migrations"], "unknown")

    def test_a_drift_check_that_itself_raises_does_not_500_the_probe(self):
        """The probe must answer even when the drift question cannot be asked.

        A health endpoint that raises is indistinguishable from a dead
        container, and the operator loses the one signal that was still working.
        """
        with patch("core.views.unapplied_migrations", side_effect=RuntimeError("boom")):
            response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["migrations"], "unknown")
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_health.py -v
```

Expected: FAIL — `KeyError: 'migrations'` on the first new case, and `AttributeError: <module 'core.views'> does not have the attribute 'unapplied_migrations'` on the rest.

- [ ] **Step 3: Write the implementation**

In `src/backend/core/views.py`, add the import beside the existing ones:

```python
from core.migration_drift import unapplied_migrations
```

and replace `health_check` (lines 11-24) with:

```python
def health_check(request):
    """Health check endpoint for Cloud Run startup/liveness probes.

    Reports *two* independent things, because they are two different outages
    with two different fixes: whether the database answers, and whether it has
    applied the migrations the running image expects.

    Drift returns 503 deliberately (E16 D2). The trade-off is explicit: a
    drifted revision is taken out of rotation. It is the right trade here
    because a drifted revision is *already* broken for every logged-in user —
    that is what 2026-08-15 was — and 503 is what makes the existing uptime
    check (policy 17994738960177318338) notice within five minutes instead of
    within a day.

    The consequence for deploys: Cloud Run's startup probe hits this endpoint,
    so an image deployed ahead of its migrations never becomes ready and the
    deploy aborts with the previous revision still serving. That is why the
    pipeline migrates first — see `.github/workflows/deploy.yml`.
    """
    db_status = "ok"
    migrations_status = "ok"
    unapplied: list[str] = []

    try:
        connection.ensure_connection()
    except Exception:
        db_status = "error"
        migrations_status = "unknown"
    else:
        try:
            unapplied = unapplied_migrations()
        except Exception:
            # The probe must still answer. A health endpoint that raises is
            # indistinguishable from a dead container, and the operator loses
            # the last signal that was working.
            migrations_status = "unknown"
        else:
            migrations_status = "drift" if unapplied else "ok"

    healthy = db_status == "ok" and migrations_status == "ok"
    return JsonResponse(
        {
            "status": "ok" if healthy else "degraded",
            "database": db_status,
            "migrations": migrations_status,
            "unapplied": unapplied,
        },
        status=200 if healthy else 503,
    )
```

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_health.py -v
```

Expected: PASS, 9 tests — the four original ones still green, since the test database is migrated.

- [ ] **Step 5: Prove the drift case can fail**

```bash
sed -i 's/^    healthy = db_status == "ok" and migrations_status == "ok"$/    healthy = db_status == "ok"/' src/backend/core/views.py
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_health.py -v
```

Expected: **FAIL** on `test_drift_degrades_the_endpoint_to_503` and `test_a_drift_check_that_itself_raises_does_not_500_the_probe`. Restore with `git checkout src/backend/core/views.py` and re-apply Step 3.

- [ ] **Step 6: Check the cost of the added work on the hot path**

`unapplied_migrations()` builds the migration graph from disk on every call. `/healthz/` is polled by the uptime check every five minutes and by Cloud Run's probes, so this must be milliseconds, not tens of them.

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
import time
from core.migration_drift import unapplied_migrations
unapplied_migrations()  # warm the module cache
t = time.perf_counter()
for _ in range(10):
    unapplied_migrations()
print(f'{(time.perf_counter() - t) / 10 * 1000:.1f} ms per call')
"
```

Expected: well under 100 ms. If it is not, do **not** add a cache — that reintroduces the blind spot Task 2's `test_it_asks_the_database_each_time_rather_than_caching` exists to prevent. Instead record the number here and raise it in review; the honest fallback is a separate `/readyz/` and a scheduled check only, which is the option D2 declined.

- [ ] **Step 7: Full suite, lint, commit**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ -q && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/views.py src/backend/core/tests/test_health.py
git commit -m "feat(E16): /healthz/ degrades to 503 on schema drift, naming the migrations

The uptime check already polls this endpoint every five minutes and already
notifies the operator, so drift now surfaces in minutes with no new alerting
infrastructure. On 2026-08-15 it took a day, because the count-based 5xx policy
never reaches 'more than 5 in 5 minutes' at family-scale traffic.

The trade-off is stated in the docstring and accepted: a drifted revision leaves
rotation. It was already broken for every logged-in user.

The deploy consequence is real — Cloud Run's startup probe reads this endpoint,
so an image deployed ahead of its migrations fails to start rather than serving
500s. The pipeline therefore migrates first."
```

---

## Task 4: Provision staging

Closes **S16-2**. Infrastructure, not code — the deliverable is a running environment plus the runbook section that lets someone else rebuild it. Decision **D1**: a separate Supabase project, so a wrong `DATABASE_URL` cannot reach production.

> **The hard rule of this task: production financial records must never be copied into staging.** Staging is seeded by `seed_qa_data`, which generates realistic fabricated households. Every restore rehearsal (Task 11) goes into a scratch database, never into staging. This is not a preference — S16-2 states it, and E13 made it a legal exposure.

**Files:**
- Modify: `.env.example` (staging block)
- Modify: `docs/runbook.md` (new section: *The staging environment*)

**Interfaces:**
- Consumes: Task 1's `config.settings.prod` (staging loads it — decision D7).
- Produces, for Task 5's workflow to reference:
  - Cloud Run service `expense-tracker-staging`, project `expense-tracker-482807`, region `southamerica-east1`.
  - A Supabase project whose **session pooler** (port 5432) is the migration connection and whose **transaction pooler** (6543) is the runtime connection.
  - GitHub Environment `staging`, holding secrets `STAGING_POSTGRES_HOST`, `STAGING_POSTGRES_PORT`, `STAGING_POSTGRES_USER`, `STAGING_POSTGRES_PASSWORD`, `STAGING_POSTGRES_DB`.

- [ ] **Step 1: Create the Supabase project and record its two connection strings**

In the Supabase dashboard, create a project named `ledger-staging` in the same region family as production. From *Project Settings → Database → Connection string*, copy both the **Session pooler** (port 5432) and **Transaction pooler** (6543) forms.

Write them into your local `.env` under new keys — never into the repo:

```
SUPABASE_STAGING_SESSION_POOLER=
SUPABASE_STAGING_TRANSACTION_POOLER=
```

**Expected failure:** the free tier allows two active projects. If creation is refused, the production project is not the second one — check for an old abandoned project and delete it, or accept decision D1's rejected alternative and say so in review rather than silently sharing production's project.

- [ ] **Step 2: Add the staging block to `.env.example`**

Beside the existing `SUPABASE_TRANSACTION_POOLER` / `SUPABASE_SESSION_POOLER` pair (`.env.example:41-44`):

```
# Staging (E16 S16-2). A SEPARATE Supabase project, not a second database inside
# production's — a wrong DATABASE_URL then cannot reach production, and a restore
# rehearsal never touches production's project. Read by scripts and by the deploy
# workflow's `staging` GitHub Environment, never by settings.py.
#
# Supabase pauses a free project after ~1 week with no queries. Staging WILL hit
# this. Unpausing is a dashboard button and takes a couple of minutes; the deploy
# workflow's migrate step is what fails first, with a connection timeout.
SUPABASE_STAGING_SESSION_POOLER=
SUPABASE_STAGING_TRANSACTION_POOLER=
```

- [ ] **Step 3: Migrate the staging database from your laptop, once**

The first migration happens by hand so the pipeline's first run is a deploy, not a bootstrap. The password contains a space in production and may in staging too, so pass libpq parts rather than a URL — this is `docs/runbook.md` § *Applying a migration to Supabase*, common failure #2.

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
POSTGRES_HOST=<staging session pooler host> \
POSTGRES_PORT=5432 \
POSTGRES_USER=<staging user> \
POSTGRES_PASSWORD='<staging password>' \
POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod \
SECRET_KEY=bootstrap-only-replaced-on-deploy \
ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py migrate
```

Expected: the full list of migrations applying, ending `Applying core.0009_policy_acceptance_and_consent... OK` or later.

**Expected failure:** `django.db.utils.OperationalError: connection to server ... failed`. The project is paused — open the dashboard and resume it.

- [ ] **Step 4: Deploy the staging service**

Every environment-specific value is set explicitly on this first deploy; bare deploys afterwards preserve them. Use the `^|^` separator form, not `^@^` — `PRIVACY_CONTACT_EMAIL` contains an `@` and gcloud would split the address in half (`docs/runbook.md` § *Passing a value that contains a comma, a space, or an `@`*).

```bash
gcloud run deploy expense-tracker-staging --source . \
  --project expense-tracker-482807 \
  --region southamerica-east1 \
  --allow-unauthenticated \
  --update-env-vars "^|^DEBUG=False|SENTRY_ENVIRONMENT=staging|LOGFIRE_ENVIRONMENT=staging|ALLOWED_HOSTS=<staging run.app host>|CSRF_TRUSTED_ORIGINS=https://<staging run.app host>|DATABASE_URL=<staging TRANSACTION pooler URL, port 6543>|ADMIN_URL_PATH=<a different unguessable path than production's>|PRIVACY_CONTROLLER_NAME=Ambiente de homologação (não é o controlador)|PRIVACY_CONTROLLER_CNPJ=00.000.000/0001-91|PRIVACY_CONTROLLER_ADDRESS=Staging|PRIVACY_CONTACT_EMAIL=staging@example.com" \
  --quiet
```

Four things about that command are deliberate:

- **`DATABASE_URL` is the transaction pooler (6543)**, matching production's runtime. Migrations use 5432 and are never run by the service.
- **`ADMIN_URL_PATH` differs from production's.** Reusing it would publish production's admin path to anyone who finds staging's.
- **The `PRIVACY_*` values are visibly not a real controller.** `core.checks_privacy` (E13.001) refuses to start with them blank, and a staging instance carrying production's CNPJ is a document claiming to be something it is not.
- **No `OPENAI_API_KEY` / `RESEND_API_KEY` is set.** Staging exercises deploys and migrations, not LLM spend. `settings.base` falls back to `sk-not-set`, and the assistant fails loudly there — which is correct and free. Add real keys only if a future task needs to exercise the assistant on staging, and use a separate key with its own spend cap.

Expected output: `Service [expense-tracker-staging] revision [expense-tracker-staging-00001-xxx] has been deployed and is serving 100 percent of traffic.`

**Expected failure:** the revision fails its startup probe with `/healthz/` returning 503. After Task 3 that means one of two things, and the response body says which — `"migrations": "drift"` means Step 3 was skipped or targeted the wrong database; `"database": "error"` means `DATABASE_URL` is wrong or the project is paused.

```bash
gcloud run services logs read expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 --limit 50
```

- [ ] **Step 5: Seed realistic, fabricated data**

```bash
S=https://<staging run.app host>
# A user to own the data.
gcloud run services proxy expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 --port 8081 &
```

Seeding runs as a one-off Cloud Run Job against the same image, mirroring the `ledger-purge` pattern so it uses the service's own env rather than a laptop's:

```bash
IMAGE=$(gcloud run services describe expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format='value(spec.template.spec.containers[0].image)')

gcloud run jobs create staging-seed \
  --project expense-tracker-482807 --region southamerica-east1 \
  --image "$IMAGE" \
  --set-env-vars "^|^DEBUG=False|DATABASE_URL=<staging session pooler URL, port 5432>|SECRET_KEY=seed-only|ALLOWED_HOSTS=localhost|PRIVACY_CONTROLLER_NAME=Staging|PRIVACY_CONTROLLER_CNPJ=00.000.000/0001-91|PRIVACY_CONTROLLER_ADDRESS=Staging|PRIVACY_CONTACT_EMAIL=staging@example.com" \
  --command python --args manage.py,seed_qa_data

gcloud run jobs execute staging-seed \
  --project expense-tracker-482807 --region southamerica-east1 --wait
```

**Read `src/backend/finances/management/commands/seed_qa_data.py` before running it** — it takes a username argument in some forms and will tell you what it needs. If it requires an existing user, create one first through staging's signup page; that also exercises E05's email verification against staging, which is worth knowing works.

Verify the money is fabricated and non-trivial:

```bash
gcloud run jobs create staging-totals --project expense-tracker-482807 \
  --region southamerica-east1 --image "$IMAGE" \
  --set-env-vars "^|^DEBUG=False|DATABASE_URL=<staging session pooler URL>|SECRET_KEY=x|ALLOWED_HOSTS=localhost|PRIVACY_CONTROLLER_NAME=Staging|PRIVACY_CONTROLLER_CNPJ=00.000.000/0001-91|PRIVACY_CONTROLLER_ADDRESS=Staging|PRIVACY_CONTACT_EMAIL=staging@example.com" \
  --command python --args manage.py,dump_ledger_totals,--json
gcloud run jobs execute staging-totals --project expense-tracker-482807 \
  --region southamerica-east1 --wait
gcloud run jobs executions logs read <execution-name> \
  --project expense-tracker-482807 --region southamerica-east1
```

Expected: JSON with at least one household, a non-zero `entry_sum`, and household names that are obviously fabricated. **If any name matches a real one, stop and rebuild the database** — production data has reached a lower environment and that is the one thing this task forbids.

- [ ] **Step 6: Smoke-test staging**

```bash
S=https://<staging run.app host>
for p in /healthz/ / /.well-known/assetlinks.json; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" -m 60 "$S$p"
done
curl -s "$S/healthz/" | python3 -m json.tool
```

Expected: `200`, `302`, `200`, and a health body of `{"status": "ok", "database": "ok", "migrations": "ok", "unapplied": []}`.

- [ ] **Step 7: Create the GitHub Environment and its secrets**

```bash
gh api -X PUT repos/bessavagner/expense_tracker_v2/environments/staging
for k in HOST PORT USER PASSWORD DB; do
  gh secret set "STAGING_POSTGRES_$k" --env staging --repo bessavagner/expense_tracker_v2
done
```

`STAGING_POSTGRES_PORT` is `5432` — the **session** pooler, because the workflow's job is migrations. `STAGING_POSTGRES_DB` is `postgres` unless the dashboard says otherwise.

Verify they exist without printing them:

```bash
gh secret list --env staging --repo bessavagner/expense_tracker_v2
```

Expected: five rows, no values.

- [ ] **Step 8: Write the runbook section**

Add to `docs/runbook.md`, immediately after § *Deploy a new revision* and before § *When something breaks*:

````markdown
## The staging environment

Cloud Run service `expense-tracker-staging`, same project and region as
production, backed by a **separate Supabase project**. It loads
`config.settings.prod` — the same hardened module production loads — because a
staging module that relaxed anything would make staging a worse predictor of
production than no staging at all (E16 D7).

**Staging has never held production data and must never hold it.** It is seeded
by `manage.py seed_qa_data`, which fabricates households. Restore rehearsals go
into a scratch database, never here.

```bash
S=https://<staging run.app host>
curl -s "$S/healthz/" | python3 -m json.tool
```

Expect `{"status": "ok", "database": "ok", "migrations": "ok", "unapplied": []}`.

**Common failure: the project is paused.** Supabase suspends a free project after
about a week with no queries, and staging is idle by design. The symptom is a
connection timeout in the deploy workflow's migrate step, or `"database":
"error"` from the health endpoint. Fix it in the Supabase dashboard —
*Project → Resume* — and re-run the workflow. Nothing is lost.

**Common failure: `ADMIN_URL_PATH` copied from production.** Staging's admin path
is deliberately different. If it ever matches, production's unguessable path has
been published to anyone who can read staging's environment.

### Rebuilding staging from nothing

Full procedure in `docs/superpowers/plans/2026-08-18-E16-operations-staging-deploy-recovery.md`,
Task 4. In summary: create the Supabase project, `manage.py migrate` against its
session pooler (port 5432), `gcloud run deploy expense-tracker-staging --source .`
with the environment block from that task, then run the `staging-seed` job.
````

- [ ] **Step 9: Commit**

```bash
git add .env.example docs/runbook.md
git commit -m "feat(E16): a staging environment with its own Supabase project

Separate project rather than a second database inside production's: a wrong
DATABASE_URL then cannot reach production, and a restore rehearsal never touches
production's project. Costs nothing on the free tier; the price is that Supabase
pauses an idle free project after a week, which the runbook now names as the
first thing to check.

Staging loads config.settings.prod. Seeded with fabricated households by
seed_qa_data — production financial records never enter a lower environment."
```

---

## Task 5: Workload Identity Federation, and the staging deploy

Closes the first half of **S16-3**: a merge to `main` migrates and deploys staging, authenticated with **no long-lived service-account key in CI**.

**Files:**
- Create: `.github/workflows/deploy.yml`
- Modify: `docs/runbook.md` (new section: *The deploy pipeline*)
- Modify: `deploy/README.md`

**Interfaces:**
- Consumes: Task 4's staging service and `staging` GitHub Environment; Task 1's `config.settings.prod`.
- Produces, for Task 6 to extend:
  - Repository variables `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_DEPLOY_SERVICE_ACCOUNT` — **variables, not secrets** (see Step 3).
  - A reusable job shape: authenticate → migrate against the session pooler → `gcloud run deploy --source .`.

- [ ] **Step 1: Create the deploy service account and grant it exactly what a deploy needs**

```bash
P=expense-tracker-482807
gcloud iam service-accounts create github-deployer \
  --project "$P" --display-name "GitHub Actions deployer"

SA="github-deployer@${P}.iam.gserviceaccount.com"
for role in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/storage.admin \
            roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$P" --member "serviceAccount:$SA" --role "$role"
done
```

Why each: `run.admin` deploys revisions and updates jobs (Task 6 re-points `ledger-purge`); `cloudbuild.builds.editor` + `storage.admin` are what `--source .` needs to upload the build context and run Cloud Build; `artifactregistry.writer` stores the resulting image; `iam.serviceAccountUser` lets the deployer act as the *runtime* service account the service already uses — without it, `gcloud run deploy` fails with `PERMISSION_DENIED: ... iam.serviceaccounts.actAs`.

- [ ] **Step 2: Create the Workload Identity pool and provider**

```bash
P=expense-tracker-482807
PROJECT_NUMBER=$(gcloud projects describe "$P" --format='value(projectNumber)')
echo "$PROJECT_NUMBER"   # expected: 654941182076 — verify, do not assume

gcloud iam workload-identity-pools create github \
  --project "$P" --location global --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --project "$P" --location global --workload-identity-pool github \
  --display-name "GitHub OIDC" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition "assertion.repository_owner == 'bessavagner'"
```

The `--attribute-condition` is not optional and not decoration: without it, **any** GitHub repository in the world can request a token from this provider. gcloud now refuses to create an unconditioned provider for exactly this reason; if yours does not, add the condition anyway.

Bind the pool identity to the service account, scoped to this one repository:

```bash
SA="github-deployer@${P}.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$P" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/bessavagner/expense_tracker_v2"
```

- [ ] **Step 3: Record the two identifiers as repository *variables***

```bash
P=expense-tracker-482807
PROJECT_NUMBER=$(gcloud projects describe "$P" --format='value(projectNumber)')
R=bessavagner/expense_tracker_v2

gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$R" \
  --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-provider"
gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "$R" \
  --body "github-deployer@${P}.iam.gserviceaccount.com"
```

**Variables, deliberately, not secrets.** Neither value is a credential — the provider path and the service-account email are public identifiers, and the *only* thing that authorises anything is the attribute condition plus the `principalSet` binding above. Storing them as secrets buys nothing and costs real operability: a masked value cannot be read back, so an operator debugging a `PERMISSION_DENIED` cannot see what identity was even attempted. Global constraint 7 is about secrets in git; these are in neither git nor a secret store, and Task 12's credential inventory records where they live.

- [ ] **Step 4: Write the workflow**

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

# Staging on every merge to main; production only on a v* tag (E16 D3).
# A deliberate trigger recorded in git history, rather than in an Actions log.
on:
  push:
    branches: [main]
    tags: ["v*"]

# No long-lived service-account key exists anywhere in this repository or its
# secrets. `id-token: write` is what lets the job mint a short-lived OIDC token
# that Google exchanges for credentials, scoped by the provider's attribute
# condition to this repository alone (E16 S16-3).
permissions:
  contents: read
  id-token: write

# A second push while a deploy is running would race two revisions of the same
# service. Queue instead, and never cancel a run that may have already migrated.
concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false

env:
  GCP_PROJECT: expense-tracker-482807
  GCP_REGION: southamerica-east1

jobs:
  staging:
    if: startsWith(github.ref, 'refs/heads/')
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.12
      - run: uv sync

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOY_SERVICE_ACCOUNT }}

      - uses: google-github-actions/setup-gcloud@v2

      # Migrations run BEFORE the new revision exists, against the DIRECT
      # (session-pooler, 5432) connection — the transaction pooler is pgbouncer
      # in transaction mode and does not support everything a migration needs.
      #
      # Passed as libpq parts rather than as a DATABASE_URL: the production
      # password contains a space, and a URL carrying one is rejected by
      # pg_dump 17 and mangled by Django's URL parser. Staging's may too.
      # See docs/runbook.md, "Applying a migration to Supabase", failure #2.
      #
      # This step failing aborts the job, so a failed migration can never leave
      # a half-migrated database serving traffic.
      - name: Migrate staging
        env:
          DJANGO_SETTINGS_MODULE: config.settings.prod
          SECRET_KEY: migration-step-only-never-serves-a-request
          ALLOWED_HOSTS: localhost
          POSTGRES_HOST: ${{ secrets.STAGING_POSTGRES_HOST }}
          POSTGRES_PORT: ${{ secrets.STAGING_POSTGRES_PORT }}
          POSTGRES_USER: ${{ secrets.STAGING_POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ secrets.STAGING_POSTGRES_PASSWORD }}
          POSTGRES_DB: ${{ secrets.STAGING_POSTGRES_DB }}
          PRIVACY_CONTROLLER_NAME: Staging
          PRIVACY_CONTROLLER_CNPJ: 00.000.000/0001-91
          PRIVACY_CONTROLLER_ADDRESS: Staging
          PRIVACY_CONTACT_EMAIL: staging@example.com
        run: uv run python src/backend/manage.py migrate --no-input

      # A bare deploy: no --set-env-vars, no --set-secrets, so the revision
      # inherits the environment Task 4 set. --set-env-vars would REPLACE the
      # whole list and wipe DATABASE_URL.
      - name: Deploy staging
        run: |
          gcloud run deploy expense-tracker-staging --source . \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --quiet

      # The revision only became ready because /healthz/ returned 200, which
      # after E16 Task 3 already proves migrations are applied. This re-checks
      # from outside and fails the job loudly if the service is degraded.
      - name: Smoke test
        run: |
          URL=$(gcloud run services describe expense-tracker-staging \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')
          BODY=$(curl -sf -m 60 "$URL/healthz/")
          echo "$BODY"
          echo "$BODY" | grep -q '"status": "ok"' \
            || { echo "::error::staging /healthz/ is not ok: $BODY"; exit 1; }
          code=$(curl -s -o /dev/null -w '%{http_code}' -m 60 "$URL/")
          [ "$code" = "302" ] || { echo "::error::/ returned $code, expected 302"; exit 1; }
```

- [ ] **Step 5: Prove it runs — on a branch, before it can touch anything**

Do not merge to `main` to find out whether the workflow parses.

```bash
git add .github/workflows/deploy.yml
git commit -m "wip: deploy workflow"
git push -u origin HEAD
gh workflow list --repo bessavagner/expense_tracker_v2
```

Expected: `Deploy` appears in the list, which means GitHub parsed the YAML. A syntax error shows as the workflow being absent.

Then trigger it for real by merging the task's branch to `main` and watching:

```bash
gh run watch --repo bessavagner/expense_tracker_v2
```

Expected: `staging` job green, with `Migrate staging` printing `No migrations to apply.` (Task 4 already migrated) and the smoke test printing `{"status": "ok", ...}`.

**Expected failure #1:** `Error: google-github-actions/auth failed ... unable to get credentials`. The `principalSet` binding names the wrong repository, or `PROJECT_NUMBER` is the project *ID* rather than the number. Re-read Step 2's output.

**Expected failure #2:** `PERMISSION_DENIED: ... iam.serviceaccounts.actAs`. The `roles/iam.serviceAccountUser` binding from Step 1 is missing.

**Expected failure #3:** the deploy succeeds but the smoke test fails with `"migrations": "drift"`. The migrate step ran against a *different* database than the service reads — check that `STAGING_POSTGRES_HOST` is the session pooler for the same project whose transaction pooler is in the service's `DATABASE_URL`.

- [ ] **Step 6: Prove the migration ordering is real, not incidental**

S16-3 requires that a failed migration aborts the deploy. Verify it rather than assume it: temporarily point `STAGING_POSTGRES_HOST` at an unreachable host, push a trivial commit to `main`, and confirm the run fails at `Migrate staging` with **no new revision created**.

```bash
gh secret set STAGING_POSTGRES_HOST --env staging --repo bessavagner/expense_tracker_v2 --body "db.invalid.example.com"
git commit --allow-empty -m "chore(E16): prove a failed migration aborts the deploy" && git push
gh run watch --repo bessavagner/expense_tracker_v2
gcloud run revisions list --service expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 --limit 3
```

Expected: the run fails at `Migrate staging`; `Deploy staging` shows as skipped; the newest revision is unchanged. Restore the secret afterwards and re-run.

Record the run URL — Task 13's DoD sweep cites it.

- [ ] **Step 7: Write the runbook section**

Add to `docs/runbook.md` after § *The staging environment*:

````markdown
## The deploy pipeline

`.github/workflows/deploy.yml`. **Merge to `main` → staging. Push a `v*` tag →
production.** Nothing else deploys anything.

Authentication is Workload Identity Federation: the job mints a short-lived OIDC
token and Google exchanges it for credentials. **There is no service-account key
in this repository or its secrets, and there must never be one.** Two repository
*variables* (not secrets — they are public identifiers, and masking them only
makes a `PERMISSION_DENIED` undebuggable) name the provider and the identity:

```bash
gh variable list --repo bessavagner/expense_tracker_v2
```

### Deploying to production

```bash
git tag -a v0.1.0 -m "what shipped"
git push origin v0.1.0
gh run watch --repo bessavagner/expense_tracker_v2
```

The job migrates first, deploys second, smoke-tests third, and re-points the
`ledger-purge` job at the new image last. **Migrating first is load-bearing**,
not tidiness: `/healthz/` returns 503 when the database is behind the image, and
Cloud Run's startup probe reads `/healthz/`, so an image deployed ahead of its
migrations never becomes ready and the deploy aborts with the previous revision
still serving.

**Common failure: the job fails at `Migrate production` and nothing deployed.**
That is the design working. The previous revision is still serving; fix the
migration and push a new tag. Do not deploy around it.

**Common failure: `PERMISSION_DENIED: ... iam.serviceaccounts.actAs`.** The
deployer service account lost `roles/iam.serviceAccountUser`. Re-grant it; see
the plan's Task 5, Step 1 for the full role list and why each is there.

**Common failure: the deploy hangs, then reports the revision failed to become
ready.** Read the health body — it names the cause:

```bash
gcloud run services logs read expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 --limit 50
```

### Deploying by hand, when the pipeline is down

The manual procedure in § *Deploy a new revision* still works and is still
correct. Run `manage.py migrate` against the session pooler **first**, then
deploy, then re-point `ledger-purge`.
````

- [ ] **Step 8: Note the new specs in `deploy/README.md`**

Append:

```markdown
- **Workload Identity Federation** for the deploy pipeline is provisioned by
  `gcloud`, not from a file here — the pool, provider, attribute condition and
  `principalSet` binding are in the plan's Task 5, and the runbook's
  § *The deploy pipeline* explains operating them. The two GitHub repository
  variables that name them are **not secrets**: they are public identifiers, and
  the authorisation is the attribute condition, not their obscurity.
```

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/deploy.yml docs/runbook.md deploy/README.md
git commit -m "feat(E16): staging deploys on merge, over Workload Identity Federation

No long-lived service-account key exists in the repository or its secrets. The
provider carries an attribute condition scoping it to this repository owner, and
the service account is bound to a principalSet naming this repository alone —
without the condition, any repository on GitHub could ask for a token.

Migrations run against the session pooler (5432) before the revision is created,
so a failed migration aborts the deploy instead of leaving a half-migrated
database serving traffic. Proven by pointing the host at an unreachable server
and confirming no revision was created."
```

---

## Task 6: Production deploys on a tag, with ordered migrations

Closes the second half of **S16-3**, and folds in decision **D13** — the `ledger-purge` re-point that the runbook currently warns about and nothing enforces.

**Files:**
- Modify: `.github/workflows/deploy.yml` (add the `production` job)
- Modify: `docs/runbook.md` (§ *Deploy a new revision* gains a pointer; § *Re-point the purge job* is corrected)

**Interfaces:**
- Consumes: Task 5's `GCP_WORKLOAD_IDENTITY_PROVIDER` / `GCP_DEPLOY_SERVICE_ACCOUNT` variables and the proven job shape.
- Produces: a `production` GitHub Environment holding `PROD_POSTGRES_HOST`, `PROD_POSTGRES_PORT`, `PROD_POSTGRES_USER`, `PROD_POSTGRES_PASSWORD`, `PROD_POSTGRES_DB`, and the `v*` tag trigger that Task 9's rollback procedure and Task 12's runbook both reference.

- [ ] **Step 1: Create the production environment and its secrets**

```bash
R=bessavagner/expense_tracker_v2
gh api -X PUT "repos/$R/environments/production"
for k in HOST PORT USER PASSWORD DB; do
  gh secret set "PROD_POSTGRES_$k" --env production --repo "$R"
done
gh secret list --env production --repo "$R"
```

`PROD_POSTGRES_PORT` is `5432` — the **session** pooler. Getting this wrong points migrations at pgbouncer in transaction mode, which fails in ways that look like unrelated SQL errors.

**The password contains a space** (recorded in `docs/runbook.md` § *Applying a migration to Supabase*, failure #2). Paste it exactly, with no quoting — `gh secret set` reads stdin verbatim.

- [ ] **Step 2: Add the production job**

Append to `.github/workflows/deploy.yml`:

```yaml
  production:
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    # A GitHub Environment, so a required-reviewer protection rule can be added
    # later without touching this file. Not enabled now: with one maintainer you
    # would be approving your own deploy, which only trains you to click through
    # the gate (E16 D3).
    environment: production
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.12
      - run: uv sync

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_DEPLOY_SERVICE_ACCOUNT }}

      - uses: google-github-actions/setup-gcloud@v2

      # Report the drift the deploy is about to fix, or prove there is none.
      # Informational — the migrate step is what acts — but it turns a surprise
      # into a line in the log naming exactly what will change.
      - name: Report schema drift before migrating
        continue-on-error: true
        env: &prod_db
          DJANGO_SETTINGS_MODULE: config.settings.prod
          SECRET_KEY: migration-step-only-never-serves-a-request
          ALLOWED_HOSTS: localhost
          POSTGRES_HOST: ${{ secrets.PROD_POSTGRES_HOST }}
          POSTGRES_PORT: ${{ secrets.PROD_POSTGRES_PORT }}
          POSTGRES_USER: ${{ secrets.PROD_POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ secrets.PROD_POSTGRES_PASSWORD }}
          POSTGRES_DB: ${{ secrets.PROD_POSTGRES_DB }}
          PRIVACY_CONTROLLER_NAME: Migration step
          PRIVACY_CONTROLLER_CNPJ: 00.000.000/0001-91
          PRIVACY_CONTROLLER_ADDRESS: Migration step
          PRIVACY_CONTACT_EMAIL: migration@example.com
        run: uv run python src/backend/manage.py check_migration_drift || true

      # Direct connection (session pooler, 5432), before the revision exists.
      # Failing here aborts the job with the previous revision still serving.
      - name: Migrate production
        env: *prod_db
        run: uv run python src/backend/manage.py migrate --no-input

      - name: Deploy production
        run: |
          gcloud run deploy expense-tracker --source . \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --quiet

      - name: Smoke test
        run: |
          URL=$(gcloud run services describe expense-tracker \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')
          BODY=$(curl -sf -m 60 "$URL/healthz/")
          echo "$BODY"
          echo "$BODY" | grep -q '"status": "ok"' \
            || { echo "::error::production /healthz/ is not ok: $BODY"; exit 1; }
          for p in / /.well-known/assetlinks.json; do
            code=$(curl -s -o /dev/null -w '%{http_code}' -m 60 "$URL$p")
            echo "$p -> $code"
          done

      # `--source` deploys push untagged digests, so ledger-purge keeps running
      # the image it was created with until told otherwise — and a stale sweep
      # still exits 0 and still logs, so E13's silence alert cannot catch it.
      # Nothing can. This was a manual step in the runbook; a manual step that
      # nothing verifies is a step that gets skipped (E16 D13).
      #
      # --image replaces ONLY the image. A deploy that also changed the
      # service's env must regenerate the whole Job spec by hand — see
      # docs/runbook.md, "Retenção de dados (E13) -> Provisioning".
      - name: Re-point the ledger-purge job at the new image
        run: |
          IMAGE=$(gcloud run services describe expense-tracker \
            --project "$GCP_PROJECT" --region "$GCP_REGION" \
            --format='value(spec.template.spec.containers[0].image)')
          echo "$IMAGE"
          gcloud run jobs update ledger-purge \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --image "$IMAGE"
```

> The YAML anchor `&prod_db` / `*prod_db` avoids repeating twelve environment lines. GitHub Actions supports YAML anchors within a single file. If the workflow fails to parse, expand them by hand rather than debugging the anchor — correctness beats brevity here.

- [ ] **Step 3: Verify the workflow still parses before tagging anything**

```bash
git add .github/workflows/deploy.yml
git commit -m "wip: production deploy job"
git push
gh workflow view Deploy --repo bessavagner/expense_tracker_v2 --yaml | head -20
```

Expected: the YAML prints. If GitHub reports the workflow as invalid, the anchor is the first suspect.

- [ ] **Step 4: Confirm production is not already drifted**

The first tagged deploy after Task 3 will fail its startup probe if it is. Check before, not during.

```bash
POSTGRES_HOST=<prod session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<prod user> POSTGRES_PASSWORD='<prod password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=check-only ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py check_migration_drift
```

Expected: `ledger_drift_check_ran: no drift`, exit 0.

- [ ] **Step 5: Cut the first tag and watch it deploy**

```bash
git tag -a v0.1.0 -m "E16: automated deploy pipeline, staging, drift detection"
git push origin v0.1.0
gh run watch --repo bessavagner/expense_tracker_v2
```

Expected, in order: drift report says none; `Migrate production` says `No migrations to apply.`; the deploy prints a new revision name; the smoke test prints `{"status": "ok", ...}` then `/ -> 302` and `/.well-known/assetlinks.json -> 200`; the purge re-point prints the image digest.

**Expected failure:** `gcloud run jobs update ledger-purge` returns `NOT_FOUND` if the job is named differently. Confirm with `gcloud run jobs list --project expense-tracker-482807 --region southamerica-east1`; memory says it was provisioned 2026-08-18 as `ledger-purge`.

Verify the purge job actually moved:

```bash
gcloud run jobs describe ledger-purge --project expense-tracker-482807 \
  --region southamerica-east1 --format='value(spec.template.spec.template.spec.containers[0].image)'
gcloud run services describe expense-tracker --project expense-tracker-482807 \
  --region southamerica-east1 --format='value(spec.template.spec.containers[0].image)'
```

Expected: identical digests.

- [ ] **Step 6: Correct the runbook where it now describes a manual step the pipeline does**

In `docs/runbook.md` § *Re-point the purge job at the new image — every time*, change the heading and add a leading paragraph:

```markdown
### Re-point the purge job at the new image

**The pipeline does this automatically** on every tagged production deploy —
`.github/workflows/deploy.yml`, step *Re-point the ledger-purge job at the new
image*. Do it by hand only after a manual `gcloud run deploy`, which is now the
exception rather than the rule.

The reason it must happen at all is unchanged: `--source` deploys push untagged
digests, so `ledger-purge` keeps running the image it was created with. A stale
sweep still exits 0 and still logs, so the E13 silence alert will not catch this;
nothing will.
```

And add to § *Deploy a new revision*, as its first line:

```markdown
> **The normal path is a `v*` tag** — see § *The deploy pipeline*. What follows
> is the manual procedure, for when the pipeline is unavailable. It is still
> correct, and migrations still come first.
```

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/deploy.yml docs/runbook.md
git commit -m "feat(E16): production deploys on a v* tag, migrations first

Merge to main deploys staging; a tag deploys production. The trigger is
deliberate and recorded in git history rather than only in an Actions log.

Migrating before the revision is created is now load-bearing: /healthz/ returns
503 on drift and Cloud Run's startup probe reads it, so deploy-then-migrate
produces a stuck deploy rather than a day of 500s.

The ledger-purge re-point becomes a pipeline step. It was a manual instruction
in the runbook, guarding a failure that nothing else can detect — a stale sweep
exits 0 and logs normally, so E13's silence alert never fires."
```

---

## Task 7: The nightly drift check

Closes the last clause of **S16-9**: *"the check runs after every production deploy, and on a schedule thereafter — the day-long window on 2026-08-15 opened at a deploy but stayed open because nothing re-checked."*

The deploy-time half is already done: Task 6 runs `check_migration_drift` and Task 3 makes the startup probe enforce it. This task is the *thereafter* — drift that arrives without a deploy, from a rollback or a `migrate` pointed at the wrong database.

**Files:**
- Create: `deploy/drift-alert-policy.json`
- Modify: `deploy/README.md`
- Modify: `docs/runbook.md` (new section: *Schema drift*)

**Interfaces:**
- Consumes: Task 2's `check_migration_drift` command; Task 6's deployed image.
- Produces: Cloud Run Job `ledger-drift-check`, Cloud Scheduler job `ledger-drift-check-nightly`, log-based metric `ledger_drift_check_ran`, alert policy on its silence.

- [ ] **Step 1: Create the Job, from the service's own spec**

Same pattern as `ledger-purge` — and the same warning applies, recorded in `deploy/README.md`: **the Job spec embeds the service's whole `env` array, which includes `ADMIN_URL_PATH`, and this repository is public.** Generate the spec at apply time; never commit it.

```bash
P=expense-tracker-482807
R=southamerica-east1
IMAGE=$(gcloud run services describe expense-tracker --project "$P" --region "$R" \
  --format='value(spec.template.spec.containers[0].image)')
SA=$(gcloud run services describe expense-tracker --project "$P" --region "$R" \
  --format='value(spec.template.spec.serviceAccountName)')

gcloud run jobs create ledger-drift-check \
  --project "$P" --region "$R" --image "$IMAGE" --service-account "$SA" \
  --max-retries 0 \
  --command python --args manage.py,check_migration_drift
```

Then copy the service's environment onto it. Do **not** hand-build a `--set-env-vars` string: the values contain spaces, commas and `@`, which is exactly what broke the E13 deploy. Generate the Job spec from JSON and `replace` it, per `docs/runbook.md` § *Retenção de dados (E13) → Provisioning* — the generator there is the one to reuse.

> **`--max-retries 0` is deliberate.** A drifted database is drifted; three retries produce three identical failures and three identical alerts.
>
> **The Job's `DATABASE_URL` is the service's**, i.e. the transaction pooler on 6543. That is correct here — reading `django_migrations` is an ordinary query and needs no session features. Only `migrate` itself requires 5432.

- [ ] **Step 2: Verify the Job answers correctly before scheduling it**

```bash
gcloud run jobs execute ledger-drift-check --project "$P" --region "$R" --wait
```

Expected: the execution succeeds. Read the line it logged:

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="ledger-drift-check"' \
  --project "$P" --limit 10 --freshness=1h --format='value(textPayload,jsonPayload.message)'
```

Expected: `ledger_drift_check_ran: no drift`.

- [ ] **Step 3: Prove the Job can fail**

A check that has only ever passed is a hypothesis. Point it at staging's database — which is a different Supabase project and therefore genuinely a different applied set — after deliberately un-recording a migration there:

```bash
# Against STAGING only. Never production.
POSTGRES_HOST=<staging session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<staging user> POSTGRES_PASSWORD='<staging password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=x ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py migrate core 0008 --fake
```

Then run the check against staging and confirm it names the migration:

```bash
POSTGRES_HOST=<staging session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<staging user> POSTGRES_PASSWORD='<staging password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=x ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py check_migration_drift; echo "exit=$?"
```

Expected: `exit=1`, and the message names `core.0009_policy_acceptance_and_consent`. Also confirm staging's `/healthz/` now returns 503 with `"migrations": "drift"` — that is Task 3 proven against a real deployment rather than a mock:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<staging run.app host>/healthz/
curl -s https://<staging run.app host>/healthz/ | python3 -m json.tool
```

Expected: `503`, and a body naming the unapplied migration. **This is the evidence S16-9's DoD asks for** — capture both outputs for Task 13.

Restore staging:

```bash
POSTGRES_HOST=<staging session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<staging user> POSTGRES_PASSWORD='<staging password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=x ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py migrate --fake
curl -s https://<staging run.app host>/healthz/ | python3 -m json.tool
```

Expected: back to `{"status": "ok", ...}`.

> `--fake` on both sides because the schema never changed — only the `django_migrations` rows did, which is exactly the shape of real drift. Running a real `migrate` here would try to re-create existing objects.

- [ ] **Step 4: Schedule it**

03:40 local — twenty minutes after `ledger-purge`, so a shared cold start does not make them contend.

```bash
gcloud scheduler jobs create http ledger-drift-check-nightly \
  --project "$P" --location "$R" \
  --schedule "40 3 * * *" --time-zone "America/Sao_Paulo" \
  --uri "https://${R}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${P}/jobs/ledger-drift-check:run" \
  --http-method POST \
  --oauth-service-account-email "$(gcloud run services describe expense-tracker \
      --project "$P" --region "$R" --format='value(spec.template.spec.serviceAccountName)')"
```

Then run it once by hand to prove the trigger works, not just the Job:

```bash
gcloud scheduler jobs run ledger-drift-check-nightly --project "$P" --location "$R"
gcloud run jobs executions list --job ledger-drift-check --project "$P" --region "$R" --limit 3
```

> **The Scheduler's green tick proves nothing** — it reports success as soon as the execution is *created*. Always read the execution list. This is the same trap the E13 alert documentation records.

- [ ] **Step 5: Create the log-based metric and the alert**

```bash
gcloud logging metrics create ledger_drift_check_ran --project "$P" \
  --description "One data point per completed nightly schema-drift check." \
  --log-filter='resource.type="cloud_run_job"
    AND resource.labels.job_name="ledger-drift-check"
    AND (textPayload:"ledger_drift_check_ran" OR jsonPayload.message:"ledger_drift_check_ran")'
```

The metric counts *completions*, drifted or not — because a **failed** drift check already surfaces two other ways (the execution fails, and `/healthz/` is 503), while a check that silently stopped running surfaces nowhere. Silence is the gap.

Create `deploy/drift-alert-policy.json`:

```json
{
  "displayName": "E16 schema-drift check has not run",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "No completed drift check in ~36h",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/ledger_drift_check_ran\" AND resource.type=\"cloud_run_job\"",
        "aggregations": [
          {
            "alignmentPeriod": "90000s",
            "perSeriesAligner": "ALIGN_SUM"
          }
        ],
        "comparison": "COMPARISON_LT",
        "thresholdValue": 1,
        "duration": "41400s",
        "evaluationMissingData": "EVALUATION_MISSING_DATA_ACTIVE",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "notificationChannels": [
    "projects/expense-tracker-482807/notificationChannels/5857707555791637518"
  ],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "The nightly `ledger-drift-check` job has not logged a completed check in 36 hours.\n\nThis alert is about the *check*, not about drift. Drift itself surfaces twice already — the job execution fails, and `/healthz/` returns 503 so the uptime policy fires. What nothing else can see is a check that quietly stopped running, which is how the 2026-08-15 window stayed open for a day.\n\n**Shape copied deliberately from `deploy/purge-alert-policy.json`.** The API caps an alignment period at 25h and a `conditionAbsent` duration at 23h30m, so neither expresses 36h alone. This is a 25h trailing sum that must stay below 1 for a further 11.5h. `evaluationMissingData: ACTIVE` is what makes it fire on silence at all; without it a metric with no data points never evaluates and the alert is decorative.\n\nCheck `gcloud run jobs executions list --job ledger-drift-check` first — the Scheduler reports success as soon as the execution is *created*, so its green tick proves nothing.\n\nSee `docs/runbook.md` § *Schema drift*."
  }
}
```

Apply it:

```bash
gcloud alpha monitoring policies create --project "$P" \
  --policy-from-file deploy/drift-alert-policy.json
```

**If the API rejects any field, record the constraint in `documentation.content`** rather than quietly simplifying the condition — that is the convention `deploy/README.md` sets, and the purge policy's documentation block is the worked example.

- [ ] **Step 6: Write the runbook section**

Add to `docs/runbook.md` after § *The deploy pipeline*:

````markdown
## Schema drift

**The failure this exists for.** On 2026-08-15, revision `00046-l64` carried
`accounts.0005`'s `Household.plan` while the database sat at `accounts.0004`.
The household resolver selects `plan_id` in middleware on every request, so
every route 500'd for every logged-in user from the 2026-08-14 deploy until the
migration was applied — about a day. Anonymous requests mostly passed, which is
why it presented as "server error after login" rather than as an outage.

Three things now watch for it:

| Where | Catches | Latency |
|---|---|---|
| `/healthz/` returns 503, naming the migrations | drift at any moment, including a rollback | ≤5 min, via uptime policy `17994738960177318338` |
| The deploy pipeline's `Migrate production` step | drift a deploy would create | before the revision exists |
| `ledger-drift-check` nightly Cloud Run Job | drift that arrived without a deploy | ≤24h |

### Is it drifted right now?

```bash
curl -s https://expense-tracker-654941182076.southamerica-east1.run.app/healthz/ \
  | python3 -m json.tool
```

`{"status": "ok", "database": "ok", "migrations": "ok", "unapplied": []}` is
healthy. `"migrations": "drift"` lists exactly what is missing.

### Fixing it

The `unapplied` list names the fix. Migrations go through the **direct/session
connection on port 5432**, never the transaction pooler — see § *Applying a
migration to Supabase*:

```bash
POSTGRES_HOST=<prod session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<prod user> POSTGRES_PASSWORD='<prod password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=fix-only ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py migrate
```

Then re-check `/healthz/`. The service recovers on its own once the endpoint
returns 200 — no redeploy is needed, because the code was always correct; only
the database was behind.

**Common failure: the alert `E16 schema-drift check has not run` fires but
`/healthz/` is fine.** That is the alert working as designed — it watches the
*checker*, not the database. Look at the Job, not the service:

```bash
gcloud run jobs executions list --job ledger-drift-check \
  --project expense-tracker-482807 --region southamerica-east1 --limit 5
```

The usual cause is a deploy that changed the service's env without regenerating
the Job spec, so the Job now has stale or missing variables.

**Common failure: `/healthz/` 503s during a deploy and the deploy hangs.** Also
by design. Cloud Run's startup probe reads `/healthz/`, so an image deployed
ahead of its migrations never becomes ready and the previous revision keeps
serving. Run the migration, then re-tag.
````

- [ ] **Step 7: Note the new spec in `deploy/README.md`, and commit**

Append to `deploy/README.md`'s list:

```markdown
- `drift-alert-policy.json` — the *E16 schema-drift check has not run* policy. It
  watches the checker's silence, not the database; drift itself surfaces through
  `/healthz/` and the uptime policy. Same 25h-sum-plus-11.5h-duration shape as
  the purge policy, and for the same API reasons — read its `documentation`
  block before simplifying the condition.

**The `ledger-drift-check` Job spec is deliberately NOT here**, for the same
reason as `ledger-purge`: it embeds the service's whole `env` array, including
`ADMIN_URL_PATH`, and this repository is public.
```

```bash
git add deploy/drift-alert-policy.json deploy/README.md docs/runbook.md
git commit -m "feat(E16): a nightly drift check, and an alert on its silence

The deploy pipeline catches drift a deploy would create; /healthz/ catches drift
at any moment. Neither catches a database that fell behind without a deploy — a
rollback, or a migrate pointed at the wrong target — which is why 2026-08-15's
window stayed open for a day after it opened.

The alert watches the checker rather than the database, deliberately: drift
already surfaces twice, while a check that quietly stopped running surfaces
nowhere.

Proven against staging by un-recording a real migration: the command exited 1
naming it, and staging's /healthz/ returned 503."
```

---

## Task 8: Alert on the 5xx *ratio*, not only the count

Closes **S16-8**. The count-based policy `4509450462948742746` fired on 2026-08-15 at 17:34 UTC — four minutes *after* the fix landed — because "more than 5 in 5 minutes" is unreachable at family-scale traffic. The ratio over that same day was effectively 100% of authenticated requests.

Decision **D8**: built on log-based metrics, because the built-in `run.googleapis.com/request_count` carries `response_code_class` but **no URL path label**, so `/healthz/` cannot be excluded from the denominator — and the uptime check's healthy pings are precisely the traffic that would have diluted the ratio.

Decision **D9**: two conditions combined with `AND` — ratio > 50% *and* at least 3 non-healthz 5xx, both over 30 minutes. The ratio alone would page on one stray 500 on an afternoon with two requests.

**Files:**
- Create: `deploy/log-metrics/ledger_requests_total.json`, `deploy/log-metrics/ledger_requests_5xx.json`
- Create: `deploy/fivexx-ratio-alert-policy.json`
- Modify: `deploy/README.md`, `docs/runbook.md` (§ *When something breaks → The alert policies*)

**Interfaces:**
- Consumes: Task 4's staging service (the policy is proven there before production gets one).
- Produces: two log-based metrics and one alert policy per environment; the runbook table gains a row.

- [ ] **Step 1: Create the two log-based metrics**

Cloud Run writes a request log per request to `run.googleapis.com%2Frequests`, carrying `httpRequest.requestUrl` and `httpRequest.status`. That is what makes excluding `/healthz/` possible at all.

`deploy/log-metrics/ledger_requests_total.json`:

```json
{
  "name": "ledger_requests_total",
  "description": "Requests to expense-tracker excluding the health endpoint. Denominator for the 5xx ratio alert (E16 S16-8). /healthz/ is excluded because the uptime check polls it every five minutes and its successes are what diluted the 2026-08-15 ratio below any usable threshold.",
  "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"expense-tracker\" AND logName:\"run.googleapis.com%2Frequests\" AND NOT httpRequest.requestUrl:\"/healthz/\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1"
  }
}
```

`deploy/log-metrics/ledger_requests_5xx.json`:

```json
{
  "name": "ledger_requests_5xx",
  "description": "5xx responses from expense-tracker excluding the health endpoint. Numerator for the 5xx ratio alert (E16 S16-8).",
  "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"expense-tracker\" AND logName:\"run.googleapis.com%2Frequests\" AND NOT httpRequest.requestUrl:\"/healthz/\" AND httpRequest.status>=500",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1"
  }
}
```

Apply both, and a `-staging` pair with `service_name="expense-tracker-staging"` and names suffixed `_staging`:

```bash
P=expense-tracker-482807
for f in deploy/log-metrics/ledger_requests_total.json deploy/log-metrics/ledger_requests_5xx.json; do
  gcloud logging metrics create "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['name'])" "$f")" \
    --project "$P" \
    --description "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['description'])" "$f")" \
    --log-filter "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['filter'])" "$f")"
done
```

Verify each metric actually matches something — a filter that matches nothing produces an alert that can never fire, which is the failure mode this whole story is about:

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="expense-tracker"
  AND logName:"run.googleapis.com%2Frequests"
  AND NOT httpRequest.requestUrl:"/healthz/"' \
  --project "$P" --limit 5 --freshness=24h \
  --format='value(httpRequest.requestUrl,httpRequest.status)'
```

Expected: real request lines, none of them `/healthz/`. **If this returns nothing, stop** — either the log name is different in this project or request logging is off, and both metrics would be decorative.

- [ ] **Step 2: Write the ratio policy**

`deploy/fivexx-ratio-alert-policy.json`:

```json
{
  "displayName": "expense-tracker 5xx ratio elevated",
  "combiner": "AND",
  "conditions": [
    {
      "displayName": "More than half of non-health requests are 5xx over 30m",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/ledger_requests_5xx\" AND resource.type=\"cloud_run_revision\"",
        "denominatorFilter": "metric.type=\"logging.googleapis.com/user/ledger_requests_total\" AND resource.type=\"cloud_run_revision\"",
        "aggregations": [
          {
            "alignmentPeriod": "1800s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM"
          }
        ],
        "denominatorAggregations": [
          {
            "alignmentPeriod": "1800s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.5,
        "duration": "0s",
        "trigger": { "count": 1 }
      }
    },
    {
      "displayName": "At least 3 non-health 5xx over 30m",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/ledger_requests_5xx\" AND resource.type=\"cloud_run_revision\"",
        "aggregations": [
          {
            "alignmentPeriod": "1800s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 2,
        "duration": "0s",
        "trigger": { "count": 1 }
      }
    }
  ],
  "notificationChannels": [
    "projects/expense-tracker-482807/notificationChannels/5857707555791637518"
  ],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "More than half of the non-health requests to expense-tracker returned 5xx over the last 30 minutes, and there were at least three of them.\n\n**This policy exists because the count-based one could not see the 2026-08-15 outage.** That policy is `4509450462948742746`, \"more than 5 5xx in 5 minutes\". A family-scale app with a broken authenticated path produces a handful of errors a day, so it never tripped; it finally fired at 17:34 UTC, four minutes *after* the fix had landed, on a day that had run at ~100% authenticated failure. A ratio makes a total failure at low volume page as loudly as a spike at high volume.\n\n**Both policies are kept on purpose.** They catch different shapes: a ratio is blind to a burst that is small relative to healthy traffic, and a count is blind to a total failure at low traffic. Neither replaces the other.\n\n**Why log-based metrics rather than `run.googleapis.com/request_count`.** The built-in metric carries `response_code_class` but no URL path label, so `/healthz/` cannot be excluded from the denominator — and the uptime check polls `/healthz/` every five minutes, which is exactly the healthy traffic that would dilute this ratio below any usable threshold. Cloud Logging's request log has `httpRequest.requestUrl`, so `ledger_requests_total` and `ledger_requests_5xx` both exclude it.\n\n**Why two conditions ANDed.** At family scale a quiet afternoon may hold two requests in total, so a ratio alone would page on one stray 500. The count condition is the volume floor; the ratio is what makes a total failure visible. The 2026-08-15 shape trips both.\n\nStart at Sentry for the exception, then `gcloud run services logs read expense-tracker`. If the errors are on authenticated paths only, check `/healthz/` for schema drift — see `docs/runbook.md` § *Schema drift*."
  }
}
```

- [ ] **Step 3: Prove it fires — on staging, at low volume, before production has one**

This is S16-8's DoD assertion: *"a simulated total failure at low request volume fires it — the 2026-08-15 shape, which the count-based policy missed for a day."*

Create the staging twin of the policy (same JSON with the metric names suffixed `_staging`) and apply it:

```bash
sed -e 's/ledger_requests_5xx/ledger_requests_5xx_staging/g' \
    -e 's/ledger_requests_total/ledger_requests_total_staging/g' \
    -e 's/expense-tracker 5xx ratio elevated/expense-tracker-staging 5xx ratio elevated/' \
    deploy/fivexx-ratio-alert-policy.json > /tmp/staging-ratio-policy.json
gcloud alpha monitoring policies create --project "$P" --policy-from-file /tmp/staging-ratio-policy.json
```

Then break staging deliberately. The cheapest total-failure-at-low-volume simulation is the 2026-08-15 shape itself — point staging's `DATABASE_URL` at a database that answers but is drifted, so authenticated paths 500 while `/healthz/`… no: after Task 3 that takes the revision out of rotation, which is a *different* shape.

Use instead a revision that raises on an authenticated path. On a throwaway branch:

```python
# src/backend/core/middleware.py — TEMPORARY, staging only, never merged
def log_context_middleware(get_response):
    def middleware(request):
        if request.user.is_authenticated:
            raise RuntimeError("E16 S16-8 alert rehearsal")
        return get_response(request)
    return middleware
```

Deploy it to staging **by hand** (not through the pipeline, and not from `main`):

```bash
gcloud run deploy expense-tracker-staging --source . \
  --project "$P" --region southamerica-east1 --quiet
```

Generate the low-volume failure — about ten authenticated requests over half an hour, which is the point: a volume the count-based policy would ignore entirely.

```bash
S=https://<staging run.app host>
# Log in once and keep the session.
curl -s -c /tmp/e16-cookies -b /tmp/e16-cookies "$S/accounts/login/" > /dev/null
# ... complete the login POST with the staging test user, then:
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code} " -b /tmp/e16-cookies "$S/"
  sleep 120
done; echo
```

Expected: ten `500`s. Then wait for the 30-minute window to close and confirm:

```bash
gcloud alpha monitoring policies list --project "$P" \
  --filter='displayName:"staging 5xx ratio"' --format='value(name,enabled)'
# The incident itself:
gcloud alpha monitoring policies describe <policy-id> --project "$P" --format=yaml | head -40
```

**The evidence is the notification email arriving.** Capture its timestamp and subject for Task 13. Then confirm the *count*-based shape would not have fired: ten 5xx spread over 20 minutes never reaches "more than 5 in 5 minutes" — say so explicitly in the evidence, because that contrast is the entire justification for this story.

Revert staging:

```bash
git checkout src/backend/core/middleware.py
gcloud run deploy expense-tracker-staging --source . --project "$P" --region southamerica-east1 --quiet
curl -s "$S/healthz/" | python3 -m json.tool
```

- [ ] **Step 4: Apply the production policy**

```bash
gcloud alpha monitoring policies create --project "$P" \
  --policy-from-file deploy/fivexx-ratio-alert-policy.json
gcloud alpha monitoring policies list --project "$P" \
  --format="table(displayName,enabled,combiner)"
```

Expected: four policies now — uptime, 5xx count, retention silence, 5xx ratio — plus the drift-check silence from Task 7 and the staging twin. **Confirm the count-based policy `4509450462948742746` is still enabled** (decision D10 and S16-8 both require it).

- [ ] **Step 5: Update the runbook's alert table**

In `docs/runbook.md` § *When something breaks → The alert policies*, replace the table and the paragraph beneath it:

````markdown
| Policy | Fires when | Id |
|---|---|---|
| `expense-tracker is down (/healthz/ uptime check failing)` | the uptime check fails more than once in a 5-minute window — including on schema drift, since `/healthz/` 503s then | `17994738960177318338` |
| `expense-tracker 5xx error rate elevated` | more than 5 `5xx` responses in 5 minutes | `4509450462948742746` |
| `expense-tracker 5xx ratio elevated` | over 30 minutes, more than half of non-`/healthz/` requests are 5xx **and** there are at least 3 of them | *(record the id after applying)* |
| `E13 retention sweep has not run` | no completed nightly purge in ~36h | `13939835533058236318` |
| `E16 schema-drift check has not run` | no completed nightly drift check in ~36h | *(record the id after applying)* |

**Which one fires for which shape of failure.** The count policy sees a *burst*:
many errors quickly, at any traffic level. The ratio policy sees a *total
failure at low volume* — the 2026-08-15 shape, where a broken authenticated path
produced perhaps a handful of errors a day and the count policy never tripped,
finally firing at 17:34 UTC, four minutes after the fix had landed. Neither
replaces the other: a ratio is blind to a burst that is small relative to
healthy traffic, and a count is blind to an outage nobody is around to trigger.

The ratio deliberately excludes `/healthz/` from both numerator and denominator.
The uptime check polls it every five minutes, and counting those successes is
what would dilute a 100% authenticated failure into a number no threshold could
catch. That exclusion is why the ratio is built on the log-based metrics
`ledger_requests_total` / `ledger_requests_5xx` rather than on Cloud Run's
built-in `request_count`, which has no URL label.

**The ratio policy has fired in a deliberate test** — see
`docs/superpowers/evidence/e16-alerts/`. The uptime policy still never has.
````

Also delete the now-false line **"Neither has ever fired"** further down that section — the count policy fired on 2026-08-15, which is what E06's own closing note records.

- [ ] **Step 6: Record the evidence and commit**

```bash
mkdir -p docs/superpowers/evidence/e16-alerts
```

Write `docs/superpowers/evidence/e16-alerts/README.md` with: the staging policy id, the ten request timestamps and status codes, the notification email's arrival time, the delta between the first 500 and the notification, and one explicit paragraph computing what the count-based policy would have done with the same traffic (nothing — the peak was one 5xx per 5-minute window against a threshold of five).

```bash
git add deploy/ docs/runbook.md docs/superpowers/evidence/e16-alerts/
git commit -m "feat(E16): alert on the 5xx ratio, not only the count

The count policy fired on 2026-08-15 at 17:34 UTC — four minutes after the fix —
on a day that had run at ~100% authenticated failure. 'More than 5 in 5 minutes'
is unreachable at family-scale traffic.

Built on log-based metrics rather than run.googleapis.com/request_count, because
the built-in metric has no URL label and /healthz/ therefore cannot leave the
denominator; the uptime check's successes are exactly what dilutes the ratio.

Two conditions ANDed: ratio over half, and at least three errors. A quiet
afternoon here can hold two requests, and a ratio alone would page on one.

Fired in a deliberate low-volume test on staging. The count policy would not
have."
```

---

## Task 9: Rollback, performed

Closes **S16-4**. The deliverable is not a procedure — it is a procedure that has been **executed at least once against staging**, plus written guidance for the hard case: rolling back when a migration has already applied.

**Files:**
- Create: `docs/superpowers/evidence/e16-rollback/README.md`
- Modify: `docs/runbook.md` (new section: *Rolling back*)
- Modify: `docs/backlog/INDEX.md` is untouched here; Task 13 does the ticking.

**Interfaces:**
- Consumes: Task 4's staging service with at least two revisions (Task 5's pipeline run created the second).
- Produces: the runbook's *Rolling back* section, which Task 12's completeness check and Task 13's DoD both cite.

- [ ] **Step 1: Confirm staging has something to roll back to**

```bash
P=expense-tracker-482807
R=southamerica-east1
gcloud run revisions list --service expense-tracker-staging \
  --project "$P" --region "$R" --format="table(name,active,creationTimestamp)"
```

Expected: at least two revisions. If not, push an empty commit to `main` and let the pipeline create one.

- [ ] **Step 2: Make the current revision distinguishable from the previous one**

A rollback you cannot see is a rollback you have not proven. Change one visible, harmless thing and deploy it through the pipeline:

```bash
git checkout -b e16-rollback-rehearsal
# In src/backend/templates/base.html or the footer partial, add a marker string
# such as "rollback-rehearsal-marker". Any user-visible, greppable string works.
git commit -am "chore(E16): temporary marker for the rollback rehearsal"
```

Merge to `main`, let the pipeline deploy staging, and confirm the marker is live:

```bash
S=https://<staging run.app host>
curl -s "$S/accounts/login/" | grep -c rollback-rehearsal-marker
```

Expected: `1` or more.

- [ ] **Step 3: Perform the rollback, and time it**

Start a clock. Record the wall time you begin.

```bash
PREV=$(gcloud run revisions list --service expense-tracker-staging \
  --project "$P" --region "$R" --format='value(name)' --sort-by='~creationTimestamp' \
  | sed -n 2p)
echo "rolling back to $PREV"

gcloud run services update-traffic expense-tracker-staging \
  --project "$P" --region "$R" --to-revisions "$PREV=100"
```

Expected output: a traffic table showing 100% to `$PREV`.

Confirm the marker is gone and the service is healthy:

```bash
curl -s "$S/accounts/login/" | grep -c rollback-rehearsal-marker   # expect 0
curl -s "$S/healthz/" | python3 -m json.tool                       # expect status ok
```

Record the elapsed seconds. `update-traffic` is a control-plane change with no build, so expect tens of seconds — that number is what makes rollback the *first* thing to reach for in an incident, and it belongs in the evidence.

- [ ] **Step 4: Roll forward again and remove the marker**

```bash
gcloud run services update-traffic expense-tracker-staging \
  --project "$P" --region "$R" --to-latest
git revert --no-edit HEAD   # the marker commit
```

Merge the revert to `main` and let the pipeline deploy.

- [ ] **Step 5: Write the runbook section**

Add to `docs/runbook.md` immediately after § *The deploy pipeline*:

````markdown
## Rolling back

**Reach for this first.** Shifting traffic to the previous revision is a
control-plane change with no build and no migration — it took **<N> seconds**
when rehearsed against staging on <date> (`docs/superpowers/evidence/e16-rollback/`).
Debugging forward under pressure takes longer and is how a five-minute outage
becomes an hour.

```bash
P=expense-tracker-482807
R=southamerica-east1

# What is serving, and what came before it.
gcloud run revisions list --service expense-tracker \
  --project "$P" --region "$R" --format="table(name,active,creationTimestamp)" --limit 5

# Send all traffic to the previous revision.
gcloud run services update-traffic expense-tracker \
  --project "$P" --region "$R" --to-revisions "expense-tracker-000NN-xxx=100"
```

Prints a traffic table. Verify, do not assume:

```bash
B=https://expense-tracker-654941182076.southamerica-east1.run.app
curl -s "$B/healthz/" | python3 -m json.tool
```

Going forward again once the fix is tagged:

```bash
gcloud run services update-traffic expense-tracker \
  --project "$P" --region "$R" --to-latest
```

**Common failure: `--to-revisions` with a revision that no longer exists.**
Cloud Run keeps revisions but the console hides inactive ones; always take the
name from `revisions list`, not from memory.

**Common failure: the rollback succeeds and the service still 503s.** Read
`/healthz/`. If it says `"migrations": "drift"`, you have rolled back *past* an
applied migration — see the next section.

### The hard case: rolling back after a migration has applied

This is the one that will happen under pressure, so decide it now rather than
then.

**A rollback does not undo a migration.** Traffic moves to the old image; the
database keeps the new schema. Whether that is survivable depends entirely on
whether the migration was backward-compatible with the previous revision:

| Migration shape | Rolling back is | Why |
|---|---|---|
| Added a nullable column, a new table, a new index | **Safe.** Just roll back. | The old code does not know the column exists and never selects it. |
| Added a non-nullable column with a default | **Safe.** | Same — the old code does not select it, and inserts get the default. |
| Renamed or dropped a column the old code still selects | **Not safe.** | The old revision queries a column that is gone; every affected path 500s. This is 2026-08-15 in reverse. |
| Changed a column's type incompatibly | **Not safe.** | The old code writes values the new type rejects. |

**So the rule that makes rollback possible at all: write migrations that are
backward-compatible with the revision currently serving.** A rename is two
deploys — add the new column and write to both, deploy, backfill, then drop the
old one in a *later* release once no serving revision reads it. A drop is the
second half of a change whose first half shipped earlier.

**When you are already in the unsafe case**, you have two options and neither is
quick:

1. **Roll the migration back too**, if it is reversible:
   ```bash
   POSTGRES_HOST=<prod session pooler host> POSTGRES_PORT=5432 \
   POSTGRES_USER=<prod user> POSTGRES_PASSWORD='<prod password>' POSTGRES_DB=postgres \
   DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=rollback-only ALLOWED_HOSTS=localhost \
     uv run python src/backend/manage.py migrate <app> <previous_migration_number>
   ```
   Global constraint 9 says migrations are reversible or the epic states why not,
   so this usually works. `/healthz/` will then report drift against the *new*
   image and be correct to.
2. **Fix forward.** Tag a new release. Slower, but it is the only option when the
   migration destroyed data a reverse cannot restore — and when data is gone,
   you are in § *Restoring from backup*, not here.
````

Replace `<N>` and `<date>` with the measured values.

- [ ] **Step 6: Write the evidence**

`docs/superpowers/evidence/e16-rollback/README.md`:

```markdown
# E16 S16-4 — a rollback that was performed

**Date:** <YYYY-MM-DD>
**Environment:** staging (`expense-tracker-staging`, project `expense-tracker-482807`, region `southamerica-east1`)
**Performed by:** <name>

## What was rolled back

Revision `<new>` carried a user-visible marker string; revision `<prev>` did not.
The marker is what makes this a proof rather than an assertion — a rollback with
no observable difference proves only that the command exits 0.

## The command

```
gcloud run services update-traffic expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 \
  --to-revisions <prev>=100
```

## Timing

| Moment | Time |
|---|---|
| Command issued | <hh:mm:ss> |
| Traffic table returned | <hh:mm:ss> |
| Marker absent from a fresh request | <hh:mm:ss> |
| **Total** | **<N> s** |

## Verification

```
$ curl -s $S/accounts/login/ | grep -c rollback-rehearsal-marker
0
$ curl -s $S/healthz/ | python3 -m json.tool
{ "status": "ok", "database": "ok", "migrations": "ok", "unapplied": [] }
```

## What this does and does not prove

Proves: traffic shifting works, is fast, and is verifiable from outside.

Does **not** prove: that a rollback across an applied migration is safe. It is
not, in general — the runbook's *The hard case* table says which migration
shapes survive it and which do not. Nothing here rehearsed that case, and
rehearsing it properly means restoring a database, which is § *Restoring from
backup* and E16 Task 11.
```

- [ ] **Step 7: Commit**

```bash
git add docs/runbook.md docs/superpowers/evidence/e16-rollback/
git commit -m "docs(E16): a rollback that was performed, and the hard case written down

Traffic shifting rehearsed against staging with a visible marker, so the proof
is an observed difference rather than a zero exit code. Timed, because how long
it takes is what decides whether it is the first thing you reach for.

The half that matters more is written, not rehearsed: a rollback does not undo a
migration. The table says which migration shapes survive being rolled back past
and which produce 2026-08-15 in reverse, and states the rule that makes rollback
possible at all — migrations backward-compatible with the serving revision, and
a rename as two releases."
```

---

## Task 10: A backup we own

The first half of **S16-5**, and decision **D11**. The spec's open question 1 asks what Supabase's retention actually is on the current plan. This task answers it — and then stops depending on the answer, because a backup whose retention is set by someone else's pricing page is not something you can state an RPO from.

**Files:**
- Modify: `.env.example` (backup bucket)
- Create: `deploy/backup-alert-policy.json`
- Modify: `deploy/README.md`, `docs/runbook.md` (new section: *Backups*)

**Interfaces:**
- Consumes: Task 6's deployed production image.
- Produces: GCS bucket `ledger-backups-expense-tracker-482807` with a 30-day lifecycle rule; Cloud Run Job `ledger-backup`; Scheduler job `ledger-backup-nightly`; log-based metric `ledger_backup_ran`; an alert on its silence. Task 11 restores from an object this job wrote.

- [ ] **Step 1: Find out what Supabase actually gives you, and write it down**

In the Supabase dashboard for the **production** project: *Database → Backups*. Record three facts verbatim in the runbook section written in Step 6 — the plan tier, the backup frequency, and the retention in days. Also record whether Point-in-Time Recovery is available and at what price.

> **Do not skip this because we are adding our own backup.** S16-5 requires the mechanism, frequency and retention to be *documented and verified*, and knowing that the vendor keeps N days changes what our own retention needs to be. If the free tier turns out to keep nothing, that is the single most important sentence in this epic and it belongs in the runbook in those words.

- [ ] **Step 2: Create the bucket with a lifecycle rule**

```bash
P=expense-tracker-482807
BUCKET="ledger-backups-${P}"

gcloud storage buckets create "gs://$BUCKET" \
  --project "$P" --location southamerica-east1 \
  --uniform-bucket-level-access --public-access-prevention

cat > /tmp/lifecycle.json <<'JSON'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 30}
    }
  ]
}
JSON
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=/tmp/lifecycle.json
gcloud storage buckets describe "gs://$BUCKET" --format="value(lifecycle_config)"
```

`--public-access-prevention` is not optional: every object here is the complete financial history of every household in the product. `--uniform-bucket-level-access` removes per-object ACLs so access is decided in exactly one place.

**30 days** because that is a full billing-month cycle plus margin, which is the unit this product's data is organised in — a corruption noticed when the next month's acumulado looks wrong is still inside the window.

- [ ] **Step 3: Grant the runtime service account write access, and nothing else**

```bash
SA=$(gcloud run services describe expense-tracker --project "$P" \
  --region southamerica-east1 --format='value(spec.template.spec.serviceAccountName)')
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member "serviceAccount:$SA" --role roles/storage.objectCreator
```

`objectCreator`, not `objectAdmin`: the job writes backups and must not be able to delete them. Deletion is the lifecycle rule's job. A compromised service that can erase its own backups has no backups.

- [ ] **Step 4: Write and provision the backup job**

The image ships `uv` and Python but **not** `pg_dump`. Rather than rebuild the image for one binary, the Job runs Django's own `dumpdata`… **no** — `dumpdata` cannot restore a database that will not start, and it loses sequences and constraints. Use the `postgres:17` image directly, which is what the runbook already reaches for and what production's PostgreSQL 17.6 requires:

```bash
P=expense-tracker-482807
R=southamerica-east1
BUCKET="ledger-backups-${P}"
```

Create a tiny image that has both `pg_dump` 17 and `gcloud storage`. Add `deploy/backup/Dockerfile`:

```dockerfile
# pg_dump must match the server: Supabase runs PostgreSQL 17.6, and pg_dump
# refuses to talk to a newer server (docs/runbook.md, "Applying a migration to
# Supabase", failure #1). Ubuntu's client 16 is what bit us there.
FROM postgres:17

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://sdk.cloud.google.com | bash -s -- --disable-prompts --install-dir=/opt
ENV PATH="/opt/google-cloud-sdk/bin:$PATH"

COPY deploy/backup/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh
ENTRYPOINT ["/usr/local/bin/backup.sh"]
```

And `deploy/backup/backup.sh`:

```bash
#!/usr/bin/env bash
# Nightly logical backup of the production database to GCS (E16 S16-5).
#
# libpq variables rather than a URL, deliberately: the production password
# contains a space, which pg_dump 17 rejects inside a URL and Django's parser
# mangles. See docs/runbook.md, "Applying a migration to Supabase", failure #2.
#
# Custom format (-Fc) rather than plain SQL: it restores selectively, in
# parallel, and compresses. The restore side is pg_restore, rehearsed and timed
# in docs/superpowers/evidence/e16-restore/.
set -euo pipefail

: "${PGHOST:?}" "${PGPORT:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${PGDATABASE:?}" "${BACKUP_BUCKET:?}"
export PGSSLMODE=require

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT="/tmp/ledger-${STAMP}.dump"

pg_dump --no-owner --no-acl -Fc -f "$OUT"
BYTES=$(stat -c %s "$OUT")

# A dump that is suspiciously small is worse than no dump, because it looks like
# one. 1 MiB is far below any real size for this database and far above an empty
# schema-only dump.
if [ "$BYTES" -lt 1048576 ]; then
  echo "ledger_backup_ran: FAILED — dump is only ${BYTES} bytes" >&2
  exit 1
fi

gcloud storage cp "$OUT" "gs://${BACKUP_BUCKET}/ledger-${STAMP}.dump"
rm -f "$OUT"

# Logged on every successful run. The alert fires on the ABSENCE of this line,
# so a quiet success is data — same shape as ledger_purge_ran (E13).
echo "ledger_backup_ran: ok ${BYTES} bytes -> gs://${BACKUP_BUCKET}/ledger-${STAMP}.dump"
```

Build and deploy it as a Job:

```bash
gcloud builds submit --project "$P" --config - <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "deploy/backup/Dockerfile", "-t", "${R}-docker.pkg.dev/${P}/cloud-run-source-deploy/ledger-backup:latest", "."]
images: ["${R}-docker.pkg.dev/${P}/cloud-run-source-deploy/ledger-backup:latest"]
YAML

SA=$(gcloud run services describe expense-tracker --project "$P" --region "$R" \
  --format='value(spec.template.spec.serviceAccountName)')

gcloud run jobs create ledger-backup \
  --project "$P" --region "$R" --service-account "$SA" \
  --image "${R}-docker.pkg.dev/${P}/cloud-run-source-deploy/ledger-backup:latest" \
  --max-retries 1 --task-timeout 30m \
  --set-env-vars "BACKUP_BUCKET=${BUCKET},PGPORT=5432,PGDATABASE=postgres" \
  --set-secrets "PGHOST=ledger-pghost:latest,PGUSER=ledger-pguser:latest,PGPASSWORD=ledger-pgpassword:latest"
```

Create those three Secret Manager entries first if they do not exist — the password contains a space, so pipe it from a file rather than echoing it:

```bash
printf '%s' '<the password, exactly>' > /tmp/pw && \
  gcloud secrets create ledger-pgpassword --project "$P" --data-file=/tmp/pw && rm -f /tmp/pw
```

> **`PGHOST` here is the session pooler (5432)**, not the transaction pooler. `pg_dump` needs session-level features that pgbouncer in transaction mode does not provide.

- [ ] **Step 5: Run it once, and verify the object**

```bash
gcloud run jobs execute ledger-backup --project "$P" --region "$R" --wait
gcloud storage ls -l "gs://$BUCKET"
```

Expected: one object, tens of megabytes. Then check its *contents* rather than its existence — an object of the right size that cannot be read is not a backup:

```bash
gcloud storage cp "gs://$BUCKET/$(gcloud storage ls "gs://$BUCKET" | tail -1 | xargs basename)" /tmp/verify.dump
docker run --rm -v /tmp:/work postgres:17 pg_restore --list /work/verify.dump | head -30
rm -f /tmp/verify.dump
```

Expected: a table of contents listing `finances_entry`, `finances_income`, `assistant_chatmessage` and friends. **Delete the local copy** — it is production data, same rule as `/tmp/ledger-prod.dump` in the existing runbook section.

- [ ] **Step 6: Schedule it, meter it, alert on its silence**

```bash
gcloud scheduler jobs create http ledger-backup-nightly \
  --project "$P" --location "$R" \
  --schedule "0 3 * * *" --time-zone "America/Sao_Paulo" \
  --uri "https://${R}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${P}/jobs/ledger-backup:run" \
  --http-method POST --oauth-service-account-email "$SA"

gcloud logging metrics create ledger_backup_ran --project "$P" \
  --description "One data point per completed nightly backup." \
  --log-filter='resource.type="cloud_run_job"
    AND resource.labels.job_name="ledger-backup"
    AND textPayload:"ledger_backup_ran: ok"'
```

Create `deploy/backup-alert-policy.json` by copying `deploy/purge-alert-policy.json` and changing four things: `displayName` to `E16 backup has not run`, the metric type to `ledger_backup_ran`, the condition `displayName`, and the `documentation.content` — which must say, in its own words, that the 25h-sum-plus-11.5h-duration shape and `evaluationMissingData: ACTIVE` are API constraints and not preferences, exactly as the purge policy's block does. Apply it:

```bash
gcloud alpha monitoring policies create --project "$P" --policy-from-file deploy/backup-alert-policy.json
```

03:00 is deliberately *before* `ledger-purge` at 03:20: the backup should capture the day's data before retention deletes anything, so a purge bug is recoverable from the previous night's dump.

- [ ] **Step 7: Write the runbook section, and `.env.example`**

Add to `docs/runbook.md` a new `## Backups` section before § *Applying a migration to Supabase*, covering: what Supabase's own backups actually are (the facts from Step 1, verbatim); the `ledger-backup` job, its schedule, its bucket and the 30-day lifecycle rule; how to list and download a backup; the size floor and why it exists; and the two common failures — a paused/rotated password (the job fails with `password authentication failed`, fix in Secret Manager and re-run) and a `pg_dump` version mismatch if anyone rebuilds the image off a non-17 base.

Add to `.env.example` near the storage block:

```
# E16 S16-5. The nightly logical backup's destination. Read by the ledger-backup
# Cloud Run Job, not by settings.py. 30-day lifecycle rule on the bucket; the
# service account has objectCreator and deliberately NOT delete, so a compromised
# service cannot erase its own backups.
BACKUP_BUCKET=
```

- [ ] **Step 8: Commit**

```bash
git add deploy/backup/ deploy/backup-alert-policy.json deploy/README.md docs/runbook.md .env.example
git commit -m "feat(E16): a nightly backup we own, with a 30-day lifecycle

Supabase's own backups are recorded and verified, and are now the second line
rather than the first. A retention set by someone else's pricing page is not
something you can state an RPO from.

pg_dump -Fc from a postgres:17 image, because Supabase runs 17.6 and a client 16
refuses to talk to it — the failure that bit during the E04 rehearsal. libpq
variables rather than a URL, because the password contains a space.

The job can write to the bucket and cannot delete: a service that can erase its
own backups has none. A size floor rejects a dump too small to be real, since a
plausible-looking empty backup is worse than a missing one."
```

---

## Task 11: The restore, performed and timed

Closes **S16-5**, and settles **D4** by measurement. The spec's own words: *"This story is the reason the epic exists. Everything else here is convenience; this is the difference between an incident and an ending."*

The deliverable is a number — the measured RTO — plus proof that the restored database holds the same money as the original, checked with `dump_ledger_totals` rather than row counts.

> **The restore goes into a scratch database, never into staging and never into production.** Staging must never hold production data (Task 4's hard rule). Production must not be overwritten by a rehearsal.

**Files:**
- Create: `docs/superpowers/evidence/e16-restore/README.md`
- Modify: `docs/runbook.md` (new section: *Restoring from backup*)
- Modify: `docs/architecture/product-readiness-review.md` (the NFR table's RTO row)

**Interfaces:**
- Consumes: Task 10's `ledger-backup` object in GCS; `manage.py dump_ledger_totals --json` (decision D12).
- Produces: the measured RTO, cited by Task 13's DoD sweep and by the architecture review.

- [ ] **Step 1: Fingerprint production's money — before touching anything**

This is the comparison baseline. Run it against production **read-only**:

```bash
cd /home/bessa/Documents/projetos/expense_tracker_v2
POSTGRES_HOST=<prod session pooler host> POSTGRES_PORT=5432 \
POSTGRES_USER=<prod user> POSTGRES_PASSWORD='<prod password>' POSTGRES_DB=postgres \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=readonly ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py dump_ledger_totals --json > /tmp/e16-before.json
head -20 /tmp/e16-before.json
```

> **Do not change `FIXED_TODAY = date(2026, 8, 12)`** in `dump_ledger_totals`. The past/future split in `build_projection` depends on `today`, and a drifting clock produces a spurious diff — which the command's own docstring says in as many words. The pin is what makes a before/after comparison meaningful at all.

Treat `/tmp/e16-before.json` as production data. It contains every household's name and balances.

- [ ] **Step 2: Start the clock and fetch the most recent backup**

**Record the wall-clock time now.** Everything from here to Step 6 is the RTO, and the measurement is worthless if it starts after the download.

```bash
P=expense-tracker-482807
BUCKET="ledger-backups-${P}"
LATEST=$(gcloud storage ls "gs://$BUCKET" | sort | tail -1)
echo "$LATEST"
time gcloud storage cp "$LATEST" /tmp/e16-restore.dump
ls -lh /tmp/e16-restore.dump
```

Record the download duration separately — on a bad connection it can dominate the RTO, and knowing that changes what would improve it.

- [ ] **Step 3: Create a scratch database and restore into it**

Scratch database inside the **staging** Supabase project, not production's — a rehearsal that touches production's project is a rehearsal that can break production.

```bash
export PGHOST=<staging session pooler host> PGPORT=5432 \
       PGUSER=<staging user> PGPASSWORD='<staging password>' \
       PGDATABASE=postgres PGSSLMODE=require

docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE \
  postgres:17 psql -c 'CREATE DATABASE ledger_restore_rehearsal;'

time docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGSSLMODE \
  -e PGDATABASE=ledger_restore_rehearsal -v /tmp:/work postgres:17 \
  pg_restore --no-owner --no-acl -d ledger_restore_rehearsal /work/e16-restore.dump
```

**Expected failure #1 — `pg_restore: warning: errors ignored on restore: 2`, `permission denied for table secrets`.** Supabase's internal `vault` schema, which the pooler user cannot write. It does **not** affect application data. Do not treat the exit code as the verdict; Step 4 is the verdict. (Recorded in the existing runbook § *Applying a migration to Supabase*, failure #3.)

**Expected failure #2 — `extension "vector" is not available`.** The dump references pgvector, used by `MemoryEmbedding`. Enable it in the scratch database before restoring:

```bash
docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGSSLMODE \
  -e PGDATABASE=ledger_restore_rehearsal postgres:17 \
  psql -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

If that fails because the extension is not available on the staging project's plan, **that is a real RTO finding** — record it, and note that recovery requires a project where pgvector is enabled.

- [ ] **Step 4: Verify the money, not the row counts**

```bash
POSTGRES_HOST="$PGHOST" POSTGRES_PORT=5432 \
POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
POSTGRES_DB=ledger_restore_rehearsal \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=readonly ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py dump_ledger_totals --json > /tmp/e16-after.json

diff <(python3 -m json.tool /tmp/e16-before.json) <(python3 -m json.tool /tmp/e16-after.json) \
  && echo "IDENTICAL — entry counts, sums, and every month's acumulado"
```

**Expected: no diff at all.** Every household's `entry_count`, `entry_sum`, `income_sum`, and every month's `total`, `income` and `acumulado`.

A diff here is the finding, not a nuisance. Two legitimate causes and one serious one:

- **Rows written to production between Step 1's fingerprint and the backup's timestamp.** The backup is from last night; the fingerprint is from now. This is expected, and it is your **RPO made visible** — measure it and record it as such. To eliminate it, re-run Step 1 against a `pg_dump` taken at the same moment, but the honest version is: record the delta and what it means.
- **The clock pin was changed.** Check `FIXED_TODAY` is still `date(2026, 8, 12)`.
- **The restore lost data.** Everything else. Stop and investigate; this is the finding the epic exists to surface.

- [ ] **Step 5: Confirm the application actually runs against the restored database**

A database that restores but that Django refuses to start against is not a recovery.

```bash
POSTGRES_HOST="$PGHOST" POSTGRES_PORT=5432 \
POSTGRES_USER="$PGUSER" POSTGRES_PASSWORD="$PGPASSWORD" \
POSTGRES_DB=ledger_restore_rehearsal \
DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=readonly ALLOWED_HOSTS=localhost \
  uv run python src/backend/manage.py check_migration_drift
```

Expected: `ledger_drift_check_ran: no drift`. This is Task 2's command doing exactly the job it was written for, against a database whose provenance is a backup file.

**Stop the clock. Record the elapsed time from Step 2 to here. That is the RTO.**

- [ ] **Step 6: Clean up — and treat every artefact as production data**

```bash
docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE \
  postgres:17 psql -c 'DROP DATABASE IF EXISTS ledger_restore_rehearsal WITH (FORCE);'
rm -f /tmp/e16-restore.dump /tmp/e16-before.json /tmp/e16-after.json
```

**`WITH (FORCE)` is required** — the connection is held by Supabase's pooler, not by a client, so `pg_terminate_backend` cannot clear it and a plain `DROP DATABASE` fails with "is being accessed by other users" while `pg_stat_activity` shows nobody. (Existing runbook, failure #4.)

- [ ] **Step 7: Write the evidence**

`docs/superpowers/evidence/e16-restore/README.md`:

```markdown
# E16 S16-5 — a restore that was performed and timed

**Date:** <YYYY-MM-DD>
**Performed by:** <name>
**Source:** `gs://ledger-backups-expense-tracker-482807/<object>` — the nightly
`ledger-backup` job's output, written <timestamp>.
**Target:** `ledger_restore_rehearsal`, a scratch database in the **staging**
Supabase project. Never staging's own database; never production.

## The measured RTO

| Phase | Duration |
|---|---|
| Download the backup from GCS | <m:ss> |
| `CREATE DATABASE` + `CREATE EXTENSION vector` | <m:ss> |
| `pg_restore` | <m:ss> |
| Verify with `dump_ledger_totals` | <m:ss> |
| Confirm no schema drift | <m:ss> |
| **Total — the RTO** | **<H:MM>** |

This replaces the estimate in `docs/architecture/product-readiness-review.md`'s
NFR table. The review proposed 4 hours; the measured number is <H:MM>.

<If the measured RTO is unacceptable, this is where the gap goes, with what
would close it — e.g. "the download dominates at N minutes; keeping a warm
standby database would remove it, at R$X/mo".>

## The RPO, made visible

The fingerprint was taken at <hh:mm>; the backup was written at <hh:mm>. The
diff between them is <N> entries and R$<X> — that gap is the RPO in the only
form that matters. With a nightly backup at 03:00 the worst case is ~24 hours of
entries.

## Integrity verification

Not row counts. `manage.py dump_ledger_totals --json` compares every household's
entry count, entry sum, income sum, and **every month's total, income and
acumulado** — because this project has a documented history of reconciliation
issues where the counts matched and the balances did not, which is why that
command exists.

```
$ diff before.json after.json
<paste the real result>
```

## Failures encountered

<Every one, in the order it bit — this section is the most valuable part of the
document for whoever does this next under pressure.>

## What this does not prove

The restore went into a scratch database. **Cutting production over to a
restored database has not been rehearsed** — that additionally requires
re-pointing `DATABASE_URL`, redeploying, and re-provisioning the `ledger-purge`,
`ledger-drift-check` and `ledger-backup` jobs against the new host. The runbook's
§ *Restoring from backup* documents that sequence; nobody has executed it.
```

- [ ] **Step 8: Write the runbook section**

Add `## Restoring from backup` to `docs/runbook.md`, after § *Backups*. It must contain, as copy-pasteable commands with realistic values: fetching the latest object; creating the scratch database with the `vector` extension; the `pg_restore` invocation through the `postgres:17` Docker image; the `dump_ledger_totals` verification; the `DROP DATABASE ... WITH (FORCE)` cleanup; and all four expected failures above with their fixes.

It must then carry a clearly-marked subsection, **"Cutting production over to a restored database"**, listing the sequence in order — restore into a new database, point `DATABASE_URL` at it, redeploy, re-point `ledger-purge` / `ledger-drift-check` / `ledger-backup`, verify `/healthz/` — with an explicit line saying **this sequence has been written but not rehearsed**, and that the rehearsed part is everything above it. A runbook that implies more has been proven than has is worse than one that admits the gap.

And it must state the measured RTO and the RPO in its first paragraph, so the number is the first thing an operator reads.

- [ ] **Step 9: Replace the estimated RTO in the architecture review**

Two lines, both read at `fef60a8`:

**Line 45**, the NFR table:

```
| RPO / RTO | RPO 24h → 1h; RTO 4h | Supabase automated backups only, retention unverified, restore never rehearsed |
```

Replace both the target and the note with the measured values and how they were measured, plus a pointer to `docs/superpowers/evidence/e16-restore/README.md`. The note's three claims are now all answerable: the retention *is* verified (Task 10 Step 1), the backups are *not* Supabase's only (Task 10), and the restore *has* been rehearsed.

**Line 344**, the risk register:

```
| Restore has never been rehearsed; RTO/RPO are assumptions | Medium | **Severe** — unrecoverable customer data loss | Rehearse a full Supabase restore into a scratch project, time it, write it into `docs/runbook.md`. Do this before the first paying customer, not after. |
```

Mark this row **mitigated**, with the date and the evidence path. Do not delete it — the register's value is that it records what was true and when it stopped being true.

```bash
grep -n "RTO\|RPO" docs/architecture/product-readiness-review.md
```

Expected after the edit: no occurrence of "never rehearsed" or "assumptions" remains attached to the restore.

- [ ] **Step 10: Commit**

```bash
git add docs/runbook.md docs/superpowers/evidence/e16-restore/ docs/architecture/product-readiness-review.md
git commit -m "docs(E16): a database restore, performed and timed — the RTO is now measured

The architecture review's NFR table carried an estimate and the risk register
carried 'restore has never been rehearsed'. Both are now a number, taken from a
real pg_restore of a real nightly backup into a scratch database.

Verified with dump_ledger_totals rather than row counts: every household's sums
and every month's acumulado, because this project has a history of the counts
matching while the balances did not.

Stated plainly in the evidence and in the runbook: cutting production over to a
restored database is written down and has NOT been rehearsed. A runbook that
implies more proof than exists is worse than one that admits the gap."
```

---

## Task 12: Finish the runbook, and survive the maintainer

Closes **S16-6** and **S16-7**. The runbook already exists — 2842 lines, twenty sections, written incrementally by E01, E06, E07, E09, E10, E12 and E13. This task is the consolidation the spec describes: *"This epic is where the whole thing is consolidated and verified as complete."*

**Files:**
- Modify: `docs/runbook.md`
- Create: `docs/operations/credentials.md`
- Create: `AGENTS.md`
- Modify: `README.md:113-128`

**Interfaces:**
- Consumes: every section written by Tasks 4–11.
- Produces: a runbook whose coverage is verified against S16-6's list, and a credential inventory Task 13 cites.

- [ ] **Step 1: Check the runbook against S16-6's list, procedure by procedure**

S16-6 names ten procedures. Against the sections that exist at this point:

| Procedure required by S16-6 | Section | State |
|---|---|---|
| Deploying | *Deploy a new revision* + *The deploy pipeline* (Task 5) | covered |
| Rolling back | *Rolling back* (Task 9) | covered |
| Running migrations | *Applying a migration to Supabase* | covered |
| Restoring from backup | *Backups* + *Restoring from backup* (Tasks 10, 11) | covered |
| Rotating secrets | — | **gap; Step 2** |
| Investigating an alert | *When something breaks* | covered; table updated by Task 8 |
| Replaying a dead-lettered task | *Async tasks (E10) → Replaying a dead-lettered task* | covered |
| Running the cost report | *Usage, credits and cost (E07)* | covered |
| Fulfilling a data-subject request | *Pedido de titular (LGPD) — 15 dias* | covered |
| Responding to a breach | *Incidente de segurança — 72 horas* | covered |

Verify each claimed-covered row by opening it and checking it has the full invocation, what it prints, and the common failure — S16-6 requires all three per section:

```bash
grep -n "^## " docs/runbook.md
```

Fix any section that names a command without saying what it prints. Do not rewrite sections that are already complete.

- [ ] **Step 2: Write the missing section — rotating secrets**

Add `## Rotating a secret` to `docs/runbook.md`. It must cover, one subsection each with the real invocation:

- **The list of secrets and where each lives.** `RESEND_API_KEY`, `OPENAI_API_KEY` / `LLM_API_KEY`, `OPENROUTER_API_KEY`, `SECRET_KEY`, the database password, `ADMIN_URL_PATH` (not a secret in the cryptographic sense, but unpublished and treated as one), and Task 10's `ledger-pghost` / `ledger-pguser` / `ledger-pgpassword`.
- **The mechanics**, per storage location — Secret Manager (`gcloud secrets versions add <name> --data-file=-`) versus a plain env var (`gcloud run services update --update-env-vars`, never `--set-env-vars`, which replaces the whole list).
- **The thing that catches people:** *the service reads secrets at start, so a new revision is required for a rotation to take effect.* That sentence already exists in § *Incidente de segurança*; this section is where it belongs in full, and the incident section should point here.
- **What else must be updated for each secret.** Rotating the database password means the Secret Manager entries *and* the `PROD_POSTGRES_PASSWORD` GitHub secret *and* re-running any Job that embeds it. Missing one produces a nightly backup that fails silently until the 36-hour alert fires.
- **The common failure:** rotating `SECRET_KEY` invalidates every session and every password-reset link in flight. That is sometimes what you want (§ *Incidente de segurança*, step 3) and sometimes an unforced outage.

- [ ] **Step 3: Write the credential inventory (S16-7)**

Create `docs/operations/credentials.md`. **It records where each credential lives and who can reissue it — never a value.**

```markdown
# Operating credentials — where they live

**No secret value appears in this file, and none ever may.** This is a map, so
that someone who is not the author can find and reissue everything the service
needs. That person is the mitigation for the sole-maintainer risk in the risk
register (E16 S16-7).

| What | Where it lives | Who can reissue it | Used by |
|---|---|---|---|
| GCP project owner | Google account <address> | — the root of everything below | all |
| Supabase production project | Supabase account <address> | Supabase dashboard | the service, `ledger-backup` |
| Supabase staging project | same account | same | staging |
| Database password (prod) | Secret Manager `ledger-pgpassword`, GitHub env `production` | Supabase dashboard → Database → Reset password | migrations, `ledger-backup` |
| `RESEND_API_KEY` | Secret Manager | Resend dashboard | transactional email |
| `OPENAI_API_KEY` | Secret Manager | OpenAI dashboard | assistant, vision, transcription |
| `OPENROUTER_API_KEY` | Secret Manager | OpenRouter dashboard | ESSENTIAL tier fallback |
| `SECRET_KEY` | Cloud Run env | generate a new one; see § *Rotating a secret* | sessions, signing |
| `ADMIN_URL_PATH` | Cloud Run env | choose a new path | admin isolation |
| Deploy identity | WIF pool `github`, service account `github-deployer` | `gcloud`; Task 5 of the E16 plan | the deploy pipeline |
| GitHub repository | `bessavagner/expense_tracker_v2` | GitHub account <address> | everything |
| TWA signing key | <where the keystore lives, and its backup> | **cannot be reissued** — losing it means a new Android package name | the Android app |
| Domain / DNS | <registrar> | <registrar account> | — |

## If the maintainer is unavailable

Everything above is reachable from two accounts: the Google account and the
GitHub account. Whoever holds those can deploy, roll back and restore by
following `docs/runbook.md` alone.

**The one thing that cannot be recovered from those two accounts is the TWA
signing key.** Losing it does not lose data; it means the Android app must ship
under a new package name and existing installs cannot be upgraded. Store its
backup somewhere that survives this machine.

## Recovery access

<Record here how a second person actually gets these accounts — a password
manager's emergency access, a sealed record, or an explicit statement that no
such mechanism exists yet. An honest "not solved" is worth more than a plan
nobody set up.>
```

Fill every `<...>` placeholder with real values before committing. **A row left as a placeholder is worse than an absent row**, because it reads as answered.

- [ ] **Step 4: Have someone else follow the deploy section**

S16-6's DoD: *"Someone other than the author has followed the deploy section successfully."* And S16-7's: *"a competent stranger could deploy, roll back, and restore from it."*

Hand `docs/runbook.md` §§ *The deploy pipeline* and *Rolling back* to a second person with no context, and have them deploy to **staging** and roll it back without help. Record what they had to ask about — every question is a gap in the document, and fixing those is the point of the exercise.

If no second person is available, say so plainly in Task 13's DoD rather than ticking the box. An untested runbook that claims to be tested is exactly the failure mode this epic exists to end.

- [ ] **Step 5: Add the pointers**

`README.md` already has a runbook block at lines 113-128. Add to it:

```markdown
> Deploying, rolling back, or restoring the database: `docs/runbook.md` →
> *The deploy pipeline*, *Rolling back*, *Restoring from backup*. Where every
> credential lives: `docs/operations/credentials.md`.
```

`AGENTS.md` does not exist. Create it with a short pointer block — the project convention asks for one, and its absence is why an agent re-derives the same operational facts every session:

```markdown
# AGENTS.md

Operator procedures live in **[`docs/runbook.md`](docs/runbook.md)** — deploying,
rolling back, migrations, restoring from backup, rotating secrets, investigating
an alert, replaying a dead-lettered task, the cost report, LGPD data-subject
requests, and breach response. One section per procedure, with the full
invocation, what it prints, and the common failure. Read it before inventing a
command.

Architecture decisions: `docs/architecture/`. The product backlog, one
self-contained file per epic: `docs/backlog/`, indexed by
[`docs/backlog/INDEX.md`](docs/backlog/INDEX.md) — §7 carries the global
constraints every change is held to.

Testing conventions, including the clock rules: `docs/testing-conventions.md`.

**Deploys go through the pipeline** — merge to `main` deploys staging, a `v*` tag
deploys production. Do not `gcloud run deploy` by hand except when the runbook's
§ *Deploying by hand, when the pipeline is down* applies.
```

- [ ] **Step 6: Commit**

```bash
git add docs/runbook.md docs/operations/credentials.md AGENTS.md README.md
git commit -m "docs(E16): close the runbook's last gaps, and map every credential

The runbook was written incrementally by seven epics and was missing one of
S16-6's ten procedures — rotating a secret, including the part that catches
people: the service reads secrets at start, so a rotation needs a new revision.

docs/operations/credentials.md maps where each credential lives and who can
reissue it, never a value. It names the one thing that cannot be recovered from
the two root accounts: the TWA signing key.

AGENTS.md finally exists, pointing at the runbook rather than letting each
session re-derive it."
```

---

## Task 13: Close the epic

**Files:**
- Modify: `docs/backlog/E16-operations-staging-deploy-recovery.md` (tick the DoD, answer the open questions)
- Modify: `docs/backlog/INDEX.md` (status, footnote, release-map note)

- [ ] **Step 1: Run the epic's Definition of Done verbatim**

Exactly as the epic writes it, with the settings module corrected for Task 1:

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

DJANGO_SETTINGS_MODULE=config.settings.prod \
  SECRET_KEY="aZ9_kQ2w-pR7x!mN4tB6vC8yE0sG1hJ3lD5fH7uI9oP2qW4eR6tY8u0" \
  ALLOWED_HOSTS=example.com CSRF_TRUSTED_ORIGINS=https://example.com \
  uv run python src/backend/manage.py check --deploy
```

> There is one **pre-existing** local failure in `core/tests/test_email_config.py`, caused by the developer's `.env` rather than by any change here. Confirm it is the same failure that existed at `fef60a8` before claiming the suite is green — and if this epic's settings split changed its shape, that is this epic's problem to fix, not a pre-existing one to wave through.

- [ ] **Step 2: Walk the twelve observable assertions and tick only what is proven**

Against the epic's checklist, each with its evidence:

| Assertion | Evidence |
|---|---|
| Hardening does not depend on `DEBUG`; a test asserts it against the production module | `TestProductionHardeningIsUnconditional`, Task 1 |
| Staging exists, own database, never held production data | Task 4; seeded by `seed_qa_data` |
| A merge to `main` deploys staging automatically | the run from Task 5 Step 5 |
| Production deploy is deliberate; migrations are an ordered separate step | Task 6; the `v0.1.0` run |
| WIF, no long-lived key in CI | Task 5; `gh secret list` shows no key |
| **A rollback has been performed** against staging and documented | `docs/superpowers/evidence/e16-rollback/` |
| **A full restore has been performed and timed**, RTO recorded | `docs/superpowers/evidence/e16-restore/` |
| Restore verification compares balances and acumulado | the `dump_ledger_totals` diff |
| `docs/runbook.md` covers every listed procedure, linked from the README | Task 12 Step 1's table |
| Someone other than the author has followed the deploy section | Task 12 Step 4 — **or say plainly that nobody has** |
| A ratio policy exists alongside the count, and a simulated low-volume total failure fires it | `docs/superpowers/evidence/e16-alerts/` |
| Drift is detected without a user hitting it, names the migrations, re-checked on a schedule | Task 7 Step 3's staging 503; the nightly job |

**Tick only what has evidence.** Every closed epic in this backlog that left a box unticked said why inline — E06 left three, E07 one, E08 one — and that convention is why the backlog is trustworthy. Follow it.

- [ ] **Step 3: Answer the epic's four open questions in the epic file**

1. **Supabase backup retention** — the facts from Task 10 Step 1, verbatim, plus the sentence that we no longer depend on them.
2. **A separate staging Supabase project** — answered by D1: yes, separate, free tier, and the pausing behaviour is the cost.
3. **What RTO is acceptable** — answered by the measurement in Task 11, not by a target chosen in advance.
4. **Approval gates** — answered by D3: a `production` GitHub Environment exists so a protection rule can be added without touching the workflow; it is deliberately not enabled with one maintainer.

- [ ] **Step 4: Update `INDEX.md`**

- E16's status → **done (2026-XX-XX)** with a footnote number, following the existing footnote style.
- The footnote itself: what closed, what did not, and the one sentence that matters most — the measured RTO.
- The R4 gate row mentions *"you can restore the database inside your stated RTO — rehearsed, not assumed"*. Note that this half of R4's gate is now observably true, and that the rest of R4 waits on E15 and E17.

- [ ] **Step 5: Final verification and commit**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
curl -s https://expense-tracker-654941182076.southamerica-east1.run.app/healthz/ | python3 -m json.tool
gcloud alpha monitoring policies list --project expense-tracker-482807 \
  --format="table(displayName,enabled)"
gcloud run jobs list --project expense-tracker-482807 --region southamerica-east1
gcloud scheduler jobs list --project expense-tracker-482807 --location southamerica-east1
```

Expected: suite green, ruff clean, health `ok`, six alert policies, four Jobs (`ledger-purge`, `ledger-drift-check`, `ledger-backup`, plus staging's), three Scheduler jobs.

```bash
git add docs/backlog/
git commit -m "docs(E16): close the epic — the restore is a number now, not an assumption

The risk register said 'restore has never been rehearsed; RTO/RPO are
assumptions'. Both are measured, from a real backup into a scratch database,
verified on balances and acumulado rather than row counts.

Deploys are a pipeline with staging in front and ordered migrations. Schema
drift — the 2026-08-15 outage — is caught three ways. The 5xx ratio alert has
fired in a deliberate low-volume test that the count-based policy would have
slept through."
```

---

## Self-review

Run against `docs/backlog/E16-operations-staging-deploy-recovery.md` after the plan was complete.

**Spec coverage.** All nine stories map to tasks: S16-1→1, S16-2→4, S16-3→5+6, S16-4→9, S16-5→10+11, S16-6→12, S16-7→12, S16-8→8, S16-9→2+3+7. All twelve DoD assertions map to Task 13's evidence table. All four open questions are answered — three by decision (D1, D3, and D4's refusal to pre-commit), one by measurement (Task 10 Step 1).

**Two spec claims corrected rather than repeated**, both flagged in the header: `docs/runbook.md` exists and is substantial, so S16-6 became gap-filling; and the settings line references have moved since the spec was written.

**One story is larger than the spec implies, and the plan says so.** S16-5 asks to *verify* the backup mechanism. Task 10 concludes we must *own* it (D11) — a scope increase, argued from the spec's own open question 1 rather than assumed. If the maintainer disagrees after Task 10 Step 1 reveals what Supabase actually retains, Task 10 Steps 2-8 are droppable and Task 11 can rehearse against a vendor backup instead.

**Deliberate scope exclusions**, matching the spec's *Out of scope*: no Terraform, no multi-region, no Cloud SQL migration, no runtime change.

**Two things this plan cannot deliver, stated where they occur rather than at the end.** Task 12 Step 4 needs a second human; if none exists, the box stays unticked. And Task 11's evidence states explicitly that *cutting production over to a restored database* is written down and unrehearsed — the runbook says so on its own face, because a runbook implying more proof than exists is the failure this epic is about.

**Type and name consistency checked across tasks.** `unapplied_migrations()` is defined in Task 2 and consumed by Tasks 3, 7 and 11 under that exact name. `check_migration_drift` is the command name in Tasks 2, 6, 7 and 11. The health payload keys `status` / `database` / `migrations` / `unapplied` are defined in Task 3 and read by Tasks 4, 5, 6, 7 and 9. `config.settings.prod` / `.dev` / `.base` are defined in Task 1 and used by every later task that runs a Django command. `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_DEPLOY_SERVICE_ACCOUNT` are created in Task 5 Step 3 and read in Tasks 5 and 6. The log-based metric names `ledger_drift_check_ran`, `ledger_requests_total`, `ledger_requests_5xx` and `ledger_backup_ran` each appear in exactly one creating task and one alert policy.

**Ordering dependencies verified.** Task 3 (drift 503s) must land before Task 4 deploys staging, or the staging smoke test asserts a key that does not exist. Task 4 must precede Task 5, which has nothing to deploy otherwise. Task 5 must precede Task 6, which reuses its identity and job shape. Task 10 must precede Task 11, which restores what it wrote. Task 8's staging rehearsal must not run while Task 9's rollback rehearsal is in flight — both mutate staging's serving revision.
