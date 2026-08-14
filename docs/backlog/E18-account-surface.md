---
id: E18
title: Account surface (Conta)
release: R3
status: ready
depends_on: [E05]
blocks: [E13, E15]
wedge_critical: false
---

# E18 · Account surface (Conta)

> **Design spec:** [`docs/superpowers/specs/2026-08-14-account-surface-design.md`](../superpowers/specs/2026-08-14-account-surface-design.md)
>
> The spec carries the decisions and their reasoning — D1 placement, D2
> structure, D3 hub-not-reimplementation, D4 email change, D5 2FA for all,
> D6 sessions deferred — plus the component table, data flows, and error
> handling. **Read it before planning.** The open questions below are already
> answered there; this epic does not need a brainstorming pass.

## Outcome

A user can see and change who they are — their name, their email address, their
password, their second factor — and who shares their household, from one page
in the product, in pt-BR, without ever being handed a bare allauth URL.

## Why now

R3's gate is "ready for strangers". E05 shipped email-as-identity, password
change, household membership, and TOTP — and gave none of it a product surface.
A beta user who mistypes their email at signup, or wants to change a password,
currently has no in-product path at all.

It lands **before E11** rather than inside it: E11 is wedge-critical and about
first-run, and account management is neither. It lands **before E15** because
deferring to R4 leaves the whole beta without account management, and E13's
export/delete arrives first with nowhere to live.

The decisive reason is the seam. E13 needs somewhere to put export and
deletion; E15 needs somewhere to put plan, invoices, and cancel. Building the
container once is cheaper than three epics each inventing an account page.

## Evidence in the codebase

Verified at `e5f08a4`.

| What | Where |
|---|---|
| Email display and logout already exist — this is *not* the gap | `templates/partials/_navbar.html:20-28` |
| Configurações exists but is **household money config only** — five HTMX tabs | `templates/settings/settings_page.html` |
| The tab idiom to copy exactly: shell + `hx-get` fragments into a target div | `templates/settings/settings_page.html:8-39` |
| Members page and its views, to be absorbed as a tab | `templates/accounts/members.html`, `accounts/views.py::MembersView` |
| `accounts` app already mounted at `/casa/` — no new include needed | `config/urls.py:62` |
| Existing account URL names to extend | `accounts/urls.py` |
| `CustomUser(AbstractUser)` → **`first_name` already exists, unused**; a display name costs zero migrations | `core/models.py:6-18` |
| `allauth.mfa` installed; `MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]` — the 2FA machinery works, it has no surface | `config/settings.py:47-51`, `config/settings.py:275` |
| Email is the sole login method, and unique — constrains the email-change design | `config/settings.py:242-244` |
| Enumeration prevention is on — the email-collision error must not be made friendlier | `config/settings.py:251` |
| Toast mechanism to reuse on save | `templates/base.html:30` (`show-toast` window event) |
| `allauth.usersessions` is **not** installed — hence S18 has no sessions story | `config/settings.py:47-51` |
| django-allauth 65.19.1 — supports `ACCOUNT_CHANGE_EMAIL` | `pyproject.toml` |

## Stories

### S18-1 · The Conta page, with Membros absorbed

- **Given** the drawer today offers `Configurações` (money) and `Membros da casa` (people)
- **When** the account surface ships
- **Then** `/casa/conta/` renders a tabbed shell — **Perfil · Segurança · Membros** — using the same idiom as `settings_page.html`: a shell whose tabs `hx-get` fragments into `#account-content`, first tab loaded by `hx-trigger="load"`
- **And** each tab fragment has its own URL and renders standalone
- **And** `MembersView`'s body is extracted to `templates/accounts/_members.html` so the tab and any full-page render share one template rather than diverging
- **And** the drawer entry `Membros da casa` is **replaced** by `Conta` — a net removal, not an addition
- **And** `/casa/membros/` permanently redirects to `/casa/conta/`
- **And** owner-only member removal and invitation revocation are still enforced — absorbing the page into a tab must not relax E05's permission checks

### S18-2 · A display name

- **Given** the product has no notion of a user's name anywhere, so housemates see each other's raw email address
- **When** the Perfil tab ships
- **Then** a user can set a name, stored in the already-existing unused `first_name` column — **no migration**
- **And** every place a person is rendered — the Membros list, pending invitations — shows the name, **falling back to the email when it is blank**
- **And** the fallback is the normal case on day one, since every existing account has a blank name — it is not an edge case

### S18-3 · Change the email address

- **Given** `ACCOUNT_UNIQUE_EMAIL = True` and email is the only login method
- **When** email change ships
- **Then** it uses allauth's `ACCOUNT_CHANGE_EMAIL = True` single-address flow — one address, changed by adding a temporary second that replaces the primary **once verified** — not a hand-rolled form and not allauth's multi-address manager
- **And** `account/email_change.html` is styled to the ledger theme, in pt-BR
- **And** the old address stays primary and usable until the new one is confirmed, so there is no window where the user cannot log in
- **And** a collision with an existing account is rejected **without confirming that the address is registered** — `ACCOUNT_PREVENT_ENUMERATION` must not be weakened for a friendlier message

