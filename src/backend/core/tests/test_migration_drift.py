"""Drift between the code's migrations and the database's applied set.

The failure this exists for is the 2026-08-15 outage: revision 00046-l64 shipped
`accounts.0005`'s `Household.plan` against a database still on `accounts.0004`,
and `resolve_active_household` selects `plan_id` in middleware on every request.
Every route 500'd for every logged-in user for a day. Anonymous requests mostly
passed, which is why it presented as "server error after login" rather than as
an outage — and why nothing noticed.

The drifted case is produced by un-recording a real migration in
`django_migrations`, which is byte-for-byte the state production was in. A mock
would only prove the mock agrees with itself.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from core.migration_drift import unapplied_migrations

# A real, long-landed migration. Un-recording it puts the test database in
# exactly the shape a drifted production database has: the column is present,
# the row saying so is not.
A_REAL_MIGRATION = ("core", "0009_policy_acceptance_and_consent")


@pytest.mark.django_db
class TestUnappliedMigrations:
    def test_a_migrated_database_reports_no_drift(self):
        assert unapplied_migrations() == []

    def test_an_unrecorded_migration_is_reported(self):
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)

        drift = unapplied_migrations()

        assert "core.0009_policy_acceptance_and_consent" in drift

    def test_the_report_names_every_migration_that_would_run(self):
        """`migrate <app>` is the fix, so the answer must name the app and the file.

        A check that says "the database is behind" sends you on an investigation.
        One that says "core.0009_policy_acceptance_and_consent" is the fix.
        """
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)

        drift = unapplied_migrations()

        assert all("." in label for label in drift), drift
        app, _, name = drift[0].partition(".")
        assert app and name

    def test_it_asks_the_database_each_time_rather_than_caching(self):
        """Drift can appear *after* a process starts — a rollback is the usual way.

        A module-level cache would make the healthz check in Task 3 report the
        state at boot forever, which is precisely the day-long blind spot the
        2026-08-15 incident opened.
        """
        assert unapplied_migrations() == []
        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)
        assert unapplied_migrations() != []


@pytest.mark.django_db
class TestCheckMigrationDriftCommand:
    """The cron- and operator-facing wrapper. Its exit code is its contract."""

    def test_it_exits_zero_and_says_so_when_in_sync(self):
        out = StringIO()
        call_command("check_migration_drift", stdout=out)
        assert "no drift" in out.getvalue().lower()

    def test_it_raises_command_error_when_drifted(self):
        """CommandError is how a management command exits non-zero.

        The exit code is the whole point: Cloud Scheduler decides the job failed
        from the process's status, and a command that printed a warning and
        exited 0 would make the nightly check decorative.
        """
        from django.core.management.base import CommandError

        MigrationRecorder(connection).record_unapplied(*A_REAL_MIGRATION)
        with pytest.raises(CommandError) as excinfo:
            call_command("check_migration_drift")
        assert "core.0009_policy_acceptance_and_consent" in str(excinfo.value)

    def test_json_output_is_machine_readable(self):
        out = StringIO()
        call_command("check_migration_drift", "--json", stdout=out)
        payload = json.loads(out.getvalue())
        assert payload == {"drift": False, "unapplied": []}
