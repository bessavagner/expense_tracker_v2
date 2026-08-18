# E16 S16-8 — the ratio alert, fired in a deliberate low-volume test

**Date:** 2026-08-18
**Environment:** staging (`expense-tracker-staging`)
**Policies:** staging twin `8752894992987066623`, production `18241775360706229059`
**Metrics:** `ledger_requests_5xx_staging` / `ledger_requests_total_staging`
(production pair: `ledger_requests_5xx` / `ledger_requests_total`)

## What was simulated

The 2026-08-15 shape: a total failure at low request volume, with `/healthz/`
still answering 200.

A temporary middleware on staging raised `RuntimeError` for every path except
`/healthz/`. Verified before generating load:

```
healthz -> 200
/       -> 500
login   -> 500
```

`/healthz/` staying at 200 matters twice over. It kept the revision passing its
startup probe (so the broken code actually served, as it did in production), and
it kept the uptime policy quiet — so the only thing that could catch this was the
ratio policy.

**Deviation from the plan:** the plan's rehearsal broke *authenticated* paths and
drove them with a logged-in `curl` session. Breaking every non-`/healthz/` path
instead produces the same measured shape with no scripted login, and it exercises
the metric pair's `/healthz/` exclusion directly, which is the part of the design
under test. What is *not* covered by this variant: nothing in the alert path —
the policy reads status codes and URLs, not identity.

## The traffic

Ten requests over 16 minutes, ~110 s apart, plus two verification requests at the
start — twelve 5xx in total.

```
16:53:57  GET /  -> 500   (verification)
16:53:58  GET /  -> 500   (verification)
16:54:13  GET /  -> 500
16:56:03  GET /  -> 500
16:57:53  GET /  -> 500
16:59:44  GET /  -> 500
17:01:34  GET /  -> 500
17:03:24  GET /  -> 500
17:04:25  GET /  -> 500
17:06:16  GET /  -> 500
17:08:06  GET /  -> 500
17:09:56  GET /  -> 500
```

Metric time series over the 30-minute alignment window (Monitoring API,
`ALIGN_SUM` + `REDUCE_SUM`):

```
ledger_requests_5xx_staging    = 12
ledger_requests_total_staging  = 12
```

Ratio **1.000**, count **12**. Both conditions met: ratio > 0.5 and count > 2.

## It fired

Two `ViolationOpenEventv1` records — one per condition, as an `AND` policy
produces:

```
2026-08-18T16:59:21Z | expense-tracker-staging 5xx ratio elevated |
  ratio(logging/user/ledger_requests_5xx_staging, ...) is above the threshold
  of 0.500 with a value of 1.000.
2026-08-18T16:59:21Z | expense-tracker-staging 5xx ratio elevated |
  logging/user/ledger_requests_5xx_staging ... above the threshold of 2.000
```

**Time to detection: 5 minutes 24 seconds** from the first 5xx (16:53:57) to the
violation opening (16:59:21). Notification channel *Operator email*
(`5857707555791637518`) is attached to the policy, the same channel the uptime
and retention policies use.

Retrieved with:

```bash
gcloud logging read \
  'logName="projects/expense-tracker-482807/logs/monitoring.googleapis.com%2FViolationOpenEventv1"' \
  --project expense-tracker-482807 --limit 5 --freshness=3h --format=json
```

That log is the durable, queryable record of a policy firing. There is no public
Monitoring API for incidents, so this is the evidence to reach for — not a
screenshot of the console.

## What the count-based policy would have done: nothing

Policy `4509450462948742746` fires on **more than 5** 5xx in 5 minutes, i.e. it
needs 6. Across the whole rehearsal the busiest 5-minute window held **5**:

```
peak = 5 5xx in the 5-minute window starting 16:53:57
count policy threshold = more than 5 in 5 minutes (needs >=6) -> would NOT have fired
```

And that peak only reached 5 because two verification requests happened to land
in the same window as the first two generated ones. The generated traffic alone —
one request per ~110 s — can never exceed 3 in any 5-minute window.

This is the entire justification for S16-8. A service returning 500 to **100% of
real traffic** does not trip a count threshold at family scale. On 2026-08-15 it
took until 17:34 UTC, four minutes after the fix had landed, on a day that had
run at ~100% authenticated failure.

## Both policies stay

Confirmed enabled after the rehearsal: `expense-tracker 5xx error rate elevated`
(the count) and `expense-tracker 5xx ratio elevated` (the ratio). A ratio is
blind to a burst that is small relative to healthy traffic; a count is blind to a
total failure at low volume. Neither replaces the other (E16 D10).

## Cleanup

Staging was restored by shifting traffic back to
`expense-tracker-staging-00003-hh6` — **10 seconds**, no rebuild, which is the
same mechanism `docs/superpowers/evidence/e16-rollback/` timed. The middleware
commit was reverted; `git diff` against the pre-rehearsal commit for the touched
files is empty.
