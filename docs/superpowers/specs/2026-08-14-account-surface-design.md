# Account surface ("Conta") — design

**Date:** 2026-08-14
**Epic:** [`E18 · Account surface`](../../backlog/E18-account-surface.md)
**Status:** approved, awaiting implementation plan
**Baseline commit:** `e5f08a4`

---

## The problem

E05 gave users an email as their login identity, a password they can change, a
household with members, and TOTP as a second factor. None of it has a product
surface. allauth ships bare pages for the mechanics — `/accounts/email/`,
`/accounts/password/change/`, `/accounts/2fa/` — and they inherit the ledger
theme through `templates/allauth/layouts/base.html`, so they render acceptably.
But they are unstyled English forms with **nothing in the product linking to
them**.

A beta user who mistypes their email at signup, or who wants to change a
password, has no in-product path. That is an R3 concern — the release gate is
"ready for strangers" — not something to defer to R4 with billing.

## What already exists (verified at `e5f08a4`)

Establishing this first, because the gap is narrower than "there is no profile
page":

| Surface | Where | What it holds |
|---|---|---|
| Email + logout | `templates/partials/_navbar.html:20-28` | Shows `request.user.email`; posts to `account_logout` |
| Configurações | `templates/settings/settings_page.html` | Five HTMX tabs — Renda, Sistemáticos, Formas de Pagamento, Categorias, Orçamentos. All **household financial config** |
| Membros da casa | `templates/accounts/members.html`, `accounts/views.py::MembersView` | Member list with roles, pending invitations, remove/revoke |

So identity *display* and logout are not the gap. The gap is a place to
**manage** what E05 created.

Two facts that make this cheap:

- `core.CustomUser` extends `AbstractUser`, so **`first_name` already exists as
  an unused column**. A display name costs zero migrations.
- `allauth.mfa` is installed and configured — `MFA_SUPPORTED_TYPES = ["totp",
  "recovery_codes"]` (`config/settings.py:275`). The 2FA machinery works; it has
  no product surface.

`allauth.usersessions` is **not** installed.

## Decisions

### D1 · Its own epic, in R3, ahead of E11

Rejected alternatives: fold into E11, fold into E15, do it as an unscheduled
chore.

E15 is R4. Deferring there means beta users spend the whole of R3 unable to
change their own email or password without being handed a bare allauth URL, and
E13's export/delete lands first with nowhere to put itself.

E11 is wedge-critical and about first-run. Account management is neither.
Folding it in dilutes the epic that carries the wedge.

The decisive argument is the seam: **E13 and E15 both need a surface.** Building
the container once, cheaply, and letting later epics add panels is far cheaper
than three epics each inventing their own account page.

### D2 · Conta absorbs Membros; Configurações stays money-only

The mental model splits on scope, and the split is real:

- **Configurações** — household-scoped shared data. Editing a category changes
  it for every member.
- **Conta** — who I am (per-user: name, email, password, 2FA) and who is in my
  house (household-scoped, but about *people*).

Membros da casa is closer to "minha conta" than to "Categorias", so it moves in
as a tab. Net effect on the drawer is **one entry removed, not one added**:
`Membros da casa` becomes `Conta`.

Rejected: a sixth tab inside Configurações. It puts per-user identity in the
same tab bar as shared money config, and reaches eight tabs once E13 and E15
add theirs — unusable on a phone, and this ships as a PWA and Android TWA.

### D3 · The Conta page is a hub, not a re-implementation

**This is the load-bearing decision.** Password change and 2FA enrolment are
security-critical flows. Reimplementing them so they look nicer is how they get
subtly wrong.

- **Conta tabs render status and link out** — "Senha → Alterar", "Verificação em
  duas etapas · inativa → Ativar".
- **allauth's own views run the flows**, styled through template overrides so
  they land in the ledger theme.

Status is limited to what is already derivable. Two-factor state comes from
allauth's authenticator records; **password age does not**, because
`AbstractUser` has no password-changed timestamp and adding one would mean a
migration this epic is committed to avoiding. Do not show a "last changed"
date.

This also answers the question the handoff left open — whether to override
allauth's manage pages one by one or build one product page composing them. The
answer is both, with the composition being *navigation and status*, never a
reimplemented form.

### D4 · Single-address email change via `ACCOUNT_CHANGE_EMAIL`

allauth 65.19.1 (installed) supports `ACCOUNT_CHANGE_EMAIL = True`: the user is
restricted to exactly one address, changed by adding a temporary second address
that replaces the primary **once verified**. It has a dedicated template,
`account/email_change.html`.

This matches what E05 already locked in — `ACCOUNT_UNIQUE_EMAIL = True`, email
as the sole login method — and is far simpler for a consumer product than
exposing allauth's native multi-address manager.

Cost: one setting, one styled template. Not a hand-rolled flow.

### D5 · 2FA is offered to every user, not just staff

`allauth.mfa` is already installed and configured, so this is a styled surface
over machinery that works. Today it is effectively staff-only, because the
admin gate is the only thing that forces enrolment. A product holding household
financial records should let any user turn on a second factor.

**Constraint:** E05's staff-admin-gate behaviour must not regress. The existing
test asserting that a staff user without TOTP is redirected to enrolment stays
passing.

### D6 · Sessions deferred

