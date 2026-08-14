---
id: E13
title: LGPD compliance
release: R3
status: blocked
depends_on: [E12, E18]
blocks: [E15]
wedge_critical: false
---

# E13 · LGPD compliance

## Outcome

Ledger can lawfully hold Brazilians' financial data: users can see, correct, export, and delete their data; retention is bounded rather than infinite; the privacy notice states what is actually true; and a data-subject request can be fulfilled inside the legal deadline.

## Why now

Review finding **M4**. There is currently no export, no deletion, no privacy policy, no terms, and no retention limit — verified by grep. Chat history is retained indefinitely and transmitted to OpenAI.

This is not a "nice for later" item once money changes hands. It blocks **E15** deliberately: charging Brazilian consumers for a service holding their complete financial history plus LLM-derived inferences about their spending, with no lawful-basis statement and no deletion path, is the kind of gap that ends a product rather than fining it.

## Legal requirements this epic must satisfy

Researched 2026-08-07. **Confirm with a Brazilian lawyer before launch — this is engineering input, not legal advice.**

| Requirement | Detail |
|---|---|
| Data subject rights | Access, correction, anonymization, deletion, and **portability** |
| Response deadline | **15 days** from request |
| Breach notification | **72 hours** |
| Privacy policy contents | Controller identity, DPO contact, and purposes of processing — at minimum |
| DPO | Required for controllers, but **ANPD exempts small businesses and startups**. Ledger likely qualifies — a contact channel is still required |
| Lawful basis | LGPD defines ten. A personal finance manager is not credit provision, so the credit exemption does not apply; consent or legitimate interest must be identified per purpose |
| Penalties | Up to 2% of Brazilian revenue, capped at R$50 million per violation |

## Evidence in the codebase

| What | Where |
|---|---|
| No export, deletion, policy, or terms | grep across `config`, `core`, `finances`, `assistant`, `templates` → zero hits |
| Chat retained indefinitely, no TTL, no purge command | `assistant/models.py` — `ChatMessage` |
| Chat content is sent to OpenAI | `assistant/views.py:94-101` |
| History window is a display limit, not a retention policy | `config/settings.py:177` — `ASSISTANT_MAX_HISTORY` |
| Deleting a user cascades the entire ledger with no export gate | `finances/models/entry.py:17` — `on_delete=CASCADE` |
| Privacy-by-default already true for media — a genuine head start | `assistant/views.py:288` — images processed then discarded; audio likewise |
| LLM-derived inferences persisted about the user | `assistant/models.py` — `MemoryRule`, `MemoryEmbedding` |
| Export machinery to build on | **E12** S12-4 |

## Stories

### S13-1 · Account and household deletion

- **Given** the right to deletion
- **When** a user requests it
- **Then** they are offered an export first, because deletion is irreversible and their financial history is not recoverable
- **And** deletion removes personal data across all models, including chat history, memory rules, and embeddings
- **And** the household case is handled explicitly: what happens to shared data when one member of a two-person household leaves, and what happens when the last owner leaves (E04 open question 3, E05 open question 4)
- **And** anything retained for legal or accounting reasons after deletion is documented and justified, not retained by accident
- **And** deletion is confirmed to the user and completes within the legal deadline
- **And** a test asserts no personal data survives deletion

### S13-2 · Access, correction, and portability

- **Given** the rights to access, correction, and portability
- **When** a user exercises them
- **Then** export from E12 S12-4 is reachable from the account UI without contacting support
- **And** the data shown is complete — including the memory rules and inferences the assistant has formed about them, which users have a right to see and are likely to find surprising
- **And** correction is possible for everything a user can see
- **And** a documented operator procedure exists for fulfilling a request that arrives by email, with the 15-day deadline stated

### S13-3 · Bounded retention

- **Given** indefinite retention of chat content is not defensible
- **When** a retention policy is set
- **Then** chat messages are purged after a defined period, implemented as a scheduled job
- **And** the period is stated in the privacy notice and is the shortest that keeps the product working — note that assistant context uses only the last `ASSISTANT_MAX_HISTORY` messages, so long retention buys little
- **And** receipt drafts, usage records, and import files each have a stated retention period
- **And** the purge job is tested and its execution is observable

