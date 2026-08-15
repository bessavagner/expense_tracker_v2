---
id: E16
title: "Operations: staging, deploy & recovery"
release: R4
status: ready
depends_on: [E06]
blocks: []
wedge_critical: false
---

# E16 · Operations: staging, deploy & recovery

## Outcome

Changes reach production through an automated, reversible pipeline with a staging environment in front of it, and the database can be restored inside a stated RTO — **rehearsed, not assumed**.

## Why now

Review finding **M7** and the risk register entry *"Restore has never been rehearsed; RTO/RPO are assumptions."*

Deploy today is a manual `gcloud run deploy --source .` from a laptop, with no staging, no migration ordering guarantee, no rollback procedure, and no `docs/runbook.md`. That is survivable when the only user is the developer. It is not survivable when a stranger's financial history depends on it.

The risk that should keep you up is not a bad deploy — it is discovering, during a real incident, that the backup you assumed exists cannot be restored in the time you assumed.

## Evidence in the codebase

| What | Where |
|---|---|
| Manual deploy from a laptop | `docs/deploy/next-session-kickoff.md:62` |
| No deploy automation in CI | `.github/workflows/ci.yml` — tests only |
| `docs/runbook.md` does not exist | required by this project's own conventions |
| Migrations must run separately from the app start | `docs/deploy/production-roadmap.md` Phase 1 item 7 |
| Migrations need the direct connection, not the pooler | `.env.example` production section; `config/settings.py:84-94` |
| Security hardening gated on a single env var | `config/settings.py:108-110, 234-244` — review **H7** |
| A guard test for that hardening exists | `core/tests/test_deploy_settings.py` |
| Health endpoint available for gating | `core/views.py:8` |
| Cost-conscious keepalive already in place | Scheduler ping rather than `min-instances=1` |
| Deploy backlog with much of this already scoped | `docs/deploy/backlog-deploy.md` items 9.4, 9.7, 12.5 |

## Stories

### S16-1 · Split the settings module

- **Given** review **H7**: a stray `DEBUG=True` silently disables SSL redirect, secure cookies, HSTS, and nosniff simultaneously
- **When** settings are split into base, dev, and prod
- **Then** production hardening is unconditional in the module production loads, not conditional on an environment variable
- **And** `core/tests/test_deploy_settings.py` is updated to assert against the production module directly
- **And** `check --deploy` passes against the production settings module
- **And** it becomes impossible to accidentally deploy an unhardened production instance

### S16-2 · A staging environment

- **Given** changes currently go straight from a laptop to production
- **When** staging exists
- **Then** it mirrors production's shape — Cloud Run, a separate Supabase project or database, its own secrets
- **And** it never shares a database with production
- **And** it has realistic seeded data, not production data — production financial records must not be copied into a lower environment
- **And** migrations are exercised there before production

### S16-3 · Automated deploy with ordered migrations

- **Given** deploys are manual and migration ordering is unguaranteed
- **When** the pipeline is built
- **Then** merging to `main` deploys to staging automatically
- **And** production deploys are triggered deliberately — a tag or a manual approval, not every merge
- **And** migrations run as a distinct step against the **direct** connection, before the new revision serves traffic
- **And** authentication uses Workload Identity Federation rather than a long-lived service account key
- **And** a failed migration aborts the deploy rather than leaving a half-migrated database serving traffic

### S16-4 · Rollback that has been performed

- **Given** rollback is currently undefined
- **When** a rollback procedure exists
- **Then** reverting to the previous Cloud Run revision is documented and has been **executed at least once** against staging
- **And** the procedure states explicitly how to handle a rollback when a migration has already applied — the hard case, and the one that will occur under pressure
- **And** the guidance that migrations should be backward-compatible with the previous revision is written down, since that is what makes rollback possible at all

### S16-5 · Backup and a rehearsed restore