"Sair de outros aparelhos" requires installing `allauth.usersessions` — a new
app, a new migration, and middleware. It is the only candidate item with real
setup cost, and it is not needed to open a beta. Recorded here so it is a
decision rather than an oversight; revisit if a lost-phone report ever happens.

## Structure

```
/casa/conta/              AccountView       shell + tab bar
/casa/conta/perfil/       ProfileTabView    fragment — nome, e-mail
/casa/conta/seguranca/    SecurityTabView   fragment — senha, 2FA (status + links)
/casa/conta/membros/      MembersTabView    fragment — existing members body
/casa/membros/            → 301 → /casa/conta/
```

The `accounts` app is already mounted at `/casa/` (`config/urls.py:62`), so the
new page needs no new include.

Tabs follow the **existing repo idiom** from `settings_page.html` exactly: a
full-page shell whose tabs `hx-get` fragments into `#account-content`, with the
first tab loaded by `hx-trigger="load"`. No new pattern is introduced.

`MembersView`'s body is extracted to `templates/accounts/_members.html`, so the
tab fragment and any full-page render share one template rather than diverging.

### Tab growth

```
now:      Perfil │ Segurança │ Membros
+ E13:    Perfil │ Segurança │ Membros │ Privacidade      (export, delete)
+ E15:    Perfil │ Segurança │ Membros │ Privacidade │ Plano
```

Five tabs at the end, mirroring Configurações. Deep-linking to a specific tab
(`?tab=`) is **not** built now — the existing settings page does not do it
either, and consistency wins. E15 may want it for "go to your plan"; that is
E15's call to make.

## Components

| Unit | Purpose | Depends on |
|---|---|---|
| `AccountView` | Renders the shell and tab bar | `LoginRequiredMixin`, household resolution |
| `ProfileTabView` | GET renders name + current email; POST saves the name | `ProfileForm` |
| `ProfileForm` | One field, `nome`, bound to `CustomUser.first_name` | — |
| `SecurityTabView` | Read-only status for password and 2FA, with links out | `allauth.mfa` authenticator lookup |
| `MembersTabView` | The existing members body as a fragment | `_members.html` |
| Styled allauth templates | `account/email_change.html`, `account/password_change.html`, `mfa/*` | allauth |

Each tab view is independently renderable and independently testable — a
fragment URL hit directly returns valid HTML, which is also how the tests reach
them.

## Data flow

Name save: `POST /casa/conta/perfil/` → `ProfileForm` → `CustomUser.first_name`
→ re-render the fragment → toast via the existing `show-toast` window event
(`base.html:30`).

Email change: Conta links to allauth's `account_change_email`. allauth creates an
unverified `EmailAddress`, sends the confirmation, and swaps primary only on
confirmation. **The old address stays primary and usable throughout** — no
window where the user cannot log in.

2FA: Conta links to allauth's MFA views. Enrolment demands re-authentication
first, which is allauth's behaviour and is already documented in the runbook.

Name display: everywhere a person is rendered — the Membros list, pending
invitations — show the name, **falling back to the email** when it is blank.
Every existing account has a blank `first_name`, so the fallback is the normal
case on day one, not an edge case.

## Error handling

- Name blank → allowed; display falls back to email.
- New email already belongs to another account → allauth rejects it. Because
  `ACCOUNT_PREVENT_ENUMERATION = True` (`config/settings.py:251`), the message
  must not confirm that the address is registered. Do not weaken this to give a
  friendlier error.
- 2FA deactivation by a staff user → they lose admin access until they
  re-enrol. This is correct and must not be special-cased.
- A non-owner reaching a member-removal action → the existing E05 permission
  checks apply unchanged; absorbing Membros into a tab must not relax them.

## Testing

- Login required and household scoping asserted on every new view.
- Each tab fragment renders standalone at its own URL.
- Name round-trips and appears on the Membros list; blank name falls back to the
  email.
- Email change: the old address stays primary until the new one is confirmed;
  a collision with an existing account is rejected without enumerating.
- 2FA enrol and disable work for a non-staff user.
- **E05's staff-admin-gate test still passes** — regression guard on D5.
- `/casa/membros/` redirects to `/casa/conta/`.
- Owner-only member removal and invitation revocation still enforced.

UI work goes through the mandatory daisyUI Blueprint chain — Setup Expert →
Rules Enforcer → Component Syntax Expert → code → Quality Inspector — skipping
Creative Director and Page Architect, because this repo has a settled design
direction. Note daisyUI 5 dropped `form-control`/`label-text`; use
`fieldset`/`label`. `btn-accent` is the established action colour and the
Inspector will flag it; that deviation is recorded and intentional.

## Out of scope

- Sessions / `allauth.usersessions` — D6.
- Avatars and profile images.
- LGPD export and deletion — **E13** adds a Privacidade tab here.
- Plan, invoices, payment method, cancel — **E15** adds a Plano tab here.
- Social login.
- Per-user timezone and currency — parked, `INDEX.md` §10.
- Redesigning Configurações.
- Deep-linkable tabs (`?tab=`).

## Backlog hygiene folded in

`docs/backlog/INDEX.md` §4 is stale at `e5f08a4`: it still lists E05 as `ready`
and E11 as `blocked`. E05 is done, so **E11 is unblocked**. The table, the
status values, and the dependency graph are corrected as part of this epic,
along with the new E18 row and its edges.
