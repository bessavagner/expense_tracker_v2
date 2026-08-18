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
# one. The floor is MEASURED, not guessed — the first version of this script used
# 1 MiB and failed on its very first run, because this database is small:
#
#   full dump (-Fc, compressed)   557,478 bytes   2026-08-18
#   schema-only dump (-Fc)        319,467 bytes   2026-08-18
#
# So the floor has to sit between those two, not above both. 350,000 B is just
# clear of a schema-only dump and 63% of a real one, which leaves room for the
# retention sweep to shrink the data without tripping it.
#
# Note what this check can and cannot do. Schema-only is 57% the size of a real
# backup here, so size is a weak signal: it catches a truncated, empty or
# schema-only dump and nothing subtler. The real verification is restoring it
# and diffing `manage.py dump_ledger_totals --json` — see
# docs/superpowers/evidence/e16-restore/.
MIN_DUMP_BYTES="${MIN_DUMP_BYTES:-350000}"
if [ "$BYTES" -lt "$MIN_DUMP_BYTES" ]; then
  echo "ledger_backup_ran: FAILED — dump is only ${BYTES} bytes, floor is ${MIN_DUMP_BYTES}" >&2
  exit 1
fi

# Upload with a metadata-server token rather than the gcloud SDK: no key, no
# SDK, and it works with the Job's own runtime service account, which holds
# objectCreator on this bucket. Requires curl to fail loudly on an HTTP error
# (-f), or a 403 would be silently treated as a successful backup.
OBJECT="ledger-${STAMP}.dump"
TOKEN=$(curl -sf -H 'Metadata-Flavor: Google' \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -sf -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@${OUT}" \
  "https://storage.googleapis.com/upload/storage/v1/b/${BACKUP_BUCKET}/o?uploadType=media&name=${OBJECT}" \
  > /dev/null

rm -f "$OUT"

# Logged on every successful run. The alert fires on the ABSENCE of this line,
# so a quiet success is data — same shape as ledger_purge_ran (E13).
echo "ledger_backup_ran: ok ${BYTES} bytes -> gs://${BACKUP_BUCKET}/${OBJECT}"
