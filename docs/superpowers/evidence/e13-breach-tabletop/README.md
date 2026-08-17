# Breach tabletop — 2026-08-17

**Scenario:** a beta user reports seeing another household's entries, 40 minutes
after a deploy touching `finances/views/`.

**Run by:** Claude, executing E13 Task 13 during the epic's implementation.
**Duration:** ~25 minutes of command execution.

**Method:** every command in `docs/runbook.md` § "Incidente de segurança" was
executed — against the live GCP project for the read-only ones, and against the
development database for the ORM ones. Nothing was read and assumed.

**One deviation, deliberate:** step 2, the traffic rollback, was **not**
executed. Switching production traffic is not something to do as a drill. Its
prerequisite — listing revisions so you know what to roll back *to* — was
executed, and that is the half that fails in a real incident if it is going to.

**What this exercise is not.** It tests whether the procedure's commands work
and whether the data can answer the ANPD's question. It does not test whether a
tired human at 09:14 on a Tuesday can follow it under pressure. That still wants
a human run before the product carries real users at scale.

## Timeline as walked

| Step | Command or source | Time taken | Worked? |
|---|---|---|---|
| Identify the serving revision | `gcloud run services describe … --format="value(status.traffic[0].revisionName)"` | 1s | ✅ `expense-tracker-00048-lgf`, 100% |
| Roll back | `gcloud run revisions list` (prerequisite only) | 1s | ✅ last 5 revisions listed with timestamps. Traffic switch deliberately not run |
| Find the user's requests by `request_id` | `gcloud logging read 'jsonPayload.request_id="<id>"'` | 16s | ⚠️ **Partly.** See "What did not" — the command is correct, the data is thin |
| Check `AdminAccessLog` | `manage.py shell -c …` | 1s | ✅ ran, 0 rows in the dev database (no staff access in the window) |
| Enumerate households the code path could reach | `household_owned_models()` + `Household.objects.count()` | 2s | ✅ 18 tenant tables, 7 households |
| Check `ExportJob` in the window | `manage.py shell -c …` | 1s | ✅ ran, 0 archives built in the window |
| Draft the notification | see below | ~10 min | ✅ draftable from what the six sources above return |

## What worked

- **Both gcloud read paths are fast and authenticated.** Identifying the serving
  revision and listing rollback candidates took a second each. In a real
  incident these are the first two commands and neither is a surprise.
- **Every ORM command in the procedure runs as written.** No typo, no missing
  import, no renamed field. This is the thing a read-through cannot check and it
  is why the step exists.
- **The tenant-table count is discoverable rather than remembered.**
  `household_owned_models()` returned 18, so "which tables could this reach" is
  answered by the code rather than by somebody's memory of E04.
- **`AdminAccessLog` answers the staff question directly.** Actor, method, path,
  IP, timestamp. If the leak had been a staff read, this is a complete answer.

## What did not

**The `request_id` correlation is much weaker than the procedure implies.**
This is the finding of the exercise.

Cloud Logging holds two kinds of entry for this service:

- **gunicorn/uvicorn access lines**, as `textPayload` — e.g.
  `169.254.169.126:43400 - "GET /healthz/ HTTP/1.1" 200`. These have **no
  `request_id`**, no user and no household.
- **Python logger records**, as `jsonPayload` with `request_id`, `user_id` and
  `household_id` — exactly the fields E06 built for this.

The second kind only exists **when application code logs something**. A request
that succeeds quietly emits no `jsonPayload` entry at all. Sampling 30 days of
this service's logs, every `jsonPayload` entry found came from a background
logger (`urllib3.connectionpool` retries) with `request_id: "None"` — i.e. logged
outside any request.

So "find every request that user made in the last hour by `request_id`" answers
**only for requests that already logged an error or warning**. In the scenario as
written — a user seeing the wrong data, with *Sentry showing no errors* — there
is likely no log line to find, and the command returns zero rows. Zero rows here
means "nothing was logged", not "nothing happened", and those look identical.

Two smaller traps, both now fixed in the runbook:

- **`gcloud logging read` defaults to a 1-day freshness window.** The incident
  window is 72 hours. Without `--freshness`, the command silently searches less
  time than the incident covers — the worst kind of wrong answer.
- The `ExportJob` query now uses `_base_manager` explicitly. Checked both:
  outside a request `objects` and `_base_manager` returned the same count here,
  so the original was not wrong — but `_base_manager` cannot be quietly defeated
  by a future change to the scoped manager, and an incident is not when you want
  to discover that.

## Gaps found, and what was done about each

| Gap | Severity | Action | Where it is tracked |
|---|---|---|---|
| No per-request access log carrying `request_id` — correlation works only for requests that logged something | **High** for incident scoping | Not fixed here: this is request-logging middleware, which is new behaviour and outside E13's scope. Documented in the runbook's "gap worth knowing" note | `docs/backlog/E17-trust-surface.md` (evidence points here) |
| No per-row read log — cannot answer "did anyone read Amanda's entries?" for a non-staff path | **High**, and already known | Not fixed. Stated plainly in the runbook and in `docs/architecture/data-inventory.md` so a notification says it rather than implying otherwise | E17 |
| `gcloud logging read` 1-day default freshness is shorter than the 72-hour window | Medium, cheap | **Fixed** — `--freshness` added to the runbook command | this file |
| Rollback step listed the target revision without saying how to find it | Low, cheap | **Fixed** — `gcloud run revisions list` added ahead of the traffic switch | this file |

## The honest answer to "whose data was exposed"

**For a non-staff read path: we cannot tell from the data we keep.**

There is no per-row read log, and — as this exercise found — not even a
per-request log for requests that complete without error. What we *can* state,
and would have to state in the notification, is:

- which revision was serving, and when it started (`gcloud run revisions list`);
- which households the affected code path *could* have reached — an upper bound
  from the 18 tenant tables, not an observation;
- whether any staff account read customer data in the window (`AdminAccessLog`,
  a complete answer);
- whether any export archive was built in the window (`ExportJob`, a complete
  answer — and the one that would matter most, because an archive is a whole
  household's history in one file).

A notification built on that is honest but coarse: it would name a *population
that may have been affected* rather than a list of people who were. LGPD art. 48
permits notifying with incomplete information on time, so this does not block
the 72 hours — but the ANPD's follow-up question is exactly the one we cannot
answer today.

**The smallest thing that would change that:** request-logging middleware that
emits one `jsonPayload` line per request with `request_id`, `user_id`,
`household_id`, path and status — regardless of whether anything failed. The
fields already exist (`core.middleware.log_context_middleware` populates them);
what is missing is a log line on the success path. That is a small change and it
would turn "we cannot tell" into "here is every request that user made". It
belongs to E17, not to E13.

## Verdict

**Yes — a notification could have gone out inside 72 hours.** Containment is one
command, the scope commands all run and return in seconds, and four of the six
scoping questions get complete answers.

The notification would have been **honest but imprecise about who was affected**,
and it would have had to say so. That is a real limitation, it is now written
down in three places instead of being discovered during an incident, and the fix
is scoped and cheap enough that it should not wait long.
