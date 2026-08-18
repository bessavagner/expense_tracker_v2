"""Is the database behind the code that is running against it?

Asked through `MigrationExecutor.migration_plan`, which is the same code
`migrate` itself uses to decide what to run — so this answer cannot disagree
with what `migrate` would do. Parsing `showmigrations` output would be a second
implementation of the same question, and two implementations of one question is
how they start to differ.

Deliberately *not* cached. Drift can appear after a process has started — a
rollback to a revision older than the applied migrations is the usual way — and
a value computed once at boot is exactly the blind spot that kept the
2026-08-15 outage open for a day after it opened.
"""

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


def unapplied_migrations(alias: str = "default") -> list[str]:
    """Return ``app.name`` labels for migrations the database has not applied.

    Empty list means in sync. The order is the order ``migrate`` would apply
    them, so the first entry is where a fix starts.

    Raises whatever the database driver raises when it cannot connect; a caller
    that cannot tell "unreachable" from "drifted" will report the wrong outage.
    """
    executor = MigrationExecutor(connections[alias])
    targets = executor.loader.graph.leaf_nodes()
    return [
        f"{migration.app_label}.{migration.name}"
        for migration, _backwards in executor.migration_plan(targets)
    ]
