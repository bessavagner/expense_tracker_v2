"""The back-fill's *rule*, tested against a table shaped like a pre-E04 one.

Same approach as phase 1's test_migration_seed: replaying a historical
migration is heavier than this project needs. What matters is that every
pre-existing row lands in its author's household with its author recorded,
and that re-running changes nothing.

**Why not the live models any more.** Phase 4 makes `household` NOT NULL, and
the whole subject of this test is rows that have no household yet. Through
phases 2 and 3 it could bake a real `finances.Entry` and blank the column with
a queryset `.update()`; the database now refuses that, correctly.

So the test builds its own table instead. `LegacyRow` has exactly the three
columns the back-fill touches — `user`, a nullable `household`, a nullable
`created_by` — which is precisely the shape a migration's historical model
has when `backfill_household_columns` runs against it. The function takes model
*classes* for this reason, so handing it one costs nothing and keeps every
case genuinely exercised against real SQL: a real bulk UPDATE, real NULLs, and
the real skip-when-no-membership behaviour.
"""

import pytest
from django.conf import settings
from django.db import connection, models
from model_bakery import baker

from accounts.backfill import backfill_household_columns
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


class LegacyRow(models.Model):
    """A domain row as it existed before E04: owned by a user, no tenant.

    Every FK is ``DO_NOTHING`` and hidden (``related_name="+"``) on purpose.
    Importing this module registers the model with the app registry for the
    whole session, but its *table* exists only inside the fixture below — so a
    cascading ``Household.delete()`` or ``user.delete()`` anywhere else in the
    suite would otherwise have Django's collector query a table that is not
    there. DO_NOTHING keeps the collector from ever looking.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name="+"
    )
    household = models.ForeignKey(
        Household, null=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

    class Meta:
        app_label = "accounts"
        managed = False

    def __str__(self):
        return f"legacy row of {self.user_id}"


@pytest.fixture(autouse=True)
def legacy_table():
    """Create the table for the duration of one test.

    `managed = False` keeps the migration autodetector from ever noticing this
    model. No explicit drop: DDL is transactional in Postgres and pytest-django
    rolls each test back, so the CREATE is undone with everything else. An
    explicit DROP here fails anyway — the rows still hold deferred FK trigger
    events inside the open transaction.
    """
    with connection.schema_editor() as editor:
        editor.create_model(LegacyRow)
    yield


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def owned_household(user):
    household = baker.make(Household, name="Casa de vagner")
    baker.make(Membership, user=user, household=household, role=Role.OWNER)
    return household


def _run():
    return backfill_household_columns(Membership, {"accounts.LegacyRow": LegacyRow})


def _unfilled_row(user):
    """A row as it existed in production before the back-fill ran."""
    return LegacyRow.objects.create(user=user, household=None, created_by=None)


def test_backfill_sets_household_from_the_owner_membership(user, owned_household):
    row = _unfilled_row(user)

    _run()

    row.refresh_from_db()
    assert row.household == owned_household
    assert row.created_by == user


def test_backfill_leaves_already_filled_rows_alone(user, owned_household):
    """Idempotence, and the safety property that matters: a row already
    assigned to a household must never be moved to another one."""
    other = baker.make(Household, name="Outra")
    row = LegacyRow.objects.create(user=user, household=other)

    _run()
    _run()

    row.refresh_from_db()
    assert row.household == other


def test_backfill_skips_a_user_with_no_membership(user):
    """Fails closed. A user with no household leaves their rows NULL rather
    than borrowing somebody's ledger — phase 4's NOT NULL surfaces it, and the
    guard in finances/0017 refuses to run until a person has looked."""
    row = _unfilled_row(user)

    _run()

    row.refresh_from_db()
    assert row.household_id is None


def test_backfill_reports_what_it_touched(user, owned_household):
    for _ in range(3):
        _unfilled_row(user)

    counts = _run()

    assert counts["accounts.LegacyRow"] == 3
