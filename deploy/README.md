# Deploy specs

Machine-readable specs applied against the live GCP project. Procedures that
use them live in `docs/runbook.md`.

- `purge-alert-policy.json` — the *E13 retention sweep has not run* alert policy.
  Apply with `gcloud alpha monitoring policies create --policy-from-file`, or
  `... policies update <id> --policy-from-file` to edit. Every field in its
  `documentation` block records an API constraint that forced its shape; read it
  before "simplifying" the condition.

**The `ledger-purge` Job spec is deliberately NOT here.** It embeds the service's
whole `env` array verbatim — which is the point, it is how values containing
commas, spaces and `@` survive — and that array includes `ADMIN_URL_PATH`, whose
only protection is that it is not published. **This repository is public.**
Generate the spec at apply time from `gcloud run services describe --format=json`;
the generator is in `docs/runbook.md` § *Retenção de dados (E13) → Provisioning*.
