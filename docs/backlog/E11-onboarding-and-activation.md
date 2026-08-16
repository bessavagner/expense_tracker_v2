---
id: E11
title: Onboarding & activation
release: R3
status: done
depends_on: [E05]
blocks: [E14, E17]
wedge_critical: true
---

# E11 · Onboarding & activation

## Outcome

A stranger who signs up reaches the product's core moment — a photographed receipt correctly in their ledger, split by category, in the right billing month — without help, without reading documentation, and without an empty screen that tells them nothing.

## Why now

The industry launch standard is unambiguous: an MVP needs **one core workflow, a defined activation event, and three to five onboarding steps maximum**. Ledger currently has none of these, because it never needed them — its only user built it.

Wedge-critical because it is where the wedge either lands or doesn't. Receipt OCR and conversational capture are the differentiator (PD-1), and a differentiator a new user never discovers is worth nothing. Incumbents win the first session by auto-importing transactions; Ledger has to win it by making one photograph feel like magic.

## Evidence in the codebase

| What | Where |
|---|---|
| Seed data exists but is a developer command, not a user flow | `finances/management/commands/seed_data.py`, `seed_qa_data.py` |
| Category rules seeding exists for the assistant | `assistant/management/commands/seed_category_rules.py` |
| A new household has no categories, so entry creation fails at the first step | `Entry.category` is `on_delete=PROTECT` and required — `finances/models/entry.py:23` |
| Payment methods are equally required, with closing-day semantics that need explanation | `finances/models/payment_method.py`, `payment_method_closing_day.py` |
| An empty-state component exists to build on | `src/backend/frontend/src/components/EmptyState.tsx` |
| Dashboard cards assume data exists | `src/backend/frontend/src/cards/*.tsx` |
| The chat widget is the wedge's entry point | `src/backend/frontend/src/cards/ChatWidget.tsx` |
| The projection has a configured origin month that a new user will not understand | `config/settings.py:196` — `PROJECTION_ORIGIN_MONTH` |

## Stories

### S11-1 · Define and instrument the activation event

- **Given** an MVP needs one defined activation event
- **When** it is chosen
- **Then** the activation event is stated explicitly in this repo and is a single observable moment
- **And** the recommendation is: **the user has confirmed a receipt photo into their ledger**, because it is the wedge, it proves value immediately, and it requires the user to have completed setup as a side effect
- **And** the event is emitted so E14 can measure it
- **And** time-to-activation is measurable per user

> Resist making activation "signed up" or "created an entry". Activation must be the moment the user experiences why this product is different from a spreadsheet.

### S11-2 · A new household is usable in under a minute

- **Given** a brand-new household has no categories and no payment methods, so it cannot record anything
- **When** the household is created
- **Then** it is seeded with a sensible default set of Brazilian categories and common payment method types
- **And** the seeded categories match the assistant's category-rule seeding, so the AI works immediately rather than after manual setup
- **And** every seeded item is editable and deletable — defaults are a starting point, not a cage
- **And** seeding is idempotent and covered by test

### S11-3 · Three-to-five-step guided setup

- **Given** the onboarding standard of three to five steps
- **When** a user first logs in
- **Then** they complete a short guided flow: confirm income, confirm the cards they use and their closing days, then take a photo
- **And** each step is skippable, and skipping does not break the product
- **And** progress is saved, so an interrupted setup can be resumed
- **And** the credit-card closing-day concept is explained in one plain sentence, because it is unfamiliar even to Brazilian users and it silently determines which month every credit purchase lands in
- **And** the flow ends by handing the user directly to the activation moment, not to an empty dashboard

### S11-4 · Empty states that teach

- **Given** every dashboard card and list renders against no data on day one
- **When** a surface has no data
- **Then** it explains what will appear there and offers the single action that fills it
- **And** the dashboard's empty state points at the wedge — photograph a receipt — rather than at manual entry
- **And** empty states are checked across the dashboard, entries, cockpit, projection, consolidated, and settings

### S11-5 · First-run assistant behaviour

- **Given** the assistant is the wedge and a new user does not know what to say to it
- **When** they open the chat for the first time
- **Then** it opens with a concrete invitation demonstrating what it can do, in pt-BR, with real examples ("me manda uma foto do cupom" / "gastei 45 no mercado no crédito")
- **And** the first interaction does not require the user to already know the category or payment-method names
- **And** the assistant's existing name-lenient resolution is exercised rather than bypassed

### S11-6 · The import path for users with history