### S18-4 · The Segurança hub

- **Given** password change and 2FA enrolment are security-critical flows that must not be reimplemented to look nicer (spec D3)
- **When** the Segurança tab ships
- **Then** it renders **status and links out** — password, and whether two-factor is active — rather than embedding the forms
- **And** allauth's own views run the flows, with `account/password_change.html` and the `mfa/*` templates styled to the ledger theme in pt-BR
- **And** TOTP enrolment and recovery codes are available to **every** user, not only staff
- **And** **E05's staff-admin-gate test still passes** — a staff user without TOTP is still redirected to enrolment before reaching admin
- **And** a staff user who deactivates 2FA loses admin access until they re-enrol; this is correct and is not special-cased

### S18-5 · Seams recorded for E13 and E15

- **Given** two later epics will add panels here
- **When** this epic closes
- **Then** E13 records that export and deletion land as a **Privacidade** tab on this page
- **And** E15 records that plan, invoices, payment method, and cancel land as a **Plano** tab on this page
- **And** neither epic invents its own account surface

### S18-6 · Backlog hygiene

- **Given** `INDEX.md` §4 is stale — it still lists E05 as `ready` and E11 as `blocked`
- **When** this epic closes
- **Then** E05 reads `done`, E11 reads `ready`, and E18 has a row
- **And** the dependency graph carries the `E05 → E18`, `E18 → E13`, and `E18 → E15` edges

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
cd src/backend/frontend && pnpm build
```

`makemigrations --check` must come back clean — S18-2 deliberately reuses an
existing column, so **any new migration in this epic is a design error worth
stopping for**.

Observable assertions:

- [ ] `/casa/conta/` renders three tabs; each fragment URL also renders standalone
- [ ] The drawer shows `Conta` and no longer shows `Membros da casa`
- [ ] `/casa/membros/` redirects to `/casa/conta/`
- [ ] A name saves and appears on the Membros list; a blank name falls back to the email — both asserted by test
- [ ] Changing the email leaves the old address primary until confirmation, asserted by test
- [ ] An email collision is rejected without enumerating, asserted by test
- [ ] A **non-staff** user can enrol and disable TOTP
- [ ] E05's staff-admin-gate test passes unchanged
- [ ] Login required and household scoping asserted on every new view
- [ ] Owner-only member removal and invitation revocation still enforced, asserted by test
- [ ] No new migration
- [ ] Every new or styled page renders in pt-BR, on a phone viewport
- [ ] E13 and E15 each name their future tab on this page

## Out of scope

- **Sessions / "sair de outros aparelhos"** — needs `allauth.usersessions`: a new app, migration, and middleware. Deliberately deferred (spec D6), not overlooked
- Avatars and profile images
- LGPD export and deletion → **E13**, as a Privacidade tab here
- Plan, invoices, cancel → **E15**, as a Plano tab here
- Social login
- Per-user timezone and currency — parked, `INDEX.md` §10
- Redesigning Configurações
- Deep-linkable tabs (`?tab=`) — the settings page does not do it either; E15 may revisit

## Open questions

**None.** All six decisions were settled in the design spec — placement (D1),
structure (D2), hub-not-reimplementation (D3), the email-change mechanism (D4),
2FA for all users (D5), sessions deferred (D6). Skip step 1 of the default
pipeline; the spec is the brainstorming output.

## Skill pipeline

Deviates from the `INDEX.md` §6 default at step 1 only.

1. ~~`superpowers:brainstorming`~~ — **skip**; done, see the spec
2. `superpowers:writing-plans` → `docs/superpowers/plans/YYYY-MM-DD-E18-account-surface.md`
3. `superpowers:using-git-worktrees`
4. `superpowers:test-driven-development`
5. `superpowers:subagent-driven-development`
6. **daisyUI Blueprint chain for all UI** — Setup Expert → Rules Enforcer → Component Syntax Expert → code → Quality Inspector. **Skip Creative Director and Page Architect**: this repo has a settled design direction. daisyUI 5 dropped `form-control`/`label-text` — use `fieldset`/`label`. `btn-accent` is the established action colour and the Inspector will flag it; that deviation is recorded and intentional
7. `oh-my-claudecode:visual-verdict` — phone viewport; this ships as a PWA and Android TWA
8. `superpowers:requesting-code-review`
9. `/security-review` — **mandatory.** This epic touches authentication surfaces. On E05 it found four real defects across two passes, three against the same control; one pass is not enough
10. `superpowers:verification-before-completion`
11. `superpowers:finishing-a-development-branch`
