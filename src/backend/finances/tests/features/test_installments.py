from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker
from pytest_bdd import given, parsers, scenario, then, when

from finances.models import InstallmentPlan


@scenario("installments.feature", "Create a 3-installment plan")
def test_create_3_installment_plan():
    pass


@scenario("installments.feature", "Rounding remainder goes to last installment")
def test_rounding_remainder():
    pass


@pytest.fixture
def context():
    return {}


@given(parsers.parse("a user with a credit card closing on day {day:d}"), target_fixture="context")
def given_user_with_credit_card(db, day, context):
    user = baker.make("core.CustomUser")
    pm = baker.make(
        "finances.PaymentMethod", user=user, name="Cartão", type="credit_card", closing_day=day
    )
    context["user"] = user
    context["payment_method"] = pm
    return context


@given(parsers.parse('a category "{name}"'))
def given_category(context, name):
    category = baker.make("finances.Category", user=context["user"], name=name)
    context["category"] = category


@when(parsers.parse("I create an installment plan for R$ {total} in {count:d} installments"))
def when_create_plan_even(context, total, count):
    total_decimal = Decimal(total)
    installment = (total_decimal / count).quantize(Decimal("0.01"))
    plan = InstallmentPlan.objects.create(
        user=context["user"],
        date=date(2026, 3, 1),
        description="Test plan",
        category=context["category"],
        payment_method=context["payment_method"],
        total_amount=total_decimal,
        num_installments=count,
        installment_amount=installment,
    )
    context["plan"] = plan
    context["entries"] = plan.generate_entries()


@when(
    parsers.parse(
        "I create an installment plan for R$ {total} in {count:d} installments at R$ {each} each"
    )
)
def when_create_plan_with_amount(context, total, count, each):
    plan = InstallmentPlan.objects.create(
        user=context["user"],
        date=date(2026, 3, 1),
        description="Test plan",
        category=context["category"],
        payment_method=context["payment_method"],
        total_amount=Decimal(total),
        num_installments=count,
        installment_amount=Decimal(each),
    )
    context["plan"] = plan
    context["entries"] = plan.generate_entries()


@then(parsers.parse("{count:d} entries should be created"))
def then_entry_count(context, count):
    assert len(context["entries"]) == count


@then(parsers.parse("each entry should have amount R$ {amount}"))
def then_each_amount(context, amount):
    expected = Decimal(amount)
    assert all(e.amount == expected for e in context["entries"])


@then("entries should have sequential billing months")
def then_sequential_months(context):
    months = [e.billing_month for e in context["entries"]]
    for i in range(1, len(months)):
        prev, curr = months[i - 1], months[i]
        if prev.month == 12:
            assert curr == date(prev.year + 1, 1, 1)
        else:
            assert curr == date(prev.year, prev.month + 1, 1)


@then(parsers.parse("the last entry should have amount R$ {amount}"))
def then_last_amount(context, amount):
    assert context["entries"][-1].amount == Decimal(amount)


@then(parsers.parse("the total of all entries should equal R$ {total}"))
def then_total_equals(context, total):
    actual_total = sum(e.amount for e in context["entries"])
    assert actual_total == Decimal(total)
