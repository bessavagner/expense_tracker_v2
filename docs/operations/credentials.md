# Operating credentials — where they live

**No secret value appears in this file, and none ever may.** This is a map, so
that someone who is not the author can find and reissue everything the service
needs. That person is the mitigation for the sole-maintainer risk in the risk
register (E16 S16-7).

Read it with [`../runbook.md`](../runbook.md) § *Rotating a secret*, which is the
*how*; this is the *where*.

| What | Where it lives | Who can reissue it | Used by |
|---|---|---|---|
| GCP project owner | Google account `bessavagner@gmail.com` — project `expense-tracker-482807` (number `654941182076`) | the root of everything below it | all |
| Supabase production project | Supabase account (same Google identity) — project ref `idhifumoajodvgcvkmwb`, region `sa-east-1` | Supabase dashboard | the service, `ledger-backup` |
| Supabase staging project | same account — project ref `amysprpoexfedbqfnwzp`, region `sa-east-1` | same | staging |
| Database password (prod) | Supabase dashboard is the source. Copies: Secret Manager `ledger-pgpassword`; GitHub env `production` secret `PROD_POSTGRES_PASSWORD`; inside the service's `DATABASE_URL` | Supabase dashboard → Database → Reset password | migrations, `ledger-backup`, the service |
| Database password (staging) | Supabase dashboard. Copies: GitHub env `staging` secret `STAGING_POSTGRES_PASSWORD`; staging's `DATABASE_URL` | same, on the staging project | staging deploys |
| `RESEND_API_KEY` | Secret Manager `resend-api-key` | Resend dashboard | transactional email |
| `OPENAI_API_KEY` / `LLM_API_KEY` | Secret Manager `llm-api-key` | OpenAI dashboard | assistant, vision, transcription |
| `OPENROUTER_API_KEY` | Secret Manager | OpenRouter dashboard | ESSENTIAL tier fallback |
| `SECRET_KEY` | Secret Manager `django-secret-key` | generate a new one; see § *Rotating a secret* — **it logs everybody out** | sessions, signing |
| `SENTRY_DSN` | Secret Manager `sentry-dsn` | Sentry project settings | error reporting |
| `LOGFIRE_TOKEN` | Secret Manager `logfire-token` | Logfire project settings | tracing |
| `ADMIN_URL_PATH` | Cloud Run env (plain value, deliberately not a Secret Manager entry) | choose a new path | admin isolation |
| `ledger-pghost`, `ledger-pguser`, `ledger-pgpassword` | Secret Manager | derived from the Supabase dashboard | `ledger-backup` Job |
| Deploy identity | WIF pool `github` + provider `github-provider`, service account `github-deployer@expense-tracker-482807.iam.gserviceaccount.com`. Named by **repository variables** `GCP_WORKLOAD_IDENTITY_PROVIDER` / `GCP_DEPLOY_SERVICE_ACCOUNT` — **not secrets**, they are public identifiers | `gcloud`; the commands are in the E16 plan's Task 5 | the deploy pipeline |
| Runtime identity | `654941182076-compute@developer.gserviceaccount.com` (the default compute account) | it is created with the project | the service and all three Jobs |
| GitHub repository | `bessavagner/expense_tracker_v2` | GitHub account `bessavagner` | everything |
| Email sending domain | `cactarus.com` — `DEFAULT_FROM_EMAIL` and `PRIVACY_CONTACT_EMAIL` both use it. **No custom domain is mapped to Cloud Run**; the product is served on its `run.app` URLs | see below — registrar not recorded | transactional email, the privacy notice |
| TWA signing key | `android.keystore` at `/home/bessa/Documents/projetos/expense_tracker_v2-twa/android.keystore` on the maintainer's workstation. Passwords are in the maintainer's local `.env` as `KEY_STORE_PASSWORD` / `KEY_PASSWORD` | **cannot be reissued** — see below | the Android app `com.bessavagner.ledger` |

## Two things this table does not answer, stated rather than implied

**The domain registrar for `cactarus.com` is not recorded anywhere in this
repository.** Whoever holds it can redirect the product's email. Record the
registrar and the account that controls it here.

**The TWA signing key exists in exactly one place: one directory on one laptop.**
`docs/deploy/twa-build.md` says to keep a backup somewhere safe; nothing verifies
that one exists, and none was found while writing this file. See below for what
losing it costs.

## If the maintainer is unavailable

Almost everything above is reachable from **two accounts**: the Google account
(`bessavagner@gmail.com`, which owns both the GCP project and the Supabase
projects) and the GitHub account (`bessavagner`). Whoever holds those two can
deploy, roll back and restore by following `docs/runbook.md` alone — every
procedure there is written to be pasted, and the restore has been rehearsed and
timed (`docs/superpowers/evidence/e16-restore/`).

**The one thing that cannot be recovered from those two accounts is the TWA
signing key.** Losing it does not lose data and does not affect the web product
at all. It means the Android app must ship under a **new package name**, and
existing installs cannot be upgraded — the two sideloaded phones would have to
uninstall and reinstall. Store its backup somewhere that survives this machine.

## Recovery access

**No recovery mechanism exists yet.** There is no shared password manager, no
emergency-access delegation, and no sealed record of the two root accounts'
credentials. If the maintainer is unavailable, nobody can reach any of the above,
and the honest consequence is that the service runs until something breaks and
then stays broken.

This is recorded as unsolved rather than planned, because an honest "not solved"
is worth more than a plan nobody set up. The cheapest thing that would change it:
a password manager with emergency access granted to one other person, holding the
Google account, the GitHub account, and a copy of `android.keystore`.
