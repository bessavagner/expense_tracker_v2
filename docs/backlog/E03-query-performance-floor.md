---
id: E03
title: Query performance floor
release: R0
status: review
depends_on: []
blocks: []
wedge_critical: false
---

# E03 · Query performance floor

## Outcome

The queries that every page load and every assistant turn depend on are backed by indexes, and there is a measured baseline showing dashboard and semantic-memory latency before and after — so future regressions are detectable rather than felt.

## Why now

Review findings **H1** and **H2**. The database has **zero** declared indexes across all 16 migrations. This is invisible at one user with ~2000 entries and is the first thing to fall over under multi-tenant load.

It is in R0 because it is entirely independent — no dependency, no coordination, one migration — and because doing it *before* E04 means the household refactor is measured against a sane baseline instead of hiding a performance cliff inside a large diff.

## Evidence in the codebase

```bash
# Returns nothing — verified at 3bbc5ca
grep -rn 'Index' src/backend/*/migrations/*.py
```

No model declares `Meta.indexes`. Only automatic FK indexes and unique constraints exist.

| Hot query pattern | Where |
|---|---|
| `Entry.objects.filter(user, billing_month=...)` — the dashboard's core predicate, in 6 endpoints | `finances/api/views.py:33, 96, 109, 161, 271, 295` |
| `Entry.objects.filter(user, billing_month__in=[6 months])` | `finances/api/views.py:161` |
| `Entry.objects.filter(user, billing_month, entry_type='installment')` | `finances/api/views.py:231, 295` |
| `Income.objects.filter(user, month=...)` / `month__in=` | `finances/api/views.py:30, 175` |
| Sequential cosine scan over every embedding for the user | `assistant/agents/memory.py:28` (`find_semantic_matches`) |
| The unindexed vector column | `assistant/models.py:114` — `VectorField(dimensions=1536)` |
| Pending-draft lookup on every chat turn | `assistant/views.py:157-161` — filter by `user` + `status`, order by `-created_at` |
| Chat history load on every turn | `assistant/views.py:59-63` — filter by `user`, order by `-created_at`, limit 20 |
| Per-row extra queries inside `save()` | `finances/models/entry.py:59-66` — reads `payment_method.type`, calls `resolve_closing_day` |

## Stories

### S03-1 · Measure first

- **Given** a database seeded to realistic product scale (use `seed_qa_data` / `seed_data`, extended — target at least tens of thousands of entries across many synthetic users)
- **When** the dashboard's endpoints and a semantic memory lookup are exercised
- **Then** query counts and wall-clock timings are recorded as a written baseline
- **And** `EXPLAIN ANALYZE` output for the hot queries is captured, showing the sequential scans

> Do this before adding indexes. Without a before-number the after-number means nothing, and the epic's DoD depends on the comparison.

### S03-2 · Index the relational hot paths

- **Given** the query patterns above
- **When** a migration adds composite indexes
- **Then** `Entry` has indexes covering `(user, billing_month)`, `(user, date)`, and `(user, entry_type, billing_month)`
- **And** `Income` has `(user, month)`
- **And** `ReceiptDraft` has an index supporting the pending-draft lookup (`user`, `status`, `created_at` descending)
- **And** `ChatMessage` has an index supporting the history load (`user`, `created_at` descending)
- **And** `EXPLAIN ANALYZE` confirms index usage, not just index existence
- **And** the migration is reversible

> Index order matters: the leading column should be the one used for equality in every query. Verify with `EXPLAIN`, do not assume.

### S03-3 · Index the vector column

- **Given** `MemoryEmbedding.embedding` is searched by cosine distance
- **When** an HNSW index with `vector_cosine_ops` is added
- **Then** `find_semantic_matches` uses it, confirmed by `EXPLAIN ANALYZE`
- **And** the migration works against both the local pgvector container and Supabase
- **And** the semantic memory tests still pass, and still return the same matches as before the index (an approximate index can change ordering — assert the expected rule is still found, and note in the plan if recall tuning is needed)

### S03-4 · Remove the per-row query in the import path

- **Given** `Entry.save()` dereferences `self.payment_method` (`finances/models/entry.py:59-66`)
- **When** the CSV importer creates many entries in a loop (`finances/views/importer.py:351`)
- **Then** the payment method is not re-fetched per row
- **And** the query count for importing N rows grows substantially slower than the current ~3 queries per row
- **And** a test asserts the query count for a multi-row import stays under an agreed bound (`django_assert_num_queries` or equivalent)

### S03-5 · Add `select_related` where the N+1 is already visible

- **Given** views that iterate entries and touch related category or payment method
- **When** those querysets are reviewed
- **Then** `importer.py` and `dashboard.py` — which currently have zero `select_related` calls — no longer trigger per-row related fetches
- **And** a query-count test guards each one

## Definition of Done

```bash
# Migration applies and reverses cleanly
uv run python src/backend/manage.py migrate
uv run python src/backend/manage.py migrate finances <previous>   # prove reversibility, then re-apply
uv run python src/backend/manage.py makemigrations --check --dry-run

# Suite, coverage, lint
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# Indexes now exist
grep -rn 'Index' src/backend/*/migrations/*.py
```

Observable assertions:

- [ ] A written before/after comparison exists with query counts and timings at seeded scale
- [ ] `EXPLAIN ANALYZE` shows index scans (not sequential scans) on the hot `Entry` and `Income` queries
- [ ] `EXPLAIN ANALYZE` shows the HNSW index used for semantic search
- [ ] Query-count tests guard the import path and the two `select_related` fixes
- [ ] The migration has been applied against a Supabase copy, not only local Postgres — the pooler has surprised this project before (`config/settings.py:84-94`)

## Out of scope

- Caching (no cache layer exists; adding one is a separate decision)
- Rewriting the projection or analytics services for algorithmic efficiency
- `find_matching_rules`' in-Python substring scan (review M8) — correct, and not the bottleneck this epic targets
- Household-scoped index redesign → the indexes will need revisiting in **E04** when the tenant column changes; that is expected and noted there

## Open questions

1. **HNSW parameters** (`m`, `ef_construction`) — defaults are usually fine at this scale. State the chosen values and why.
2. **How much seed data is "realistic product scale"?** Pick a target and justify it. Enough that a sequential scan is unambiguously visible in `EXPLAIN ANALYZE`.
3. **Will E04 invalidate these indexes?** Partly — leading columns change from `user` to `household`. Decide whether to index for `user` now and re-index in E04, or wait. Recommendation: **do it now**; the measurement discipline and the migration pattern are what carry forward, and R0 shipping sooner is worth one extra migration.

## Skill pipeline

1. `superpowers:writing-plans`
2. `superpowers:using-git-worktrees`
3. `superpowers:test-driven-development` — the tests here are query-count and index-usage assertions
4. `superpowers:subagent-driven-development`
5. `superpowers:requesting-code-review`
6. `superpowers:verification-before-completion` — paste the before/after `EXPLAIN ANALYZE` output as evidence
7. `superpowers:finishing-a-development-branch`
