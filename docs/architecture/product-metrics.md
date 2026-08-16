# Product metrics

**Decided:** 2026-08-16, in E14 (`docs/backlog/E14-product-analytics.md`, S14-1).
**Reads:** [`docs/architecture/activation-event.md`](activation-event.md) — the
activation definition E11 decided, which this document does not redefine.
**Read by:** `core/metrics.py`, `manage.py retention_report`,
`manage.py activation_report`, `/metricas/`, and
[`docs/architecture/ga-criteria.md`](ga-criteria.md).

Changing a definition here changes what every reported number means, including
the ones already reported. That makes it a decision, not an edit: say what
changed, leave the old wording visible, and date it. The alternative is a chart
whose line moves because the definition moved, which is worse than no chart.

## The four metrics

### Exposição (exposure)

Distinct visitors who reach the signup form.

**This is deliberately not a `ProductEvent`, and cannot be one.**
`ProductEvent.household` is non-null — every scoped read in this codebase depends
on that — and a visitor who has not signed up has no household. Modelling
pre-signup steps would mean nullable-household events, which breaks the scoping
base class every other read is built on. Not worth it for a number that is zero
until there is traffic.

**Measured at the edge instead:** Cloud Run request counts on the signup URL,
until E17 ships a landing page and there is something to be exposed *to*. Until
then this metric is defined and unmeasured, and saying so is the honest state
(E14 open question 3).

### Ativação (activation)

> **A household is activated the first time it confirms a photographed receipt
> into its ledger.**

That sentence is quoted from [`activation-event.md`](activation-event.md), which
owns it. Read that file for the cardinality, the T0, and the eight edge cases —
they are not restated here, because a second copy drifts and then two documents
disagree about what a number means.

Reported by `manage.py activation_report` as activations ÷ signups.

### Time-to-value

Minutes from a household's `signup` event to its `activated` event.

T0 is the **event**, not `User.date_joined` — one table answers the question, and
a product metric never has to join the auth tables. Reported as **p50 and p90**
(nearest-rank, so a single sample reports itself rather than an average) by
`activation_report`.

A household that never activates contributes to the activation **rate** and not
to this number. Counting non-activations as an infinite time would make the
median meaningless; excluding them makes it "how long it took the people it
worked for", which is the question.

### Retenção (retention)

**Rolling.** A household is **DN-retained** if it was *active* on day N after its
signup **or on any later day**.

*Active* means any of these carrying that household, dated after its signup:

- a `ProductEvent` row
- a `ChatMessage`
- an `Entry`

The signup event itself is day 0 and does not make a household retained.

**A household that comes back on day 9 counts for D7.** That is the whole point
of rolling retention, and it is the answer to the edge case S14-1 raised.
Exact-day retention is noise at beta sample sizes — one household's Tuesday
decides the number — and rolling retention answers the question the operator
actually has: *did they come back and stay?* It is also a named, standard
definition rather than one invented here.

**A cohort younger than N days is excluded, not counted as lost.** A household
that signed up yesterday has not failed D7; it has not had the chance. Reporting
it as unretained is how a growing beta reports collapsing retention.
`rolling_retention` returns `None` for such a cohort and the reports print `—`.

## Engagement and the wedge ratio

Three numbers, reported by `manage.py retention_report`:

1. **Assistant turns per active household per week.**
2. **Receipts confirmed per week.**
3. **The AI-captured : manually-entered ratio** — the one S14-3 calls the most
   important number in the product.

The ratio is computed from `entry_created` events, grouped by `metadata.source`:

| Source | Counts as | Why |
|---|---|---|
| `receipt` | AI-captured | The wedge itself. |
| `chat` | AI-captured | Still a capture the user did not type into a form. |
| `form` | Manually typed | The thing a spreadsheet already does. |
| `import` | **Excluded from the ratio** | A CSV backfill is migration, not capture behaviour, and one import of two thousand rows would swamp every real signal. Emitted once per *run*, not per row, for the same reason. |

If people are typing entries rather than photographing receipts, the wedge is not
landing. That is the stop condition in [`ga-criteria.md`](ga-criteria.md).

## Edge cases, decided

**An invited member's auto-created household does not count as a signup.**
`accounts/signals.py::create_household_for_new_user` mints a household on every
signup, including for a user who then joins someone else's. Counting those as
failed signups understates activation for exactly the users an invite flow
brings in. Such a household is excluded from both the numerator and the
denominator when all three hold: it has exactly one membership, its sole member
also holds a membership in a *different* household, and it has no `activated`
event. All three — a legitimate solo household must not be excluded because the
owner happens to be in a second one. `core.metrics.excluded_shadow_households`
implements this, and every report prints how many it dropped.

**A household that returns on day 9 is D7-retained.** See *Retenção* above.

## Every event the funnel emits

In funnel order. "Once" means the event carries `once=True` and is covered by the
`one_once_event_per_household` partial unique index — the database, not a
convention, enforces it.

| Event | Once? | Fires when | `metadata` |
|---|---|---|---|
| `signup` | yes | A new account gets its own household (`accounts/signals.py`). The funnel's T0. | — |
| `email_verified` | yes | allauth's `email_confirmed` fires for the household's owner. `emit_once`, because re-confirming an address would otherwise report more verifications than signups. | — |
| `household_seeded` | yes | Starter categories and payment methods are in place (`accounts/starter_data.py`). | — |
| `onboarding_step` | no | Each guided-setup step is marked (`accounts/onboarding.py`). Repeats by design — it is the per-step drop-off. | `{"step": …, "action": …}` |
| `onboarding_done` | yes | The last guided-setup step completes. | — |
| `receipt_photo` | no | A photo extracts successfully and a `ReceiptDraft` is created (`assistant/views.py`). **Counted, not once**: photos taken against receipts committed *is* the extraction failure rate, and it separates "nobody tried the wedge" from "the wedge did not work" — opposite problems with opposite fixes. | `{"needs_review": bool}` |
| `first_ai_entry` | yes | The household's first assistant-captured entry, receipt or chat. | `{"source": "receipt"\|"chat"}` |
| `activated` | yes | A photographed receipt is confirmed into the ledger. The moment the product exists for. | `{"lines": int}` |
| `entry_created` | no | **Every** entry write, at all four paths. The only event that counts, and the one the wedge ratio is a GROUP BY over. | `{"source": "receipt"\|"chat"\|"form"\|"import"}`, plus `{"count": int}` for `import` |

## LGPD

This instrumentation is **first-party and server-side**, writes no user content,
and identifies a household rather than a person. `ProductEvent.metadata` carries
counts, ids and enum values only — the same discipline as
`core.observability.scrub_event`, and for the same reason: this table is read by
operators and exported by E13.

On that basis it **proceeds under legitimate interest** (E14 open question 4),
and it goes on E13's processing inventory as a processing activity. E13 owns the
privacy notice; this document owns the fact that there is something to notice
about.

`core.models.Feedback` is separate and deliberately different: it stores
user-authored text on purpose, which is precisely why it is not a `ProductEvent`.
It is inventoried separately.

## No vendor

Every number here is computed from Postgres. Adding an analytics vendor would put
another sub-processor on E13's inventory and another PII surface in the product,
for numbers this database already holds — and a vendor's pipeline cannot
recompute history when a definition changes, which is the one thing this document
guarantees will eventually happen (E14 open question 1, and Out of scope).