- **Given** a user arriving from a spreadsheet or another app has months of history
- **When** they onboard
- **Then** the CSV importer is discoverable during setup, not buried in a menu
- **And** it is presented as optional — a user with no history must not feel blocked

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
cd src/backend/frontend && pnpm build
```

Observable assertions:

- [x] The activation event is documented in this repo and emitted as a measurable event — `docs/architecture/activation-event.md`; emitted from `assistant/agents/tools.py::commit_receipt`; `assistant/tests/test_activation_event.py`
- [x] A brand-new household can record an entry with zero manual setup — `accounts/tests/test_starter_data.py::TestSignupSeeds`
- [x] Seeded categories align with the assistant's category rules, verified by test — `test_every_starter_memory_rule_targets_a_starter_category`, which reads both lists from independent modules
- [x] Guided setup is at most five steps, every one skippable, progress resumable — `accounts/tests/test_onboarding_flow.py`, `test_onboarding_state.py`; three steps against a ceiling of five
- [x] Every listed surface has a purposeful empty state — `finances/tests/test_empty_states.py` covers dashboard, entries, cockpit, projection, consolidated and settings
- [x] **An unaided walkthrough has been done by a real person who has not seen the product**, from signup to activation, and their friction points are recorded — done 2026-08-16, **with one hint given**, see ¹
- [x] The walkthrough was performed on a phone, since the product ships as a PWA and Android TWA — Android, Chrome, PWA installed from the LAN address
- [x] Time from signup to activation is measurable — `manage.py activation_report`, `core/tests/test_activation_report.py`

¹ **The walkthrough happened on 2026-08-16 and the wedge landed.** A
first-time user on an Android phone went from the guided setup appearing to a
photographed supermarket coupon correctly in the ledger in **83 seconds**,
filling in every step rather than skipping any: income R$ 3.000, card `Banco do
Brasil` closing day 25, then the photo. One coupon became three entries across
Alimentação, Casa and Limpeza, split correctly. `activation_report` measured 21
minutes end to end and is right — the other ~19 were a blocked verification
email, not product friction. Full record with timestamps:
`docs/superpowers/evidence/e11-walkthrough/README.md`.

**One hint was given, so "unaided" is qualified.** `EMAIL_HOST` was empty in the
local `.env`, so the verification message went to the console backend instead of
a mailbox and the participant was handed the confirmation link. Everything from
the guided setup onward was unaided. Two consequences: the run does **not**
answer E05's open question about whether a mandatory-verification wall costs
activation for someone waiting on real email, and the **skip paths remain
unexercised by a human** — they completed every step.

**The walkthrough found a wedge-critical defect, filed as [D05](D05-a-backdated-receipt-activates-into-an-invisible-month.md).**
The coupon was dated 2023-06-04, so the entries filed correctly into
`billing_month 06/2023` — and the dashboard shows the current month, so a
successful activation looked like nothing had happened. 114 seconds later the
participant hand-created a second entry in the current month that nobody asked
for. The date logic is correct and must not change; what is missing is telling
the user where the receipt went. That is exactly the *"empty screen that tells
them nothing"* this epic's Outcome forbids, so E11 closes having proved the
wedge works and having found the one thing that makes it look like it doesn't.

Of the three gaps flagged in advance, none surfaced: no 390px layout problem
appeared in the timings, the projection window did not come up, and the chat
history never failed. The `[observer]` sections of the record — friction quotes,
whether the closing-day sentence landed, and why that second manual entry
happened — are still blank and are worth filling in from memory while it is
fresh.

## Out of scope

- Measuring activation rate and retention over time → **E14**; this epic *emits* the event, E14 *analyzes* it
- Paywall and trial mechanics → **E15**
- Marketing landing page → **E17**
- In-app product tours or tooltip systems beyond the setup flow — YAGNI
- Redesigning the dashboard

## Open questions

1. **What exactly is the activation event?** S11-1 recommends confirmed-receipt. Confirm, because E14's entire measurement design follows from it.
2. **What is the default category set?** It should reflect real Brazilian household spending. The existing production data is the best available evidence — derive it from actual category usage rather than inventing a list.
3. **Is email verification required before onboarding starts?** Open question 3 in E05. Decide the two together — a verification wall before the magic moment costs activation.
4. **How is the closing-day concept explained** without a paragraph of text? This is a design problem, not a copy problem.

## Skill pipeline

1. `superpowers:brainstorming` — **required**; open questions 1 and 2 define what gets built
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `frontend-design` — this is the first impression of the product; generic output undercuts the wedge
5. `superpowers:test-driven-development`
6. `superpowers:subagent-driven-development`
7. `oh-my-claudecode:visual-verdict` — verify the flow renders correctly on a phone viewport
8. `superpowers:requesting-code-review`
9. `superpowers:verification-before-completion` — the unaided walkthrough is the evidence; a passing test suite is not sufficient for this epic
10. `superpowers:finishing-a-development-branch`
