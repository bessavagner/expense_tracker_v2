---
id: E05
title: Identity, invitations & admin isolation
release: R1
status: blocked
depends_on: [E04]
blocks: [E11]
wedge_critical: false
---

# E05 · Identity, invitations & admin isolation

## Outcome

A stranger can create an account, verify their email, log in, reset a forgotten password, and invite a partner into their household — without ever seeing Django admin. Staff access to customer financial data is gated and logged.

## Why now

Review finding **B1** and **ADR-007**. There is no signup, no verification, and no password reset anywhere in the codebase. The front door is `/admin/login/`, and `/admin/` is publicly routed on an `--allow-unauthenticated` Cloud Run service with every model registered — including `ChatMessage`, which holds every user's raw conversation.

Depends on E04 because invitations are invitations *to a household*. Building an invite flow before the household exists means building it twice.

## Evidence in the codebase

| What | Where |
|---|---|
| Admin login is the product's login | `config/settings.py:168` — `LOGIN_URL = "/admin/login/"` |
| Admin publicly routed | `config/urls.py:16` |
| Logout redirects back to admin login | `config/urls.py:15` |
| Every model registered in admin, incl. raw chat | `assistant/admin.py:6` (`ChatMessage`), `finances/admin.py` (8 registrations), `core/admin.py:7` |
| No auth flows exist | `grep -rniE 'signup\|register/\|password_reset\|allauth' src/backend/config src/backend/core` → zero hits |
| The user model to extend | `core/models.py` — `CustomUser(AbstractUser)` |
| Cloud Run is public | `docs/deploy/next-session-kickoff.md:62` — `--allow-unauthenticated` |
| Login throttling — added in E01, must survive the login move | see E01 S01-4 |

## Stories

### S05-1 · Self-service account lifecycle

- **Given** `django-allauth` (ADR-007)
- **When** identity flows are implemented
- **Then** a stranger can sign up with email and password, receives a verification email, and cannot use the product until verified
- **And** password reset works end to end via email
- **And** the flows are styled to match the existing DaisyUI design — allauth's default templates must not ship as-is
- **And** all user-facing copy is pt-BR, consistent with the rest of the product
- **And** password validators from `config/settings.py:129-134` still apply
- **And** signing up creates a `Household` and an owner `Membership` for the new user

### S05-2 · Transactional email infrastructure

- **Given** verification, reset, and invitation emails must actually arrive
- **When** email is configured
- **Then** a real email provider is configured via environment variables, with credentials in Secret Manager
- **And** SPF and DKIM are configured for the sending domain, because unverified financial-app email lands in spam
- **And** local development uses a console or file backend so no real mail is sent
- **And** a deliverability check has been performed against at least Gmail, since the target market is Brazilian consumers

### S05-3 · Household invitations

- **Given** a household owner
- **When** they invite someone by email
- **Then** the invitee receives an email with a single-use, expiring token
- **And** accepting it creates a `Membership` in that household
- **And** an invitee who has no account is taken through signup first, then joins
- **And** an owner can revoke a pending invitation and remove an existing member
- **And** a removed member immediately loses access to that household's data — asserted by a test
- **And** invitation tokens are not guessable and are invalidated on use

### S05-4 · Move the front door off Django admin

- **Given** the product now has real login
- **When** routing is updated
- **Then** `LOGIN_URL` points at the product login page and logout returns to a product page
- **And** `/admin/` is no longer the path any customer encounters
- **And** the login throttling from E01 S01-4 applies to the new login view — verified by test, since the view has moved

### S05-5 · Isolate and harden staff access

- **Given** admin holds every customer's financial records and chat history
- **When** admin is hardened
- **Then** `/admin/` is restricted at the infrastructure or middleware layer (Cloud Run IAM, IP allowlist, or equivalent) so it is not reachable from the open internet
- **And** staff accounts require a second factor
- **And** `ChatMessage` is either removed from admin or its content is redacted in list and detail views
- **And** staff access to customer data is logged with actor, target, and timestamp
- **And** a test asserts a non-staff authenticated user gets no admin access

