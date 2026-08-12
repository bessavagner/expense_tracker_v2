#!/usr/bin/env bash
# Rehearse E04 phase 2 against a COPY of production Supabase data.
#
# The epic's Definition of Done: "entry counts, balances, and the monthly
# acumulado match before and after". Phase 2 changes no read path, so the
# fingerprint must be byte-identical — any diff is corruption.
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
# The fingerprint code is PINNED, the migrations are not. This experiment varies
# the schema and holds the observer constant; running `dump_ledger_totals` from
# the working tree would vary both at once. It went unnoticed through phase 2
# only because that command was schema-agnostic then — it read `user`, a column
# both sides of the migration have. Phase 3 points its acumulado at
# `build_projection(household, ...)`, so the working-tree command can no longer
# read the pre-E04 schema REWIND=1 produces, and the BEFORE fingerprint dies on
# `column finances_income.household_id does not exist`.
#
# FINGERPRINT_REF therefore defaults to the phase-2 merge, the last commit whose
# `dump_ledger_totals` reads a column every schema in this epic has. Phase 4
# drops `user` and re-points the command; bump this ref in the same commit, or
# delete the script if the epic no longer needs it.
#
# To prove phase 3 itself moved no money — a *code*-version question, not a
# schema one — use scripts/verify-e04-phase3-money.sh instead.
#
# Required env: PGHOST PGPORT PGUSER PGPASSWORD PGSSLMODE
# Usage: scripts/rehearse-e04-migration.sh
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# de143a1 = "Merge E04 phase 2 leftovers"; set to "" to use the working tree.
FINGERPRINT_REF="${FINGERPRINT_REF-de143a1}"
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

FP_TREE="$ROOT"  # where the fingerprint command is run from; see FINGERPRINT_REF

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
fingerprint() {  # ...but the observer is pinned, so only the schema varies
  on_copy_at "$FP_TREE" dump_ledger_totals --json
}

if [[ -n "$FINGERPRINT_REF" ]]; then
  echo "==> pinning the fingerprint command to $FINGERPRINT_REF"
  FP_TREE="$WORK/fingerprint-code"
  git -C "$ROOT" worktree add --detach "$FP_TREE" "$FINGERPRINT_REF" >/dev/null
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
  echo "==> rewinding the copy to pre-E04 (REWIND=1)"
  # For rehearsing against a source that is ALREADY migrated — the local dev
  # ledger, say. Production is still pre-E04, so it needs no rewind.
  on_copy migrate finances 0012
  on_copy migrate assistant 0009
fi

echo "==> BEFORE fingerprint"
fingerprint > "$BEFORE"
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('  users:',len(d));[print(f\"  {u}: {v['entry_count']} entries, sum {v['entry_sum']}\") for u,v in d.items()]" "$BEFORE"

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER fingerprint"
fingerprint > "$AFTER"

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

echo "Rehearsal complete."  # the EXIT trap removes the container and the dump
