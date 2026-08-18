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
| A deploy that shipped code ahead of its migration, undetected for a day | the 2026-08-15 incident, below |
| The 5xx alert policy that fired four minutes *after* the fix | policy `4509450462948742746`, provisioned by E06 |

### The 2026-08-15 incident — why S16-8 and S16-9 exist

Revision `00046-l64` carried `accounts.0005`'s `Household.plan` while production's
database sat at `accounts.0004`. `resolve_active_household` selects `plan_id` in
middleware on every request, so **every route 500'd for any logged-in user** from
the 2026-08-14 deploy until the migration was applied on 2026-08-15 — roughly a
day. Anonymous requests mostly passed, which is why it presented as "server error
after login" rather than as an outage.

Two independent failures, and the second is the more interesting one:

1. **Nothing verified that the deployed image's migrations were applied.** S16-3
   fixes this for *future* deploys by ordering migrations inside the pipeline. It
   does not detect an already-deployed system that is drifted — which is the state
   production was in for a day. Hence S16-9.
2. **The alerting could not see it.** The 5xx policy is a *count* — "more than 5 in
   5 minutes". A family-scale app with a broken authenticated path produces perhaps
   a handful of errors a day, so the count never tripped until the operator sat
   down and clicked around; the alert then fired at 17:34 UTC, four minutes after
   the fix had already landed. The *ratio* was effectively 100% of authenticated
   requests for a full day. Hence S16-8.

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

### S16-8 · Alert on the 5xx *ratio*, not only the count

- **Given** the only error-rate policy counts absolute 5xx responses in a window, and a family-scale app never reaches that threshold on a persistent low-traffic failure — the 2026-08-15 outage ran a full day at ~100% failure for authenticated requests without alerting
- **When** a ratio-based condition is added alongside the existing count
- **Then** it alerts when 5xx exceed an agreed *share* of requests over a window, so a total failure at low volume pages as loudly as a spike at high volume
- **And** the window and threshold are chosen so a single error on a quiet afternoon does not page — the failure mode to avoid is an alert nobody trusts
- **And** the count-based policy is kept, because the two catch different shapes: a ratio is blind to a burst that is small relative to healthy traffic
- **And** both policies' behaviour is recorded in the runbook's "When something breaks", including which one fires for which shape of failure

> The existing keepalive ping is *healthy* traffic and inflates the denominator — a broken authenticated path against a passing `/healthz/` is exactly the case this story exists for. Verify the ratio still crosses the threshold with the keepalive counted, or exclude it from the metric.

### S16-9 · Detect schema drift between the deployed image and the database

- **Given** nothing today notices that a running revision's code expects a migration the database has never applied, and the symptom is a 500 in middleware rather than anything naming the cause
- **When** drift detection exists
- **Then** an unapplied migration for the currently-serving revision is surfaced without waiting for a user to hit the broken path
- **And** the check runs after every production deploy, and on a schedule thereafter — the day-long window on 2026-08-15 opened at a deploy but stayed open because nothing re-checked
- **And** it reports *which* migrations are missing, so the fix is `migrate <app>` rather than an investigation
- **And** `/healthz/` is considered as the place to surface it, so the existing uptime check catches it — noting the deliberate trade-off that a health endpoint failing on drift takes the service out of rotation, which may be correct here since the service is already broken for its users

