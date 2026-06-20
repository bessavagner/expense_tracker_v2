import pytest


@pytest.mark.django_db
def test_dashboard_mounts_projection_island(logged_client):
    resp = logged_client.get("/")
    assert resp.status_code == 200
    # Projection is now a React island fed by the projection API endpoint.
    assert b'data-react-component="ProjectionCard"' in resp.content
    assert b"/api/dashboard/projection/" in resp.content