> Support will eventually need to look at a customer's account. Resist building impersonation here — record it as a need for E17 and solve it deliberately, with consent and logging, rather than by handing out admin.

## Definition of Done

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g; print(g())") \
  ALLOWED_HOSTS=example.com ADMIN_URL_PATH=gestao-test/ uv run python src/backend/manage.py check --deploy
```

The third command needed `ADMIN_URL_PATH` adding: from S05-5 the admin mount
reads it, and the deploy check builds the URLconf.

Run on branch `e05-identity`: **1322 passed, 3 skipped**, coverage **91%**
(floor 80), ruff clean, `check --deploy` reports "System check identified no
issues". The suite is also time-stable — identical results under
`TEST_CLOCK_SHIFT=+1m` and `+1y`, which matters because this epic added
expiry logic.

Observable assertions:

- [x] End-to-end test: sign up → verify → log in → reset password → log in with the new password — `core/tests/test_account_lifecycle.py`
- [x] End-to-end test: owner invites → invitee signs up → both see the same ledger — `accounts/tests/test_invite_flow.py::TestBothSeeOneLedger`
- [x] Test: removed member loses data access immediately — `accounts/tests/test_membership_removal.py::test_a_removed_member_loses_data_access_on_the_very_next_request`
- [x] Test: invitation token is single-use and expires — `accounts/tests/test_invitations.py::TestRedeem`
- [x] Test: login throttling still applies at the new login URL — `core/tests/test_lockout_at_allauth_login.py`
- [x] Test: non-staff user cannot reach admin — `core/tests/test_admin_isolation.py`
- [x] **Manually verified: a real verification email arrives in a Gmail inbox** — done 2026-08-14, and by the strongest evidence available: a **real signup completed in production**. `bessavagner.dev@gmail.com` signed up at 11:27 UTC on revision `00044-2kq`, received "Confirme seu e-mail no Expense Tracker" from `Ledger <nao-responda@cactarus.com>`, clicked the link (`EmailAddress.verified = True`), and `create_household_for_new_user` minted `Casa de bessavagner.dev` with role owner. That is signup → verification email → verify → household, end to end, through a real mailbox rather than `mail.outbox`.
  - **Still uncaptured: the `Authentication-Results` header.** The operator confirmed the message arrived and acted on it, which means it was findable — but `spf=pass`/`dkim=pass` was not read off the message, so it is not recorded below. Paste it into `docs/runbook.md` the next time a verification email is sent, so deliverability rests on evidence rather than on the message having been found.
- [ ] **Manually verified: the Android TWA login flow works against the deployed revision** — **NOT DONE.** Requires a deploy. `/login/` is now a 301 to `/accounts/login/`; the redirect and `SESSION_COOKIE_SAMESITE = "Lax"` are same-origin so it should survive the TWA's navigation, but that is a prediction, not a verification.
- [x] `/security-review` passed with no authentication finding — but **only on the third pass**, and the first two passes each found real defects in this branch's own work. See "What the security review actually found" below.

### What the security review actually found

Recorded because "passed" alone would misrepresent it. Every finding was in
code this epic added, and each defeated a control this epic claims:

1. **`sw.js` published `ADMIN_URL_PATH`.** The service worker is served to
   anyone who asks, so templating the secret admin path into its cache-bypass
   list handed it to every anonymous visitor — `curl /sw.js`. It also bought
   nothing: `networkFirstNav` never writes to the cache.
2. **The admin path was enumerable anyway.** `CommonMiddleware`'s APPEND_SLASH
   rewrites a 404 into a 301 when the unslashed URL does not resolve and the
   slashed one does, so `/gestao-xxxx` answered 301 while every wrong guess
   answered 404.
3. **Case bought a fresh lockout budget.** allauth resolves an address
   case-insensitively, but the lockout counted the string as submitted — 2^n
   budgets for an n-letter address.
4. **The refusal was distinguishable by its headers.** After fixing 2, the
   gate's 404 still lacked `X-Frame-Options: DENY` (a middleware's response
   only travels out through the middleware above it, and the gate sat above
   `XFrameOptionsMiddleware`), so one `curl -sI` still separated the real path
   from a wrong guess.

Findings 1, 2 and 4 were about the *same* control — an unguessable path — and
none of them granted access, which is why the second control (staff + TOTP)
matters. Each has a regression test; the header one compares the whole header
set rather than one header, so the next middleware added cannot reopen it
quietly.

## Out of scope

- Social login (Google, Apple) — a conversion optimization, not an MVP requirement. Note it for post-GA.
- Support impersonation → **E17**
- Onboarding after first login → **E11**
- Account deletion → **E13** (LGPD owns the deletion semantics)
- Subscription and paywall → **E15**

## Open questions — all four decided

1. **Which email provider?** → **Resend, over plain SMTP.** No SDK: Django
   already speaks SMTP, so changing provider is an environment change rather
   than a deploy. SPF/DKIM at the registrar is still required and is still
   the operator's to do — see the unticked box above.
2. **How is `/admin/` restricted?** → **A secret path (`ADMIN_URL_PATH`) plus a
   staff-and-TOTP middleware that 404s everyone else and logs every answered
   request.** Cloud Run stays `--allow-unauthenticated` because the product
   needs it to be. Rejected: an IP allowlist (the home IP is dynamic) and a
   second IAM-gated service (doubles the deploy surface). Documented in
   `docs/runbook.md`, "Reaching the admin".
3. **Is verification mandatory?** → **Mandatory.**
   `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`. One code path, and no
   half-trusted account state for E11 to inherit. The one exemption is narrow
   and reasoned: an address that received an invitation link has already
   proven itself, so an invitee is not asked for the same proof twice
   (`accounts/signals.py::verify_invited_email`).
4. **What happens when the last owner leaves?** → **Refused, not solved.**
   `MemberRemoveView` returns 400 rather than orphaning a household. The real
   semantics stay with **E13**, together with account deletion.

## What this epic deliberately did not solve

- **Last-owner-leaves** → E13. Refusing is the only answer that cannot corrupt
  a household, and it is enforced in the view and named in the test.
- **Support impersonation** → E17. This epic went the other way and
  *unregistered* `ChatMessage` from admin entirely: raw conversations with the
  assistant are not an admin list column. E17 owns the deliberate, consented,
  logged way to look at a customer's account, and `AdminAccessLog` is the
  first half of it.

## Two things the plan got wrong, found by executing it

Recorded so the next reader does not re-derive them:

1. **Mandatory verification would have locked out every existing account.**
   allauth checks its own `EmailAddress` table, which is empty for accounts
   created before this epic — so the deploy would have answered a correct
   password with "confirme seu e-mail" for a signup that never happened.
   `core/0004_seed_email_addresses` back-fills a verified address for each,
   and skips the `.invalid` placeholders, which prove nothing. Rehearsed
   against a copy of production: 2 of 3 accounts back-filled.
2. **The "invited address is proven" exemption cannot live in an
   `ACCOUNT_ADAPTER`.** Both adapter hooks sit on the wrong side of the moment
   that matters — `save_user` runs before the `EmailAddress` row exists,
   `should_send_confirmation_mail` runs after `perform_login` has already
   decided the account is unverified. It lives on `user_signed_up`, which
   fires between them.

## Skill pipeline

1. `superpowers:brainstorming` — open questions 1-3 are product decisions, not implementation details
2. `superpowers:writing-plans`
3. `superpowers:using-git-worktrees`
4. `frontend-design` — the auth pages are the first thing a stranger sees; allauth defaults would undercut the product
5. `superpowers:test-driven-development`
6. `superpowers:subagent-driven-development`
7. `superpowers:requesting-code-review`
8. `/security-review` — **mandatory**; authentication is where homegrown and misconfigured flows leak
9. `superpowers:verification-before-completion`
10. `superpowers:finishing-a-development-branch`
