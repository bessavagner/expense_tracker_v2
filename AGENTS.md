# AGENTS.md

Operator procedures live in **[`docs/runbook.md`](docs/runbook.md)** — deploying,
rolling back, migrations, backups, restoring from backup, rotating secrets,
schema drift, investigating an alert, replaying a dead-lettered task, the cost
report, LGPD data-subject requests, and breach response. One section per
procedure, with the full invocation, what it prints, and the common failure.
Read it before inventing a command.

Architecture decisions: `docs/architecture/`. The product backlog, one
self-contained file per epic: `docs/backlog/`, indexed by
[`docs/backlog/INDEX.md`](docs/backlog/INDEX.md) — §7 carries the global
constraints every change is held to.

Testing conventions, including the clock rules: `docs/testing-conventions.md`.

Where every operating credential lives (never a value):
[`docs/operations/credentials.md`](docs/operations/credentials.md).

**Deploys go through the pipeline** — merge to `main` deploys staging, a `v*` tag
deploys production. Do not `gcloud run deploy` by hand except when the runbook's
§ *Deploying by hand, when the pipeline is down* applies.

**Settings is a package.** `config.settings.dev` locally, `config.settings.prod`
in Cloud Run — production and staging alike. `config.settings` is not a usable
settings module, deliberately: `prod.py` states `DEBUG = False` as a literal and
hardens unconditionally, so no environment variable can unharden a deployed
instance. Any Django command you run against a real database needs
`DJANGO_SETTINGS_MODULE` named explicitly.
