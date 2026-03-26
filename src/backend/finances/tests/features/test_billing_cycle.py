import pytest
from datetime import datetime
from decimal import Decimal
from model_bakery import baker
from pytest_bdd import given, when, then, scenario, parsers
from finances.models import Entry, EntryType


@scenario("billing_cycle.feature", "Pix purchase stays in current month")
def test_pix_stays_in_current_month():
    pass

@scenario("billing_cycle.feature", "Credit card purchase before closing day")
def test_credit_before_closing():
    pass

@scenario("billing_cycle.feature", "Credit card purchase after closing day")
def test_credit_after_closing():
    pass

@scenario("billing_cycle.feature", "Credit card purchase on closing day")
def test_credit_on_closing():
    pass

@scenario("billing_cycle.feature", "December purchase after closing rolls to January")
def test_december_rolls_to_january():
    pass


@pytest.fixture
def context():
    return {}

@given(parsers.parse('a user with payment method "{name}" of type "{pm_type}"'), target_fixture="context")
def given_user_with_payment_method(db, name, pm_type, context):
    user = baker.make("core.CustomUser")
    pm = baker.make("finances.PaymentMethod", user=user, name=name, type=pm_type)
    category = baker.make("finances.Category", user=user, name="Test")
    context["user"] = user
    context["payment_method"] = pm
    context["category"] = category
    return context

@given(parsers.parse("a user with a credit card closing on day {day:d}"), target_fixture="context")
def given_user_with_credit_card(db, day, context):
    user = baker.make("core.CustomUser")
    pm = baker.make("finances.PaymentMethod", user=user, name="Cartão Teste", type="credit_card", closing_day=day)
    category = baker.make("finances.Category", user=user, name="Test")
    context["user"] = user
    context["payment_method"] = pm
    context["category"] = category
    return context

@when(parsers.parse('I create an expense on "{date_str}" with that payment method'))
def when_create_expense(context, date_str):
    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    entry = Entry.objects.create(
        user=context["user"], date=entry_date, amount=Decimal("100.00"),
        description="Test expense", category=context["category"],
        payment_method=context["payment_method"], entry_type=EntryType.REGULAR,
    )
    context["entry"] = entry

@then(parsers.parse('the billing month should be "{expected_str}"'))
def then_billing_month_is(context, expected_str):
    expected = datetime.strptime(expected_str, "%Y-%m-%d").date()
    assert context["entry"].billing_month == expected
