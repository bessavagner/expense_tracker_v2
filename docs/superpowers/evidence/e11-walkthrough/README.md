# E11 · Unaided walkthrough

**Status: PERFORMED 2026-08-16 — activation reached.** The timings and the
ledger contents below are read straight from the instrumentation, not from
memory. The sections marked **[observer]** are the ones only the person in the
room can fill in; they are deliberately left blank rather than guessed.

**Date:** 2026-08-16
**Participant:** first-time user, had not seen the product before
**Device:** Android phone, Chrome, PWA installed from `http://192.168.1.12:8701`
**Build:** `92dde29` (local LAN server, not a deployed revision)

## What the instrumentation recorded

| Moment | Timestamp | Notes |
|---|---|---|
| Signup submitted | 12:16:06 | `signup` event |
| Household seeded | 12:16:10 | 14 categories, 2 payment methods, 3 memory rules — 4s after signup |
| Verification email | — | **blocked ~19 min**, see "The email gap" below. Not product friction. |
| Guided setup opened | ~12:35:40 | |
| Income step | 12:35:43 | **filled, not skipped** — `Salário`, R$ 3.000,00 |
| Cards step | 12:35:58 | **filled, not skipped** — `Banco do Brasil`, closing day 25. 15s after the income step. |
| Capture step | 12:36:02 | 4s later |
| Onboarding complete | 12:36:02 | `onboarding_done` |
| Receipt confirmed — **ACTIVATION** | 12:37:03 | `activated`, `{"lines": 3}` |

**Time to activation: 21 minutes** as measured by `activation_report`.
**Time to activation excluding the email block: 1 minute 23 seconds**
(12:35:43 → 12:37:03).

That second number is the real one for the product. From the moment the guided
setup was in front of them, a stranger who had never seen this app went to a
photographed receipt correctly in the ledger in **83 seconds**, filling in every
step rather than skipping any.

Cross-check — `activation_report --days 1` agrees with the event log:

```
Janela: últimos 1 dia(s)
Cadastros: 1
Ativados: 1
Taxa de ativação: 100.0%
Tempo até ativação (min): p50 21 · p90 21 (n=1)
```

The instrumentation is correct: 21 minutes is the true elapsed time. The
interpretation needs the email caveat, which is why it is written down here.

## What the receipt produced

One photograph of a MATEUS SUPERMERCADOS coupon → three entries, three
categories, split correctly:

| Amount | Category | Description |
|---|---|---|
| R$ 181,48 | Alimentação | carnes e frios, hortifruti, laticínios |
| R$ 12,09 | Casa | silicone |
| R$ 8,19 | Limpeza | papel toalha |

This is the wedge doing exactly what PD-1 claims it does, on a real coupon, for
a real stranger, on a phone.

## Findings

### 1. The activated ledger was invisible — the receipt was from 2023

**This is the most important finding of the walkthrough.**

The coupon was a real one the participant had to hand, dated **2023-06-04**.
The extraction read that date correctly (verified against the stored
`ReceiptDraft` payload — `date: "2023-06-04"`, not a misread year), and
`Entry.save()` correctly computed `billing_month = 06/2023`.

Correct behaviour, bad outcome: the dashboard shows the **current** month, so
after a successful activation the participant was looking at a screen with
nothing on it. That is precisely what this epic's Outcome says must not happen
— *"without an empty screen that tells them nothing."*

The behavioural evidence that this landed badly: **at 12:38:57, 114 seconds
after activating, they created a second entry by hand** — `Frutaria`,
R$ 100,00, Alimentação, billing month 08/2026, the current month. Nobody asked
them to. The most natural reading is that the first attempt looked like it had
failed and they tried again a different way — but see [observer] below, because
only the person in the room knows.

Not obviously a bug to fix by changing the date logic: filing a receipt by its
own date is right, and overriding it with "today" would corrupt the billing
month for every genuine backdated receipt. Candidate responses, none decided:

- after a commit whose billing month is not the current one, say so in the
  confirmation ("registrado na fatura de 06/2023") and offer to jump there;
- have the dashboard's empty state mention that entries exist in other months;
- treat it as acceptable and expect real users to photograph recent receipts.

Worth resolving before beta, because a first receipt that vanishes is an
activation the user does not believe in.

### 2. The email gap was a dev-environment artifact, not the product

`EMAIL_HOST` was empty in `.env`, so Django used the console backend
(`settings.py:314-321`) and the verification message was printed to the server
log instead of being delivered. The participant reported *"Fiz o cadastro e ele
disse que ia mandar o e-mail, mas n chegou"* and had checked spam.

Resolved mid-session by setting `EMAIL_HOST=smtp.resend.com` and
`DEFAULT_FROM_EMAIL=Ledger <nao-responda@cactarus.com>`; the confirmation link
was also handed over manually to unblock them.

**This means the run was not strictly unaided** — one hint was given, at the
verification step. Everything from the guided setup onward was unaided.

It also means the walkthrough did **not** answer E05's real open question:
whether a mandatory-verification wall costs activation for a user waiting on a
real email. That question is still open and needs a run with real SMTP from the
first second.

### 3. Steps were completed, not skipped

Every one of the three guided steps was filled in rather than skipped, and the
gaps between them were 15s and 4s. Whatever else is true, the flow did not
stall anyone. The skip paths therefore remain **unexercised by a real user**.

## [observer] Friction points

Verbatim quotes where possible — a paraphrase loses the thing that made it
friction.

1.
2.
3.

## [observer] What was NOT understood

- Did the closing-day sentence land? They entered day 25 for Banco do Brasil in
  15 seconds, which suggests either that it was clear or that they already knew
  the concept — those look identical from the log.
- Did they know the chat could read a photo before being told?
- Did they find the importer link, and did they want it?
- **Why the second, manual entry at 12:38:57?** See finding 1 — this is the
  single most valuable thing the observer can answer.

## [observer] Verdict

- [ ] Reached activation unaided
- [x] Needed one hint — the email verification link, because of the console-backend
      configuration described in finding 2. Unaided from the guided setup onward.
- [ ] Did not reach activation

## Known gaps watched for, from the build

- **390px layout** — the guided setup had never been viewed at phone width. No
  layout problem surfaced in the timings; whether anything looked wrong is an
  [observer] question.
- **A household created this month loses the previous month from the default
  projection window** — did not surface, and finding 1 dominated anyway.
- **A failed chat-history request renders a blank panel with no error** — did
  not surface.

## DoD command output

From build `92dde29`, run immediately before the walkthrough:

```
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/   → 1787 passed, 3 skipped
uv run coverage report --fail-under=80                          → TOTAL 92%
uv run ruff check src/backend/                                  → All checks passed
uv run ruff format --check src/backend/                         → 417 files already formatted
cd src/backend/frontend && corepack pnpm@10.23.0 build          → built clean
manage.py makemigrations --check --dry-run                      → No changes detected
manage.py check                                                 → no issues
```

Not run on a deployed revision — this walkthrough was against the local LAN
server. Repeating it post-deploy is still worth doing, per the E09 precedent of
migrations that had never reached production.
