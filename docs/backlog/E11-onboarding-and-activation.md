---
id: E11
title: Onboarding & activation
release: R3
status: review
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
- [ ] **An unaided walkthrough has been done by a real person who has not seen the product**, from signup to activation, and their friction points are recorded — **NOT DONE**, see ¹
- [ ] The walkthrough was performed on a phone, since the product ships as a PWA and Android TWA — **NOT DONE**, see ¹
- [x] Time from signup to activation is measurable — `manage.py activation_report`, `core/tests/test_activation_report.py`

¹ **The two unticked boxes are the same box, and they are the point of the
epic.** Everything a machine can check is green: 1787 tests, coverage 92%
against a gate of 80%, lint and format clean, migrations reversible and
rehearsed, and the frontend building. None of that is the evidence this epic
asked for. The DoD says in its own words that a passing suite is not sufficient
here — the evidence is a stranger reaching activation on a phone without help,
and no agent can be that stranger.

The protocol, the record to fill in, and a list of gaps already suspected from
the build are at `docs/superpowers/evidence/e11-walkthrough/`. Three things
worth knowing before running it: the guided setup was verified by tests and
type-checking but **never looked at on a 390px viewport**; a household created
in the current month loses the previous month from its default projection
window (correct, but it may read as missing data); and a failed chat-history
request renders a blank panel with no error, deliberately, because error UX is
E17's.

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
