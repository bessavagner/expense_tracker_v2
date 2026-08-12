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
    "src/backend/assistant/throttling.py",
    "src/backend/assistant/views.py",
    "src/backend/finances/api/views.py",
    "src/backend/finances/forms.py",
    "src/backend/finances/management/commands/import_csv.py",
    "src/backend/finances/management/commands/seed_qa_data.py",
    "src/backend/finances/management/commands/transfer_entries.py",
    "src/backend/finances/services/budget_stats.py",
    "src/backend/finances/services/category_stats.py",
    "src/backend/finances/services/daily_trend.py",
    "src/backend/finances/services/income_recurrence.py",
    "src/backend/finances/services/installment_month.py",
    "src/backend/finances/services/projection.py",
    "src/backend/finances/services/systemic_month.py",
    "src/backend/finances/services/systemic_recurrence.py",
    "src/backend/finances/views/cockpit.py",
    "src/backend/finances/views/consolidated.py",
    "src/backend/finances/views/entries.py",
    "src/backend/finances/views/importer.py",
    "src/backend/finances/views/projection.py",
    "src/backend/finances/views/settings.py",
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
    regressions = sorted(_files_scoping_by_user() - BASELINE)
    assert not regressions, (
        "These files scope a domain query by user=. Use the household-scoped "
        f"manager (accounts.scoping) instead: {regressions}"
    )


def test_baseline_has_no_stale_entries():
    """A file that has been converted must leave the baseline, or the ratchet
    stops ratcheting."""
    stale = sorted(BASELINE - _files_scoping_by_user())
    assert not stale, f"These files no longer scope by user — remove them from BASELINE: {stale}"
