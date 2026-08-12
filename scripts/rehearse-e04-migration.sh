#!/usr/bin/env bash
# Rehearse E04 phase 2 against a COPY of production Supabase data.
#
# The epic's Definition of Done: "entry counts, balances, and the monthly
# acumulado match before and after". Phase 2 changes no read path, so the
# fingerprint must be byte-identical — any diff is corruption.
#
# Credentials come from libpq/Django env vars, never a URL: the production
# password contains a space (docs/runbook.md, "Common failure #2").
#
# Required env: PGHOST PGPORT PGUSER PGPASSWORD PGSSLMODE
# Usage: scripts/rehearse-e04-migration.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPY="${COPY:-ledger_rehearsal}"
DUMP="${DUMP:-/tmp/ledger-prod.dump}"
: "${PGHOST:?set PGHOST}" "${PGUSER:?set PGUSER}" "${PGPASSWORD:?set PGPASSWORD}"
export PGPORT="${PGPORT:-5432}" PGSSLMODE="${PGSSLMODE:-require}"

pg17() {
  docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGSSLMODE \
    -e PGDATABASE -v /tmp:/tmp postgres:17 "$@"
}
on_copy() {  # run manage.py against the rehearsal copy
  POSTGRES_HOST="$PGHOST" POSTGRES_PORT="$PGPORT" POSTGRES_USER="$PGUSER" \
  POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$COPY" \
    uv run python "$ROOT/src/backend/manage.py" "$@"
}

echo "==> dumping production (treat $DUMP as production data)"
PGDATABASE=postgres pg17 pg_dump --no-owner --no-acl -Fc -f "$DUMP"

echo "==> (re)creating $COPY"
PGDATABASE=postgres pg17 psql -q -c "DROP DATABASE IF EXISTS $COPY WITH (FORCE);"
PGDATABASE=postgres pg17 psql -q -c "CREATE DATABASE $COPY;"
PGDATABASE="$COPY" pg17 psql -q -c "CREATE EXTENSION IF NOT EXISTS vector;"
PGDATABASE="$COPY" pg17 pg_restore -d "$COPY" --no-owner "$DUMP" || \
  echo "   (pg_restore errors on Supabase's vault schema are expected — checking data instead)"

echo "==> BEFORE fingerprint"
on_copy dump_ledger_totals --json > /tmp/e04-before.json
python3 -c "import json;d=json.load(open('/tmp/e04-before.json'));print('  users:',len(d));[print(f\"  {u}: {v['entry_count']} entries, sum {v['entry_sum']}\") for u,v in d.items()]"

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER fingerprint"
on_copy dump_ledger_totals --json > /tmp/e04-after.json

echo "==> diff"
if diff -u /tmp/e04-before.json /tmp/e04-after.json; then
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
PGDATABASE="$COPY" pg17 psql -tAc "
  SELECT indexname FROM pg_indexes
   WHERE indexname IN ('entry_hh_billing_type_idx','entry_hh_date_recent_idx',
                       'income_hh_month_idx','chat_hh_recent_idx',
                       'draft_hh_status_recent_idx','usage_hh_kind_recent_idx')
   ORDER BY indexname;"
echo "   (expect six rows)"

echo "==> cleaning up"
PGDATABASE=postgres pg17 psql -q -c "DROP DATABASE IF EXISTS $COPY WITH (FORCE);"
rm -f "$DUMP" /tmp/e04-before.json /tmp/e04-after.json
echo "Rehearsal complete."
