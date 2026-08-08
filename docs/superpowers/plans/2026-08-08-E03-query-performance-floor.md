# E03 · Query Performance Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The queries every page load and every assistant turn depend on are backed by indexes, with a written before/after measurement at realistic scale so future regressions are detectable rather than felt.

**Architecture:** Measure, then index, then measure again. A new `seed_perf_data` management command builds a database at product scale (200 users, ~50k entries) so a sequential scan is unambiguous in `EXPLAIN ANALYZE`. Two migrations add composite B-tree indexes on the relational hot paths and an HNSW index on the embedding column. The semantic-search query is rewritten to `ORDER BY … LIMIT` with the threshold applied in Python, because a `WHERE distance < x` predicate is precisely what stops pgvector from using an HNSW index. Separately, the CSV import loop's per-row closing-day lookup is removed by making `resolve_closing_day` read a prefetchable cache instead of issuing a fresh `filter()` per row.

**Tech Stack:** Django 6.0, PostgreSQL 16 + pgvector (local container on `:5433`, Supabase in production), `pgvector.django` (`VectorField`, `HnswIndex`, `CosineDistance`), pytest + pytest-django (`django_assert_num_queries`), model-bakery, `uv`, Ruff.

## Global Constraints

Copied from `docs/backlog/INDEX.md` §7. Violating any of these fails review even if every task's tests pass.

- **TDD.** Test first, always. Here the tests are query-count and index-usage assertions.
- **Worktrees.** Feature work happens in an isolated worktree.
- **The money boundary holds.** No arithmetic moves into a prompt.
- **Coverage gate.** `coverage report --fail-under=80` must keep passing.
- **Lint gate.** `ruff check src/backend/` and `ruff format --check src/backend/` clean. Line length 100, double quotes, `target-version = "py312"`. Note `"*/migrations/*" = ["E501"]` and `"*/management/commands/seed_*" = ["S311"]` are already in the per-file ignores — the new seed command inherits the `S311` (non-crypto `random`) exemption.
- **pt-BR in the product UI, English in code, comments, and docs.**
- **Migrations are reversible.** `AddIndex`/`RemoveIndex` are reversible by construction; prove it by migrating down and back up.
- **No time-bomb tests.** The seed command takes an explicit anchor date rather than reading the clock.
- **Tests run against the local pgvector container on port 5433**: prefix every pytest invocation with `POSTGRES_PORT=5433`.

### Out of scope — do not drag these in

- Caching. No cache layer exists; adding one is a separate decision.
- Rewriting the projection or analytics services for algorithmic efficiency.
- `find_matching_rules`' in-Python substring scan (review M8) — correct, and not the bottleneck this epic targets.
- Household-scoped index redesign. The leading column changes from `user` to `household` in **E04**; that is expected and noted there.

---

## Decisions this plan locks in

**Open question 1 — HNSW parameters.** `m=16`, `ef_construction=64` — pgvector's own defaults. At this scale (thousands of vectors, not millions) the defaults give effectively exhaustive recall, and raising them buys nothing measurable while costing build time and index memory on a Supabase instance that is not sized for it. State these values in the migration's comment so the next person does not have to guess whether they were chosen or inherited.

**Open question 2 — how much seed data is "realistic product scale"?** **200 users × ~250 entries = ~50,000 `Entry` rows**, ~2,400 `Income` rows, ~4,000 `ChatMessage` rows, ~2,000 `MemoryEmbedding` rows. The number is chosen so the *selectivity* is unambiguous, not because 200 users is a revenue forecast: a `filter(user, billing_month)` returns roughly 20 rows out of 50,000, which is far enough below Postgres' seq-scan crossover that the planner will pick an index when one exists and cannot hide behind a small table when one does not. Today's production database (one user, ~2,000 entries) is small enough that Postgres correctly seq-scans everything — which is exactly why measuring there would prove nothing.

**Open question 3 — will E04 invalidate these indexes?** Partly. The leading column becomes `household` instead of `user`. Do it now anyway, as the epic recommends: the measurement discipline, the `EXPLAIN ANALYZE` baseline, and the migration pattern all carry forward, and one extra migration in E04 is cheaper than shipping R0 later. Record in the baseline document that E04 must re-run the same measurements after the tenant column changes.

---

## A finding that changes story S03-5

The epic's S03-5 says *"`importer.py` and `dashboard.py` — which currently have zero `select_related` calls — no longer trigger per-row related fetches."* Verified at `HEAD`, that premise does not hold as written:

- `src/backend/finances/views/dashboard.py` is a 20-line `TemplateView` that builds a context of integers and ranges. It contains **no queryset at all**. There is nothing to add `select_related` to. The dashboard's data comes from `finances/api/views.py`, and the two endpoints there that iterate entities already use `select_related` (`api/views.py:272`, `api/views.py:300`).
- `src/backend/finances/views/importer.py` never iterates a queryset touching related objects. It assigns `Category` and `PaymentMethod` instances it already holds in `cat_map` / `pm_map`, so `entry.category` is never a lazy fetch.

The *real* per-row query in the import path is `resolve_closing_day`, and it is what story S03-4 already targets — Task 4 below. So S03-5 is re-scoped from "add `select_related` to two named files" to its actual intent: **prove, with query-count tests at seeded scale, that the hot read paths do not scale their query count with row count, and fix whatever the measurement catches.** That is Task 5. If the measurement finds nothing, the tests are still the deliverable — they are what stops E04's ~200-site rewrite from quietly reintroducing an N+1.

