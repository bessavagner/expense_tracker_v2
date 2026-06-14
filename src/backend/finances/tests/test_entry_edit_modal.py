import pytest
from datetime import date
from django.urls import reverse
from model_bakery import baker

from finances.models import Entry
from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return baker.make(django_user_model)


@pytest.fixture
def entry(user):
    return baker.make(
        Entry,
        user=user,
        entry_type=EntryType.REGULAR,
        amount="10.00",
        description="Old desc",
        date=date(2026, 6, 1),
        billing_month=date(2026, 6, 1),
    )


def test_get_returns_prefilled_form(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Old desc" in resp.content
    assert b"entry-edit-form" in resp.content


def test_post_valid_updates_and_returns_row(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.post(
        url,
        {
            "date": "2026-06-02",
            "amount": "25.50",
            "description": "New desc",
            "category": entry.category_id,
            "payment_method": entry.payment_method_id,
        },
    )
    assert resp.status_code == 200
    entry.refresh_from_db()
    assert entry.description == "New desc"
    assert str(entry.amount) == "25.50"
    assert f'id="entry-{entry.id}"'.encode() in resp.content
    assert resp.headers.get("HX-Trigger") and "entry-saved" in resp.headers["HX-Trigger"]


def test_post_invalid_returns_form_with_errors(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    resp = client.post(url, {"date": "", "amount": "", "description": ""})
    assert resp.status_code == 200
    assert b"entry-edit-form" in resp.content
    entry.refresh_from_db()
    assert entry.description == "Old desc"


def test_cannot_edit_other_users_entry(client, django_user_model, entry):
    other = baker.make(django_user_model)
    client.force_login(other)
    url = reverse("finances:entry_edit_modal", args=[entry.id])
    assert client.get(url).status_code == 404
