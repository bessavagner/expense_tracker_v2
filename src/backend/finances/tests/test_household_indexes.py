"""E03's indexes, re-created with household as the leading column.

The user-leading originals stay until phase 4: phase 3 converts one surface
at a time, and until a surface is converted its queries still filter by user.
Dropping the old indexes now would deoptimise the app mid-refactor.
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

USER_LEADING_STILL_PRESENT = [
    "entry_user_billing_type_idx",
    "entry_user_date_recent_idx",
    "income_user_month_idx",
    "chat_user_recent_idx",
    "draft_user_status_recent_idx",
    "usage_user_kind_recent_idx",
]


def _index_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        return {row[0] for row in cursor.fetchall()}


def test_every_household_leading_index_exists():
    existing = _index_names()
    expected = [name for names in HOUSEHOLD_LEADING.values() for name in names]

    assert set(expected) <= existing, sorted(set(expected) - existing)


def test_the_user_leading_indexes_are_still_there():
    """Phase 4 drops these with the column. Removing one earlier would slow
    every not-yet-converted query path in phase 3."""
    existing = _index_names()

    assert set(USER_LEADING_STILL_PRESENT) <= existing


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
