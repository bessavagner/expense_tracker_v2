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
  ALLOWED_HOSTS=example.com uv run python src/backend/manage.py check --deploy
```

Observable assertions:

- [ ] End-to-end test: sign up → verify → log in → reset password → log in with the new password
- [ ] End-to-end test: owner invites → invitee signs up → both see the same ledger
- [ ] Test: removed member loses data access immediately
- [ ] Test: invitation token is single-use and expires
- [ ] Test: login throttling still applies at the new login URL
- [ ] Test: non-staff user cannot reach admin
- [ ] Manually verified: a real verification email arrives in a Gmail inbox, not spam
- [ ] Manually verified: the Android TWA login flow works against the deployed revision
- [ ] `/security-review` passed with no authentication finding

## Out of scope

- Social login (Google, Apple) — a conversion optimization, not an MVP requirement. Note it for post-GA.
- Support impersonation → **E17**
- Onboarding after first login → **E11**
- Account deletion → **E13** (LGPD owns the deletion semantics)
- Subscription and paywall → **E15**

## Open questions

1. **Which email provider?** Needs a decision: Resend, Postmark, SendGrid, and Amazon SES differ mainly on price and Brazilian deliverability. Whichever is chosen, SPF/DKIM setup is required.
2. **How is `/admin/` restricted?** Cloud Run IAM is strongest but complicates access from a laptop on a dynamic IP. An authenticated proxy or IP allowlist may be more practical. Decide and document in `docs/runbook.md`.
3. **Is email verification mandatory before use, or may a user try the product first?** Mandatory is safer and simpler; deferred verification converts better. This interacts with E11's activation target — decide the two together.
4. **What happens when the last owner leaves a household** that still has members? Related to E04 open question 3.

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
