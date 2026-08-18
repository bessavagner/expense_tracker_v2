# E16 S16-4 — a rollback that was performed

**Date:** 2026-08-18
**Environment:** staging (`expense-tracker-staging`, project `expense-tracker-482807`, region `southamerica-east1`)
**Performed by:** Vagner Bessa

## What was rolled back

Revision `expense-tracker-staging-00004-s9s` carried a marker string
(`rollback-rehearsal-marker`, an HTML comment in `templates/base_public.html`,
which the login page renders); revision `expense-tracker-staging-00003-hh6` did
not. The marker is what makes this a proof rather than an assertion — a rollback
with no observable difference proves only that the command exits 0.

Deployed by hand rather than through the pipeline, because Workload Identity
Federation was not yet provisioned when the rehearsal ran. The rollback command
itself is identical either way; the pipeline is not involved in a traffic split.

## The command

```
gcloud run services update-traffic expense-tracker-staging \
  --project expense-tracker-482807 --region southamerica-east1 \
  --to-revisions expense-tracker-staging-00003-hh6=100
```

The target revision was chosen with
`--filter='status.conditions[0].status=True'`, not by taking the second line of
an unfiltered `revisions list`. See *Failures encountered* below.

## Timing

| Moment | Time (UTC) |
|---|---|
| Command issued | 16:36:56.686 |
| Traffic table returned | 16:37:06.423 |
| Marker absent from a fresh request | 16:37:42.159 |
| **Total** | **45.5 s** |

The traffic switch itself was **9.7 s**. The remaining 36 s was a cold start on
the target revision plus the `curl` that confirmed the marker was gone — i.e.
the verification, not the rollback. Under real pressure the meaningful number is
the 9.7 s: that is how long production spends serving the bad revision after you
decide to move.

## Verification

```
$ curl -s $S/accounts/login/ | grep -c rollback-rehearsal-marker
0
$ curl -s $S/healthz/ | python3 -m json.tool
{
    "status": "ok",
    "database": "ok",
    "migrations": "ok",
    "unapplied": []
}
```

Rolling forward again with `--to-latest` restored the marker (`grep -c` → 1),
so both directions are proven, not just one.

## Failures encountered

**The obvious "previous revision" was a revision that had never served.** While
switching staging's startup probe from a TCP check to an HTTP check on
`/healthz/`, revision `00002` failed its probe and was left behind — newer than
the healthy `00001`, older than the healthy `00003`. A rollback that takes "the
second line of `gcloud run revisions list`" would have routed 100% of traffic to
a revision that never became ready. The runbook's command now filters on
`status.conditions[0].status=True`, and § *Rolling back* names this as the first
common failure.

## What this does and does not prove

Proves: traffic shifting works, is fast, is verifiable from outside, and works in
both directions.

Does **not** prove: that a rollback across an applied migration is safe. It is
not, in general — the runbook's *The hard case* table says which migration
shapes survive it and which do not. Nothing here rehearsed that case, and
rehearsing it properly means restoring a database, which is § *Restoring from
backup* and E16 Task 11.
