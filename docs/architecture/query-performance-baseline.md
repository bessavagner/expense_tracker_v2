# Query performance baseline

Measured for **E03**, at `0e616e6` on 2026-08-09, against a throwaway database
seeded by `manage.py seed_perf_data --yes`. Production today is one user with
~2,000 entries — too small for the planner's choice to be visible, which is why
the numbers below come from synthetic scale.

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
  query count that moves with the data is the signature of a per-row query. Task 5
  should pin this endpoint's count, and Task 4 should check whether the extra two
  come from the same pattern as the import path.

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

## After

Filled in by Task 2, Task 3 and Task 6.

## Re-run this after E04

E04 changes the tenant column from `user` to `household`, which changes the
leading column of every index below. Re-run the same script and append an
"After E04" section — the comparison is only meaningful against a baseline
measured the same way.