Surface this to the owner when the plan is reviewed; do not silently drop the story.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/backend/finances/management/commands/seed_perf_data.py` (create) | Build a database at product scale, deterministically |
| `docs/architecture/query-performance-baseline.md` (create) | The written before/after: query counts, timings, `EXPLAIN ANALYZE` output |
| `src/backend/finances/models/entry.py` (modify) | `Meta.indexes` |
| `src/backend/finances/models/income.py` (modify) | `Meta.indexes` |
| `src/backend/finances/migrations/0010_query_indexes.py` (create) | Entry + Income indexes |
| `src/backend/assistant/models.py` (modify) | `ChatMessage`, `ReceiptDraft` and `MemoryEmbedding` `Meta.indexes` |
| `src/backend/assistant/migrations/0006_query_indexes.py` (create) | Chat/draft B-tree indexes + the HNSW vector index |
| `src/backend/assistant/agents/memory.py` (modify) | `find_semantic_matches` — order+limit in SQL, threshold in Python |
| `src/backend/finances/services/billing.py` (modify) | `resolve_closing_day` reads a prefetchable cache |
| `src/backend/finances/views/importer.py` (modify) | Prefetch `monthly_closing_days` when building `pm_map` |

Tests:

| File | Covers |
|---|---|
| `src/backend/finances/tests/test_query_indexes.py` (create) | Task 2 — index existence and index *usage* |
| `src/backend/assistant/tests/test_semantic_index.py` (create) | Task 3 |
| `src/backend/finances/tests/test_import_query_count.py` (create) | Task 4 |
| `src/backend/finances/tests/test_hot_path_query_counts.py` (create) | Task 5 |

> **Migration numbering.** If E01 has already landed, `assistant/migrations/0006_assistant_usage_event.py` exists and this epic's assistant migration becomes `0007_query_indexes.py`. Check `ls src/backend/assistant/migrations/` before naming it, and let `makemigrations` pick the number.

---

### Task 1: Measure first

No index is added in this task. Without a before-number the after-number means nothing, and the epic's DoD is a comparison.

**Files:**
- Create: `src/backend/finances/management/commands/seed_perf_data.py`
- Create: `docs/architecture/query-performance-baseline.md`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `python manage.py seed_perf_data --users N --entries-per-user M --anchor YYYY-MM --seed S` — idempotent-by-truncation seeding for a throwaway database
  - `docs/architecture/query-performance-baseline.md` — Tasks 2, 3 and 6 append their "after" sections to it

- [ ] **Step 1: Confirm the current state — zero declared indexes**

```bash
grep -rn 'Index' src/backend/*/migrations/*.py ; echo "exit=$?"
```

Expected: no output, `exit=1`. This is finding H1 and is the thing this epic closes.

- [ ] **Step 2: Write the seeding command**

Create `src/backend/finances/management/commands/seed_perf_data.py`:

```python
"""Seed a database at product scale so query plans are meaningful.

Production today is one user with ~2,000 entries — small enough that Postgres
correctly sequential-scans everything, so measuring there proves nothing about
whether an index would be used. This builds a database where a
``filter(user, billing_month)`` returns tens of rows out of tens of thousands,
which is where the planner's choice actually becomes visible.

Destructive: it truncates the tables it fills. Never point it at production.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assistant.models import ChatMessage, MemoryEmbedding, MessageRole
from core.models import CustomUser
from finances.models import Category, Entry, EntryType, Income, PaymentMethod

CATEGORY_NAMES = [
    "Alimentação", "Lanche", "Combustível", "Lazer", "Farmácia",
    "Álcool", "Casa", "Transporte", "Saúde", "Educação",
]
EMBEDDING_DIMENSIONS = 1536


class Command(BaseCommand):
    help = "Seed synthetic data at product scale for query-plan measurement."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=200)
        parser.add_argument("--entries-per-user", type=int, default=250)
        parser.add_argument(
            "--anchor",
            type=str,
            default="2026-08",
            help="YYYY-MM the generated window ends on. Explicit so runs are "
            "reproducible and the command never reads the wall clock.",
        )
        parser.add_argument("--seed", type=int, default=20260808)
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required. Confirms you understand this truncates tables.",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError(
                "This TRUNCATES entries, incomes, chat messages and embeddings. "
                "Re-run with --yes if that is what you want."
            )
        try:
            year, month = (int(p) for p in options["anchor"].split("-"))
            anchor = date(year, month, 1)
        except (ValueError, TypeError) as exc:
            raise CommandError("--anchor must look like 2026-08") from exc

        rng = random.Random(options["seed"])
        n_users = options["users"]
        per_user = options["entries_per_user"]

        self.stdout.write("Truncating…")
        Entry.objects.all().delete()
        Income.objects.all().delete()
        ChatMessage.objects.all().delete()
        MemoryEmbedding.objects.all().delete()
        CustomUser.objects.filter(username__startswith="perf_").delete()

        for index in range(n_users):
            self._seed_user(rng, index, per_user, anchor)
            if (index + 1) % 25 == 0:
                self.stdout.write(f"  {index + 1}/{n_users} users")

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {n_users} users, {Entry.objects.count()} entries, "
                f"{Income.objects.count()} incomes, "
                f"{ChatMessage.objects.count()} chat messages, "
                f"{MemoryEmbedding.objects.count()} embeddings."
            )
        )

    @transaction.atomic
    def _seed_user(self, rng, index, per_user, anchor):
        user = CustomUser.objects.create(username=f"perf_{index:04d}")
        categories = [
            Category.objects.create(user=user, name=name) for name in CATEGORY_NAMES
        ]
        pix = PaymentMethod.objects.create(user=user, name="Pix", type="pix")
        card = PaymentMethod.objects.create(
            user=user, name="Crédito", type="credit_card", closing_day=25
        )

        # 24 months of history ending at the anchor.
        entries = []
        for _ in range(per_user):
            months_back = rng.randint(0, 23)
            billing_month = _add_months(anchor, -months_back)
            entry_date = billing_month + timedelta(days=rng.randint(0, 27))
            entries.append(
                Entry(
                    user=user,
                    date=entry_date,
                    amount=Decimal(rng.randrange(500, 40000)) / 100,
                    description=f"Lançamento sintético {rng.randrange(10**6)}",
                    category=rng.choice(categories),
                    payment_method=rng.choice([pix, card]),
                    entry_type=rng.choices(
                        [EntryType.REGULAR, EntryType.INSTALLMENT, EntryType.SYSTEMIC],
                        weights=[80, 12, 8],
                    )[0],
                    billing_month=billing_month,
                    # Pre-computed and pinned: bulk_create bypasses save(), so the
                    # billing month has to be right going in.
                    billing_month_override=True,
                )
            )
        Entry.objects.bulk_create(entries, batch_size=500)

        Income.objects.bulk_create(
            [
                Income(
                    user=user,
                    name="Salário",
                    amount=Decimal("5000.00"),
                    month=_add_months(anchor, -back),
                )
                for back in range(12)
            ]
        )

        ChatMessage.objects.bulk_create(
            [
                ChatMessage(
                    user=user,
                    role=MessageRole.USER if turn % 2 == 0 else MessageRole.ASSISTANT,
                    content=f"mensagem sintética {turn}",
                )
                for turn in range(20)
            ]
        )

        MemoryEmbedding.objects.bulk_create(
            [
                MemoryEmbedding(
                    user=user,
                    text=f"regra sintética {slot}",
                    embedding=[rng.random() for _ in range(EMBEDDING_DIMENSIONS)],
                )
                for slot in range(10)
            ]
        )


def _add_months(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)
```

- [ ] **Step 3: Create a throwaway database and seed it**

Never run this against the dev database you use daily, and never against Supabase.

```bash
PGPASSWORD=postgres createdb -h localhost -p 5433 -U postgres expense_tracker_perf

POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf \
  uv run python src/backend/manage.py migrate

POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf \
  uv run python src/backend/manage.py seed_perf_data --yes
```

Expected, after a few minutes: `Seeded 200 users, 50000 entries, 2400 incomes, 4000 chat messages, 2000 embeddings.`

**Common failure:** `relation "vector" does not exist` on the embedding insert means the `vector` extension is missing. It is created by `assistant/migrations/0004_add_memory_embedding.py`, so this means `migrate` did not complete — re-run it and read the output.

- [ ] **Step 4: Capture the "before" query plans**

```bash
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d expense_tracker_perf <<'SQL' > /tmp/e03-before.txt
\timing on
\echo '--- Entry: (user, billing_month) — the dashboard core predicate'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
    AND billing_month = DATE '2026-08-01';

\echo '--- Entry: (user, billing_month, entry_type)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
    AND billing_month = DATE '2026-08-01' AND entry_type = 'installment';

\echo '--- Entry: (user, billing_month IN 6 months)'
EXPLAIN (ANALYZE, BUFFERS) SELECT billing_month, sum(amount) FROM finances_entry
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
    AND billing_month IN (DATE '2026-08-01', DATE '2026-07-01', DATE '2026-06-01',
                          DATE '2026-05-01', DATE '2026-04-01', DATE '2026-03-01')
  GROUP BY billing_month;

\echo '--- Entry: recent list (user, -date)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_entry
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
  ORDER BY date DESC, created_at DESC LIMIT 50;

\echo '--- Income: (user, month)'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM finances_income
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
    AND month = DATE '2026-08-01';

\echo '--- ChatMessage: history load'
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM assistant_chatmessage
  WHERE user_id = (SELECT id FROM core_customuser WHERE username='perf_0100')
  ORDER BY created_at DESC LIMIT 20;

\echo '--- MemoryEmbedding: cosine nearest neighbours'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, text FROM assistant_memoryembedding
  ORDER BY embedding <=> (SELECT embedding FROM assistant_memoryembedding LIMIT 1)
  LIMIT 5;
SQL

grep -c "Seq Scan" /tmp/e03-before.txt
```

Expected: every plan shows `Seq Scan on finances_entry` / `assistant_chatmessage` / `assistant_memoryembedding`, and the `grep -c` returns a non-zero count. That count is the "before" number.

- [ ] **Step 5: Capture the "before" query counts from Django**

```bash
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf \
  uv run python src/backend/manage.py shell -c "
import time
from datetime import date
from django.db import connection, reset_queries
from django.conf import settings
from django.test import Client
from core.models import CustomUser

settings.DEBUG = True   # required for connection.queries to record anything
user = CustomUser.objects.get(username='perf_0100')
client = Client()
client.force_login(user)

for path in [
    '/api/dashboard/summary/?year=2026&month=8',
    '/api/dashboard/top-categories/?year=2026&month=8',
    '/api/dashboard/evolution/?year=2026&month=8',
    '/api/dashboard/alerts/?year=2026&month=8',
    '/api/dashboard/recent-entries/?year=2026&month=8',
    '/api/dashboard/installments/?year=2026&month=8',
    '/entries/2026/8/',
    '/projection/?start=2026-07&months=14',
    '/consolidated/',
]:
    reset_queries()
    started = time.perf_counter()
    response = client.get(path)
    elapsed = (time.perf_counter() - started) * 1000
    print(f'{response.status_code}  {len(connection.queries):4d} queries  {elapsed:7.1f} ms  {path}')
"
```

The exact URLs come from `src/backend/finances/api/urls.py` — read that file and correct any path that 404s rather than recording a 404 as a result.

- [ ] **Step 6: Write the baseline document**

Create `docs/architecture/query-performance-baseline.md`:

````markdown
# Query performance baseline

Measured for **E03**, at `<commit sha>` on `<date>`, against a throwaway database
seeded by `manage.py seed_perf_data --yes` (200 users, ~50,000 entries, 24 months
of history, anchor 2026-08). Production today is one user with ~2,000 entries —
too small for the planner's choice to be visible, which is why the numbers below
come from synthetic scale.

## Method

```bash
PGPASSWORD=postgres createdb -h localhost -p 5433 -U postgres expense_tracker_perf
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf uv run python src/backend/manage.py seed_perf_data --yes
```

Then the `EXPLAIN (ANALYZE, BUFFERS)` script and the Django client loop from
`docs/superpowers/plans/2026-08-08-E03-query-performance-floor.md`, Task 1.

## Before — no declared indexes

`grep -rn 'Index' src/backend/*/migrations/*.py` returned nothing.

| Endpoint | Queries | Wall time |
|---|---|---|
| `/api/dashboard/summary/` | | |
| `/api/dashboard/top-categories/` | | |
| `/api/dashboard/evolution/` | | |
| `/api/dashboard/alerts/` | | |
| `/api/dashboard/recent-entries/` | | |
| `/api/dashboard/installments/` | | |
| `/entries/2026/8/` | | |
| `/projection/` | | |
| `/consolidated/` | | |

| Query | Plan | Rows scanned | Time |
|---|---|---|---|
| `Entry(user, billing_month)` | Seq Scan | | |
| `Entry(user, billing_month, entry_type)` | Seq Scan | | |
| `Entry(user, billing_month IN 6)` | Seq Scan | | |
| `Entry(user) ORDER BY -date LIMIT 50` | Seq Scan | | |
| `Income(user, month)` | Seq Scan | | |
| `ChatMessage(user) ORDER BY -created_at LIMIT 20` | Seq Scan | | |
| `MemoryEmbedding ORDER BY embedding <=> q LIMIT 5` | Seq Scan | | |

<details>
<summary>Raw EXPLAIN output</summary>

```
<paste /tmp/e03-before.txt verbatim>
```

</details>

## After

Filled in by Task 2, Task 3 and Task 6.

## Re-run this after E04

E04 changes the tenant column from `user` to `household`, which changes the
leading column of every index below. Re-run the same script and append an
"After E04" section — the comparison is only meaningful against a baseline
measured the same way.
````

Fill in every blank cell from Steps 4 and 5. A table of empty cells is not a baseline.

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances/management/commands/seed_perf_data.py \
        docs/architecture/query-performance-baseline.md
git commit -m "perf(measure): seed at product scale and record the pre-index baseline"
```

---

### Task 2: Index the relational hot paths

**Files:**
- Modify: `src/backend/finances/models/entry.py:51-54` (`Meta`)
- Modify: `src/backend/finances/models/income.py:23-26` (`Meta`)
- Modify: `src/backend/assistant/models.py` (`ChatMessage.Meta`, `ReceiptDraft.Meta`)
- Create: `src/backend/finances/migrations/0010_query_indexes.py` (generated)
- Create: `src/backend/assistant/migrations/000N_query_indexes.py` (generated; N depends on whether E01 landed)
- Create: `src/backend/finances/tests/test_query_indexes.py`
- Modify: `docs/architecture/query-performance-baseline.md` (the "After" section)

**Interfaces:**
- Consumes from Task 1: the seeded database and the baseline document.
- Produces these index names, which Task 5's tests and the DoD grep reference:
  - `entry_user_billing_type_idx` on `Entry(user, billing_month, entry_type)`
  - `entry_user_date_recent_idx` on `Entry(user, -date, -created_at)`
  - `income_user_month_idx` on `Income(user, month)`
  - `chat_user_recent_idx` on `ChatMessage(user, -created_at)`
  - `draft_user_status_recent_idx` on `ReceiptDraft(user, status, -created_at)`

**Index-shape reasoning — read before writing the migration.** The epic asks for `(user, billing_month)` *and* `(user, entry_type, billing_month)` as separate indexes. One composite `(user, billing_month, entry_type)` serves both: a B-tree index is usable by any query with equality on a *prefix* of its columns, so it answers `filter(user, billing_month)` (two-column prefix) and `filter(user, billing_month, entry_type)` (full match) alike. Two indexes would double the write cost and the bloat for no read benefit. The epic itself says "Index order matters … Verify with `EXPLAIN`, do not assume" — Step 5 does exactly that, and if `EXPLAIN` disagrees with this reasoning, believe `EXPLAIN` and split the index.

Similarly, `(user, -date, -created_at)` rather than the epic's `(user, date)`: `Entry.Meta.ordering` is `["-date", "-created_at"]` (`entry.py:54`), so every unordered `Entry` queryset sorts by both columns. Covering both lets the planner skip the sort entirely, not just the scan.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/finances/tests/test_query_indexes.py`:

```python
"""The hot query predicates must be index-backed, and the indexes must be used.

Two different assertions, deliberately. "The index exists" is a schema fact and
survives a refactor that stops using it; "the planner chose it" is the property
that actually makes a page fast. The second needs enough rows for the planner to
prefer an index, so those tests seed their own.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from model_bakery import baker

from assistant.models import ChatMessage, MessageRole, ReceiptDraft
from finances.models import Entry, Income

EXPECTED_INDEXES = {
    "finances_entry": {"entry_user_billing_type_idx", "entry_user_date_recent_idx"},
    "finances_income": {"income_user_month_idx"},
    "assistant_chatmessage": {"chat_user_recent_idx"},
    "assistant_receiptdraft": {"draft_user_status_recent_idx"},
}


def _index_names(table):
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", [table])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
@pytest.mark.parametrize("table,expected", sorted(EXPECTED_INDEXES.items()))
def test_expected_indexes_exist(table, expected):
    assert expected <= _index_names(table), (
        f"{table} is missing {expected - _index_names(table)}"
    )


@pytest.mark.django_db
class TestIndexesAreActuallyUsed:
    """Seed enough rows that a sequential scan is the wrong choice."""

    ROWS = 4000

    @pytest.fixture
    def bulk_user(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        Entry.objects.bulk_create(
            [
                Entry(
                    user=user,
                    date=date(2026, 1 + (i % 12), 1 + (i % 28)),
                    amount=Decimal("10.00"),
                    description=f"e{i}",
                    category=category,
                    payment_method=pm,
                    billing_month=date(2026, 1 + (i % 12), 1),
                    billing_month_override=True,
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        Income.objects.bulk_create(
            [
                Income(
                    user=user,
                    name=f"i{i}",
                    amount=Decimal("100.00"),
                    month=date(2026, 1 + (i % 12), 1),
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        ChatMessage.objects.bulk_create(
            [
                ChatMessage(user=user, role=MessageRole.USER, content=f"m{i}")
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        with connection.cursor() as cursor:
            # Without fresh statistics the planner works from defaults and may
            # choose a seq scan on a table it has never seen.
            cursor.execute(
                "ANALYZE finances_entry, finances_income, assistant_chatmessage;"
            )
        return user

    @staticmethod
    def _plan(queryset):
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN {sql}", params)
            return "\n".join(row[0] for row in cursor.fetchall())

    def test_entry_billing_month_predicate_uses_an_index(self, bulk_user):
        plan = self._plan(
            Entry.objects.filter(user=bulk_user, billing_month=date(2026, 3, 1))
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_user_billing_type_idx" in plan, plan

    def test_entry_type_predicate_uses_the_same_index(self, bulk_user):
        plan = self._plan(
            Entry.objects.filter(
                user=bulk_user, billing_month=date(2026, 3, 1), entry_type="installment"
            )
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_user_billing_type_idx" in plan, plan

    def test_entry_recent_ordering_uses_an_index(self, bulk_user):
        plan = self._plan(Entry.objects.filter(user=bulk_user)[:50])
        assert "Seq Scan" not in plan, plan
        assert "entry_user_date_recent_idx" in plan, plan

    def test_income_month_predicate_uses_an_index(self, bulk_user):
        plan = self._plan(Income.objects.filter(user=bulk_user, month=date(2026, 3, 1)))
        assert "Seq Scan" not in plan, plan
        assert "income_user_month_idx" in plan, plan

    def test_chat_history_load_uses_an_index(self, bulk_user):
        plan = self._plan(
            ChatMessage.objects.filter(user=bulk_user).order_by("-created_at")[:20]
        )
        assert "Seq Scan" not in plan, plan
        assert "chat_user_recent_idx" in plan, plan


@pytest.mark.django_db
def test_pending_draft_lookup_uses_an_index(user):
    """The lookup ``assistant/views.py:157-161`` runs on every chat turn."""
    ReceiptDraft.objects.bulk_create(
        [ReceiptDraft(user=user, payload={}, status="discarded") for _ in range(3000)],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_receiptdraft;")
    queryset = (
        ReceiptDraft.objects.filter(user=user, status="pending")
        .order_by("-created_at")[:1]
    )
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Seq Scan" not in plan, plan
    assert "draft_user_status_recent_idx" in plan, plan
```

`user` comes from `src/backend/finances/tests/conftest.py`, which covers `finances/tests/`. The `ReceiptDraft` test lives in this file rather than the assistant app so it can reuse that fixture.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_query_indexes.py -v
```

Expected: `test_expected_indexes_exist` FAILS for all four tables (`is missing {...}`), and every plan test FAILS on `assert "Seq Scan" not in plan`.

- [ ] **Step 3: Declare the indexes**

In `src/backend/finances/models/entry.py`, replace the `Meta` (lines 51-54):

```python
    class Meta:
        verbose_name = "entrada"
        verbose_name_plural = "entradas"
        ordering = ["-date", "-created_at"]
        indexes = [
            # The dashboard's core predicate. One composite instead of two
            # indexes: a B-tree serves any query with equality on a prefix, so
            # this answers filter(user, billing_month) and
            # filter(user, billing_month, entry_type) alike.
            models.Index(
                fields=["user", "billing_month", "entry_type"],
                name="entry_user_billing_type_idx",
            ),
            # Matches Meta.ordering exactly, so the planner can skip the sort as
            # well as the scan on every unordered Entry queryset.
            models.Index(
                fields=["user", "-date", "-created_at"],
                name="entry_user_date_recent_idx",
            ),
        ]
```

In `src/backend/finances/models/income.py`, replace the `Meta` (lines 23-26):

```python
    class Meta:
        verbose_name = "renda"
        verbose_name_plural = "rendas"
        ordering = ["-month", "name"]
        indexes = [
            models.Index(fields=["user", "month"], name="income_user_month_idx"),
        ]
```

In `src/backend/assistant/models.py`, replace `ChatMessage.Meta` (lines 26-29):

```python
    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["created_at"]
        indexes = [
            # Every chat turn loads the last ASSISTANT_MAX_HISTORY messages
            # newest-first (assistant/views.py:59-63), which is the opposite of
            # Meta.ordering — hence the explicit descending index.
            models.Index(fields=["user", "-created_at"], name="chat_user_recent_idx"),
        ]
```

and `ReceiptDraft.Meta` (lines 101-104):

```python
    class Meta:
        verbose_name = "rascunho de recibo"
        verbose_name_plural = "rascunhos de recibo"
        ordering = ["-created_at"]
        indexes = [
            # The pending-draft lookup on every chat turn
            # (assistant/views.py:157-161).
            models.Index(
                fields=["user", "status", "-created_at"],
                name="draft_user_status_recent_idx",
            ),
        ]
```

- [ ] **Step 4: Generate the migrations**

```bash
ls src/backend/assistant/migrations/    # confirm the next free number
uv run python src/backend/manage.py makemigrations finances --name query_indexes
uv run python src/backend/manage.py makemigrations assistant --name query_indexes
```

Expected: two files containing only `AddIndex` operations. Read both — `AddIndex` is reversible by construction, so there should be nothing to hand-write.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_query_indexes.py -v
```

Expected: all PASS.

If `test_entry_type_predicate_uses_the_same_index` fails while the two-column one passes, the composite-prefix reasoning above was wrong for this planner and data shape. Believe the plan output: split into `(user, billing_month)` and `(user, entry_type, billing_month)` as the epic originally specified, regenerate the migration, and record why in the baseline document.

- [ ] **Step 6: Prove reversibility**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0009
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0005
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Use whatever the previous migration numbers actually are — `0005` for assistant only if E01 has not landed. Expected: clean unapply and reapply, then `No changes detected`.

- [ ] **Step 7: Re-measure at scale and fill in the "After" section**

```bash
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf \
  uv run python src/backend/manage.py migrate
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d expense_tracker_perf \
  -c "ANALYZE;"
```

Re-run the `EXPLAIN` script and the Django client loop from Task 1 Steps 4 and 5, writing to `/tmp/e03-after.txt`, and fill in the "After" tables in `docs/architecture/query-performance-baseline.md` with both the plans and the timings.

Expected: `Index Scan` or `Bitmap Index Scan` naming the new indexes on every `Entry`, `Income` and `ChatMessage` plan. The vector query is still a `Seq Scan` — that is Task 3.

Write one sentence per row saying what changed. A table of numbers without a reading is not a comparison.

- [ ] **Step 8: Commit**

```bash
git add src/backend/finances/models/entry.py src/backend/finances/models/income.py \
        src/backend/assistant/models.py \
        src/backend/finances/migrations/0010_query_indexes.py \
        src/backend/assistant/migrations/*_query_indexes.py \
        src/backend/finances/tests/test_query_indexes.py \
        docs/architecture/query-performance-baseline.md
git commit -m "perf(db): composite indexes for the dashboard, chat history and draft lookups"
```

---

### Task 3: Index the vector column

**Files:**
- Modify: `src/backend/assistant/models.py` (`MemoryEmbedding.Meta`)
- Modify: `src/backend/assistant/agents/memory.py:27-36` (`find_semantic_matches`)
- Modify: the assistant migration from Task 2, or a new one — let `makemigrations` decide
- Create: `src/backend/assistant/tests/test_semantic_index.py`
- Modify: `docs/architecture/query-performance-baseline.md`

**Interfaces:**
- Consumes from Task 2: the migration numbering already settled.
- Produces: `memory_embedding_hnsw_cosine_idx`, and a `find_semantic_matches` whose signature is unchanged — `find_semantic_matches(user, query_vector, threshold=0.8, limit=5) -> list[MemoryEmbedding]`, each with a `.distance` attribute.

**The part that will be got wrong.** Adding the index is not enough. Today's query is:

```python
MemoryEmbedding.objects.filter(user=user)
    .annotate(distance=CosineDistance("embedding", query_vector))
    .filter(distance__lt=1 - threshold)
    .order_by("distance")[:limit]
```

That `.filter(distance__lt=…)` compiles to a `WHERE` clause over the distance expression, and pgvector's HNSW index cannot answer a range predicate — it answers *"give me the k nearest"*. With the `WHERE` in place, Postgres must compute the distance for every candidate row, so it sequential-scans no matter what index exists. The index only gets used for the `ORDER BY embedding <=> q LIMIT k` shape. So the threshold has to move out of SQL and into Python, after the limit.

This changes behaviour in one visible way: today the query returns "up to `limit` rows that are all within the threshold, chosen from every row that qualifies"; after the change it returns "the `limit` nearest rows, of which we keep the ones within the threshold". For an exhaustive scan those are identical. For an approximate index they can differ at the margin, which is why the tests below assert on the *rule being found*, not on a fixed row count.

- [ ] **Step 1: Write the failing tests**

Create `src/backend/assistant/tests/test_semantic_index.py`:

```python
"""Semantic memory search must use the HNSW index and keep finding the match.

An approximate index can reorder ties, so these tests assert that the expected
memory is returned — never that some exact list of five rows comes back in some
exact order.
"""

import random

import pytest
from django.db import connection

from assistant.agents.memory import find_semantic_matches
from assistant.models import MemoryEmbedding

DIMENSIONS = 1536


def _vector(rng):
    return [rng.random() for _ in range(DIMENSIONS)]


@pytest.fixture
def haystack(user):
    """One known needle plus enough noise that a seq scan is the wrong plan."""
    rng = random.Random(20260808)
    needle_vector = _vector(rng)
    needle = MemoryEmbedding.objects.create(
        user=user, text="mercado cosmos é alimentação", embedding=needle_vector
    )
    MemoryEmbedding.objects.bulk_create(
        [
            MemoryEmbedding(user=user, text=f"ruído {i}", embedding=_vector(rng))
            for i in range(3000)
        ],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_memoryembedding;")
    return needle, needle_vector


@pytest.mark.django_db
def test_hnsw_index_exists():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'assistant_memoryembedding'"
        )
        rows = dict(cursor.fetchall())
    assert "memory_embedding_hnsw_cosine_idx" in rows
    definition = rows["memory_embedding_hnsw_cosine_idx"]
    assert "hnsw" in definition.lower()
    assert "vector_cosine_ops" in definition


@pytest.mark.django_db
def test_exact_match_is_found(user, haystack):
    needle, needle_vector = haystack
    matches = find_semantic_matches(user, needle_vector, threshold=0.8, limit=5)
    assert needle.id in [m.id for m in matches]


@pytest.mark.django_db
def test_threshold_still_excludes_distant_rows(user, haystack):
    """A near-orthogonal probe must return nothing, index or no index."""
    _, needle_vector = haystack
    orthogonal = [-value for value in needle_vector]
    assert find_semantic_matches(user, orthogonal, threshold=0.99, limit=5) == []


@pytest.mark.django_db
def test_limit_is_respected(user, haystack):
    _, needle_vector = haystack
    assert len(find_semantic_matches(user, needle_vector, threshold=0.0, limit=3)) <= 3


@pytest.mark.django_db
def test_results_are_scoped_to_the_user(user, other_user, haystack):
    _, needle_vector = haystack
    MemoryEmbedding.objects.create(
        user=other_user, text="vizinho", embedding=needle_vector
    )
    matches = find_semantic_matches(user, needle_vector, threshold=0.0, limit=50)
    assert all(m.user_id == user.id for m in matches)


@pytest.mark.django_db
def test_the_nearest_neighbour_query_uses_the_hnsw_index(user, haystack):
    """The ORDER BY … LIMIT shape is the only one HNSW can answer.

    Asserted on raw SQL rather than through find_semantic_matches so the test
    fails loudly if someone reintroduces a WHERE on the distance expression.
    """
    _, needle_vector = haystack
    literal = "[" + ",".join(str(v) for v in needle_vector) + "]"
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off;")
        cursor.execute(
            "EXPLAIN SELECT id FROM assistant_memoryembedding "
            "ORDER BY embedding <=> %s::vector LIMIT 5",
            [literal],
        )
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "memory_embedding_hnsw_cosine_idx" in plan, plan
```

`other_user` is not defined in `src/backend/assistant/tests/conftest.py` — it only exists in the finances conftest. Add it to the assistant conftest:

```python
@pytest.fixture
def other_user(db):
    return baker.make("core.CustomUser", username="amanda")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_semantic_index.py -v
```

Expected: `test_hnsw_index_exists` FAILS on the missing index; `test_the_nearest_neighbour_query_uses_the_hnsw_index` FAILS because the plan shows a seq scan. The behavioural tests should already PASS — they pin the behaviour that must survive Step 3.

- [ ] **Step 3: Add the index**

In `src/backend/assistant/models.py`, add the import:

```python
from pgvector.django import HnswIndex, VectorField
```

and replace `MemoryEmbedding.Meta` (lines 123-125):

```python
    class Meta:
        verbose_name = "embedding de memória"
        verbose_name_plural = "embeddings de memória"
        indexes = [
            # pgvector's own defaults. At this scale — thousands of vectors, not
            # millions — they give effectively exhaustive recall, and raising
            # them costs build time and index memory on a Supabase instance that
            # is not sized for it. vector_cosine_ops must match the distance
            # operator used by CosineDistance (<=>), or the index is ignored.
            HnswIndex(
                name="memory_embedding_hnsw_cosine_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
```

- [ ] **Step 4: Rewrite the search so the index can be used**

Replace `find_semantic_matches` in `src/backend/assistant/agents/memory.py` (lines 27-36):

```python
def find_semantic_matches(
    user, query_vector: list[float], threshold: float = 0.8, limit: int = 5
) -> list:
    """Memory embeddings similar to ``query_vector``, nearest first.

    The threshold is applied in Python, deliberately. A ``WHERE distance < x``
    predicate makes Postgres compute the distance for every candidate row, which
    means a sequential scan no matter what index exists — pgvector's HNSW index
    answers "the k nearest", not "everything within a radius". Ordering and
    limiting in SQL, then filtering the small result set here, is what lets the
    index do its job.
    """
    max_distance = 1 - threshold
    nearest = (
        MemoryEmbedding.objects.filter(user=user)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[:limit]
    )
    return [match for match in nearest if match.distance < max_distance]
```

- [ ] **Step 5: Generate the migration**

```bash
uv run python src/backend/manage.py makemigrations assistant --name memory_hnsw_index
```

Expected: a single `AddIndex` with an `HnswIndex`. Read it — it must import `pgvector.django.indexes.HnswIndex` and it must be reversible via `RemoveIndex`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_semantic_index.py -v
```

Expected: all PASS.

- [ ] **Step 7: Run the whole assistant app — semantic memory has existing tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```

Expected: no failures, in particular `test_semantic_memory.py` and `test_memory.py`. If a test that asserted an exact ordering now fails, read it before changing it: an approximate index legitimately reorders near-ties, but a *missing* expected match is a recall problem, not a test problem. In that case raise `ef_search` at query time (`SET LOCAL hnsw.ef_search = 100;`) or raise `m`, and record the change and its reason in the baseline document.

- [ ] **Step 8: Verify against seeded scale, and record it**

```bash
POSTGRES_PORT=5433 POSTGRES_DB=expense_tracker_perf \
  uv run python src/backend/manage.py migrate
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d expense_tracker_perf <<'SQL'
ANALYZE assistant_memoryembedding;
EXPLAIN (ANALYZE, BUFFERS) SELECT id, text FROM assistant_memoryembedding
  ORDER BY embedding <=> (SELECT embedding FROM assistant_memoryembedding LIMIT 1)
  LIMIT 5;
SQL
```

Expected: `Index Scan using memory_embedding_hnsw_cosine_idx`. Add the before/after rows to `docs/architecture/query-performance-baseline.md`.

**If it still seq-scans at 2,000 rows:** that is the planner being right, not the index being broken — an HNSW traversal is not cheaper than reading 2,000 rows. Re-run with `SET LOCAL enable_seqscan = off;` to confirm the index *can* be used (which is what the test asserts), then say so explicitly in the baseline document rather than claiming a speedup that does not exist at current scale.

- [ ] **Step 9: Commit**

```bash
git add src/backend/assistant/models.py src/backend/assistant/agents/memory.py \
        src/backend/assistant/migrations/*_memory_hnsw_index.py \
        src/backend/assistant/tests/test_semantic_index.py \
        src/backend/assistant/tests/conftest.py \
        docs/architecture/query-performance-baseline.md
git commit -m "perf(memory): HNSW cosine index and an ORDER BY/LIMIT search that uses it"
```

---

### Task 4: Remove the per-row query in the import path

**Files:**
- Modify: `src/backend/finances/services/billing.py:6-18` (`resolve_closing_day`)
- Modify: `src/backend/finances/views/importer.py:283` (`pm_map` construction)
- Create: `src/backend/finances/tests/test_import_query_count.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `resolve_closing_day(payment_method, entry_date) -> int | None` — unchanged signature, but it now iterates `payment_method.monthly_closing_days.all()` so a `prefetch_related` cache is honoured.

**The mechanism, precisely.** For each imported row, `ImportExecuteView.post` does:

1. `resolve_closing_day(payment_method, entry_date)` → `payment_method.monthly_closing_days.filter(month=month).first()` — **one query**
2. `Entry.objects.create(...)` → `Entry.save()` (`entry.py:59-66`) recomputes the billing month because `billing_month_override=False`, calling `resolve_closing_day` again — **one more query**
3. the `INSERT` — **one query**

That is the ~3 queries per row the epic describes. The fix is not to skip the recomputation (`billing_month_override=True` means *the user pinned this month* and is read by `backfill_billing_months`; setting it on imports would corrupt that meaning). The fix is to make the lookup free: `.filter()` on a related manager always hits the database, but `.all()` returns the `prefetch_related` cache when one exists. Filter in Python, prefetch once, and the loop becomes O(payment methods) instead of O(rows).

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_import_query_count.py`:

```python
"""Importing N rows must not cost O(N) closing-day lookups.

The importer resolves the card's closing day per row, and Entry.save() resolves
it again — both through a related-manager .filter(), which always queries. With
a prefetch and an in-Python filter the whole loop pays for it once.
"""

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from model_bakery import baker

from finances.models import Entry, PaymentMethodClosingDay
from finances.services.billing import resolve_closing_day

CSV_HEADER = "date,description,amount,category,payment_method\n"


def _csv(rows):
    body = CSV_HEADER + "".join(
        f"2026-03-{1 + (i % 27):02d},compra {i},{10 + i}.00,Alimentação,Crédito\n"
        for i in range(rows)
    )
    return SimpleUploadedFile("import.csv", body.encode(), content_type="text/csv")


@pytest.fixture
def import_fixtures(user):
    baker.make("finances.Category", user=user, name="Alimentação")
    return baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito",
        type="credit_card",
        closing_day=25,
    )


@pytest.mark.django_db
class TestResolveClosingDayUsesThePrefetchCache:
    def test_override_is_still_honoured(self, user, import_fixtures):
        pm = import_fixtures
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 3, 1), closing_day=10
        )
        assert resolve_closing_day(pm, date(2026, 3, 15)) == 10

    def test_falls_back_to_the_default_closing_day(self, user, import_fixtures):
        pm = import_fixtures
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 4, 1), closing_day=10
        )
        assert resolve_closing_day(pm, date(2026, 3, 15)) == 25

    def test_no_override_at_all(self, user, import_fixtures):
        assert resolve_closing_day(import_fixtures, date(2026, 3, 15)) == 25

    def test_a_prefetched_payment_method_costs_zero_queries(
        self, user, import_fixtures, django_assert_num_queries
    ):
        from finances.models import PaymentMethod

        PaymentMethodClosingDay.objects.create(
            payment_method=import_fixtures, month=date(2026, 3, 1), closing_day=10
        )
        pm = (
            PaymentMethod.objects.filter(pk=import_fixtures.pk)
            .prefetch_related("monthly_closing_days")
            .first()
        )
        with django_assert_num_queries(0):
            for day in range(1, 21):
                resolve_closing_day(pm, date(2026, 3, day))


@pytest.mark.django_db
class TestImportQueryCount:
    """The gate: query count must be near-flat in the number of rows."""

    def _run_import(self, client, rows):
        client.post("/import/", {"file": _csv(rows), "import_type": "regular"})
        client.post("/import/map/", {})
        client.post("/import/preview/", {})
        return client.post("/import/execute/", {})

    def test_importing_more_rows_does_not_multiply_the_query_count(
        self, logged_client, import_fixtures
    ):
        """Compare 10 rows against 50 — the slope is what matters, not the value.

        An absolute bound would encode today's implementation. Measuring the
        marginal cost per row survives refactors and still catches an N+1.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            self._run_import(logged_client, 10)
        small_count = len(small.captured_queries)

        Entry.objects.all().delete()

        with CaptureQueriesContext(connection) as large:
            self._run_import(logged_client, 50)
        large_count = len(large.captured_queries)

        per_row = (large_count - small_count) / 40
        assert per_row <= 1.5, (
            f"{per_row:.2f} queries per imported row "
            f"(10 rows -> {small_count}, 50 rows -> {large_count})"
        )

    def test_the_import_still_creates_the_entries(self, logged_client, import_fixtures):
        self._run_import(logged_client, 10)
        assert Entry.objects.count() == 10

    def test_billing_month_is_still_computed_from_the_closing_day(
        self, logged_client, import_fixtures
    ):
        self._run_import(logged_client, 10)
        # closing_day=25: a purchase on the 1st-25th of March lands on the May
        # invoice month (closes in March, paid in April... see billing.py).
        entry = Entry.objects.filter(date=date(2026, 3, 1)).first()
        assert entry is not None
        assert entry.billing_month == date(2026, 4, 1)
```

The three-POST flow in `_run_import` mirrors `ImportUploadView` → `ImportMappingView` → `ImportPreviewView` → `ImportExecuteView`. Read `src/backend/finances/views/importer.py` and `src/backend/finances/tests/test_views_importer.py` and match the exact form fields each step expects — copy the working sequence from the existing test file rather than inventing one. The `test_billing_month_is_still_computed_from_the_closing_day` expectation must be derived from `compute_billing_month` in `finances/services/billing.py:20-45`, not guessed: run it once in a shell and assert what it actually returns.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_query_count.py -v
```

Expected: `test_a_prefetched_payment_method_costs_zero_queries` FAILS (`20 queries executed, 0 expected`) and `test_importing_more_rows_does_not_multiply_the_query_count` FAILS with roughly 3 queries per row. The three behavioural tests PASS — they pin what must not change.

- [ ] **Step 3: Make `resolve_closing_day` cache-friendly**

Replace it in `src/backend/finances/services/billing.py`:

```python
def resolve_closing_day(payment_method, entry_date: date) -> int | None:
    """Resolve the closing day applicable to ``entry_date`` for a payment method.

    Looks up a per-month override (:class:`PaymentMethodClosingDay`) for the
    month of ``entry_date``; falls back to the payment method's default
    ``closing_day`` when there is no override.

    Iterates ``.all()`` and filters in Python rather than calling ``.filter()``:
    a related manager's ``.filter()`` always issues a query, while ``.all()``
    returns the ``prefetch_related`` cache when the caller has one. The CSV
    importer creates hundreds of entries against a handful of payment methods,
    and this is the difference between one query and one per row — twice per
    row, in fact, because ``Entry.save()`` calls this again.

    A payment method has at most a handful of monthly overrides, so scanning
    them in Python is free.
    """
    month = entry_date.replace(day=1)
    for override in payment_method.monthly_closing_days.all():
        if override.month == month:
            return override.closing_day
    return payment_method.closing_day
```

- [ ] **Step 4: Prefetch in the importer**

In `src/backend/finances/views/importer.py`, replace line 283:

```python
        pm_map = {p.name.lower(): p for p in PaymentMethod.objects.filter(user=user)}
```

with:

```python
        # Prefetched so resolve_closing_day (called twice per row — here and
        # again inside Entry.save) reads a cache instead of querying.
        pm_map = {
            p.name.lower(): p
            for p in PaymentMethod.objects.filter(user=user).prefetch_related(
                "monthly_closing_days"
            )
        }
```

The same view creates payment methods from `pm_resolutions` and adds them to `pm_map` (lines 291-294). A freshly created instance has no prefetch cache, so its first `.all()` costs one query and then caches — bounded by the number of new payment methods, not by rows. That is acceptable; do not add a second prefetch pass for it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_import_query_count.py -v
```

Expected: all PASS, with the reported per-row cost at or near 1 (the `INSERT`).

- [ ] **Step 6: Run everything that touches billing — this function is load-bearing**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/ src/backend/assistant/ -q
```

Expected: no failures. `resolve_closing_day` is called from `Entry.save()`, `installment_billing_months`, the cockpit, the importer, and two management commands — a behaviour change here shows up far from the diff.

- [ ] **Step 7: Commit**

```bash
git add src/backend/finances/services/billing.py src/backend/finances/views/importer.py \
        src/backend/finances/tests/test_import_query_count.py
git commit -m "perf(import): resolve the closing day once per payment method, not per row"
```

---

### Task 5: Query-count guards on the hot read paths

Story S03-5, re-scoped per the finding above. The deliverable is the guard, whether or not it catches something today — E04 rewrites ~200 query sites, and these tests are what stop that rewrite from silently reintroducing an N+1.

**Files:**
- Create: `src/backend/finances/tests/test_hot_path_query_counts.py`
- Modify: whatever the tests catch

**Interfaces:**
- Consumes from Task 2: the indexes (they change plans, not query counts, but the tests run against the same models).
- Produces: nothing other tasks import.

- [ ] **Step 1: Write the guards**

Create `src/backend/finances/tests/test_hot_path_query_counts.py`:

```python
"""Query count on the hot read paths must not scale with row count.

Each test loads a page or endpoint twice — once with a few rows, once with many —
and asserts the query count barely moves. Measuring the *slope* rather than an
absolute bound means these survive refactors that legitimately add or remove a
query, while still failing loudly on an N+1.

E04 rewrites every tenant-scoped queryset in the project. These tests are what
that rewrite gets measured against.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from model_bakery import baker

from finances.models import Entry

BILLING_MONTH = date(2026, 3, 1)


@pytest.fixture
def scenario(user):
    """Categories and payment methods; entries are added per measurement."""
    categories = [
        baker.make("finances.Category", user=user, name=name)
        for name in ("Alimentação", "Lazer", "Casa", "Saúde")
    ]
    pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.Income",
        user=user,
        name="Salário",
        amount=Decimal("5000"),
        month=BILLING_MONTH,
    )
    return categories, pm


def _add_entries(user, categories, pm, count):
    Entry.objects.bulk_create(
        [
            Entry(
                user=user,
                date=date(2026, 3, 1 + (i % 27)),
                amount=Decimal("25.00"),
                description=f"lançamento {i}",
                category=categories[i % len(categories)],
                payment_method=pm,
                billing_month=BILLING_MONTH,
                billing_month_override=True,
            )
            for i in range(count)
        ],
        batch_size=200,
    )


def _queries_for(client, path):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"
    return len(captured.captured_queries)


HOT_PATHS = [
    "/api/dashboard/summary/?year=2026&month=3",
    "/api/dashboard/top-categories/?year=2026&month=3",
    "/api/dashboard/evolution/?year=2026&month=3",
    "/api/dashboard/alerts/?year=2026&month=3",
    "/api/dashboard/recent-entries/?year=2026&month=3",
    "/api/dashboard/installments/?year=2026&month=3",
    "/entries/2026/3/",
    "/consolidated/",
    "/projection/?start=2026-03&months=6",
]


@pytest.mark.django_db
@pytest.mark.parametrize("path", HOT_PATHS)
def test_query_count_does_not_scale_with_rows(logged_client, user, scenario, path):
    categories, pm = scenario

    _add_entries(user, categories, pm, 5)
    logged_client.get(path)  # warm any per-session work out of the measurement
    few = _queries_for(logged_client, path)

    _add_entries(user, categories, pm, 95)
    many = _queries_for(logged_client, path)

    assert many <= few + 2, (
        f"{path}: {few} queries at 5 entries, {many} at 100 — "
        f"the count scales with row count (N+1)"
    )
```

The paths must match `src/backend/finances/api/urls.py` and `src/backend/finances/urls.py`. Read both and correct any that 404 — the `assert response.status_code == 200` will tell you which.

- [ ] **Step 2: Run them and read what they say**

```bash
POSTGRES_PORT=5433 uv run pytest \
  src/backend/finances/tests/test_hot_path_query_counts.py -v
```

Two outcomes, both valid:

- **All PASS.** The hot paths are already N+1-free — which matches the static reading (`api/views.py:272` and `:300` already use `select_related`; `views/entries.py:108`, `views/consolidated.py:112`, `views/settings.py:176` likewise). The tests are the deliverable. Record in the commit message that the guards found nothing and that this confirms the finding about S03-5's premise.
- **Something FAILS.** Fix it with `select_related` (forward FK) or `prefetch_related` (reverse FK / M2M) on the offending queryset, guided by the failure message naming the path. Then re-run. Do not raise the `+2` tolerance to make a test pass — that tolerance exists for genuinely constant extra queries (a session write, a savepoint), not for a slope.

- [ ] **Step 3: Cross-check against the template that renders each path**

For any path that passes, confirm the test is actually exercising the related-object access — a template that renders zero rows cannot trigger an N+1. The templates that dereference `entry.category` / `entry.payment_method` are:

```bash
grep -rln "entry\.category\|entry\.payment_method\|s\.category\|s\.payment_method" \
  src/backend/templates/
```

Currently: `entries/_entry_card.html`, `entries/_entry_row.html`, `consolidated/_category_entries.html`, `settings/_systemics_tab.html`. Make sure a hot path in the list above renders each one; if `settings/_systemics_tab.html` is not covered, add `/settings/systemics/` to `HOT_PATHS`.

- [ ] **Step 4: Full suite and gates**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: no failures, `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/backend/finances/tests/test_hot_path_query_counts.py
git add -u src/backend/   # any select_related fixes from step 2
git commit -m "test(perf): guard the hot read paths against query counts that scale with rows"
```

---

### Task 6: Full Definition of Done, including Supabase

**Files:**
- Modify: `docs/architecture/query-performance-baseline.md` (the Supabase section)
- Modify: `docs/runbook.md` (how to apply a migration to Supabase)
- Modify: `docs/backlog/E03-query-performance-floor.md`, `docs/backlog/INDEX.md` (status)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: the evidence block pasted into the review.

- [ ] **Step 1: Migration applies and reverses**

```bash
# The target is the last migration BEFORE this epic's. Read them, do not guess:
uv run python src/backend/manage.py showmigrations finances assistant

POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate finances 0009
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate assistant 0005
POSTGRES_PORT=5433 uv run python src/backend/manage.py migrate
uv run python src/backend/manage.py makemigrations --check --dry-run
```

`assistant 0005` is correct only if E01 has not landed; if it has,
`0006_assistant_usage_event` is E01's and the target here is `0006`. The
`showmigrations` output above tells you which.

Expected: clean unapply and reapply both times, then `No changes detected`.

- [ ] **Step 2: Suite, coverage, lint**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && \
  uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Expected: zero failures, `TOTAL` ≥ 80%, `All checks passed!`

- [ ] **Step 3: Indexes now exist**

```bash
grep -rn 'Index' src/backend/*/migrations/*.py
```

Expected: hits in the new `finances` and `assistant` migrations. This is the exact inverse of Task 1 Step 1 — paste both outputs side by side.

- [ ] **Step 4: Apply against a Supabase copy, not only local Postgres**

The pooler has surprised this project before (`config/settings.py:84-94`), and index creation is the kind of DDL that behaves differently through pgbouncer in transaction mode.

**Migrations must use the Supabase direct/session connection on port 5432, never the transaction pooler on 6543** — the pooler does not support everything migrations need. This is already documented in `.env.example`.

Take a copy first. Do not test DDL on the live database:

```bash
# 1. Snapshot production
pg_dump "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  --no-owner --no-acl -Fc -f /tmp/ledger-prod.dump

# 2. Restore into a scratch database on the same Supabase project (or a local
#    container if the project has no spare database)
createdb -h HOST -p 5432 -U USER ledger_e03_test
pg_restore -h HOST -p 5432 -U USER -d ledger_e03_test --no-owner /tmp/ledger-prod.dump

# 3. Migrate the copy
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/ledger_e03_test?sslmode=require" \
  uv run python src/backend/manage.py migrate

# 4. Confirm the indexes landed
psql "postgresql://USER:PASSWORD@HOST:5432/ledger_e03_test?sslmode=require" -c "
  SELECT tablename, indexname FROM pg_indexes
   WHERE indexname IN ('entry_user_billing_type_idx','entry_user_date_recent_idx',
                       'income_user_month_idx','chat_user_recent_idx',
                       'draft_user_status_recent_idx',
                       'memory_embedding_hnsw_cosine_idx')
   ORDER BY tablename;"

# 5. Drop the copy
dropdb -h HOST -p 5432 -U USER ledger_e03_test
```

Expected: six rows in step 4. Record the output in the baseline document under a "Supabase" heading.

**Common failure #1:** `CREATE EXTENSION vector` denied on the restored database. Supabase enables `vector` per-database; enable it on the copy (`CREATE EXTENSION IF NOT EXISTS vector;` as the owner) before migrating.

**Common failure #2:** the HNSW build runs out of `maintenance_work_mem` on a small Supabase instance. At 2,000 vectors this will not happen; if it does, `SET maintenance_work_mem = '256MB';` in the session before migrating, and note in the baseline document that production needs the same.

- [ ] **Step 5: Document the Supabase migration procedure in the runbook**

Add to `docs/runbook.md`:

````markdown
## Applying a migration to Supabase

Migrations go through the **direct/session connection on port 5432**, never the
transaction pooler on 6543 — the pooler is pgbouncer in transaction mode and does
not support everything a migration needs. The app runtime uses 6543; migrations
do not.

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  uv run python src/backend/manage.py migrate
```

For anything schema-heavy — a new index, a column type change — rehearse it on a
restored copy first:

```bash
pg_dump "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require" \
  --no-owner --no-acl -Fc -f /tmp/ledger-prod.dump
createdb -h HOST -p 5432 -U USER ledger_rehearsal
pg_restore -h HOST -p 5432 -U USER -d ledger_rehearsal --no-owner /tmp/ledger-prod.dump
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/ledger_rehearsal?sslmode=require" \
  uv run python src/backend/manage.py migrate
dropdb -h HOST -p 5432 -U USER ledger_rehearsal
```

**Common failure:** `CREATE EXTENSION vector` is denied on a restored copy.
Supabase enables extensions per database — run
`CREATE EXTENSION IF NOT EXISTS vector;` on the copy as its owner first.
````

- [ ] **Step 6: Confirm each of the epic's observable assertions**

- [ ] A written before/after comparison exists with query counts and timings at seeded scale → `docs/architecture/query-performance-baseline.md`, every cell filled
- [ ] `EXPLAIN ANALYZE` shows index scans (not sequential scans) on the hot `Entry` and `Income` queries → the "After" section
- [ ] `EXPLAIN ANALYZE` shows the HNSW index used for semantic search → Task 3, Step 8, including the honest note if the planner still prefers a seq scan at current scale
- [ ] Query-count tests guard the import path and the hot read paths → `test_import_query_count.py`, `test_hot_path_query_counts.py`
- [ ] The migration has been applied against a Supabase copy, not only local Postgres → Step 4 output

- [ ] **Step 7: Clean up the throwaway database**

```bash
PGPASSWORD=postgres dropdb -h localhost -p 5433 -U postgres expense_tracker_perf
```

- [ ] **Step 8: Update the epic's status**

Change `status: ready` to `status: review` in the frontmatter of `docs/backlog/E03-query-performance-floor.md`, and update the E03 row in the §4 table of `docs/backlog/INDEX.md`. E03 blocks nothing, so no other row changes.

```bash
git add docs/backlog/ docs/runbook.md docs/architecture/query-performance-baseline.md
git commit -m "chore(backlog): E03 to review — indexes measured before and after"
```

- [ ] **Step 9: Hand off for review**

Run `superpowers:requesting-code-review`, then `superpowers:verification-before-completion` — paste the before/after `EXPLAIN ANALYZE` output as the evidence, as the epic's skill pipeline requires — then `superpowers:finishing-a-development-branch`.
