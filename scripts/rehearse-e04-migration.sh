#!/usr/bin/env bash
# Rehearse the WHOLE E04 tenancy chain against a COPY of production Supabase
# data — accounts/0001-0003, finances/0013-0019, assistant/0010-0016, in one go,
# which is exactly what the next deploy applies.
#
# The epic's Definition of Done: "entry counts, balances, and the monthly
# acumulado match before and after". No E04 phase changes what a read path
# *reports*, so the two fingerprints must match — any diff is corruption.
#
# Production is touched exactly once, read-only, by pg_dump. The copy is
# restored into a throwaway LOCAL container, so nothing here can create,
# migrate or drop a database on the production server.
#
# The dump holds every row of the real ledger. It lives in a 0700 temp dir
# that a trap removes on ANY exit — including the fingerprint-mismatch exit,
# which is the one you actually care about.
#
# Credentials come from libpq/Django env vars, never a URL: the production
# password contains a space (docs/runbook.md, "Common failure #2").
#
# TWO OBSERVERS, ONE EXPERIMENT. Through phases 2 and 3 the observer was pinned
# and the schema varied. Phase 4 drops `user` outright, so no single version of
# `dump_ledger_totals` can read both sides: the pinned one reads
# `finances_entry.user_id` (gone after the migration), the working-tree one
# reads `household_id` (absent before it). Each side is therefore read by the
# observer that fits its schema, and the BEFORE keys — usernames — are mapped
# through the same rule the seed migration used, so the two reports compare.
# See `normalise_before` below.
#
# To prove phase 3 itself moved no money — a *code*-version question, not a
# schema one — use scripts/verify-e04-phase3-money.sh instead.
#
# Required env: PGHOST PGPORT PGUSER PGPASSWORD PGSSLMODE
# Optional env: BEFORE_REF SOURCE_DB COPY LOCAL_PORT IMAGE CLIENT_IMAGE
# Usage: scripts/rehearse-e04-migration.sh
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The BEFORE observer: the last commit whose `dump_ledger_totals` reads `user`.
# de143a1 = "Merge E04 phase 2 leftovers"; set to "" to use the working tree,
# which only makes sense against a source that is already migrated.
BEFORE_REF="${BEFORE_REF-de143a1}"
COPY="${COPY:-ledger_rehearsal}"
SOURCE_DB="${SOURCE_DB:-postgres}"  # Supabase's database is `postgres`
IMAGE="${IMAGE:-pgvector/pgvector:pg17}"
CLIENT_IMAGE="${CLIENT_IMAGE:-postgres:17}"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-e04-rehearsal-$$}"
LOCAL_PORT="${LOCAL_PORT:-55432}"
LOCAL_PASSWORD="rehearsal"  # throwaway container, bound to 127.0.0.1 only
: "${PGHOST:?set PGHOST}" "${PGUSER:?set PGUSER}" "${PGPASSWORD:?set PGPASSWORD}"
export PGPORT="${PGPORT:-5432}" PGSSLMODE="${PGSSLMODE:-require}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/e04-rehearsal.XXXXXX")"
DUMP="$WORK/ledger-prod.dump"
BEFORE="$WORK/e04-before.json"
AFTER="$WORK/e04-after.json"

FP_TREE="$ROOT"  # where the BEFORE fingerprint is run from; see BEFORE_REF

