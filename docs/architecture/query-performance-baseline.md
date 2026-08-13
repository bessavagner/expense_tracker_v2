# Query performance baseline

Measured for **E03**, at `0e616e6` on 2026-08-09, and re-measured for **E04**
at `e9e1d2f` on 2026-08-13 once the tenant column became `household` — see
[After E04 — household-leading](#after-e04--household-leading). Both runs used a
throwaway database seeded by `manage.py seed_perf_data --yes`. Production today
is one user with ~2,000 entries — too small for the planner's choice to be
visible, which is why the numbers below come from synthetic scale.

Two shapes were measured, because they answer different questions:

| Shape | Command | Total entries | Entries per user |
|---|---|---|---|
| **A — wide** | `seed_perf_data --yes` (defaults) | 50,000 | 250 |
| **B — deep** | `seed_perf_data --yes --users 20 --entries-per-user 5000` | 100,000 | 5,000 |

Shape B is the one that matters. Every hot query filters by `user`, so what a
single user's slice costs is set by *their* history, not by the table's size. A
household using this app for five years lands in shape B. Shape A is kept because
it is the plan's default and because the contrast is itself the finding.

## Method

```bash
PGPASSWORD=postgres createdb -h localhost -p 5433 -U postgres expense_tracker_perf
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf uv run python src/backend/manage.py seed_perf_data --yes
```

Then the `EXPLAIN (ANALYZE, BUFFERS)` script and the Django client loop from
`docs/superpowers/plans/2026-08-08-E03-query-performance-floor.md`, Task 1, with
two corrections that the plan's version needs:

- `ALLOWED_HOSTS=testserver` must be set, or every request is a `400` and the
  measurement records nothing.
- The loop runs **twice** and only the second pass counts. The first request in a
  process pays ~1,100 ms of URLconf and template import that has nothing to do
  with queries; recording it as a query cost would overstate the endpoint by 200×.

## Before — what is actually indexed

The plan expected `grep -rn 'Index' src/backend/*/migrations/*.py` to return
nothing. It returns three hits, all from E01: `assistant/migrations/0006_assistant_usage_event.py`
and two in `core/migrations/0002_login_attempt.py`. **No `finances` migration
declares an index**, which is the part of finding H1 that still stands.

But "no declared index" is not "no index". Django creates a B-tree on every
`ForeignKey` column automatically, so `finances_entry.user_id`,
`finances_income.user_id` and `assistant_chatmessage.user_id` are all indexed
already. Every relational plan below uses one. **There is no sequential scan on
any of those three tables at either shape** — the `Seq Scan` lines that do appear
are on `core_customuser`, from the measurement script's own
`WHERE username='perf_0100'` lookup, and on `assistant_memoryembedding`.

So the "before" problem is not a missing index on `user`. It is that the index
stops at `user`, and everything after it is a filter:

| Query (shape B, 5,000 entries for the user) | Rows returned | Rows read then discarded | Time |
|---|---|---|---|
| `Entry(user, billing_month)` | 189 | **4,811** | 0.416 ms |
| `Entry(user, billing_month, entry_type)` | 25 | **4,975** | 0.312 ms |
| `Entry(user, billing_month IN 6)` | 1,235 | 3,765 | 0.561 ms |
| `Entry(user) ORDER BY -date LIMIT 50` | 50 | sorts all 5,000 | 0.516 ms |
| `Income(user, month)` | 1 | 11 | 0.025 ms |
| `ChatMessage(user) ORDER BY -created_at LIMIT 20` | 20 | — | 0.035 ms |
| `MemoryEmbedding ORDER BY embedding <=> q LIMIT 5` | 5 | **Seq Scan, 200 rows** | 1.360 ms |

The same queries at shape A (250 entries for the user):

| Query | Rows returned | Rows read then discarded | Time |
|---|---|---|---|
| `Entry(user, billing_month)` | 7 | 243 | 0.085 ms |
| `Entry(user, billing_month, entry_type)` | 0 | 250 | 0.038 ms |
| `Entry(user, billing_month IN 6)` | 73 | 177 | 0.072 ms |
| `Entry(user) ORDER BY -date LIMIT 50` | 50 | sorts all 250 | 0.076 ms |
| `Income(user, month)` | 1 | 11 | 0.026 ms |
| `ChatMessage(user) ORDER BY -created_at LIMIT 20` | 20 | — | 0.031 ms |
| `MemoryEmbedding ORDER BY embedding <=> q LIMIT 5` | 5 | **Seq Scan, 2,000 rows** | 10.150 ms |

**Read those two tables together.** Every `Entry` query costs in proportion to
the user's whole history and not to the size of its answer: 20× the history, 5×
the time, to return a comparable number of rows. Nothing here is slow *yet* — the
worst relational query is half a millisecond — so this is a floor being laid
before it is needed, not an outage being fixed. The honest summary is "the work
grows with the wrong number", not "the dashboard is slow".

**The vector search is the exception and the only real defect.** It has no index
of any kind, so it reads every embedding in the table and sorts them: 2,000 rows
and 12,049 buffer hits for 10.15 ms, to return 5 rows. It is the only query in
the set measured in double-digit milliseconds, and it is linear in the number of
embeddings, which grows with every remembered correction.

## Before — endpoints

Second pass, shape B (20 users × 5,000 entries):

| Endpoint | Queries | Wall time |
|---|---|---|
| `/api/dashboard/summary/` | 7 | 5.1 ms |
| `/api/dashboard/top-categories/` | 5 | 5.3 ms |
| `/api/dashboard/evolution/` | 4 | 3.6 ms |
| `/api/dashboard/alerts/` | 9 | 7.3 ms |
| `/api/dashboard/recent-entries/` | 3 | 2.9 ms |
| `/api/dashboard/installments/` | 3 | 2.3 ms |
| `/entries/2026/8/` | 14 | **61.4 ms** |
| `/projection/?start=2026-07&months=14` | 10 | 10.9 ms |
| `/consolidated/` | 4 | 4.9 ms |

Shape A (200 users × 250 entries), for contrast:

| Endpoint | Queries | Wall time |
|---|---|---|
| `/api/dashboard/summary/` | 7 | 4.8 ms |
| `/api/dashboard/top-categories/` | 5 | 4.3 ms |
| `/api/dashboard/evolution/` | 4 | 3.1 ms |
| `/api/dashboard/alerts/` | 7 | 4.8 ms |
| `/api/dashboard/recent-entries/` | 3 | 2.3 ms |
| `/api/dashboard/installments/` | 3 | 2.3 ms |
| `/entries/2026/8/` | 14 | 14.6 ms |
| `/projection/?start=2026-07&months=14` | 10 | 9.2 ms |
| `/consolidated/` | 4 | 4.6 ms |

Two things to carry forward:

- **`/entries/<y>/<m>/` is the hot path**: 14 queries, and 14.6 → 61.4 ms for the
  same 14 queries when the user's history grows 20×. It is the page this epic
  should be judged on.
- **`/api/dashboard/alerts/` issued 7 queries at shape A and 9 at shape B.** A
  query count that moves with the data is the signature of a per-row query.
  *Resolved by Task 5, and it is not an N+1*: guards that hold the code fixed and
  scale entries 5 → 100, then categories and budgets 4 → 24, show this endpoint
  flat at 7 queries in both dimensions. The two extra queries in the seeded
  database are a conditional branch that runs when there is something to report,
  not work repeated per row. No fix needed; the guards are what keeps it that way.

<details>
<summary>Raw EXPLAIN output — shape B (deep)</summary>

```
Timing is on.
--- Entry: (user, billing_month) — the dashboard core predicate
                                                                       QUERY PLAN                                                                       
--------------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=2.54..293.54 rows=211 width=156) (actual time=0.035..0.389 rows=189 loops=1)
   Index Cond: (user_id = $0)
   Filter: (billing_month = '2026-08-01'::date)
   Rows Removed by Filter: 4811
   Buffers: shared hit=114
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.011..0.012 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
 Planning:
   Buffers: shared hit=247
 Planning Time: 0.341 ms
 Execution Time: 0.416 ms
(14 rows)

Time: 1.275 ms
--- Entry: (user, billing_month, entry_type)
                                                                      QUERY PLAN                                                                      
------------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=2.54..306.04 rows=25 width=156) (actual time=0.045..0.302 rows=25 loops=1)
   Index Cond: (user_id = $0)
   Filter: ((billing_month = '2026-08-01'::date) AND ((entry_type)::text = 'installment'::text))
   Rows Removed by Filter: 4975
   Buffers: shared hit=114
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.003..0.004 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
 Planning Time: 0.047 ms
 Execution Time: 0.312 ms
(12 rows)

Time: 0.499 ms
--- Entry: (user, billing_month IN 6 months)
                                                                          QUERY PLAN                                                                           
---------------------------------------------------------------------------------------------------------------------------------------------------------------
 HashAggregate  (cost=324.87..325.17 rows=24 width=36) (actual time=0.541..0.542 rows=6 loops=1)
   Group Key: finances_entry.billing_month
   Batches: 1  Memory Usage: 24kB
   Buffers: shared hit=114
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.003..0.003 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
   ->  Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=0.29..316.29 rows=1265 width=10) (actual time=0.012..0.424 rows=1235 loops=1)
         Index Cond: (user_id = $0)
         Filter: (billing_month = ANY ('{2026-08-01,2026-07-01,2026-06-01,2026-05-01,2026-04-01,2026-03-01}'::date[]))
         Rows Removed by Filter: 3765
         Buffers: shared hit=114
 Planning:
   Buffers: shared hit=34
 Planning Time: 0.078 ms
 Execution Time: 0.561 ms
(18 rows)

Time: 0.861 ms
--- Entry: recent list (user, -date)
                                                                              QUERY PLAN                                                                              
----------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=447.14..447.26 rows=50 width=156) (actual time=0.502..0.505 rows=50 loops=1)
   Buffers: shared hit=120
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.003..0.003 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
   ->  Sort  (cost=444.89..457.39 rows=5000 width=156) (actual time=0.501..0.502 rows=50 loops=1)
         Sort Key: finances_entry.date DESC, finances_entry.created_at DESC
         Sort Method: top-N heapsort  Memory: 47kB
         Buffers: shared hit=120
         ->  Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=0.29..278.79 rows=5000 width=156) (actual time=0.008..0.274 rows=5000 loops=1)
               Index Cond: (user_id = $0)
               Buffers: shared hit=114
 Planning:
   Buffers: shared hit=16
 Planning Time: 0.048 ms
 Execution Time: 0.516 ms
(18 rows)

Time: 0.717 ms
--- Income: (user, month)
                                                                     QUERY PLAN                                                                     
----------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_income_user_id_0193ced0 on finances_income  (cost=2.52..11.76 rows=1 width=67) (actual time=0.018..0.020 rows=1 loops=1)
   Index Cond: (user_id = $0)
   Filter: (month = '2026-08-01'::date)
   Rows Removed by Filter: 11
   Buffers: shared hit=5
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.003..0.003 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
 Planning:
   Buffers: shared hit=74
 Planning Time: 0.087 ms
 Execution Time: 0.025 ms
(14 rows)

Time: 0.252 ms
--- ChatMessage: history load
                                                                                  QUERY PLAN                                                                                  
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=13.30..13.35 rows=20 width=93) (actual time=0.028..0.029 rows=20 loops=1)
   Buffers: shared hit=5
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..2.25 rows=1 width=8) (actual time=0.002..0.003 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0010'::text)
           Rows Removed by Filter: 19
           Buffers: shared hit=2
   ->  Sort  (cost=11.05..11.10 rows=20 width=93) (actual time=0.027..0.028 rows=20 loops=1)
         Sort Key: assistant_chatmessage.created_at DESC
         Sort Method: quicksort  Memory: 27kB
         Buffers: shared hit=5
         ->  Index Scan using assistant_chatmessage_user_id_99675823 on assistant_chatmessage  (cost=0.27..10.62 rows=20 width=93) (actual time=0.019..0.020 rows=20 loops=1)
               Index Cond: (user_id = $0)
               Buffers: shared hit=5
 Planning:
   Buffers: shared hit=50
 Planning Time: 0.069 ms
 Execution Time: 0.035 ms
(18 rows)

Time: 0.195 ms
--- MemoryEmbedding: cosine nearest neighbours
                                                                           QUERY PLAN                                                                            
-----------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=33.97..33.98 rows=5 width=43) (actual time=1.002..1.003 rows=5 loops=1)
   Buffers: shared hit=1279
   InitPlan 1 (returns $0)
     ->  Limit  (cost=0.00..0.15 rows=1 width=18) (actual time=0.003..0.004 rows=1 loops=1)
           Buffers: shared hit=25
           ->  Seq Scan on assistant_memoryembedding assistant_memoryembedding_1  (cost=0.00..30.00 rows=200 width=18) (actual time=0.003..0.003 rows=1 loops=1)
                 Buffers: shared hit=25
   ->  Sort  (cost=33.82..34.32 rows=200 width=43) (actual time=1.002..1.002 rows=5 loops=1)
         Sort Key: ((assistant_memoryembedding.embedding <=> $0))
         Sort Method: top-N heapsort  Memory: 25kB
         Buffers: shared hit=1279
         ->  Seq Scan on assistant_memoryembedding  (cost=0.00..30.50 rows=200 width=43) (actual time=0.127..0.974 rows=200 loops=1)
               Buffers: shared hit=1276
 Planning:
   Buffers: shared hit=50
 Planning Time: 0.059 ms
 Execution Time: 1.360 ms
(17 rows)

Time: 1.567 ms
```

</details>

<details>
<summary>Raw EXPLAIN output — shape A (wide)</summary>

```
Timing is on.
--- Entry: (user, billing_month) — the dashboard core predicate
                                                                     QUERY PLAN                                                                     
----------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=4.79..22.79 rows=10 width=156) (actual time=0.041..0.058 rows=7 loops=1)
   Index Cond: (user_id = $0)
   Filter: (billing_month = '2026-08-01'::date)
   Rows Removed by Filter: 243
   Buffers: shared hit=11
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.011..0.021 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
 Planning:
   Buffers: shared hit=274
 Planning Time: 0.396 ms
 Execution Time: 0.085 ms
(14 rows)

Time: 1.030 ms
--- Entry: (user, billing_month, entry_type)
                                                                    QUERY PLAN                                                                     
---------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=4.79..23.42 rows=1 width=156) (actual time=0.030..0.030 rows=0 loops=1)
   Index Cond: (user_id = $0)
   Filter: ((billing_month = '2026-08-01'::date) AND ((entry_type)::text = 'installment'::text))
   Rows Removed by Filter: 250
   Buffers: shared hit=11
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.006..0.011 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
 Planning Time: 0.041 ms
 Execution Time: 0.038 ms
(12 rows)

Time: 0.163 ms
--- Entry: (user, billing_month IN 6 months)
                                                                        QUERY PLAN                                                                        
----------------------------------------------------------------------------------------------------------------------------------------------------------
 HashAggregate  (cost=24.36..24.63 rows=22 width=36) (actual time=0.049..0.050 rows=6 loops=1)
   Group Key: finances_entry.billing_month
   Batches: 1  Memory Usage: 24kB
   Buffers: shared hit=11
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.007..0.011 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
   ->  Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=0.29..19.54 rows=63 width=10) (actual time=0.016..0.037 rows=73 loops=1)
         Index Cond: (user_id = $0)
         Filter: (billing_month = ANY ('{2026-08-01,2026-07-01,2026-06-01,2026-05-01,2026-04-01,2026-03-01}'::date[]))
         Rows Removed by Filter: 177
         Buffers: shared hit=11
 Planning:
   Buffers: shared hit=34
 Planning Time: 0.072 ms
 Execution Time: 0.072 ms
(18 rows)

Time: 0.337 ms
--- Entry: recent list (user, -date)
                                                                            QUERY PLAN                                                                             
-------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=30.47..30.60 rows=50 width=156) (actual time=0.065..0.068 rows=50 loops=1)
   Buffers: shared hit=17
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.006..0.010 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
   ->  Sort  (cost=25.97..26.60 rows=250 width=156) (actual time=0.065..0.066 rows=50 loops=1)
         Sort Key: finances_entry.date DESC, finances_entry.created_at DESC
         Sort Method: top-N heapsort  Memory: 46kB
         Buffers: shared hit=17
         ->  Index Scan using finances_entry_user_id_7697a46d on finances_entry  (cost=0.29..17.67 rows=250 width=156) (actual time=0.013..0.027 rows=250 loops=1)
               Index Cond: (user_id = $0)
               Buffers: shared hit=11
 Planning:
   Buffers: shared hit=16
 Planning Time: 0.045 ms
 Execution Time: 0.076 ms
(18 rows)

Time: 0.280 ms
--- Income: (user, month)
                                                                     QUERY PLAN                                                                     
----------------------------------------------------------------------------------------------------------------------------------------------------
 Index Scan using finances_income_user_id_0193ced0 on finances_income  (cost=4.78..13.02 rows=1 width=67) (actual time=0.020..0.021 rows=1 loops=1)
   Index Cond: (user_id = $0)
   Filter: (month = '2026-08-01'::date)
   Rows Removed by Filter: 11
   Buffers: shared hit=5
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.006..0.010 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
 Planning:
   Buffers: shared hit=58
 Planning Time: 0.079 ms
 Execution Time: 0.026 ms
(14 rows)

Time: 0.195 ms
--- ChatMessage: history load
                                                                                 QUERY PLAN                                                                                  
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=13.56..13.61 rows=20 width=93) (actual time=0.024..0.025 rows=20 loops=1)
   Buffers: shared hit=5
   InitPlan 1 (returns $0)
     ->  Seq Scan on core_customuser  (cost=0.00..4.50 rows=1 width=8) (actual time=0.006..0.010 rows=1 loops=1)
           Filter: ((username)::text = 'perf_0100'::text)
           Rows Removed by Filter: 199
           Buffers: shared hit=2
   ->  Sort  (cost=9.06..9.11 rows=20 width=93) (actual time=0.024..0.024 rows=20 loops=1)
         Sort Key: assistant_chatmessage.created_at DESC
         Sort Method: quicksort  Memory: 27kB
         Buffers: shared hit=5
         ->  Index Scan using assistant_chatmessage_user_id_99675823 on assistant_chatmessage  (cost=0.28..8.63 rows=20 width=93) (actual time=0.019..0.021 rows=20 loops=1)
               Index Cond: (user_id = $0)
               Buffers: shared hit=5
 Planning:
   Buffers: shared hit=46
 Planning Time: 0.065 ms
 Execution Time: 0.031 ms
(18 rows)

Time: 0.181 ms
--- MemoryEmbedding: cosine nearest neighbours
                                                                            QUERY PLAN                                                                            
------------------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=83.24..83.25 rows=5 width=43) (actual time=9.789..9.791 rows=5 loops=1)
   Buffers: shared hit=12052
   InitPlan 1 (returns $0)
     ->  Limit  (cost=0.00..0.02 rows=1 width=18) (actual time=0.001..0.002 rows=1 loops=1)
           Buffers: shared hit=1
           ->  Seq Scan on assistant_memoryembedding assistant_memoryembedding_1  (cost=0.00..45.00 rows=2000 width=18) (actual time=0.001..0.001 rows=1 loops=1)
                 Buffers: shared hit=1
   ->  Sort  (cost=83.22..88.22 rows=2000 width=43) (actual time=9.789..9.789 rows=5 loops=1)
         Sort Key: ((assistant_memoryembedding.embedding <=> $0))
         Sort Method: top-N heapsort  Memory: 25kB
         Buffers: shared hit=12052
         ->  Seq Scan on assistant_memoryembedding  (cost=0.00..50.00 rows=2000 width=43) (actual time=0.043..9.565 rows=2000 loops=1)
               Buffers: shared hit=12049
 Planning:
   Buffers: shared hit=48
 Planning Time: 0.053 ms
 Execution Time: 10.150 ms
(17 rows)

Time: 10.484 ms
```

</details>

## After — Task 2, the relational indexes

Five indexes were added (`entry_user_billing_type_idx`,
`entry_user_date_recent_idx`, `income_user_month_idx`, `chat_user_recent_idx`,
`draft_user_status_recent_idx`) and **four were removed**: Django's implicit
per-`ForeignKey` index on `user_id` for `Entry`, `Income`, `ChatMessage` and
`ReceiptDraft`. The removal is the part that made the addition work; see below.

### A note on what these numbers can and cannot show

This machine runs other work. During the "after" measurements its load average
was 7.6, and the same unchanged endpoint measured 61 ms in one session and 170 ms
in another. **Wall-clock times from different sessions are not comparable**, and
any table that compares them is measuring the machine, not the change. Two kinds
of evidence here are trustworthy, and only those are used to draw conclusions:

- **Rows read and plan shape**, from `EXPLAIN (ANALYZE)`. Load-independent.
- **Interleaved A/B**: the same measurement run alternately with and without the
  indexes, minutes apart, twice.

### Query plans

| Query | Index chosen | Rows read → returned | Before |
|---|---|---|---|
| `Entry(user, billing_month)` | `entry_user_billing_type_idx` | 189 → 189 | FK index, **5,000 → 189** |
| `Entry(user, billing_month, entry_type)` | `entry_user_billing_type_idx` | 25 → 25 | FK index, **5,000 → 25** |
| `Entry(user, billing_month IN 6)` | `entry_user_billing_type_idx` | 1,235 → 1,235 | FK index, **5,000 → 1,235** |
| `Entry(user) ORDER BY -date LIMIT 50` | `entry_user_date_recent_idx` | 50 → 50 | FK index, **sorted all 5,000** |
| `Income(user, month)` | `income_user_month_idx` | 1 → 1 | FK index, 12 → 1 |
| `ChatMessage(user) ORDER BY -created_at LIMIT 20` | `chat_user_recent_idx` | 20 → 20 | FK index, 20 → 20 |
| `MemoryEmbedding ORDER BY embedding <=> q LIMIT 5` | none — `Seq Scan` | 200 → 5 | unchanged; **Task 3** |

That is the whole point of the epic in one column: every `Entry` query now reads
exactly the rows it returns. The work no longer grows with the user's history.

### The FK index had to go, and finding that out required disagreeing with the planner

Adding the composite index was not enough. With Django's `user_id` index still in
place, Postgres kept choosing it for `filter(user, billing_month)` — the single
predicate the composite was built for — and went on discarding 4,811 rows. The
composite is wider, so the planner costs it higher (362.75 vs 293.54) and picks
the cheaper-looking plan. Measured in one session, same data, same cache:

| `Entry(user, billing_month)` | Rows read | Time |
|---|---|---|
| FK index present (planner's choice) | 5,000 | 1.698 ms |
| FK index dropped, composite forced | 189 | 0.288 ms |

The estimate was wrong by roughly 6×. Dropping the FK index is safe because it is
a strict *prefix* of the composite: `user_id` is the composite's leading column,
so every user-only lookup still resolves — verified directly, `count(*)` filtered
by user alone becomes an **Index Only Scan** on `entry_user_billing_type_idx`,
touching no heap at all. What was removed was a redundant index that cost writes,
disk and — because it looked cheap — correct plans.

### Endpoints, interleaved A/B

Two rounds, alternating, on shape B. Each cell is round 1 / round 2:

| Endpoint | Without the indexes | With the indexes |
|---|---|---|
| `/api/dashboard/summary/` | 7.7 / 8.5 ms | 7.2 / 5.9 ms |
| `/api/dashboard/top-categories/` | 8.1 / 7.9 ms | 6.7 / 4.7 ms |
| `/api/dashboard/evolution/` | 6.4 / 4.5 ms | 5.2 / 5.0 ms |
| `/api/dashboard/alerts/` | 13.2 / 8.9 ms | 8.6 / 7.4 ms |
| `/api/dashboard/recent-entries/` | 5.1 / 3.2 ms | 3.9 / 2.3 ms |
| `/api/dashboard/installments/` | 5.0 / 2.8 ms | 4.0 / 2.4 ms |
| `/entries/2026/8/` | 76.8 / 71.5 ms | 66.1 / 62.8 ms |
| `/projection/?start=2026-07&months=14` | 12.6 / 12.1 ms | 15.5 / 10.5 ms |
| `/consolidated/` | 7.1 / 5.0 ms | 5.2 / 4.5 ms |

Every endpoint is faster with the indexes in both rounds except `/projection/`,
whose 15.5 ms in round 1 is the one measurement that inverts and is inside this
machine's noise. The honest reading of the size of the win: **10–25% at the
endpoint level**, and ~13% on `/entries/`, the hot path — far less than the 5×
the query plans show, because most of these endpoints' time is Python and
template rendering rather than waiting on Postgres. Indexing was still the right
move: the query cost is now flat in the user's history where it used to be
linear, so this gap widens every month the app is used. But nobody should expect
a user-visible speedup today, and the epic should not claim one.

Query *counts* are unchanged by this task, as expected — an index changes what a
query costs, not how many are issued. `/api/dashboard/alerts/` still issues 9 on
shape B against 7 on shape A; that is Task 4/5's problem, not this one's.

## After — Task 3, the vector index

`memory_embed_hnsw_cosine_idx`, an HNSW index with `vector_cosine_ops`, plus a
rewrite of `find_semantic_matches` that moves the similarity threshold out of SQL
and into Python. Measured on 2,000 embeddings — the same table the 10.15 ms
"before" row above came from.

| Query shape | Plan | Buffers | Time |
|---|---|---|---|
| **Before**: no index, `ORDER BY … LIMIT 5` | Seq Scan, 2,000 rows | 12,049 | 10.150 ms |
| **After**: index, `ORDER BY … LIMIT 5` | `Index Scan using memory_embed_hnsw_cosine_idx` | 1,064 | **1.360 ms** |
| After, with `enable_seqscan = off` | same index | 1,030 | 0.660 ms |
| **The old query shape, with the index present**: `WHERE distance < 0.2 ORDER BY … LIMIT 5` | **Seq Scan, 1,999 rows removed by filter** | 12,033 | 7.130 ms |

The last row is the point of this task. Adding the index changes nothing on its
own: a `WHERE` over the distance expression forces Postgres to compute the
distance for every row, so it sequential-scans with the index sitting unused.
HNSW answers "the k nearest", not "everything within a radius". The threshold had
to move into Python — applied to the k rows the index returns — and only then
does the plan change. **7.5× fewer buffers and 7.5× less time**, and unlike the
relational indexes this one is a real speedup at today's data size, not just a
better slope.

The behavioural contract shifted slightly and the tests were written for it:
before, "up to `limit` rows within the threshold, chosen from all that qualify";
after, "the `limit` nearest, of which we keep those within the threshold". For an
exhaustive scan these are identical; for an approximate index they can differ at
the margin, so the tests assert that the expected memory is *found*, never that a
fixed list comes back in a fixed order. The existing 303 assistant tests pass
unchanged, so recall did not regress at this scale and `ef_search` was left at
its default.

### A gate this exposed

The index was first declared as `memory_embedding_hnsw_cosine_idx` — 32
characters against Django's 31-character limit — and without
`django.contrib.postgres` in `INSTALLED_APPS`, which `HnswIndex` requires. Both
are `manage.py check` errors, and **both passed CI's check step and the entire
test suite**: plain `check` skips every check needing a database connection, and
pytest-django runs migrations with checks disabled. They surface only at
`migrate`, which is to say on container start in production. CI now runs
`check --database default` as well.

## Migrations

Five migrations, applied and unapplied cleanly against local Postgres 16 with
pgvector (`localhost:5433`), then reapplied, with `makemigrations --check
--dry-run` reporting `No changes detected` afterwards:

| Migration | What it does |
|---|---|
| `finances/0010_query_indexes` | adds `entry_user_billing_type_idx`, `entry_user_date_recent_idx`, `income_user_month_idx` |
| `finances/0011_drop_redundant_user_fk_indexes` | drops Django's implicit `user_id` index on `Entry` and `Income` |
| `assistant/0007_query_indexes` | adds `chat_user_recent_idx`, `draft_user_status_recent_idx` |
| `assistant/0008_drop_redundant_user_fk_indexes` | drops it on `ChatMessage` and `ReceiptDraft` |
| `assistant/0009_memory_hnsw_index` | adds `memory_embed_hnsw_cosine_idx` |

The inverse of the Task 1 check: `grep -rn 'Index' src/backend/*/migrations/*.py`
returned three hits before this epic, all E01's on its own tables and none in
`finances`. It now returns those three plus every migration above.

## Supabase — rehearsed against a copy of production

Run on 2026-08-09, with the owner's explicit approval, against a restored copy of
the live database rather than the live database itself. Procedure and every
failure encountered are in
[`docs/runbook.md`](../runbook.md#applying-a-migration-to-supabase).

The copy held real production data: **2,298 entries, 91 incomes, 262 chat
messages, 0 embeddings**. Supabase runs PostgreSQL 17.6.

```
Applying assistant.0006_assistant_usage_event... OK
Applying assistant.0007_query_indexes... OK
Applying assistant.0008_drop_redundant_user_fk_indexes... OK
Applying assistant.0009_memory_hnsw_index... OK
Applying core.0002_login_attempt... OK
Applying finances.0010_query_indexes... OK
Applying finances.0011_drop_redundant_user_fk_indexes... OK

real    0m8.176s
```

All six indexes present afterwards:

| tablename | indexname |
|---|---|
| `assistant_chatmessage` | `chat_user_recent_idx` |
| `assistant_memoryembedding` | `memory_embed_hnsw_cosine_idx` |
| `assistant_receiptdraft` | `draft_user_status_recent_idx` |
| `finances_entry` | `entry_user_billing_type_idx` |
| `finances_entry` | `entry_user_date_recent_idx` |
| `finances_income` | `income_user_month_idx` |

And all three redundant FK indexes gone — the query for
`finances_entry_user_id_7697a46d`, `finances_income_user_id_0193ced0` and
`assistant_chatmessage_user_id_99675823` returned `0`. The copy was then dropped
and the local dump deleted; the project is back to a single `postgres` database.

Three things this established that local Postgres could not:

- **The whole epic's DDL takes 8 seconds on production-sized data**, so the
  deploy needs no maintenance window. The HNSW build is instant because
  **production currently holds zero embeddings** — worth knowing, because it also
  means Task 3's 7.5× improvement is real but not yet *felt* in production. It
  starts mattering as remembered corrections accumulate.
- **Migrations work through the session pooler on port 5432**, including
  `CREATE DATABASE` and index DDL. The 6543 transaction pooler is still the wrong
  door; nothing here tested it, and nothing should.
- **The rehearsal also applied E01's migrations** — `assistant/0006_assistant_usage_event`
  and `core/0002_login_attempt` were both pending on the copy, confirming from the
  database side that E01 was merged but not deployed.

## Applied to production

2026-08-09, after the rehearsal above and in that order — migrations first, then
code, because E01's code writes to `assistant_assistantusageevent` and
`core_loginattempt` on every assistant turn and every login. Deploying first
would have 500'd both.

All seven migrations applied to the live database in **8.345s**, within 2% of the
8.18s the rehearsal predicted, and `showmigrations` reports nothing pending. Row
counts unchanged either side: 2,298 entries, 91 incomes, 262 chat messages. All
nine indexes E01 and E03 declare are present, and the three redundant FK indexes
are gone.

Cloud Run revision **`expense-tracker-00040-x7q`** then took 100% of traffic,
replacing `00039-rg6`. Smoke test `200 / 302 / 200`, `/admin/login/` renders,
`--max-instances 3` carried over as a bare deploy should, and the revision logged
no error at or since startup.

## Re-run this after E04

E04 changes the tenant column from `user` to `household`, which changes the
leading column of every index below. Re-run the same script and append an
"After E04" section — the comparison is only meaningful against a baseline
measured the same way.

**Done — see the next section.**

## After E04 — household-leading

Measured at `e9e1d2f` on 2026-08-13, shape B, same script and same machine
class as E03's "after". **One thing changed: the leading column.** Every index
above was rebuilt with `household_id` where it had `user_id`, and the queries
were re-pointed to match. No predicate, no ordering and no arithmetic moved, so
these numbers should reproduce E03's — and where one does not, that is a
finding rather than a footnote.

```bash
PGPASSWORD=postgres createdb -h localhost -p 5433 -U postgres expense_tracker_perf_e04
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf_e04 \
  uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf_e04 \
  uv run python src/backend/manage.py seed_perf_data --yes --users 20 --entries-per-user 5000
# -> Seeded 20 users, 100000 entries, 240 incomes, 400 chat messages, 200 embeddings.
```

A household here has exactly one member, so it holds exactly the rows that
member held under E03. The comparison is like-for-like by construction.

### Query plans

| Query | Index chosen | Rows read → returned | E03's equivalent |
|---|---|---|---|
| `Entry(household, billing_month)` | `entry_hh_billing_type_idx` | 223 → 223 | `entry_user_billing_type_idx`, 189 → 189 |
| `Entry(household, billing_month, entry_type)` | `entry_hh_billing_type_idx` | 24 → 24 | `entry_user_billing_type_idx`, 25 → 25 |
| `Entry(household, billing_month IN 6)` | `entry_hh_billing_type_idx` | 1,248 → 1,248 | `entry_user_billing_type_idx`, 1,235 → 1,235 |
| `Entry(household) ORDER BY -date LIMIT 50` | `entry_hh_date_recent_idx` | 50 → 50 | `entry_user_date_recent_idx`, 50 → 50 |
| `Income(household, month)` | none — `Seq Scan` | 240 → 1 | `income_user_month_idx`, 1 → 1 |
| `ChatMessage(household) ORDER BY -created_at LIMIT 20` | `chat_hh_recent_idx` | 20 → 20 | `chat_user_recent_idx`, 20 → 20 |
| `MemoryEmbedding ORDER BY embedding <=> q LIMIT 5` | none — `Seq Scan` | 200 → 5 | unchanged; see Task 3 |

Row counts differ from E03's by a percent or two on `Entry` because
`seed_perf_data` distributes months with a seeded RNG and the seed is not
pinned across runs. The property that matters is unchanged and is the whole
point of E03: **every `Entry` query reads exactly the rows it returns.** The
work is flat in the household's history, not linear.

`Seq Scan` appears three times, all benign: twice on `accounts_household` (the
measurement script's own `ORDER BY name LIMIT 1` sub-select, against 20 rows)
and once on `assistant_memoryembedding`, exactly as E03 recorded — the HNSW
index needs more than 200 vectors before the planner will prefer it.

### `Income` is the one row that moved, and it is the table being too small

E03 recorded an Index Scan reading 1 row; this run records a `Seq Scan` reading
240 and discarding 239. That reads like a regression and is not one.
`finances_income` holds **240 rows** at shape B — 12 months × 20 households —
which is five heap pages. Postgres is right that scanning them beats an index
lookup, and it says so with an honest estimate. Forcing the issue confirms the
index is present and exact:

```
SET enable_seqscan=off;
 Index Scan using income_hh_month_idx on finances_income
   (cost=10000000001.57..10000000009.59 rows=1) (actual rows=1 loops=1)
```

One row read, one returned, no `Rows Removed by Filter`. The index works; the
table is too small for the planner to want it, and it will want it as soon as
the table is big enough for the choice to matter. E03's Index Scan on the same
row count is the planner making a marginal call the other way — a difference in
statistics freshness, not in what is indexed. **`Income` at shape B is not
evidence in either direction**, and no conclusion here rests on it.

### What this re-measurement caught: four indexes that came back

The interesting finding is not in the table above. E03 removed Django's
implicit per-`ForeignKey` index on `user_id` for `Entry`, `Income`,
`ChatMessage` and `ReceiptDraft` — that removal is what made the composites
work, and the reasoning is [above](#the-fk-index-had-to-go-and-finding-that-out-required-disagreeing-with-the-planner).
E04 phase 2 added `household` as an ordinary `ForeignKey`, so Django created
**all four of those indexes again** under `household_id`:

```
finances_entry        | finances_entry_household_id_4120ac8c
finances_income       | finances_income_household_id_95d4be0f
assistant_chatmessage | assistant_chatmessage_household_id_6faffb46
assistant_receiptdraft| assistant_receiptdraft_household_id_ceb479f6
```

Each is a strict prefix of the composite that leads with the same column, so it
serves no query the composite cannot — while costing writes, disk, and
sometimes a correct plan. The E04 test suite did not catch it: the assertion
that the planner picks the household-leading indexes
(`finances/tests/test_query_indexes.py`) runs against ~4,000 rows, where the
choice is not visible. **This measurement is what caught it**, which is the
argument for doing it at scale rather than trusting the unit test.

Measured impact at shape B was smaller than E03's history suggests:

| | With the FK indexes | Without |
|---|---|---|
| `Entry(household, billing_month)` | `entry_hh_billing_type_idx`, 223 → 223 | unchanged |
| `ChatMessage(household) ORDER BY -created_at` | **`..._household_id_6faffb46`**, then a sort | `chat_hh_recent_idx` |
| `Income(household, month)` | `Seq Scan` either way (240 rows) | `Seq Scan` |
| `Entry` count by household alone | Index Only Scan on the composite | unchanged |

Only `ChatMessage` demonstrably picked the wrong index, and on a 400-row table
the time difference is inside noise. `Entry` — the one where E03 measured the
planner going badly wrong, 5,000 rows read against 189 — kept choosing the
composite here. So this was a structural hazard restored, not a live
performance bug.

It was fixed anyway, in `finances/0019` and `assistant/0016`, by overriding
`household` with `db_index=False` on those four models. Three reasons: the
composites make the FK index redundant by construction rather than by luck; the
planner's preference for the narrower index is exactly the trap E03 documented
and there is no reason to keep re-testing it; and the fix had to land *before*
the production rehearsal, or the rehearsal would have tested a schema we do not
ship. `finances/tests/test_household_indexes.py` now asserts no standalone
`household_id` index exists on those four tables, so this cannot come back a
third time.

<details>
<summary>Raw EXPLAIN output — after E04, shape B</summary>

```
--- Entry: (household, billing_month) — the dashboard core predicate
 Bitmap Heap Scan on finances_entry  (cost=7.67..618.61 rows=202 width=172) (actual time=0.049..0.164 rows=223 loops=1)
   Recheck Cond: ((household_id = $0) AND (billing_month = '2026-08-01'::date))
   Heap Blocks: exact=101
   Buffers: shared hit=107
   InitPlan 1 (returns $0)
     ->  Limit  (cost=1.30..1.30 rows=1 width=34) (actual time=0.023..0.024 rows=1 loops=1)
           ->  Sort  (cost=1.30..1.35 rows=20 width=34) (actual time=0.022..0.023 rows=1 loops=1)
                 Sort Key: accounts_household.name
                 Sort Method: top-N heapsort  Memory: 25kB
                 ->  Seq Scan on accounts_household  (cost=0.00..1.20 rows=20 width=34) (actual time=0.002..0.003 rows=20 loops=1)
   ->  Bitmap Index Scan on entry_hh_billing_type_idx  (cost=0.00..6.31 rows=202 width=0) (actual time=0.038..0.038 rows=223 loops=1)
         Index Cond: ((household_id = $0) AND (billing_month = '2026-08-01'::date))
         Buffers: shared hit=6
 Planning Time: 0.395 ms
 Execution Time: 0.200 ms

--- Entry: (household, billing_month, entry_type)
 Bitmap Heap Scan on finances_entry  (cost=5.90..95.01 rows=24 width=172) (actual time=0.018..0.030 rows=24 loops=1)
   Recheck Cond: ((household_id = $0) AND (billing_month = '2026-08-01'::date) AND ((entry_type)::text = 'installment'::text))
   Heap Blocks: exact=24
   Buffers: shared hit=27
   ->  Bitmap Index Scan on entry_hh_billing_type_idx  (cost=0.00..4.59 rows=24 width=0) (actual time=0.015..0.015 rows=24 loops=1)
         Index Cond: ((household_id = $0) AND (billing_month = '2026-08-01'::date) AND ((entry_type)::text = 'installment'::text))
         Buffers: shared hit=3
 Planning Time: 0.050 ms
 Execution Time: 0.041 ms

--- Entry: (household, billing_month IN 6 months)
 HashAggregate  (cost=2094.86..2095.16 rows=24 width=36) (actual time=0.322..0.324 rows=6 loops=1)
   Group Key: finances_entry.billing_month
   Batches: 1  Memory Usage: 24kB
   Buffers: shared hit=133
   ->  Bitmap Heap Scan on finances_entry  (cost=38.67..2087.27 rows=1258 width=10) (actual time=0.052..0.214 rows=1248 loops=1)
         Recheck Cond: ((household_id = $0) AND (billing_month = ANY ('{2026-08-01,2026-07-01,2026-06-01,2026-05-01,2026-04-01,2026-03-01}'::date[])))
         Heap Blocks: exact=117
         ->  Bitmap Index Scan on entry_hh_billing_type_idx  (cost=0.00..38.36 rows=1258 width=0) (actual time=0.043..0.043 rows=1248 loops=1)
               Index Cond: ((household_id = $0) AND (billing_month = ANY ('{2026-08-01,...}'::date[])))
               Buffers: shared hit=16
 Planning Time: 0.078 ms
 Execution Time: 0.338 ms

--- Entry: recent list (household, -date)
 Limit  (cost=1.72..96.93 rows=50 width=172) (actual time=0.025..0.045 rows=50 loops=1)
   Buffers: shared hit=55
   ->  Index Scan using entry_hh_date_recent_idx on finances_entry  (cost=0.42..9521.61 rows=5000 width=172) (actual time=0.025..0.042 rows=50 loops=1)
         Index Cond: (household_id = $0)
         Buffers: shared hit=55
 Planning Time: 0.047 ms
 Execution Time: 0.052 ms

--- Income: (household, month)
 Seq Scan on finances_income  (cost=1.30..8.90 rows=1 width=83) (actual time=0.010..0.031 rows=1 loops=1)
   Filter: ((household_id = $0) AND (month = '2026-08-01'::date))
   Rows Removed by Filter: 239
   Buffers: shared hit=5
 Planning Time: 0.092 ms
 Execution Time: 0.035 ms

--- ChatMessage: history load
 Limit  (cost=12.41..12.46 rows=20 width=109) (actual time=0.028..0.029 rows=20 loops=1)
   Buffers: shared hit=7
   ->  Sort  (cost=11.11..11.16 rows=20 width=109) (actual time=0.028..0.028 rows=20 loops=1)
         Sort Key: assistant_chatmessage.created_at DESC
         Sort Method: quicksort  Memory: 27kB
         ->  Bitmap Heap Scan on assistant_chatmessage  (cost=4.43..10.68 rows=20 width=109) (actual time=0.019..0.020 rows=20 loops=1)
               Recheck Cond: (household_id = $0)
               Heap Blocks: exact=1
               ->  Bitmap Index Scan on chat_hh_recent_idx  (cost=0.00..4.42 rows=20 width=0) (actual time=0.015..0.015 rows=20 loops=1)
                     Index Cond: (household_id = $0)
 Planning Time: 0.082 ms
 Execution Time: 0.036 ms

--- MemoryEmbedding: cosine nearest neighbours (unchanged by E04)
 Limit  (cost=8.85..8.86 rows=5 width=43) (actual time=0.957..0.958 rows=5 loops=1)
   Buffers: shared hit=1230
   ->  Sort  (cost=8.82..9.32 rows=200 width=43) (actual time=0.956..0.956 rows=5 loops=1)
         Sort Key: ((assistant_memoryembedding.embedding <=> $0))
         Sort Method: top-N heapsort  Memory: 25kB
         ->  Seq Scan on assistant_memoryembedding  (cost=0.00..5.50 rows=200 width=43) (actual time=0.034..0.930 rows=200 loops=1)
               Buffers: shared hit=1227
 Planning Time: 0.425 ms
 Execution Time: 0.974 ms
```

</details>

### What was not re-measured

The endpoint-level A/B table from E03 was not repeated. E03's own conclusion was
that the index change is worth 10–25% at the endpoint and that most of the time
there is Python and template rendering — and E04 changes neither the number of
queries nor their shape, only which column leads the index. Re-running that loop
would measure this machine's load, not the change. If an endpoint regression is
ever suspected, the loop in the E03 plan is still the way to look for it.