- **Given** RPO and RTO are currently assumptions
- **When** recovery is established
- **Then** the backup mechanism, frequency, and retention are documented and verified — Supabase's automated backups exist, but the retention on the current plan must be confirmed rather than assumed
- **And** a **full restore has been performed** into a scratch environment, and **timed**
- **And** the measured restore time is recorded as the real RTO, replacing the estimate in the architecture review's NFR table
- **And** restore verification checks data integrity — entry counts, balances, and the monthly acumulado — not merely that the database starts
- **And** if the measured RTO is unacceptable, the gap is recorded with what would close it

> This story is the reason the epic exists. Everything else here is convenience; this is the difference between an incident and an ending.

### S16-6 · The runbook

- **Given** this project's conventions require `docs/runbook.md`, and it does not exist
- **When** it is written
- **Then** it covers, one section per procedure with full invocations and realistic values: deploying, rolling back, running migrations, restoring from backup, rotating secrets, investigating an alert, replaying a dead-lettered task, running the cost report, fulfilling a data-subject request, and responding to a breach
- **And** each section states what the command prints and the common failure
- **And** it is written to be pasted as-is by someone who has not memorized any of it
- **And** the README quickstart and `AGENTS.md` (if present) each carry a one-line pointer to it

> Sections of this runbook are owed by earlier epics — E01, E06, E07, E09, E10, E12, E13. This epic is where the whole thing is consolidated and verified as complete.

### S16-7 · Address the single-maintainer risk

- **Given** the risk register lists the sole maintainer as a single point of failure
- **When** this is mitigated
- **Then** every credential needed to operate the service is recorded in a way that survives the maintainer being unavailable
- **And** the runbook is complete enough that a competent stranger could deploy, roll back, and restore from it

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# Production settings are hardened unconditionally
DJANGO_SETTINGS_MODULE=config.settings.prod uv run python src/backend/manage.py check --deploy
```

Observable assertions:

- [ ] Production hardening does not depend on `DEBUG`; a test asserts this against the production module
- [ ] Staging exists, has its own database, and has never held production data
- [ ] A merge to `main` deploys to staging automatically
- [ ] Production deploy requires a deliberate trigger, and migrations run as an ordered, separate step
- [ ] Deploy authentication uses Workload Identity Federation, with no long-lived key in CI
- [ ] **A rollback has been performed** against staging and documented
- [ ] **A full database restore has been performed and timed**, with the measured RTO recorded
- [ ] Restore verification compares balances and acumulado, not just row counts
- [ ] `docs/runbook.md` exists, covers every listed procedure, and is linked from the README quickstart
- [ ] Someone other than the author has followed the deploy section successfully

## Out of scope

- Multi-region or high availability — parked (INDEX §10)
- Kubernetes or a different runtime — ADR-002 keeps the single Cloud Run service
- Infrastructure as code (Terraform) — worth doing, and not required for MVP; note it as a follow-up
- Migrating off Supabase to Cloud SQL — open decision D5 in the architecture review; this epic documents the current setup rather than changing it

## Open questions

1. **What is the actual Supabase backup retention** on the current plan? The free tier's retention is limited, and it may be inadequate for the stated RPO. Verify before relying on it.
2. **Is a separate staging Supabase project affordable,** or should staging share a project with a separate database? Sharing is cheaper and weakens isolation.
3. **What RTO is acceptable?** The review proposed 4 hours. Confirm after S16-5 measures the real number — the measurement may make the target moot in either direction.
4. **Does the deploy pipeline need approval gates,** given one maintainer? Probably not now, but the mechanism should exist before there is a second engineer.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `fullstack-dev-skills:devops-engineer` — CI/CD, Workload Identity Federation, and Cloud Run deployment specifics
4. `superpowers:test-driven-development` — for the settings-split assertions
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion` — the evidence is a **timed restore** and a **performed rollback**, not a written procedure
8. `superpowers:finishing-a-development-branch`