cleanup() {
  docker rm -f "$LOCAL_CONTAINER" >/dev/null 2>&1 || true
  [[ "$FP_TREE" == "$ROOT" ]] || git -C "$ROOT" worktree remove --force "$FP_TREE" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

prod_pg17() {  # read-only client against PRODUCTION; runs as us so $WORK stays ours
  docker run --rm --user "$(id -u):$(id -g)" \
    -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGSSLMODE -e PGDATABASE \
    -v "$WORK:$WORK" "$CLIENT_IMAGE" "$@"
}
local_pg17() {  # client inside the throwaway container (root, so it can read $DUMP)
  docker exec -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres \
    -e PGPASSWORD="$LOCAL_PASSWORD" -e PGDATABASE="$COPY" \
    "$LOCAL_CONTAINER" "$@"
}
on_copy_at() {  # run manage.py from a given source tree, against the local copy
  # PGSSLMODE is exported for the production client and libpq would apply it
  # here too — Django sets host/port/user/password but not sslmode, so the
  # loopback connection would demand TLS the throwaway container has not got.
  local tree="$1"; shift
  ( cd "$tree" && \
    DATABASE_URL="" PGSSLMODE=disable \
    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$LOCAL_PORT" POSTGRES_USER=postgres \
    POSTGRES_PASSWORD="$LOCAL_PASSWORD" POSTGRES_DB="$COPY" \
      uv run python src/backend/manage.py "$@" )
}
on_copy() {  # the migrations under test always come from the working tree
  on_copy_at "$ROOT" "$@"
}
normalise_before() {  # username-keyed JSON on stdin -> household-name-keyed on stdout
  # accounts/migrations_helpers.py::_household_name_for names a seeded household
  # `Casa de <username>`, clipped to 120 chars. The mapping is exact and
  # mechanical — but it is a *rule*, not a lookup: renaming a household in the
  # app makes this normalisation wrong and the diff a false alarm.
  python3 -c '
import json, sys
report = json.load(sys.stdin)
print(json.dumps({f"Casa de {k}"[:120]: v for k, v in report.items()},
                 indent=2, sort_keys=True))
'
}

fingerprint_before() { on_copy_at "$FP_TREE" dump_ledger_totals --json | normalise_before; }
fingerprint_after()  { on_copy    dump_ledger_totals --json; }

if [[ -n "$BEFORE_REF" ]]; then
  echo "==> pinning the BEFORE fingerprint command to $BEFORE_REF"
  FP_TREE="$WORK/fingerprint-code"
  git -C "$ROOT" worktree add --detach "$FP_TREE" "$BEFORE_REF" >/dev/null
  cp "$ROOT/.env" "$FP_TREE/.env" 2>/dev/null || true
fi

echo "==> dumping production, read-only (treat $DUMP as production data)"
PGDATABASE="$SOURCE_DB" prod_pg17 pg_dump --no-owner --no-acl -Fc -f "$DUMP"

echo "==> starting throwaway local Postgres ($IMAGE) as $COPY"
docker run -d --name "$LOCAL_CONTAINER" \
  -e POSTGRES_PASSWORD="$LOCAL_PASSWORD" -e POSTGRES_DB="$COPY" \
  -p "127.0.0.1:$LOCAL_PORT:5432" -v "$WORK:$WORK" "$IMAGE" >/dev/null
for _ in $(seq 60); do
  docker exec "$LOCAL_CONTAINER" pg_isready -U postgres -q && break
  sleep 1
done
docker exec "$LOCAL_CONTAINER" pg_isready -U postgres -q

echo "==> restoring into the local copy"
local_pg17 psql -q -c "CREATE EXTENSION IF NOT EXISTS vector;"
local_pg17 pg_restore -d "$COPY" --no-owner --no-acl "$DUMP" || \
  echo "   (pg_restore errors on Supabase's own schemas are expected — checking data instead)"

if [[ "${REWIND:-0}" == "1" ]]; then
  cat >&2 <<'DEAD'
!! REWIND=1 stopped working at E04 phase 4, and it fails in a way that looks
   like data corruption. Do not re-enable it without reading this.

   It rewound an already-migrated copy with `migrate finances 0012` /
   `migrate assistant 0009`. Since finances/0018_drop_user that rewind re-adds
   `user` as an ALL-NULL column — 0018 threw the data away, exactly as its
   docstring says. Three things then go wrong, in order:

     1. The BEFORE observer filters `Entry.objects.filter(user=user)`, so it
        reports zero entries for every user: a clean-looking file full of zeros.
     2. finances/0014_backfill_household derives `household` from the user's
        owner Membership. With `user` NULL there is nothing to derive from.
     3. finances/0017_household_required's NOT NULL guard then fails the migrate.

   Rehearse against a source that is genuinely pre-E04 instead. Production is
   one — it has no `household` column at all — so it needs no rewind and is the
   stronger test anyway. Failing that, restore a pre-E04 dump into a scratch
   database and point SOURCE_DB at it, with no REWIND.
DEAD
  exit 2
fi

echo "==> BEFORE fingerprint (pre-E04 schema, user-keyed, normalised)"
fingerprint_before > "$BEFORE"
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('  households:',len(d));[print(f\"  {u}: {v['entry_count']} entries, sum {v['entry_sum']}\") for u,v in d.items()]" "$BEFORE"

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER fingerprint (post-E04 schema, household-keyed)"
fingerprint_after > "$AFTER"

echo "==> diff"
if diff -u "$BEFORE" "$AFTER"; then
  echo "OK — counts, sums and acumulado identical across the migration."
else
  echo "!! FINGERPRINT CHANGED. Do not apply this migration to production." >&2
  exit 1
fi

echo "==> no row left tenant-less"
on_copy shell -c "
from accounts.models import household_owned_models
bad = {m._meta.label: m.objects.filter(household__isnull=True).count() for m in household_owned_models()}
bad = {k: v for k, v in bad.items() if v}
print('unfilled rows:', bad or 'none')
assert not bad, bad
print('OK')
"

echo "==> household-leading indexes present"
local_pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE indexname IN ('entry_hh_billing_type_idx','entry_hh_date_recent_idx',
                       'income_hh_month_idx','chat_hh_recent_idx',
                       'draft_hh_status_recent_idx','usage_hh_kind_recent_idx')
   ORDER BY indexname;"
echo "   (expect six rows)"

echo "==> the actor-leading index survives"
# Not an oversight among the five below: the throttle counts per person, so
# scoping it by household would give two members one shared rate-limit budget.
local_pg17 psql -tAc "
  SELECT indexname FROM pg_indexes WHERE indexname = 'usage_user_kind_recent_idx';"
echo "   (expect ONE row — the only user-leading index left anywhere)"

echo "==> the user-leading indexes are gone"
local_pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE indexname IN ('entry_user_billing_type_idx','entry_user_date_recent_idx',
                       'income_user_month_idx','chat_user_recent_idx',
                       'draft_user_status_recent_idx');"
echo "   (expect NO rows — dropped by finances/0018 and assistant/0015 with the column)"

echo "==> no redundant standalone index on household_id"
# E03 removed Django's implicit per-FK index on the tenant column for these
# four; E04 phase 2 re-created it under `household_id` by adding an ordinary
# ForeignKey, and only a product-scale measurement caught it. Matched by
# definition rather than by name — the name carries a Django hash suffix.
local_pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE schemaname = 'public'
     AND tablename IN ('finances_entry','finances_income',
                       'assistant_chatmessage','assistant_receiptdraft')
     AND indexdef ~ '\(household_id\)\$';"
echo "   (expect NO rows — dropped by finances/0019 and assistant/0016)"

echo "Rehearsal complete."  # the EXIT trap removes the container and the dump
