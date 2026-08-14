"""E03's indexes, re-created with household as the leading column.

Phase 4 dropped the user-leading originals with the column they led on. The
one survivor is `usage_user_kind_recent_idx`: `UsageInteraction.user` is the
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


# The four models whose composite leads with household_id. Django's implicit
# per-FK index on household_id is a strict prefix of that composite, so it
# serves no query the composite cannot — while costing writes, disk, and
# sometimes a correct plan. E03 removed the same four when the tenant column
# was `user`; E04 phase 2 re-created them by adding an ordinary ForeignKey, and
# Task 14 caught it at product scale. This test is why it cannot come back a
# third time.
NO_REDUNDANT_FK_INDEX = [
    "finances_entry",
    "finances_income",
    "assistant_chatmessage",
    "assistant_receiptdraft",
]


def _index_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        return {row[0] for row in cursor.fetchall()}


def _indexes_on(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = %s",
            [table],
        )
        return cursor.fetchall()


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


@pytest.mark.parametrize("table", NO_REDUNDANT_FK_INDEX)
def test_no_standalone_index_on_household_id(table):
    """A single-column index on household_id is a strict prefix of this table's
    composite. Keeping it is not free: the planner costs the narrower index
    lower and can pick it for a query the composite was built for, then discard
    most of the rows it read. E03 measured that at 5,000 entries — 5,000 rows
    read against 189 — and the same trap was reintroduced under a new name."""
    redundant = [
        name
        for name, definition in _indexes_on(table)
        # The column list, normalised: "... USING btree (household_id)" -> "household_id"
        if definition.split("(", 1)[1].rstrip(")").replace('"', "").strip() == "household_id"
    ]

    assert not redundant, (
        f"{table} has a standalone index on household_id ({redundant}). It is a "
        "prefix of the household-leading composite; set db_index=False on the "
        "field. See docs/architecture/query-performance-baseline.md."
    )


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
