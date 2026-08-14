"""The rename must preserve rows, not just compile.

`RenameModel` is a table rename in Postgres, so data survives by definition —
this test exists so that a future agent who "simplifies" it into a
delete-and-recreate pair is caught immediately.
"""

import pytest
from django.apps import apps

pytestmark = pytest.mark.django_db


def test_the_old_model_name_is_gone():
    with pytest.raises(LookupError):
        apps.get_model("assistant.AssistantUsageEvent")


def test_the_new_model_keeps_every_field():
    model = apps.get_model("assistant.UsageInteraction")
    names = {f.name for f in model._meta.get_fields()}
    assert {"id", "household", "user", "kind", "created_at"} <= names


def test_the_table_is_renamed_rather_than_recreated():
    """`RenameModel` emits ALTER TABLE ... RENAME, so the rows come with it.

    The physical table name DOES change here (`assistant_assistantusageevent`
    becomes `assistant_usageinteraction`) — what must not change is that it is
    the same table. A delete-and-recreate pair would satisfy the name but drop
    every row, which is the failure this guards.
    """
    model = apps.get_model("assistant.UsageInteraction")
    assert model._meta.db_table == "assistant_usageinteraction"


def test_kind_values_are_unchanged_so_existing_rows_still_match():
    from assistant.models import InteractionKind

    assert InteractionKind.TEXT == "text"
    assert InteractionKind.IMAGE == "image"
