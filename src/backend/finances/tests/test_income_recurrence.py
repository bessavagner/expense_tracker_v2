from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Income
from finances.services.income_recurrence import apply_income_recurrence


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser")


@pytest.mark.django_db
def test_noop_when_not_recurring(household):
    inc = baker.make(
        Income,
        household=household,
        name="Salário",
        amount="100",
        month=date(2026, 6, 1),
        is_recurring=False,
    )
    assert apply_income_recurrence(inc) == 0
    assert Income.objects.for_household(household).count() == 1


@pytest.mark.django_db
def test_materializes_window(household):
    inc = baker.make(
        Income,
        household=household,
        name="Salário",
        amount="5000",
        month=date(2026, 6, 1),
        is_recurring=True,
        recurrence_start=date(2026, 6, 1),
        recurrence_end=date(2026, 9, 1),
    )
    touched = apply_income_recurrence(inc)
    assert touched == 4
    months = sorted(
        Income.objects.for_household(household)
        .filter(name="Salário")
        .values_list("month", flat=True)
    )
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]


@pytest.mark.django_db
def test_upserts_existing_amount(household):
    baker.make(Income, household=household, name="Salário", amount="4000", month=date(2026, 7, 1))
    inc = baker.make(
        Income,
        household=household,
        name="Salário",
        amount="5000",
        month=date(2026, 6, 1),
        is_recurring=True,
        recurrence_start=date(2026, 6, 1),
        recurrence_end=date(2026, 7, 1),
    )
    apply_income_recurrence(inc)
    july = Income.objects.for_household(household).get(name="Salário", month=date(2026, 7, 1))
    assert july.amount == Decimal("5000")
    assert Income.objects.for_household(household).filter(name="Salário").count() == 2


@pytest.mark.django_db
def test_defaults_to_year_end_when_blank(household):
    inc = baker.make(
        Income,
        household=household,
        name="Bolsa",
        amount="600",
        month=date(2026, 10, 1),
        is_recurring=True,
        recurrence_start=None,
        recurrence_end=None,
    )
    apply_income_recurrence(inc)
    months = sorted(
        Income.objects.for_household(household).filter(name="Bolsa").values_list("month", flat=True)
    )
    assert months == [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]


@pytest.mark.django_db
def test_duplicate_same_name_month_does_not_raise(household):
    baker.make(Income, household=household, name="Freelance", amount="100", month=date(2026, 6, 1))
    inc = baker.make(
        Income,
        household=household,
        name="Freelance",
        amount="500",
        month=date(2026, 6, 1),
        is_recurring=True,
        recurrence_start=date(2026, 6, 1),
        recurrence_end=date(2026, 6, 1),
    )
    # Must not raise MultipleObjectsReturned
    apply_income_recurrence(inc)
    rows = Income.objects.for_household(household).filter(name="Freelance", month=date(2026, 6, 1))
    assert rows.count() == 2
    assert all(r.amount == Decimal("500") for r in rows)


@pytest.mark.django_db
def test_cockpit_edit_modal_materializes(user, household):
    inc = baker.make(
        Income, household=household, name="Salário", amount="5000", month=date(2026, 6, 1)
    )
    c = Client()
    c.force_login(user)
    resp = c.post(
        f"/cockpit/2026/6/income/{inc.pk}/edit-modal/",
        {
            "name": "Salário",
            "amount": "5000",
            "month": "2026-06-01",
            "is_recurring": "on",
            "recurrence_start": "2026-06-01",
            "recurrence_end": "2026-08-01",
        },
    )
    assert resp.status_code == 200
    months = sorted(
        Income.objects.for_household(household)
        .filter(name="Salário")
        .values_list("month", flat=True)
    )
    assert months == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]


@pytest.mark.django_db
def test_recurrence_copies_carry_the_author(user, household):
    """The copies must record who wrote them.

    Before this phase the write bridge filled `created_by` as a side effect of
    filling `household`. Now that the service sets `household` explicitly the
    bridge returns early, so the author has to be set here or it is lost.
    """
    original = baker.make(
        Income,
        household=household,
        created_by=user,
        name="Salário",
        amount=Decimal("8000.00"),
        month=date(2026, 6, 1),
        is_recurring=True,
        recurrence_start=date(2026, 6, 1),
        recurrence_end=date(2026, 8, 1),
    )

    apply_income_recurrence(original)

    copies = Income.objects.for_household(household).filter(name="Salário").exclude(pk=original.pk)
    assert copies.count() == 2
    assert not copies.filter(created_by=None).exists()
    assert all(c.household == household for c in copies)
