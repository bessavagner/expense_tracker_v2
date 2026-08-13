"""E03's indexes, re-created with household as the leading column.

Phase 4 dropped the user-leading originals with the column they led on. The
one survivor is `usage_user_kind_recent_idx`: `AssistantUsageEvent.user` is the
acting member, and the throttle counts per person (E04 decision 1).
"""

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

HOUSEHOLD_LEADING = {
    "finances_entry": ["entry_hh_billing_type_idx", "entry_hh_date_recent_idx"],
    "finances_income": ["income_hh_month_idx"],
    "assistant_chatmessage": ["chat_hh_recent_idx"],
    "assistant_receiptdraft": ["draft_hh_status_recent_idx"],
    "assistant_assistantusageevent": ["usage_hh_kind_recent_idx"],
}

# The actor-scoped index, and the only user-leading one left anywhere.
ACTOR_LEADING_STILL_PRESENT = ["usage_user_kind_recent_idx"]

# Dropped by 0018_drop_user / 0015_drop_user, with the columns they led on.
USER_LEADING_GONE = [
    "entry_user_billing_type_idx",
    "entry_user_date_recent_idx",
    "income_user_month_idx",
    "chat_user_recent_idx",
    "draft_user_status_recent_idx",
]


def _index_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        return {row[0] for row in cursor.fetchall()}


def test_every_household_leading_index_exists():
    existing = _index_names()
    expected = [name for names in HOUSEHOLD_LEADING.values() for name in names]

    assert set(expected) <= existing, sorted(set(expected) - existing)


def test_the_user_leading_indexes_are_gone():
    """They indexed the tenant column, which no longer exists. An index that
    survived the drop would mean a stale migration state, not a spare tyre."""
    existing = _index_names()

    assert set(USER_LEADING_GONE).isdisjoint(existing)


def test_the_actor_leading_index_survives():
    """Per-person rate limiting needs `(user, kind, -created_at)`; scoping that
    query by household would give two members one shared budget."""
    existing = _index_names()

    assert set(ACTOR_LEADING_STILL_PRESENT) <= existing


def test_household_index_leads_with_household():
    """Leading column decides whether a household-only filter can use it."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            ["entry_hh_billing_type_idx"],
        )
        definition = cursor.fetchone()[0]

    columns = definition.split("(", 1)[1].rstrip(")")
    assert columns.split(",")[0].strip().startswith("household_id")
