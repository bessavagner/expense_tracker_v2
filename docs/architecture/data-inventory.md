# Data inventory and data flows

**Owner:** E13 · LGPD compliance. **Kept beside** the privacy notice
(`src/backend/templates/legal/privacidade.html`), which renders the same lists.

Two things live here that do not fit in code:

- the **flow** — which data crosses which boundary, and what triggers it;
- the **evidence** — what has actually been verified, and by which test.

The lists themselves are code. `src/backend/core/privacy/inventory.py` holds
one record per model and `src/backend/core/privacy/subprocessors.py` holds one
per third party; both are rendered by the notice and enforced by
`src/backend/core/tests/test_privacy_inventory.py`. **Do not restate them
here** — a second copy of a list is how a notice starts describing a product
that no longer exists.

## Boundaries

Four, and nothing personal crosses any other.

| # | Boundary | What crosses it | When |
|---|---|---|---|
| 1 | Browser → Cloud Run (Google, `southamerica-east1`) | Everything the person types, photographs or records | Every request |
| 2 | Cloud Run → Supabase PostgreSQL | Every stored row | Every request that reads or writes |
| 3 | Cloud Run → OpenAI | Chat text, recent history, memory rules, receipt images, audio | Only when the person has granted AI consent, and only on an assistant turn |
| 4 | Cloud Run → Google Cloud Storage | Uploaded CSVs and generated export archives | Import and export jobs only |

Three more receive data that is *about* a person:

| # | Boundary | What crosses it |
|---|---|---|
| 5 | Cloud Run → Resend | Email address and the body of a transactional message |
| 6 | Cloud Run → Sentry | Exception type, file, line, URL, method, query string |
| 7 | Cloud Run → Logfire | Model name, latency, token counts, cost — **and the prompt and completion content**, see below |

## What boundary 3 actually sends, and what it does not

The disclosure that matters most, because it is the one people are surprised by.

**Sent:** the message text; the last `ASSISTANT_MAX_HISTORY` (20) turns of the
conversation; the household's memory rules that matched; the receipt image
bytes; the audio bytes.

**Not sent:** the ledger. The assistant reaches entries through tools that run
in Python and return computed answers, never a table dump — that is the money
boundary from `INDEX.md` §7.3, and it is a privacy property as much as a
correctness one.

**Not retained by us:** the image and the audio. Both are read into memory,
processed and dropped inside the request — the audio at
`assistant/views.py:397` (`transcribe_audio(audio.read(), ...)`), the image at
`assistant/views.py:514` (`prepare_receipt_image(image.read(), ...)`). Neither
path touches `core.storage` or writes a file anywhere. Only the extracted text
and values are stored. This predates E13 and is the one genuinely good privacy
property this product had before it had a privacy policy.

*(E13's epic file cites `assistant/views.py:288` for this; that line moved
before the epic was implemented, and the two sites above were re-verified on
2026-08-17 after E13's consent gate shifted them again. They move whenever the
view changes — re-check with `grep -n "\.read()" src/backend/assistant/views.py`
before trusting this paragraph, because it is a claim the privacy notice
repeats.)*

**Gate:** `core.privacy.consent`. Verified by
`src/backend/assistant/tests/test_ai_consent_gate.py`, including that a refusal
opens no interaction and charges no credit.

## Boundary 7 — Logfire receives content, and the notice says so

Worth stating plainly, because the obvious assumption is wrong. Logfire is a
tracing tool, so it looks like it would receive only timings and costs. It does
not: `LOGFIRE_CAPTURE_CONTENT` **defaults to on** (`config/settings.py`), which
is a deliberate operator decision from E06 (2026-08-14, open question 2), taken
so that debugging a bad extraction does not require reproducing it. The
consequence, in that setting's own words, is that Logfire holds chat content and
receipt descriptions, which makes Pydantic a sub-processor of personal financial
data.

`LOGFIRE_CAPTURE_BINARY` is a **separate** decision and defaults **off**, so
receipt photographs and audio are not uploaded to it.

The sub-processor row in `core/privacy/subprocessors.py` states this, and the
privacy notice renders that row. If the flag is ever turned off, change the row
in the same commit — not before, and not after.

## Boundary 6 — what Sentry is verified NOT to receive

The privacy notice claims Sentry gets the shape of a failure and never its
contents. That claim is **verified, not assumed**, by
`src/backend/core/tests/test_sentry_scrubbing.py`, which builds an event in the
SDK's own shape carrying a chat message, an entry description, a session
cookie, an API key and an email address, runs it through
`core.observability.scrub_event`, and asserts none of the five survives
anywhere in the serialized payload.

It also asserts what does survive — URL, method, query string, exception type,
file, line — because a scrubbed event nobody can locate is as useless as no
event, and a scrubber that passes by deleting everything would be a false pass.

Configuration facts the same file asserts: `send_default_pii` is `False`,
`before_send` really is `scrub_event`, and no DSN means nothing is transmitted
at all (the local-development and CI path).

**If a new integration is added to `sentry_sdk.init`, re-read this section.**
An integration can attach payloads the scrubber's key list does not know about;
the whole-payload assertion in that test is what catches it.

## Retention

Every period is declared in `core/privacy/inventory.py` and enforced daily by
`manage.py purge_expired_data` — see `docs/runbook.md`, "Retenção de dados
(E13)". Uploaded CSVs and export archives are **not** on that timer: the
bucket's own 7-day lifecycle rule deletes them, because a deletion that depends
on our cron running is a deletion that does not happen (E12 decision 2).

Account deletion does not wait for that rule. `core.privacy.deletion` collects
every `ImportJob.storage_key` and `ExportJob.storage_key` belonging to a
household it is about to remove, and deletes those blobs after the transaction
commits — so "your data is deleted" is true of the bucket as well as of
Postgres, and the lifecycle rule is only the backstop for one it missed.

**E13 is the first scheduled job this project has.** The cron objection E12
recorded is answered by making a stopped sweep detectable rather than by
assuming it will run: a `TaskRun` row per run, a log-based metric
(`ledger_purge_ran`) and an alert policy that fires after 36 hours with none.
**None of those three is provisioned yet** — the procedure is in the runbook and
the act is deliberate, per environment.

## Contracts still outstanding

Engineering cannot close these. They are listed so nobody assumes they are done.

- [ ] **A DPA with OpenAI**, and confirmation that its retention policy does not
      contradict what the notice promises. Epic open question 5.
- [ ] **A DPA with Supabase and with Resend.**
- [ ] **A DPA with Pydantic (Logfire)**, which receives prompt and completion
      content while `LOGFIRE_CAPTURE_CONTENT` is on — see boundary 7.
- [ ] **Legal review of the notice and the terms by a Brazilian lawyer.** The
      Definition of Done's last item, and the one this repository cannot satisfy.

## Changing anything here

1. Add or edit the `Record` / `SubProcessor` in code.
2. The notice re-renders itself. Do not edit its tables.
3. Update the flow section above if a *boundary* changed, not if a field did.
4. `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_inventory.py
   src/backend/core/tests/test_sentry_scrubbing.py -q` must be green.
