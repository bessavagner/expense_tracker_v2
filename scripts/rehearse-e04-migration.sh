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
# Required env: PGHOST PGPORT PGUSER PGPASSWORD PGSSLMODE
# Usage: scripts/rehearse-e04-migration.sh
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

cleanup() {
  docker rm -f "$LOCAL_CONTAINER" >/dev/null 2>&1 || true
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
on_copy() {  # run manage.py against the local rehearsal copy
  # PGSSLMODE is exported for the production client and libpq would apply it
  # here too — Django sets host/port/user/password but not sslmode, so the
  # loopback connection would demand TLS the throwaway container has not got.
  DATABASE_URL="" PGSSLMODE=disable \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$LOCAL_PORT" POSTGRES_USER=postgres \
  POSTGRES_PASSWORD="$LOCAL_PASSWORD" POSTGRES_DB="$COPY" \
    uv run python "$ROOT/src/backend/manage.py" "$@"
}

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
on_copy dump_ledger_totals --json > "$BEFORE"
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('  users:',len(d));[print(f\"  {u}: {v['entry_count']} entries, sum {v['entry_sum']}\") for u,v in d.items()]" "$BEFORE"

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER fingerprint"
on_copy dump_ledger_totals --json > "$AFTER"

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
