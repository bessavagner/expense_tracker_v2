import json

from django.test import override_settings


def test_assetlinks_served_at_well_known_path(client):
    resp = client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")


@override_settings(
    TWA_PACKAGE_NAME="com.bessavagner.ledger",
    TWA_CERT_FINGERPRINTS=["AB:CD:EF:01:23"],
)
def test_assetlinks_structure(client):
    resp = client.get("/.well-known/assetlinks.json")
    data = json.loads(resp.content)
    assert isinstance(data, list)
    assert len(data) == 1
    stmt = data[0]
    assert stmt["relation"] == ["delegate_permission/common.handle_all_urls"]
    target = stmt["target"]
    assert target["namespace"] == "android_app"
    assert target["package_name"] == "com.bessavagner.ledger"
    assert target["sha256_cert_fingerprints"] == ["AB:CD:EF:01:23"]


@override_settings(TWA_CERT_FINGERPRINTS=[])
def test_assetlinks_without_fingerprint_is_still_valid_json(client):
    resp = client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    data = json.loads(resp.content)
    assert data[0]["target"]["sha256_cert_fingerprints"] == []
