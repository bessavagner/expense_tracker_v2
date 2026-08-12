import io

import pytest
from django.test import Client
from model_bakery import baker
from pytest_bdd import given, scenario, then, when

from accounts.resolution import household_for_user
from finances.models import Entry, ImportBatch, InstallmentPlan


@scenario("import.feature", "Import regular entries from CSV")
def test_import_regular():
    pass


@scenario("import.feature", "Import installments from CSV")
def test_import_installments():
    pass


@pytest.fixture
def ctx():
    return {}


@given("a logged-in user with seed data", target_fixture="ctx")
def given_user_with_seed(db, ctx):
    user = baker.make("core.CustomUser")
    # Resolved eagerly: the middleware reads `request.household` from a
    # Membership, and a user without one makes every scoped queryset return
    # none() — which would turn every assertion below into a vacuous pass.
    household = household_for_user(user)
    client = Client()
    client.force_login(user)
    baker.make("finances.Category", user=user, household=household, name="Álcool")
    baker.make("finances.Category", user=user, household=household, name="Lanche")
    baker.make("finances.Category", user=user, household=household, name="Roupa")
    baker.make("finances.PaymentMethod", user=user, household=household, name="Pix", type="pix")
    baker.make(
        "finances.PaymentMethod",
        user=user,
        household=household,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )
    ctx.update({"user": user, "household": household, "client": client})
    return ctx


@given("a CSV file with 3 regular entries", target_fixture="ctx")
def given_csv_regular(ctx):
    ctx["csv_content"] = (
        b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
        b'01/03/2026,"R$ 42,00",Entry 1,\xc3\x81lcool,Pix\n'
        b'02/03/2026,"R$ 14,00",Entry 2,Lanche,Pix\n'
        b'03/03/2026,"R$ 50,00",Entry 3,\xc3\x81lcool,Pix\n'
    )
    ctx["import_type"] = "regular"
    return ctx


@given("a CSV file with 1 installment of 2 parcels", target_fixture="ctx")
def given_csv_installment(ctx):
    ctx["csv_content"] = (
        b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma,parcelas,valor_parcela\n"
        b'01/11/2025,"R$ 193,19",Mercado Livre,Roupa,Cr\xc3\xa9dito C6,2,"R$ 96,60"\n'
    )
    ctx["import_type"] = "installment"
    return ctx


@when("I upload the CSV as regular entries")
def when_upload_regular(ctx):
    csv_file = io.BytesIO(ctx["csv_content"])
    csv_file.name = "test.csv"
    ctx["client"].post("/import/", data={"file": csv_file, "import_type": "regular"})


@when("I upload the CSV as installments")
def when_upload_installments(ctx):
    csv_file = io.BytesIO(ctx["csv_content"])
    csv_file.name = "test.csv"
    ctx["client"].post("/import/", data={"file": csv_file, "import_type": "installment"})


@when("I confirm the column mapping")
def when_confirm_mapping(ctx):
    import_type = ctx.get("import_type", "regular")
    if import_type == "installment":
        data = {
            "date": "0",
            "total_amount": "1",
            "description": "2",
            "category": "3",
            "payment_method": "4",
            "num_installments": "5",
            "installment_amount": "6",
        }
    else:
        data = {
            "date": "0",
            "amount": "1",
            "description": "2",
            "category": "3",
            "payment_method": "4",
        }
    ctx["client"].post("/import/map/", data=data)


@when("I execute the import")
def when_execute(ctx):
    ctx["response"] = ctx["client"].post("/import/execute/")


@then("3 entries should exist in the database")
def then_3_entries(ctx):
    assert Entry.objects.filter(user=ctx["user"], entry_type="regular").count() == 3


@then("1 installment plan should exist")
def then_1_plan(ctx):
    assert InstallmentPlan.objects.filter(user=ctx["user"]).count() == 1


@then("2 installment entries should exist")
def then_2_entries(ctx):
    assert Entry.objects.filter(user=ctx["user"], entry_type="installment").count() == 2


@pytest.mark.django_db
def test_import_batch_belongs_to_the_household(ctx):
    """The importer writes rows; an ImportBatch with no household would be a
    row the family cannot see. Drives the same wizard the scenarios above do."""
    given_user_with_seed(None, ctx)
    given_csv_regular(ctx)
    when_upload_regular(ctx)
    when_confirm_mapping(ctx)
    when_execute(ctx)

    batch = ImportBatch.objects.latest("created_at")

    assert batch.household == ctx["household"]
    assert batch.created_by == ctx["user"]
    assert batch.created_count == 3

    entry = Entry.objects.filter(entry_type="regular").first()
    assert entry.household == ctx["household"]
    assert entry.created_by == ctx["user"]
