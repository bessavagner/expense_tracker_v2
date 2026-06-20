import pytest


@pytest.mark.django_db
def test_dashboard_has_projection_card(logged_client):
    resp = logged_client.get("/")
    assert resp.status_code == 200
    assert b'id="projection-card"' in resp.content  # server-rendered projection card
