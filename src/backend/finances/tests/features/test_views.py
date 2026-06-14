from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker
from pytest_bdd import given, parsers, scenario, then, when


@scenario("views.feature", "View entries for a specific month")
def test_view_entries_for_month():
    pass


@scenario("views.feature", "Create entry via inline form")
def test_create_entry_inline():
    pass


@scenario("views.feature", "Create installment via modal")
def test_create_installment():
    pass


@scenario("views.feature", "View consolidated expenses by category")
def test_view_consolidated():
    pass


@scenario("views.feature", "Change category budget in settings")
def test_change_budget():
    pass


@pytest.fixture
def ctx():
    return {}


@given("a logged-in user with entries in March 2026", target_fixture="ctx")
def given_user_with_march_entries(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make(
        "finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300")
    )
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 5),
        amount=Decimal("100"),
        category=cat,
        payment_method=pm,
        billing_month=date(2026, 3, 1),
    )
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 15),
        amount=Decimal("200"),
        category=cat,
        payment_method=pm,
        billing_month=date(2026, 3, 1),
    )
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 2, 10),
        amount=Decimal("50"),
        category=cat,
        payment_method=pm,
        billing_month=date(2026, 2, 1),
    )
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with categories and payment methods", target_fixture="ctx")
def given_user_with_cats_pms(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with a credit card closing on day 25", target_fixture="ctx")
def given_user_with_cc(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make("finances.Category", user=user, name="Trabalho")
    pm = baker.make("finances.PaymentMethod", user=user, type="credit_card", closing_day=25)
    ctx.update({"user": user, "client": client, "category": cat, "pm": pm})
    return ctx


@given("a logged-in user with entries in multiple categories", target_fixture="ctx")
def given_user_with_multi_cat(db, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat1 = baker.make(
        "finances.Category", user=user, name="Alimentação", budget_ceiling=Decimal("1300")
    )
    cat2 = baker.make(
        "finances.Category", user=user, name="Combustível", budget_ceiling=Decimal("460")
    )
    pm = baker.make("finances.PaymentMethod", user=user, type="pix")
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 5),
        amount=Decimal("1400"),
        category=cat1,
        payment_method=pm,
        billing_month=date(2026, 3, 1),
    )
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 3, 10),
        amount=Decimal("200"),
        category=cat2,
        payment_method=pm,
        billing_month=date(2026, 3, 1),
    )
    ctx.update({"user": user, "client": client, "cat1": cat1, "cat2": cat2})
    return ctx


@given(
    parsers.parse('a logged-in user with a category "{name}" with ceiling {ceiling:d}'),
    target_fixture="ctx",
)
def given_user_with_category(db, name, ceiling, ctx):
    user = baker.make("core.CustomUser")
    client = Client()
    client.force_login(user)
    cat = baker.make(
        "finances.Category", user=user, name=name, budget_ceiling=Decimal(str(ceiling))
    )
    ctx.update({"user": user, "client": client, "category": cat})
    return ctx


@when("I visit the entries page for March 2026")
def when_visit_entries(ctx):
    ctx["response"] = ctx["client"].get("/entries/2026/3/")


@then("I should see only March entries")
def then_see_march_entries(ctx):
    entries = ctx["response"].context["entries"]
    assert len(entries) == 2
    assert all(e.billing_month.month == 3 for e in entries)


@then("I should see a summary with total expenses")
def then_see_summary(ctx):
    summary = ctx["response"].context["summary"]
    assert summary["total_expenses"] == Decimal("300")
    assert summary["entry_count"] == 2


@when(parsers.parse('I submit an inline entry for "{desc}" with amount {amount}'))
def when_submit_inline(ctx, desc, amount):
    ctx["response"] = ctx["client"].post(
        "/entries/create/",
        data={
            "date": "2026-03-15",
            "amount": amount,
            "description": desc,
            "category": str(ctx["category"].id),
            "payment_method": str(ctx["pm"].id),
        },
        HTTP_HX_REQUEST="true",
    )


@then("the entry should be created")
def then_entry_created(ctx):
    from finances.models import Entry

    assert Entry.objects.filter(user=ctx["user"]).exists()


@then("the entry should appear in the table")
def then_entry_in_table(ctx):
    assert ctx["response"].status_code == 200


@when(parsers.parse("I create a {count:d}-installment plan for R$ {total}"))
def when_create_installment(ctx, count, total):
    total_decimal = Decimal(total)
    installment = (total_decimal / count).quantize(Decimal("0.01"))
    ctx["response"] = ctx["client"].post(
        "/entries/modal/",
        data={
            "entry_mode": "installment",
            "date": "2026-03-15",
            "description": "Test plan",
            "category": str(ctx["category"].id),
            "payment_method": str(ctx["pm"].id),
            "total_amount": str(total_decimal),
            "num_installments": str(count),
            "installment_amount": str(installment),
        },
        HTTP_HX_REQUEST="true",
    )


@then(parsers.parse("{count:d} installment entries should be created"))
def then_installment_entries(ctx, count):
    from finances.models import Entry

    assert Entry.objects.filter(user=ctx["user"], entry_type="installment").count() == count


@then("the first billing month should be the computed month")
def then_first_billing_month(ctx):
    from finances.models import Entry

    first = (
        Entry.objects.filter(user=ctx["user"], entry_type="installment")
        .order_by("billing_month")
        .first()
    )
    # March 15 with closing day 25 → March (15 <= 25)
    assert first.billing_month == date(2026, 3, 1)


@when(parsers.parse("I visit the consolidated page for {year:d}"))
def when_visit_consolidated(ctx, year):
    # The fixture creates March entries; the consolidated view is month-scoped.
    ctx["response"] = ctx["client"].get(f"/consolidated/?year={year}&month=3")


@then("I should see category totals per month")
def then_see_category_totals(ctx):
    cards = ctx["response"].context["category_cards"]
    assert len(cards) >= 2


@then("categories over budget should be highlighted")
def then_over_budget_highlighted(ctx):
    cards = ctx["response"].context["category_cards"]
    food = next(c for c in cards if c["name"] == "Alimentação")
    assert food["status"] == "error"


@when(parsers.parse("I change the budget ceiling to {new_ceiling:d}"))
def when_change_ceiling(ctx, new_ceiling):
    ctx["response"] = ctx["client"].post(
        f"/settings/categories/{ctx['category'].id}/edit/",
        data={"budget_ceiling": str(new_ceiling)},
        HTTP_HX_REQUEST="true",
    )


@then(parsers.parse("the ceiling should be updated to {expected:d}"))
def then_ceiling_updated(ctx, expected):
    ctx["category"].refresh_from_db()
    assert ctx["category"].budget_ceiling == Decimal(str(expected))
