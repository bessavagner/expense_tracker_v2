---
id: E15
title: Billing & subscription
release: R4
status: blocked
depends_on: [E07, E13, E18]
blocks: []
wedge_critical: false
---

# E15 · Billing & subscription

## Outcome

A Brazilian household can subscribe in BRL by Pix or card, is charged correctly and repeatedly, understands what they are paying for, and can cancel without contacting anyone — and a failed payment is recovered rather than silently ending the relationship.

## Why now

Decision **PD-3**: free capped beta, paid at GA. This epic is the transition.

It depends on **E07** because you cannot price what you cannot measure — E07's p50/p90/p99 cost per household is the input to the price. It depends on **E13** because charging for a service holding financial data requires a lawful basis, a privacy notice, and terms that cover payment and termination.

## Market context

From research on 2026-08-07: **Mobills charges R$119,90/year** (~R$10/month) with Open Finance auto-sync across 200+ institutions; Organizze is roughly 30% more expensive annually. Both include auto-sync in their paid tiers.

Ledger is not competing on automation (INDEX §2) and should not anchor on their price by default. The AI capture wedge is a different value proposition with a genuinely different cost base — E07's measured cost per household is the floor, and the price must clear it with margin.

## Evidence in the codebase

| What | Where |
|---|---|
| No billing of any kind | no payment integration anywhere in `src/backend` |
| Household — the natural billing unit | `accounts` app, from **E04** |
| Plan allowances, enforced but not charged | **E07** S07-4 |
| Cost per household — the pricing input | **E07** S07-5 |
| The quota chokepoint a paywall must reuse | **E07** S07-3 |
| Terms covering payment and termination | **E13** S13-4 |
| Task infrastructure for webhooks and dunning | **E10** |

## Stories

### S15-1 · Choose the provider and model the domain

- **Given** Brazilian consumers expect Pix, and card is table stakes for recurring charges
- **When** the provider is chosen
- **Then** the decision is recorded with its reasoning — Stripe's Pix support is narrower than a Brazilian PSP's; Pagar.me, Asaas, and Iugu are the local alternatives
- **And** `Plan` and `Subscription` models exist, with the subscription belonging to a household
- **And** subscription state covers at minimum: trialing, active, past due, canceled, and expired
- **And** the domain model is provider-agnostic enough that the provider is replaceable without a data migration

> Pix recurrence deserves specific attention. Pix Automático exists as of the 2025-2026 Central Bank agenda, but provider support varies. If recurring Pix is not viable, the fallback is card for recurring plus one-off Pix for annual — and that shapes the pricing structure, so settle it early.

### S15-2 · Subscribe, upgrade, cancel

- **Given** a household on the free beta
- **When** they subscribe
- **Then** they can do so in-product, in BRL, by Pix or card
- **And** they can cancel without contacting support, and cancellation is honoured at the end of the paid period rather than immediately destroying access
- **And** they can see their current plan, renewal date, and payment method
- **And** invoices or receipts are available for download
- **And** the transition from beta to paid is handled explicitly for existing beta households — with notice, not a surprise

### S15-3 · Enforce entitlements at the existing chokepoint

- **Given** E07 built a single quota chokepoint
- **When** paid entitlements are added
- **Then** the plan's allowances flow through **that same chokepoint** — no second enforcement path
- **And** an expired or past-due subscription degrades access according to a decided policy, applied consistently
- **And** the user's own financial data remains accessible even when the subscription lapses, because holding a person's financial records hostage is not defensible
- **And** export (E12/E13) remains available regardless of subscription state

> This is the ethical line in the epic. Ledger may stop providing AI capture to a lapsed subscriber. It must not lock them out of the record of their own money.

### S15-4 · Webhooks and reconciliation

- **Given** payment state changes happen at the provider
- **When** webhooks are handled
- **Then** signatures are verified, handlers are idempotent, and out-of-order delivery does not corrupt subscription state
- **And** a reconciliation job detects divergence between local state and the provider's, because webhooks are lost in practice
- **And** webhook failures reach the error tracker

### S15-5 · Dunning, tested end to end

- **Given** the launch standard requires billing and dunning tested end to end before going live
- **When** a payment fails
- **Then** the customer is notified and given a clear path to fix it
- **And** retries follow a defined schedule before the subscription lapses
- **And** the entire sequence — failure, notification, retry, recovery, and lapse — has been exercised in the provider's sandbox
- **And** an involuntary lapse is distinguishable from a deliberate cancellation in the data

### S15-6 · Set the price on evidence

- **Given** E07's measured cost and E14's engagement data
- **When** the price is set
- **Then** the decision is recorded with the numbers behind it: cost per household at p50/p90/p99, the intended gross margin, and the competitive context
- **And** the price clears the p90 cost with margin — not the p50, because a price that only works for median users loses money on the tail that LLM spend distributions are known to produce
- **And** the plan structure is recorded, including whether AI capture is metered separately or bundled with a generous allowance

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Observable assertions:

- [ ] A real end-to-end subscription completes in the provider's sandbox, by both Pix and card
- [ ] Cancellation works in-product and is honoured at period end
- [ ] Webhook handlers verify signatures and are idempotent, asserted by test
- [ ] Out-of-order webhook delivery does not corrupt state, asserted by test
- [ ] The reconciliation job detects a deliberately introduced divergence
- [ ] The full dunning sequence has been exercised in sandbox
- [ ] A lapsed subscriber can still read and export their own financial data, asserted by test
- [ ] Entitlements flow through E07's chokepoint — `grep` proves no second enforcement path
- [ ] The pricing decision is recorded with the cost evidence behind it
- [ ] `docs/runbook.md` covers refunds, manual subscription fixes, and investigating a failed payment

## Out of scope

- Multiple currencies — Brazil only (INDEX §10)
- Annual versus monthly plan proliferation — start with the simplest structure that works
- Coupons, referrals, affiliate programs — post-GA growth work
- Invoicing for businesses, `nota fiscal` — consumer product; revisit only if a B2B need appears
- Tax handling beyond what the provider does — get accounting advice separately

## Open questions

1. **Which provider?** The open decision D3 from the architecture review. Pix support quality is the deciding factor, not API elegance.
2. **Is recurring Pix viable** with the chosen provider, or is card the only recurring option? Determines the plan structure.
3. **What is the price?** Answerable only after E07 and E14 produce data. Do not set it earlier.
4. **What happens to a lapsed subscriber's data over time?** Read-only forever is generous and cheap at this data size. Decide, state it in the terms, and honour it.
5. **Is there a trial, and is it time-limited or usage-limited?** A usage-limited trial aligns better with the actual cost structure.

## Skill pipeline

1. `superpowers:brainstorming` — **required**; open questions 1, 2, and 5 determine the domain model
2. `pm-product-strategy:pricing-strategy` — for S15-6, grounded in E07's real cost data rather than in category benchmarks alone
3. `superpowers:writing-plans`
4. `superpowers:using-git-worktrees`
5. `superpowers:test-driven-development`
6. `superpowers:subagent-driven-development`
7. `superpowers:requesting-code-review`
8. `/security-review` — **mandatory**; webhook verification and entitlement bypass are both exploitable
9. `superpowers:verification-before-completion` — sandbox transaction evidence required, not just green tests
10. `superpowers:finishing-a-development-branch`
