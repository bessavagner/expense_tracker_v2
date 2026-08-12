"""Global constraint 4, enforced while E04 is still in flight.

After E04 lands, the baseline below is empty and this becomes a flat "no
domain query scopes by user" assertion. Until then it is a ratchet: the set
may shrink, never grow.
"""

import re
from pathlib import Path

# tests → accounts → backend → src → repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

# Every file that scoped by user at the start of E04 phase 1 (2026-08-11).
# Strike entries as phases 3 and 4 convert them. Never add one.
BASELINE = {
    "src/backend/assistant/agents/analytics.py",
    "src/backend/assistant/agents/memory.py",
    "src/backend/assistant/agents/tools.py",
    "src/backend/assistant/management/commands/seed_category_rules.py",
    "src/backend/assistant/views.py",
    "src/backend/finances/api/views.py",
    "src/backend/finances/management/commands/import_csv.py",
    "src/backend/finances/management/commands/seed_qa_data.py",
    "src/backend/finances/management/commands/transfer_entries.py",
}

# Tenancy-transition tooling. Deliberately *not* in BASELINE, which may only
# ever shrink: these files are not legacy leaks awaiting conversion, they read
# by user because that is their job. `dump_ledger_totals` fingerprints the
# ledger exactly as the pre-E04 code did, which is the only reason its
# before/after comparison proves the migration lossless — scoping it by
# household would compare two different questions. Phase 4 re-points it at
# household in the same commit that drops the `user` columns.
E04_TRANSITION_TOOLS = {
    "src/backend/finances/management/commands/dump_ledger_totals.py",
}

# Files where `user` is the ACTOR, not the tenant — permanently exempt.
# `AssistantUsageEvent.user` is who spent the turn: rate limiting is
# per-person, so two people in one household each get their own budget.
# Phase 2 decided this and phase 4 does not drop `user` from that model.
# This set is permanent; E04_TRANSITION_TOOLS is not.
ACTOR_SCOPED = {
    "src/backend/assistant/throttling.py",
}

PATTERN = re.compile(r"\.(filter|get|exclude)\([^)]*user=")


def _files_scoping_by_user():
    found = set()
    for app in ("finances", "assistant"):
        for path in (REPO_ROOT / "src" / "backend" / app).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel or "/migrations/" in rel:
                continue
            if PATTERN.search(path.read_text(encoding="utf-8")):
                found.add(rel)
    return found


def test_no_new_file_scopes_a_domain_query_by_user():
    regressions = sorted(_files_scoping_by_user() - BASELINE - E04_TRANSITION_TOOLS - ACTOR_SCOPED)
    assert not regressions, (
        "These files scope a domain query by user=. Use the household-scoped "
        f"manager (accounts.scoping) instead: {regressions}"
    )


def test_baseline_has_no_stale_entries():
    """A file that has been converted must leave the baseline, or the ratchet
    stops ratcheting."""
    stale = sorted(BASELINE - _files_scoping_by_user())
    assert not stale, f"These files no longer scope by user — remove them from BASELINE: {stale}"


def test_transition_tools_still_need_their_exemption():
    """The escape hatch rots shut. A transition tool that no longer scopes by
    user has been converted, and its entry must go — otherwise the set slowly
    becomes a place to hide real leaks."""
    stale = sorted(E04_TRANSITION_TOOLS - _files_scoping_by_user())
    assert not stale, (
        f"These no longer scope by user — remove them from E04_TRANSITION_TOOLS: {stale}"
    )


def test_actor_scoped_files_still_scope_by_user():
    """If one of these stops scoping by user, the actor/tenant distinction has
    been erased somewhere — check it was deliberate before deleting the entry."""
    stale = sorted(ACTOR_SCOPED - _files_scoping_by_user())
    assert not stale, f"No longer scope by user — remove from ACTOR_SCOPED: {stale}"
