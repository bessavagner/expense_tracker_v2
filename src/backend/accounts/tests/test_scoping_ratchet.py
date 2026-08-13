"""Global constraint 4: no domain query scopes by user.

E04 is complete, so this is no longer a ratchet — it is the rule. The only
exemption is `ACTOR_SCOPED`, where `user` is the person acting rather than the
tenant owning, and that distinction is permanent.
"""

import re
from pathlib import Path

# tests → accounts → backend → src → repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

# Files where `user` is the ACTOR, not the tenant — permanently exempt.
# `AssistantUsageEvent.user` is who spent the turn: rate limiting is
# per-person, so two people in one household each get their own budget.
# Phase 2 decided this and phase 4 did not drop `user` from that model.
ACTOR_SCOPED = {
    "src/backend/assistant/throttling.py",
}

# `get_or_create` and `update_or_create` were invisible to the first version of
# this pattern: `\.get\(` does not match `.get_or_create(`. That blind spot let
# `seed_data.py` scope its catalogue by user through phases 2 and 3.
PATTERN = re.compile(r"\.(filter|get|exclude|get_or_create|update_or_create)\([^)]*user=")


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


def test_no_domain_query_scopes_by_user():
    offenders = sorted(_files_scoping_by_user() - ACTOR_SCOPED)
    assert not offenders, (
        "These files scope a domain query by user=. Use the household-scoped "
        f"manager (accounts.scoping) instead: {offenders}"
    )


def test_actor_scoped_files_still_scope_by_user():
    """If one of these stops scoping by user, the actor/tenant distinction has
    been erased somewhere — check it was deliberate before deleting the entry."""
    stale = sorted(ACTOR_SCOPED - _files_scoping_by_user())
    assert not stale, f"No longer scope by user — remove from ACTOR_SCOPED: {stale}"