### S13-4 · Privacy notice and terms that are true

- **Given** the policy must state what actually happens
- **When** it is written
- **Then** it names the controller, gives a data-protection contact, and states the purpose of each category of processing
- **And** it discloses that content is sent to an LLM provider for processing, which provider, and that voice and image media are processed and immediately discarded
- **And** it states the lawful basis for each purpose
- **And** it states retention periods matching what S13-3 actually implements
- **And** it is written in Portuguese, for the users who must understand it
- **And** terms of service exist covering the service, payment (forward-looking to E15), and termination
- **And** both are versioned, and acceptance is recorded at signup

> The failure mode here is a generic template that describes a product this is not. Every claim must match the implementation. If the policy and the code disagree, the code is the violation.

### S13-5 · Breach response readiness

- **Given** a 72-hour notification deadline
- **When** a breach occurs
- **Then** a documented procedure exists in `docs/runbook.md`: how to assess scope, who to notify, in what order, and within what deadline
- **And** it identifies what logging and audit data would be needed to determine scope — and confirms that data is actually being collected (E06, and `created_by` from E04)
- **And** the procedure has been walked through once as a tabletop exercise, not merely written

### S13-6 · Sub-processor and data-flow inventory

- **Given** the LLM provider, email provider, error tracker, and hosting all process personal data
- **When** the inventory is made
- **Then** every third party receiving personal data is listed with what it receives and why
- **And** the error tracker's PII scrubbing (E06 S06-1) is verified against this inventory, not assumed
- **And** the inventory is kept with the privacy notice so both stay consistent

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Observable assertions:

- [ ] A user can export and then delete their account entirely from the UI
- [ ] A test asserts no personal data survives deletion, parameterized across every model holding personal data
- [ ] Household deletion edge cases are implemented and tested
- [ ] The chat purge job runs on schedule and is tested
- [ ] The privacy notice's every factual claim has been checked against the implementation
- [ ] Signup records acceptance of a specific policy version
- [ ] `docs/runbook.md` contains the data-subject-request procedure with the 15-day deadline and the breach procedure with the 72-hour deadline
- [ ] The breach tabletop exercise has been run once
- [ ] The sub-processor inventory exists and matches the error tracker's scrubbing configuration
- [ ] **A Brazilian lawyer has reviewed the privacy notice and terms** — this cannot be satisfied by engineering alone

## Out of scope

- Charging money → **E15**; this epic makes charging *lawful*, it does not implement it
- SOC 2, ISO 27001, or other voluntary certifications
- GDPR — no EU users at MVP; the architectures are similar if that changes
- Building the export machinery → **E12**; this epic consumes it

## Open questions

1. **What is the lawful basis for each purpose?** Consent for the AI processing, legitimate interest for core bookkeeping, is a plausible split — needs legal confirmation.
2. **Does Ledger qualify for the ANPD small-business DPO exemption?** Likely yes. Confirm, and provide a contact channel regardless.
3. **What is the chat retention period?** Shorter is safer and cheaper. Given the assistant only uses the recent window, a short period costs the product little.
4. **What happens to shared household data when one member deletes their account?** Their personal data must go; the household's shared financial history may legitimately remain for the other member. This needs a clear, defensible rule.
5. **Is a DPA needed with OpenAI or the chosen LLM provider,** and does the provider's data-retention policy conflict with what the privacy notice promises?

## Skill pipeline

1. `superpowers:brainstorming` — **required**; open questions 1, 3, and 4 are policy decisions with real implementation consequences
2. `pm-toolkit:privacy-policy` — drafting the notice; then verify every claim against the implementation
3. `superpowers:writing-plans`
4. `superpowers:using-git-worktrees`
5. `superpowers:test-driven-development`
6. `superpowers:subagent-driven-development`
7. `superpowers:requesting-code-review`
8. `/security-review` — deletion completeness and export authorization are both security-relevant
9. `superpowers:verification-before-completion`
10. `superpowers:finishing-a-development-branch`
