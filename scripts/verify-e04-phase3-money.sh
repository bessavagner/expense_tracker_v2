#!/usr/bin/env bash
# Prove E04 phase 3 moved no money: the household-scoped read paths must return
# exactly what the user-scoped ones did, on the real local ledger.
#
# Why not scripts/rehearse-e04-migration.sh? That one validates the phase-2
# *migration*, by fingerprinting a copy before and after `manage.py migrate`.
# Phase 3 adds no migration at all, and its REWIND=1 mode rolls the schema back
# to pre-E04 — at which point `dump_ledger_totals`, which now asks
# `build_projection` for a household's rows, hits a table with no household
# column. The before/after-migration diff is simply not the question phase 3
# asks.
#
# The question phase 3 asks is a *code-version* diff: same database, fully
# migrated, one fingerprint from the pre-phase-3 commit and one from HEAD. If
# household scoping selects different rows than user scoping did, the acumulado
# moves and this exits 1.
#
# Read-only: `dump_ledger_totals` only aggregates. Nothing here writes.
#
# Usage:
#   POSTGRES_PORT=5433 scripts/verify-e04-phase3-money.sh [<baseline-ref>]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE="${1:-main}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/e04-money.XXXXXX")"
BEFORE="$WORK/before.json"
AFTER="$WORK/after.json"
TREE="$WORK/baseline"

cleanup() {
  git -C "$ROOT" worktree remove --force "$TREE" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> checking out $BASELINE to fingerprint the pre-phase-3 read paths"
git -C "$ROOT" worktree add --detach "$TREE" "$BASELINE" >/dev/null
cp "$ROOT/.env" "$TREE/.env" 2>/dev/null || true

echo "==> BEFORE fingerprint ($BASELINE, user-scoped)"
(cd "$TREE" && uv run python src/backend/manage.py dump_ledger_totals --json) > "$BEFORE"

echo "==> AFTER fingerprint (working tree, household-scoped)"
(cd "$ROOT" && uv run python src/backend/manage.py dump_ledger_totals --json) > "$AFTER"

echo "==> diff"
if diff -u "$BEFORE" "$AFTER"; then
  echo "OK — counts, sums and acumulado identical across the re-scoping."
else
  echo "!! FINGERPRINT CHANGED. Household scoping selects different rows than" >&2
  echo "   user scoping did. For a single-household ledger that is a bug in the" >&2
  echo "   conversion, not in the migration." >&2
  exit 1
fi
