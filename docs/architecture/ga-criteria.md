# GA criteria

**Decided:** 2026-08-16, in E14 (S14-6), **before any beta data existed.**
**Reads:** [`docs/architecture/product-metrics.md`](product-metrics.md) — what
each number here means.
**Read by:** the beta → GA decision in PD-3.

These are **commitments, not predictions.** Writing thresholds after seeing the
data is how every result becomes a good result, and this file exists to make that
impossible. Revising a number here after data arrives is allowed — it is
sometimes even right — but it must be done *in this file*, saying so, with the
old number left visible and dated. A threshold that quietly moved is not a
threshold.

## The thresholds

| Criterion | Threshold | Measured by |
|---|---|---|
| Activation rate | **≥ 25%** of signups | `manage.py activation_report --days 30` → *Taxa de ativação* |
| D7 rolling retention | **≥ 15%** of the signup cohort | `manage.py retention_report` → the `D7` column |
| Cost per household | **≤ R$ 5,00/month** | `manage.py usage_report` + `/metricas/`, against a ~R$ 10/month intended price |
| Time-to-value | reported, not gated | `activation_report` → p50 / p90 |

**Time-to-value is deliberately not a gate.** It is the number that tells us
*where* to fix activation when activation is short, so a threshold on it would
duplicate the activation gate while adding a way to fail on a technicality.

### The cost threshold, and the currency it is not in

`UsageRecord.cost_usd` is stored in **USD**; the threshold is written in **BRL**
because the price is. The comparison is therefore made at the rate on the day it
is run, and the rate used is recorded alongside the result — it is **re-run**
when the rate moves, never re-derived from an old conversion. A ceiling that
silently drifts with the exchange rate is not a ceiling.

At R$ 5,00 against a ~R$ 10/month intended price, the gate is a 50% gross margin
before any other cost. That is thin for a business and fine for a beta: the
question this beta answers is whether the wedge lands, not whether the unit
economics are good, and a cost above this would mean the answer cannot be
"launch" whatever the other numbers say.

## Why these numbers and not higher ones

**Learning mode, chosen deliberately.** This beta exists to find out whether
receipt capture is a wedge, on a handful of households, most of them known to the
operator. Thresholds set for a funded launch would not measure that; they would
measure whether the sample was lucky.

**The risk in that, named rather than hidden:** thresholds this low mean almost
any result reads as a good result. That is exactly what the stop condition below
is for, and it is why the stop condition is a *ratio* rather than another
floor — it can fail while every threshold above passes.

## The stop condition

> **AI-captured : manually-typed below 1:1 after 30 days of beta means the wedge
> is not landing.**

This is the one result that means **rethinking rather than launching**, and it
does not trade off against the thresholds above. A beta with 40% activation and
90% of entries typed by hand has not validated this product; it has validated a
nicer spreadsheet, which is the thing PD-1 says this is not.

Decided by the ratio line in `manage.py retention_report`, which prints the
verdict itself when it trips:

```
== A cunha ==
IA 3 : 11 manual (21%)
⚠️ Mais lançamentos digitados que capturados por IA — a cunha não está pegando.
```

CSV imports are excluded from that ratio — a backfill is migration, not capture,
and one import of two thousand rows would decide the question by itself. See
`product-metrics.md`.

## What is not measurable yet, and why that is recorded rather than fudged

**Exposure has no number.** There is no landing page, so there is nothing to be
exposed to; it is defined in `product-metrics.md` and measured at the edge (Cloud
Run request counts on the signup URL) once E17 ships one. A GA decision made
before then is made without it, knowingly — not with a zero standing in for it.

## How each is evaluated, in one sitting

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py activation_report --days 30
POSTGRES_PORT=5433 uv run python src/backend/manage.py retention_report
POSTGRES_PORT=5433 uv run python src/backend/manage.py usage_report
```

Every threshold above maps to a line one of those three prints. **A criterion no
command can evaluate is a wish**, and none of these are.
