# E11 · Unaided walkthrough

**Status: PERFORMED 2026-08-16 — activation reached, unaided.** The timings and
the ledger contents below are read straight from the instrumentation, not from
memory. The observer's answers were added on 2026-08-16 after the fact; the one
section still marked **[observer]** is deliberately blank rather than guessed.

**Date:** 2026-08-16
**Participant:** wife — first-time user, had not seen the product before
**Device:** Motorola ("Signature"), Android, Chrome, PWA installed from `http://192.168.1.12:8701`
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

Still blank. The observer's notes came back as answers to "what was NOT
understood" rather than as moments of friction, and they are recorded in that
section below rather than duplicated here. Left as an open section rather than
deleted: a second session should fill it, and an empty heading is a more honest
record than a removed one.

1.
2.
3.

## What was NOT understood

Answered by the observer after the session. Recorded in the participant's own
language where they said it.

- **"Entradas" reads as income, not as spending.** *O nome "Entradas" confunde,
  pois parece se referir apenas a receita.* The nav labels the ledger
  `Entradas`, which in everyday pt-BR means money coming **in** — but the screen
  is mostly money going out. Not filed anywhere before this walkthrough; see
  "Follow-ups this raises" below.
- **The 2023 receipt could not be navigated to.** *O recibo foi de 2023. Não há
  seletor para esse ano, apesar de o registro ter sido feito.* This is finding 1
  seen from the other side, and it is worse than finding 1 assumed: the dashboard
  does not merely *default* to the current month, it **cannot reach 2023 at all**.
  `DashboardView` builds its year options as `range(2024, today.year + 2)`
  (`finances/views/dashboard.py:18`) — 2024 to 2027. A URL with `?year=2023`
  still works, because the view reads the query string directly; the *selector*
  is what cannot get there.
- **The guided setup did not register as a walkthrough.** *Falta um
  wizard/walkthrough após o registro e log in: registrar renda, saldo inicial,
  tutorial, etc.* Recorded verbatim because it is uncomfortable: the log shows
  they went **through** E11's three-step setup and filled in every step. So
  either the flow did not read as an onboarding while it was happening, or it
  ended too early — note that **saldo inicial (opening balance) is genuinely not
  one of the steps**, and it is the one they named that does not exist.

Still unanswered, and worth asking if there is a second session:

- Did the closing-day sentence land? They entered day 25 for Banco do Brasil in
  15 seconds, which suggests either that it was clear or that they already knew
  the concept — those look identical from the log.
- Did they know the chat could read a photo before being told?
- Did they find the importer link, and did they want it?
- **Why the second, manual entry at 12:38:57?** Finding 1 reads it as a retry
  after the ledger looked empty; the observer's note about the missing 2023
  selector supports that reading but does not confirm it.

## Verdict

- [x] **Reached activation unaided** — the observer's verdict, and it governs:
      they were in the room.
- [ ] Needed one hint
- [ ] Did not reach activation

**Reconciling this with finding 2.** A verification link *was* handed over
mid-session. The observer's judgement is that this does not make the run aided,
and the reasoning holds: `EMAIL_HOST` was empty in `.env`, so the console backend
swallowed the message — a dev-environment misconfiguration, not a thing the
product does to a real user. Everything the walkthrough was testing, from the
guided setup to activation, was reached with no help at all.

The caveat that survives regardless: this run still did **not** answer E05's open
question about whether a mandatory-verification wall costs activation for someone
waiting on a real email. That needs a run with real SMTP from the first second.

## Follow-ups this raises

What the observer's notes turn into, so none of it is lost in a document nobody
re-reads. Filed status as of 2026-08-16.

| Finding | Status |
|---|---|
| A backdated receipt activates into an invisible month | **Filed as D05**, plan at `docs/superpowers/plans/2026-08-16-D05-backdated-receipt-visibility.md`. Its remedy is a link to that month, which works — the view honours `?year=2023`. |
| The year selector cannot reach 2023 | **Not filed.** Distinct from D05, whose Out of scope says "a month-picker redesign → not this". A one-line fix to `year_range`, but it needs a decision about the lower bound — the earliest year with data, rather than a hardcoded 2024. Candidate: **D06**. |
| "Entradas" reads as income-only | **Not filed.** A naming problem, not a bug: the fix is a word, and the word is user-facing in several templates plus the nav. Worth deciding before beta, since it is the label on the product's main screen. Candidate: **D07**, or fold into E17's trust-surface copy pass. |
| Opening balance is not an onboarding step | **Not filed.** E11 shipped three steps against S11-3's ceiling of five, so there is room. Whether it belongs there is a product decision, not a defect. |

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
