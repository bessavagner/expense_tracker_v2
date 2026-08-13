import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from finances.models import Entry


def _setup(user, household):
    """The entry keeps a `user` beside its `household` on purpose.

    `transfer_entries export` still reads `e.user.username` and filters on
    `user__username` — decision 7 re-points it at `created_by` in Task 13, and
    that is the commit that drops these `user=` kwargs. Until then a row with
    no user makes the export raise rather than fail an assertion.
    """
    cat = baker.make("finances.Category", household=household, name="Saúde")
    pix = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    baker.make(
        "finances.Entry",
        user=user,
        household=household,
        date=date(2026, 6, 23),
        amount=Decimal("31.99"),
        description="Amazon - coletor",
        category=cat,
        payment_method=pix,
    )
    return cat, pix


@pytest.mark.django_db
def test_export_then_import_roundtrip_idempotent(user, household, tmp_path):
    _setup(user, household)
    path = tmp_path / "entries.json"
    call_command(
        "transfer_entries",
        "export",
        "--user",
        user.username,
        "--file",
        str(path),
        stderr=StringIO(),
    )
    # simulate transferring to another DB: remove the entry, then import it back
    Entry.objects.all().delete()
    assert Entry.objects.count() == 0

    call_command("transfer_entries", "import", "--apply", "--file", str(path), stdout=StringIO())
    e = Entry.objects.get()
    assert e.amount == Decimal("31.99")
    assert e.category.name == "Saúde"  # resolved by NAME, not id
    assert e.payment_method.name == "Pix"
    assert e.description == "Amazon - coletor"

    # re-import must be idempotent (no duplicate)
    out = StringIO()
    call_command("transfer_entries", "import", "--apply", "--file", str(path), stdout=out)
    assert Entry.objects.count() == 1
    assert "Created 0" in out.getvalue()


@pytest.mark.django_db
def test_import_dry_run_writes_nothing(user, household, tmp_path):
    _setup(user, household)
    path = tmp_path / "entries.json"
    call_command("transfer_entries", "export", "--file", str(path), stderr=StringIO())
    Entry.objects.all().delete()
    out = StringIO()
    call_command("transfer_entries", "import", "--file", str(path), stdout=out)  # no --apply
    assert Entry.objects.count() == 0
    assert "Would create 1" in out.getvalue()


@pytest.mark.django_db
def test_import_reports_missing_category(user, household, tmp_path):
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    path = tmp_path / "entries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "user": user.username,
                    "date": "2026-06-23",
                    "amount": "10.00",
                    "category": "CategoriaInexistente",
                    "payment": "Pix",
                    "description": "x",
                }
            ]
        ),
        encoding="utf-8",
    )
    out = StringIO()
    call_command("transfer_entries", "import", "--apply", "--file", str(path), stdout=out)
    assert Entry.objects.count() == 0
    assert "no category 'CategoriaInexistente'" in out.getvalue()
