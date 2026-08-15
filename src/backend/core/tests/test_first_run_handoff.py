"""The last onboarding step lands on a page that opens the chat by itself."""

import pytest


@pytest.mark.django_db
def test_the_handoff_url_renders_the_dashboard_with_the_chat_flag(logged_client):
    response = logged_client.get("/?comecar=foto")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-react-component="ChatWidget"' in body
    assert 'data-autostart="foto"' in body
