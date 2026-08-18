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

- `fivexx-ratio-alert-policy.json` — the *expense-tracker 5xx ratio elevated*
  policy (S16-8), `18241775360706229059`. Two conditions ANDed: the ratio of
  non-`/healthz/` 5xx over 30 minutes above 50%, **and** at least three of them.
  The count-based policy `4509450462948742746` is kept alongside it deliberately;
  the two catch different shapes of failure and neither replaces the other.
  Fired in a deliberate low-volume test — `docs/superpowers/evidence/e16-alerts/`.

- `log-metrics/ledger_requests_total.json`, `log-metrics/ledger_requests_5xx.json`
  — the numerator and denominator the ratio policy reads. They exist because
  Cloud Run's built-in `request_count` carries `response_code_class` but **no URL
  path label**, so `/healthz/` cannot be excluded from the denominator — and the
  uptime check's five-minute pings are exactly the healthy traffic that would
  dilute the ratio below any usable threshold. A `_staging` pair exists with the
  same filters against `expense-tracker-staging`, so the shape can be rehearsed
  without breaking production.
