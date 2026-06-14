import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_main_has_bottom_padding_for_floating_controls(client):
    """The shared <main> must pad the bottom so the fixed FAB/chat button
    never cover the last row of long pages (e.g. Configurações)."""
    User = get_user_model()
    User.objects.create_user(username="u1", password="pw")
    client.login(username="u1", password="pw")
    resp = client.get(reverse("finances:settings"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "pb-28" in html
