#!/usr/bin/env bash
# Rehearse core/0003_customuser_email_unique against a COPY of production data.
#
# That migration adds a UNIQUE constraint to a live `core_customuser.email`
# column that has been nullable-in-practice (`blank=True`, default `''`) since
# the project started. `ALTER TABLE ... ADD CONSTRAINT UNIQUE` is not a
# rehearsable-in-your-head operation: it either succeeds, or it aborts the whole
# deploy the moment two rows share a value — and `''` is the value they would
# share. The migration back-fills blanks with `<username>@sem-email.invalid`
# first; this script proves that back-fill is enough on the *real* rows.
#
# Production is touched exactly once, read-only, by pg_dump. The copy is
# restored into a throwaway LOCAL container, so nothing here can create,
# migrate or drop a database on the production server.
#
# The dump holds every row of the real ledger. It lives in a 0700 temp dir that
# a trap removes on ANY exit — including the failure exits, which are the ones
# you actually care about.
#
# Credentials come from libpq env vars, never a URL: the production password
# contains a space (docs/runbook.md, "Common failure #2"). Run without them and
# the script reads .env's SUPABASE_SESSION_POOLER and splits it itself.
#
# Usage: scripts/rehearse-e05-email-unique.sh
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPY="${COPY:-ledger_rehearsal}"
SOURCE_DB="${SOURCE_DB:-postgres}"  # Supabase's database is `postgres`
IMAGE="${IMAGE:-pgvector/pgvector:pg17}"
CLIENT_IMAGE="${CLIENT_IMAGE:-postgres:17}"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-e05-rehearsal-$$}"
LOCAL_PORT="${LOCAL_PORT:-55433}"
LOCAL_PASSWORD="rehearsal"  # throwaway container, bound to 127.0.0.1 only

if [[ -z "${PGHOST:-}" && -f "$ROOT/.env" ]]; then
  # Split the URL here rather than handing it to libpq: the password contains a
  # space, so the URL form is malformed and fails with a misleading error.
  eval "$(
    uv run --project "$ROOT" python - "$ROOT/.env" <<'PY'
import shlex, sys
from urllib.parse import urlsplit, unquote

for line in open(sys.argv[1]):
    if line.startswith("SUPABASE_SESSION_POOLER="):
        u = urlsplit(line.split("=", 1)[1].strip().strip("\"'"))
        for var, value in (
            ("PGHOST", u.hostname), ("PGPORT", str(u.port or 5432)),
            ("PGUSER", unquote(u.username or "")),
            ("PGPASSWORD", unquote(u.password or "")),
        ):
            print(f"export {var}={shlex.quote(value)}")
        break
PY
  )"
fi
: "${PGHOST:?set PGHOST (or put SUPABASE_SESSION_POOLER in .env)}"
: "${PGUSER:?set PGUSER}" "${PGPASSWORD:?set PGPASSWORD}"
export PGPORT="${PGPORT:-5432}" PGSSLMODE="${PGSSLMODE:-require}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/e05-rehearsal.XXXXXX")"
DUMP="$WORK/ledger-prod.dump"

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
local_pg17() {
  docker exec -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres \
    -e PGPASSWORD="$LOCAL_PASSWORD" -e PGDATABASE="$COPY" \
    "$LOCAL_CONTAINER" "$@"
}
on_copy() {  # manage.py from the working tree, against the local copy
  # PGSSLMODE is exported for the production client and libpq would apply it
  # here too — the throwaway container has no TLS.
  ( cd "$ROOT" && \
    DATABASE_URL="" PGSSLMODE=disable \
    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$LOCAL_PORT" POSTGRES_USER=postgres \
    POSTGRES_PASSWORD="$LOCAL_PASSWORD" POSTGRES_DB="$COPY" \
      uv run python src/backend/manage.py "$@" )
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

echo "==> BEFORE: what production's addresses actually look like"
local_pg17 psql -c "
  SELECT count(*) AS accounts,
         count(*) FILTER (WHERE email IS NULL OR email = '') AS blank,
         count(DISTINCT email) FILTER (WHERE email <> '') AS distinct_real
    FROM core_customuser;"
echo "   duplicates among NON-BLANK addresses (must be empty — the back-fill"
echo "   cannot repair these, and resolving them is an operator decision):"
DUPES="$(local_pg17 psql -tAc "
  SELECT count(*) FROM (
    SELECT email FROM core_customuser
     WHERE email IS NOT NULL AND email <> ''
     GROUP BY email HAVING count(*) > 1) d;" | tr -d '[:space:]')"
if [[ "$DUPES" != "0" ]]; then
  local_pg17 psql -c "
    SELECT email, count(*) FROM core_customuser
     WHERE email IS NOT NULL AND email <> ''
     GROUP BY email HAVING count(*) > 1;"
  echo "!! $DUPES duplicated real address(es). Resolve by hand before shipping." >&2
  exit 1
fi
echo "   none."

echo "==> the migration plan"
on_copy migrate core 0003 --plan

echo "==> migrating the copy"
on_copy migrate

echo "==> AFTER: the constraint holds and nobody lost an identity"
local_pg17 psql -c "
  SELECT count(*) AS accounts,
         count(*) FILTER (WHERE email LIKE '%@sem-email.invalid') AS placeholders
    FROM core_customuser;"
REMAINING="$(local_pg17 psql -tAc "
  SELECT count(*) FROM (
    SELECT email FROM core_customuser GROUP BY email HAVING count(*) > 1) d;" \
  | tr -d '[:space:]')"
if [[ "$REMAINING" != "0" ]]; then
  echo "!! $REMAINING duplicated address(es) survived the migration." >&2
  exit 1
fi
echo "   zero duplicates."

echo "==> the UNIQUE constraint is really on the table"
local_pg17 psql -tAc "
  SELECT conname FROM pg_constraint
   WHERE conrelid = 'core_customuser'::regclass AND contype = 'u';"

echo "==> placeholders an operator still has to repair by hand"
local_pg17 psql -c "
  SELECT id, username, email, is_staff, last_login
    FROM core_customuser
   WHERE email LIKE '%@sem-email.invalid'
   ORDER BY id;"

echo "OK — core/0003 applies to a copy of production and leaves no duplicate."
