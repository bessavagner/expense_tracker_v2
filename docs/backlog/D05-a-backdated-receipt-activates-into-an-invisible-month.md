---
id: D05
title: A backdated receipt activates the user into a month they are not looking at
release: R3
status: done
depends_on: [E11]
blocks: []
wedge_critical: true
---

# D05 · A backdated receipt activates the user into an invisible month

## Outcome

A user who photographs a receipt always sees where it landed, so a successful
first capture never looks like a failed one.

## Symptom

Found by E11's unaided walkthrough on 2026-08-16, by a first-time user on a
phone. Full record: `docs/superpowers/evidence/e11-walkthrough/README.md`.

The participant photographed a real supermarket coupon dated **2023-06-04**.
Everything worked: extraction read the date correctly, `propose_receipt` split
eleven items into three categories, `commit_receipt` wrote three entries and
emitted `activated`. Elapsed time from the guided setup to activation: **83
seconds**.

Then they looked at a dashboard with nothing on it, because the dashboard shows
the **current** month and the entries were filed in `billing_month = 06/2023`.

**114 seconds later they created a second entry by hand** — `Frutaria`,
R$ 100,00, current month — which nobody asked them to do. The most natural
reading is that the capture looked like it had failed and they retried a
different way.

## Root cause — not a bug in the date logic

`commit_receipt` (`assistant/agents/tools.py:617`) deliberately omits
`billing_month_override` and lets `Entry.save()` derive the billing month from
`date` + `payment_method`. That is correct and was itself a fix for a historical
"frozen billing_month" defect — see
`docs/superpowers/plans/` and the `backfill_billing_months` command.

Filing a receipt under its own date is right. Overriding it with today would
corrupt the billing month of every genuinely backdated receipt, which is the
exact bug this codebase already paid to fix once.

**The defect is that nothing tells the user where the entry went.** The
confirmation string returned by `commit_receipt` names the store, the date and
the total, but the user is looking at a dashboard, and the dashboard is silent
about months it is not showing.

This directly contradicts E11's stated Outcome — *"without an empty screen that
tells them nothing"* — on the one path E11 exists to make work.

## Why this is wedge-critical

PD-1 says receipt capture *is* the product. A first capture that succeeds but
appears to have done nothing teaches a new user that the wedge does not work.
It is worse than an error, because an error at least invites a retry with
information.

## Stories

### SD05-1 · The confirmation says which invoice it landed in

- **Given** a committed receipt whose billing month is not the current month
- **When** the assistant confirms it
- **Then** the confirmation says so in plain pt-BR — the invoice month, not
  only the purchase date
- **And** it offers the one action that shows it: a link to that month

### SD05-2 · The empty dashboard knows the ledger is not empty

- **Given** a household with entries, none of them in the month on screen
- **When** the dashboard renders
- **Then** its empty state distinguishes "you have recorded nothing" from
  "nothing in *this* month", and names the nearest month that has data
- **And** the wedge-pointing empty state from E11 S11-4 stays for the genuinely
  empty case

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Observable assertions:

- [x] Committing a receipt into a non-current billing month says which month, in the confirmation
- [x] A dashboard with data in other months does not claim the ledger is empty
- [x] Both are covered by test, with the clock frozen
- [x] The 2023 receipt from the walkthrough, replayed, produces a confirmation a stranger could act on

## Out of scope

- Changing how `billing_month` is derived. It is correct. This defect is about
  what the user is told, not where the row goes.
- A month-picker redesign → not this.
- Backfilling or moving the walkthrough's existing 06/2023 entries — they are
  correct where they are.

## Open questions — answered 2026-08-16

Kept rather than deleted: a question with a recorded answer is worth more than a
deleted one, and the next person to touch this will want the reasoning.

1. **Should a receipt older than some threshold prompt rather than commit
   silently?** **Yes, prompt — and it costs no extra turn.** `propose_receipt`
   already ends in "Confirma?", so the warning enriches the confirmation turn
   that existed rather than adding one. The threshold is not an age in days but
   a comparison: it fires only when the *prospective billing month is earlier
   than the current one*. A card purchase made today lands in M+1 or M+2 by
   design, and warning about that would nag on nearly every receipt — which is
   exactly how a real warning stops being read.
2. **Is the dashboard the right place, or the confirmation?** **Both**, because
   the spec has a story for each and they fail in different places. The
   confirmation is missed if the user looks away or scrolls the chat; the
   dashboard is where they actually go looking, and it is where the walkthrough
   participant was standing when they concluded the capture had failed. The
   redundancy is the point.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development`
4. `superpowers:requesting-code-review`
5. `superpowers:verification-before-completion`
6. `superpowers:finishing-a-development-branch`
