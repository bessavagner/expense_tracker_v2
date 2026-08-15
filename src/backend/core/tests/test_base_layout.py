import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.mark.django_db
def test_main_has_bottom_padding_for_floating_controls(client):
    """The shared <main> must pad the bottom so the fixed FAB/chat button
    never cover the last row of long pages (e.g. Configurações)."""
    from accounts.resolution import household_for_user
    from conftest import complete_onboarding

    User = get_user_model()
    user = User.objects.create_user(username="u1", email="u1@example.com", password="pw")
    complete_onboarding(household_for_user(user))
    # E05: the login identifier is the address, not the username.
    client.login(username="u1@example.com", password="pw")
    resp = client.get(reverse("finances:settings"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "pb-28" in html
