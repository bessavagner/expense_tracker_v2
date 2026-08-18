#!/usr/bin/env bash
# Nightly logical backup of the production database to GCS (E16 S16-5).
#
# libpq variables rather than a URL, deliberately: the production password
# contains a space, which pg_dump 17 rejects inside a URL and Django's parser
# mangles. See docs/runbook.md, "Applying a migration to Supabase", failure #2.
#
# Custom format (-Fc) rather than plain SQL: it restores selectively, in
# parallel, and compresses. The restore side is pg_restore, rehearsed and timed
# in docs/superpowers/evidence/e16-restore/.
set -euo pipefail

: "${PGHOST:?}" "${PGPORT:?}" "${PGUSER:?}" "${PGPASSWORD:?}" "${PGDATABASE:?}" "${BACKUP_BUCKET:?}"
export PGSSLMODE=require

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT="/tmp/ledger-${STAMP}.dump"

pg_dump --no-owner --no-acl -Fc -f "$OUT"
BYTES=$(stat -c %s "$OUT")

# A dump that is suspiciously small is worse than no dump, because it looks like
# one. 1 MiB is far below any real size for this database and far above an empty
# schema-only dump.
if [ "$BYTES" -lt 1048576 ]; then
  echo "ledger_backup_ran: FAILED — dump is only ${BYTES} bytes" >&2
  exit 1
fi

gcloud storage cp "$OUT" "gs://${BACKUP_BUCKET}/ledger-${STAMP}.dump"
rm -f "$OUT"

# Logged on every successful run. The alert fires on the ABSENCE of this line,
# so a quiet success is data — same shape as ledger_purge_ran (E13).
echo "ledger_backup_ran: ok ${BYTES} bytes -> gs://${BACKUP_BUCKET}/ledger-${STAMP}.dump"
