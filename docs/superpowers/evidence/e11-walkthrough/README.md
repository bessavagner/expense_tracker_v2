# E11 · Unaided walkthrough

**Status: NOT YET PERFORMED.** This file is the protocol and the empty record.
E11's Definition of Done is explicit that a passing test suite is not sufficient
evidence for this epic — the evidence is a real person reaching activation
without help. Until the table below is filled in from an actual session, the
corresponding DoD boxes stay unticked.

**Date:**
**Participant:** (someone who has not seen this product — not the operator)
**Device:** (make, model, browser; the PWA or the installed TWA)
**Build:** (git SHA, and the deployed revision if not local)

## Protocol

Hand them a phone at the signup screen and say exactly this, then say nothing else:

> "Este app registra os gastos da casa. Faça o que achar que deve fazer."

Do not explain. Do not answer questions with answers — answer with
"o que você faria?". Note the timestamp when they start, and the timestamp when
a receipt is confirmed into the ledger.

Have a real supermarket receipt ready to photograph.

**Do it on a phone.** The product ships as a PWA and an Android TWA, and the
guided setup was only ever verified at desktop width by the test suite. A
desktop walkthrough does not satisfy the DoD.

## What to record

| Moment | Timestamp | Notes |
|---|---|---|
| Signup submitted | | |
| Verification email opened | | verification is mandatory (E05) — note how long the wait felt |
| Guided setup opened | | |
| Income step | | filled / skipped, and why |
| Cards step | | did the closing-day sentence land? |
| Capture step | | |
| Photo taken | | |
| Receipt confirmed — **ACTIVATION** | | |

**Time to activation:** ______ minutes.

Cross-check against the command:

```bash
uv run python src/backend/manage.py activation_report --days 1
```

The number it prints and the number on the stopwatch should agree. If they do
not, the instrumentation is wrong and that is a finding in itself.

## Friction points

One line each. Verbatim quotes where you have them — a paraphrase loses the
thing that made it friction.

1.
2.
3.

## What was NOT understood

Specifically: did they understand the closing day? Did they know the chat could
read a photo before being told? Did they find the importer, and did they want it?

## Verdict

- [ ] Reached activation unaided
- [ ] Needed one hint (record which)
- [ ] Did not reach activation

## Known gaps to watch for, from the build

Recorded in advance so the observer knows what is already suspected. Do not
prompt the participant about these — just note whether they surface.

- The guided setup was verified by tests and by type-checking, **not** by anyone
  looking at it on a 390px viewport. Layout problems are unverified.
- A household created in the current month loses the previous month from the
  default projection window. Correct, but it may read as missing data.
- If the chat's history request fails, the panel renders blank with no error
  message. Deliberate for now — error UX belongs to E17.

## DoD command output

Paste the output of the four Definition-of-Done commands from the walkthrough
build here, so the record shows what was true when the walkthrough ran.
