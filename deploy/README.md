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

- **Workload Identity Federation** for the deploy pipeline is provisioned by
  `gcloud`, not from a file here — the pool, provider, attribute condition and
  `principalSet` binding are in the E16 plan's Task 5, and the runbook's
  § *The deploy pipeline* explains operating them. The two GitHub repository
  variables that name them are **not secrets**: they are public identifiers, and
  the authorisation is the attribute condition, not their obscurity.
