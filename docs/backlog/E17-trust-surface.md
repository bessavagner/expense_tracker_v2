---
id: E17
title: "Trust surface: audit, error UX & landing"
release: R4
status: ready
depends_on: [E11]
blocks: []
wedge_critical: false
---

# E17 · Trust surface: audit, error UX & landing

## Outcome

A stranger arriving at Ledger understands what it is and why it is different within seconds; a user can see where every entry in their ledger came from; and when something goes wrong they get an honest, actionable message instead of a generic apology.

## Why now

The launch standard names *trust safeguards* as a foundation requirement, alongside the core workflow and analytics. For a product that holds a family's money records and lets an AI write to them, trust is not a marketing layer — it is a feature.

Three related gaps, grouped because they share one theme:

- **Provenance** (review **M5**): you cannot tell whether an entry was created by a person, the agent, or a CSV import. For an AI-writes-to-your-ledger product, that is the single most reasonable question a cautious user will ask.
- **Error UX**: failures currently produce generic messages that neither explain nor guide.
- **Discovery**: there is no page that explains the product to someone who has not already been sold on it.

## Evidence in the codebase

| What | Where |
|---|---|
| `created_by` — provenance groundwork delivered by E04 | E04 S04-3 |
| Entry has no field distinguishing how it was created | `finances/models/entry.py` |
| `ChatMessage.metadata` exists and is unused | `assistant/models.py` |
| The mutating-tool list the agent can invoke | `assistant/views.py:24-28` |
| Generic error message on any agent failure | `assistant/views.py:104-107` — `"Erro ao processar mensagem. Tente novamente."` |
| Transcription failure message | `assistant/views.py:220-222` |
| Unreadable-receipt message — a good example already | `assistant/views.py:338-341` |
| Import errors counted, never explained to the user | `finances/views/importer.py:363-364` — improved in E12 |
| Empty-state component to build on | `src/backend/frontend/src/components/EmptyState.tsx` |
| Existing PWA and TWA delivery | `core/views.py` — manifest, service worker, asset links |
| The dashboard screenshot that already sells the product | `docs/images/dashboard.png` |

## Stories

### S17-1 · Visible provenance on every entry

- **Given** `created_by` exists after E04, and the source of an entry is not recorded
- **When** provenance is completed
- **Then** every entry records how it was created — manual form, assistant conversation, receipt photo, CSV import, or systematic posting
- **And** the entry detail and edit views show the source and who created it, in plain pt-BR
- **And** an AI-created entry can be traced back to the conversation that produced it
- **And** existing entries are back-filled with the best available inference, and rows where the source is genuinely unknown say so rather than guessing

> This directly serves the wedge. The objection to an AI that writes to your ledger is "how do I know what it did?" Provenance is the answer, and it is nearly free given E04 already adds `created_by`.

### S17-2 · Honest, actionable error messages

- **Given** the generic failure message at `assistant/views.py:104-107`
- **When** error handling is reviewed
- **Then** the failures a user can actually encounter are distinguished: provider unavailable, quota exhausted, unreadable receipt, unsupported audio format, network interruption
- **And** each says what happened and what to do next, in pt-BR
- **And** none of them expose internal detail or a stack trace
- **And** the unreadable-receipt message at `assistant/views.py:338-341` is the model to follow — it already explains and offers a next step
- **And** a failure that loses user input (a voice note, a photo) says so plainly rather than failing silently

### S17-3 · A landing page

- **Given** nothing explains the product to someone who has not seen it
- **When** the landing page exists
- **Then** it leads with the wedge — photograph a receipt, get itemized, categorized entries — because that is the differentiator against auto-sync incumbents
- **And** it is honest about what Ledger does **not** do: no automatic bank sync (INDEX §2). Setting that expectation up front prevents the most predictable churn there is
- **And** it explains the privacy posture that is already true: media processed and discarded, data in Brazil
- **And** it links to the privacy notice and terms from E13
- **And** it works well on a phone, since that is where the product is used
- **And** it states the price once E15 has set one

> Do not let this page make claims the product does not honour. This project's README is already accurate and specific; hold the landing page to the same standard.

### S17-4 · Support foundations

- **Given** E05 deliberately deferred impersonation rather than handing out Django admin
- **When** support tooling is built
- **Then** a support view exists showing a household's subscription, usage, and recent errors — **without** exposing entry descriptions or chat content
- **And** if impersonation is implemented, it requires explicit user consent, is time-limited, and every session is logged with actor, target, and reason
- **And** a support contact channel exists and is reachable from inside the product
- **And** the LGPD data-subject-request procedure from E13 is linked from the support tooling, so a request arriving through support is handled correctly

### S17-5 · Polish the surfaces a stranger judges you by

- **Given** a paid product is judged on details a personal tool is forgiven for
- **When** the polish pass runs
- **Then** loading states exist wherever data is fetched, so the app never appears frozen
- **And** the PWA install prompt and offline fallback are verified end to end
- **And** the app has been checked on a real phone across the primary flows, not only in a desktop browser
- **And** basic accessibility is checked on the core flows — contrast, focus order, and labels
- **And** the dashboard, entries, cockpit, and chat are reviewed for anything that reads as unfinished

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
cd src/backend/frontend && pnpm build
```

Observable assertions:

- [ ] Every entry shows its source and creator; existing entries are back-filled or honestly marked unknown
- [ ] An AI-created entry links back to its originating conversation
- [ ] Each distinguishable failure mode has its own actionable pt-BR message, verified by test
- [ ] The landing page states plainly that there is no automatic bank sync
- [ ] Every factual claim on the landing page has been checked against the implementation
- [ ] The support view exposes no entry descriptions or chat content, asserted by test
- [ ] Impersonation, if built, requires consent, expires, and is logged
- [ ] Primary flows verified on a real phone
- [ ] Accessibility checked on the core flows

## Out of scope

- A full marketing site, blog, or SEO programme — one honest landing page is the MVP requirement
- A help centre or documentation site — a support channel suffices at beta scale
- A design system refactor — DaisyUI conventions already exist; follow them
- Referral and growth mechanics — post-GA
- Redesigning the dashboard, which already works

## Open questions

1. **Where does the landing page live** — the same Django app at `/`, or separate hosting? Same app is simpler and keeps the domain unified; separate hosting decouples marketing changes from deploys.
2. **Is impersonation needed at MVP?** It is the highest-risk item in the epic. If support can be handled without it, defer it and keep the risk off the table.
3. **How far back can provenance be inferred** for existing entries? Import-created entries may be identifiable by pattern; others may not. Marking unknown honestly is better than a confident wrong label.
4. **What accessibility standard applies?** No legal requirement forces a specific level here, but core flows should be usable with a screen reader. Pick a pragmatic bar and meet it.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1 and 2 are scope decisions
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `frontend-design` — for the landing page and the polish pass
5. `superpowers:test-driven-development`
6. `superpowers:subagent-driven-development`
7. `oh-my-claudecode:visual-verdict` — verify the landing page and core flows render correctly across viewports
8. `superpowers:requesting-code-review`
9. `/security-review` — **only if impersonation is built**; it is a deliberate authorization bypass and must be reviewed as one
10. `superpowers:verification-before-completion`
11. `superpowers:finishing-a-development-branch`
