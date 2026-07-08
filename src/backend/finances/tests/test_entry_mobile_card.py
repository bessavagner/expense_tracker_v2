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
