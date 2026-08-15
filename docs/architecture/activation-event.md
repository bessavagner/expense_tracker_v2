# The activation event

**Decided:** 2026-08-15, in E11 (`docs/backlog/E11-onboarding-and-activation.md`, S11-1).
**Read by:** E14 (product analytics), E15 (the beta → GA decision).

## The event

> **A household is activated the first time it confirms a photographed receipt
> into its ledger.**

Emitted as `ProductEvent(name="activated", once=True)` from
`assistant.agents.tools.commit_receipt` — the single code path where an
extracted receipt becomes real `Entry` rows.

## Why this and not something easier to count

*Signed up* measures a form submission. *Created an entry* measures a
spreadsheet with extra steps. Neither is the moment the user learns why this
product is not the thing they already have.

Confirming a receipt is the wedge (PD-1), it is the thing incumbents with bank
feeds structurally cannot do, and it can only happen after the user has a
category, a payment method and a working chat — so it certifies setup as a side
effect rather than measuring it separately.

## Precise definition, for E14

| Question | Answer |
|---|---|
| Unit | The **household**, not the user. A second member joining an activated household does not activate it again. |
| Cardinality | At most one per household, enforced by a partial unique index (`one_once_event_per_household`). |
| T0 for time-to-activation | The household's `signup` event, not `User.date_joined`. |
| Does a manually typed entry count? | No. |
| Does a chat-captured entry count? | No — it emits `first_ai_entry` instead. |
| Does a CSV import count? | No. |
| What if the receipt is later deleted? | The event stands. It records that the moment happened. |

### An invited member's household is not the household they work in

`accounts/signals.py::create_household_for_new_user` runs on every
`user_signed_up`, invitation or not, and unconditionally creates a fresh
household for the new account with the new account as its owner — carrying
that household's own `signup` event. Accepting an invitation (`accounts/
invitations.py`) then adds a *second* `Membership`, to the inviter's household,
which is where the invitee actually works from then on.

So an invited user ends up in **two** households: their own, auto-created and
never used, and the inviter's, shared and active. This is pre-existing tenancy
behaviour (predates E11, unchanged by it) — not a decision this epic made, and
not one this task changes.

The consequence for measurement: the invitee's own household shows up in the
funnel as signed-up-but-never-activated forever, while the shared household
they actually use already has its own, older `signup` event from whoever
created it. `activation_report` (below) counts both households as ordinary
rows — it has no way to know they are linked, and does not try to. E14's S14-1
open question ("does an invited household member count as a separate
activation?") should be answered against this fact rather than guessed: the
invited member's *own* household will never activate, and counting it as a
failed signup understates the real activation rate for invited users.

## The companion event

`first_ai_entry` (also once per household) is emitted by **any** assistant write
path — `create_entry` from chat, and `commit_receipt`. Its `metadata.source` is
`"chat"` or `"receipt"`. E14 uses it for the AI-versus-manual ratio, which S14-3
calls the most important number in the product.

## Where the numbers come from

    uv run python src/backend/manage.py activation_report --days 30

See `docs/runbook.md`, "Onboarding & activation".