> Related to S16-3 but not covered by it: S16-3 orders migrations *within* a deploy. This story detects a database that is already behind, including drift caused by a rollback, a manual `migrate` against the wrong target, or a deploy performed outside the pipeline.

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# Production settings are hardened unconditionally
DJANGO_SETTINGS_MODULE=config.settings.prod uv run python src/backend/manage.py check --deploy
```

Observable assertions:

- [x] Production hardening does not depend on `DEBUG`; a test asserts this against the production module — `TestProductionHardeningIsUnconditional` in `core/tests/test_deploy_settings.py`. All three cases go red against a verbatim recreation of the H7 bug.
- [x] Staging exists, has its own database, and has never held production data — `expense-tracker-staging`, Supabase project `amysprpoexfedbqfnwzp`, seeded by `seed_data` + `seed_qa_data`. Its one household is `Casa de qa.homologacao`.
- [x] A merge to `main` deploys to staging automatically — run `32170464187`, green through migrate → deploy → smoke test.
- [x] Production deploy requires a deliberate trigger, and migrations run as an ordered, separate step — tag `v0.1.0`, run `32172610057`. That a failed migration *aborts* the deploy is proven, not assumed: run `32171826600` failed at `Migrate staging`, `Deploy staging` was skipped, and no revision was created.
- [x] Deploy authentication uses Workload Identity Federation, with no long-lived key in CI — provider `github-provider` with `assertion.repository_owner == 'bessavagner'`, bound to a `principalSet` naming this repository alone. `gcloud iam service-accounts keys list --managed-by user` returns nothing; the repository holds no secret containing a key.
- [x] **A rollback has been performed** against staging and documented — `docs/superpowers/evidence/e16-rollback/`. 9.7 s for the traffic switch, 45.5 s including verification, both directions.
- [x] **A full database restore has been performed and timed**, with the measured RTO recorded — `docs/superpowers/evidence/e16-restore/`. **1 min 45 s** to recover and verify the data. The review's estimate was 4 hours.
- [x] Restore verification compares balances and acumulado, not just row counts — `dump_ledger_totals --json` over 3 households and 110 household-months, zero lines of diff.
- [x] `docs/runbook.md` exists, covers every listed procedure, and is linked from the README quickstart — all ten of S16-6's procedures; *Rotating a secret* was the one gap and is now written.
- [ ] ~~Someone other than the author has followed the deploy section successfully~~ — **NOT DONE. Nobody else has read it.** There is no second person available, so this box stays unticked rather than being ticked on the author's own reading. It is the one assertion in this epic with no evidence behind it, and it is the one that most directly tests S16-7.
- [x] A **ratio-based** 5xx policy exists alongside the count-based one, and a simulated total failure at low request volume fires it — `docs/superpowers/evidence/e16-alerts/`. Twelve 5xx over sixteen minutes on staging, ratio 1.000, violation opened 5m24s after the first error. The count policy's busiest 5-minute window held **5** against a threshold needing **6** — it would not have fired.
- [x] Schema drift between the serving revision and the database is detected without a user hitting it, names the missing migrations, and is re-checked on a schedule rather than only at deploy time — `docs/superpowers/evidence/e16-drift/`. Against a genuinely drifted staging database, `/healthz/` returned **503** with `"migrations": "drift"` and the migration named. Nightly `ledger-drift-check` at 03:50.

### One thing the plan assumed that was false, and had to be fixed for this epic to mean anything

**The startup probe was a TCP check on port 8080, not an HTTP check on
`/healthz/`.** Decisions D2 and D6 both rest on the probe seeing a 503 — a TCP
probe cannot, so a revision deployed ahead of its migrations would have become
ready and served errors, which is exactly 2026-08-15. Both services now probe
`/healthz/` over HTTP. That change requires `127.0.0.1` in `ALLOWED_HOSTS`,
because the probe sends that Host header; without it every probe gets a Django
400 that Cloud Run reports as a *timeout*.

Two smaller corrections, both recorded where they bite: the backup size floor of
1 MiB was above the real dump size (545 KiB) and failed the first run — it is now
a measured 350,000 bytes; and the pipeline now re-points `ledger-drift-check` as
well as `ledger-purge`, because a stale drift check compares the *old* image's
migration graph against the current database and can report "no drift" while the
serving revision is drifted.

## Out of scope

- Multi-region or high availability — parked (INDEX §10)
- Kubernetes or a different runtime — ADR-002 keeps the single Cloud Run service
- Infrastructure as code (Terraform) — worth doing, and not required for MVP; note it as a follow-up
- Migrating off Supabase to Cloud SQL — open decision D5 in the architecture review; this epic documents the current setup rather than changing it

## Open questions

1. **What is the actual Supabase backup retention** on the current plan? — **Still unanswered, and deliberately no longer load-bearing.** The facts live only in the dashboard (*Project → Database → Backups*) and could not be read from the CLI; `docs/runbook.md` § *Backups* carries a marked placeholder for them. What changed is that the answer no longer matters much: we now take our own nightly `pg_dump -Fc` to GCS with a 30-day lifecycle rule (D11), and Supabase's backups are the second line. A retention set by someone else's pricing page is not something an RPO can be stated from. **Fill the placeholder in anyway** — knowing whether the vendor keeps anything changes what our own retention needs to be.
2. **Is a separate staging Supabase project affordable?** — **Yes. Answered by D1: separate project, R$0** on the free tier. The cost is operational, not financial: Supabase pauses a free project after about a week of inactivity, and staging is idle by design. The runbook names that as the first thing to check when the deploy workflow times out at its migrate step.
3. **What RTO is acceptable?** — **Answered by measurement rather than by choosing a target (D4): 1 min 45 s** to recover and verify the data, ~15 minutes to have the product serving again. The review proposed 4 hours; the estimate was made without knowing the dump is 545 KiB. The RPO is ~24 hours and is set by the 03:00 schedule, not by any technical limit — halving it costs one more Scheduler job.
4. **Does the deploy pipeline need approval gates?** — **Not now, and the mechanism exists (D3).** A `production` GitHub Environment holds the deploy secrets, so a required-reviewer protection rule can be added without touching the workflow. It is deliberately not enabled: with one maintainer you would be approving your own deploy, which only trains you to click through the gate.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `fullstack-dev-skills:devops-engineer` — CI/CD, Workload Identity Federation, and Cloud Run deployment specifics
4. `superpowers:test-driven-development` — for the settings-split assertions
5. `superpowers:subagent-driven-development`
6. `superpowers:requesting-code-review`
7. `superpowers:verification-before-completion` — the evidence is a **timed restore** and a **performed rollback**, not a written procedure
8. `superpowers:finishing-a-development-branch`
