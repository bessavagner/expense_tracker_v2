from datetime import date

import pytest
from django.template.loader import render_to_string
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


def test_card_opens_edit_modal_and_has_delete(entry):
    html = render_to_string("entries/_entry_card.html", {"entry": entry})
    edit_url = reverse("finances:entry_edit_modal", args=[entry.id])
    delete_url = reverse("finances:entry_delete", args=[entry.id])
    assert f'id="entry-card-{entry.id}"' in html
    assert f'hx-get="{edit_url}"' in html
    assert "showModal()" in html
    assert f'hx-delete="{delete_url}"' in html
    assert "event.stopPropagation()" in html
    # plain render (no oob flag) must NOT carry the oob attribute
    assert "hx-swap-oob" not in html


def test_card_oob_flag_adds_swap_oob(entry):
    html = render_to_string("entries/_entry_card.html", {"entry": entry, "oob": True})
    assert 'hx-swap-oob="true"' in html


def test_edit_save_syncs_both_row_and_card(client, user, entry):
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
    body = resp.content.decode()
    # desktop row (primary swap target)
    assert f'id="entry-{entry.id}"' in body
    # mobile card, delivered out-of-band
    assert f'id="entry-card-{entry.id}"' in body
    assert 'hx-swap-oob="true"' in body
    # updated value present in the card representation
    assert "New desc" in body
    assert resp.headers.get("HX-Trigger") and "entry-saved" in resp.headers["HX-Trigger"]


def test_delete_removes_both_row_and_card(client, user, entry):
    client.force_login(user)
    url = reverse("finances:entry_delete", args=[entry.id])
    resp = client.delete(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f'id="entry-{entry.id}"' in body and 'hx-swap-oob="delete"' in body
    assert f'id="entry-card-{entry.id}"' in body
    assert not Entry.objects.filter(pk=entry.id).exists()
    assert resp.headers.get("HX-Trigger") and "entries-changed" in resp.headers["HX-Trigger"]


def test_entries_page_renders_mobile_card_include(client, user, entry):
    """Page-level guard: EntryListView GET renders the mobile card via the
    {% include %}. A broken include would slip past the partial-only tests
    above, so assert on the card's unique id in the full page body."""
    client.force_login(user)
    resp = client.get(f"/entries/{entry.date.year}/{entry.date.month}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    edit_url = reverse("finances:entry_edit_modal", args=[entry.id])
    # `entry-card-{id}` is unique to the mobile card partial (the desktop row
    # is `entry-{id}`), so its presence proves the include rendered.
    assert f'id="entry-card-{entry.id}"' in body
    assert f'hx-get="{edit_url}"' in body
