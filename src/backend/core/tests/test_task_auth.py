"""The only thing between a stranger and the task handlers.

Cloud Run does not check the token for us — the service is deployed
--allow-unauthenticated because it is a public web app. Every one of these
tests is a way the door could be left open.
"""

from unittest import mock

import pytest
from django.test import RequestFactory, override_settings

from core.tasks import auth

SERVICE_ACCOUNT = "ledger-tasks@expense-tracker-482807.iam.gserviceaccount.com"
AUDIENCE = "https://ledger.example.com"

CONFIGURED = override_settings(
    CLOUD_TASKS_OIDC_SERVICE_ACCOUNT=SERVICE_ACCOUNT,
    CLOUD_TASKS_AUDIENCE=AUDIENCE,
)


@pytest.fixture
def post():
    return RequestFactory().post("/tasks/test.name/")


def _with_token(request, token="a-token"):  # noqa: S107 — a placeholder, verified by a stub
    request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return request


@override_settings(CLOUD_TASKS_OIDC_SERVICE_ACCOUNT="", CLOUD_TASKS_AUDIENCE="")
def test_it_fails_closed_with_no_service_account_configured(post):
    """A missing setting must mean 'refuse everything', never 'allow everything'."""
    assert auth.rejection_reason(_with_token(post)) is not None


@CONFIGURED
def test_a_request_with_no_authorization_header_is_refused(post):
    assert auth.rejection_reason(post) == "missing bearer token"


@CONFIGURED
def test_a_non_bearer_authorization_header_is_refused(post):
    post.META["HTTP_AUTHORIZATION"] = "Basic dXNlcjpwYXNz"

    assert auth.rejection_reason(post) == "missing bearer token"


@CONFIGURED
def test_an_empty_bearer_token_is_refused(post):
    post.META["HTTP_AUTHORIZATION"] = "Bearer    "

    assert auth.rejection_reason(post) == "empty bearer token"


@CONFIGURED
def test_a_token_google_rejects_is_refused(post):
    with mock.patch.object(auth, "verify_id_token", side_effect=ValueError("bad signature")):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "token rejected: ValueError"


@CONFIGURED
def test_a_token_for_another_service_account_is_refused(post):
    claims = {"email": "someone-else@example.com", "email_verified": True}

    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "wrong service account"


@CONFIGURED
def test_an_unverified_service_account_email_is_refused(post):
    claims = {"email": SERVICE_ACCOUNT, "email_verified": False}

    with mock.patch.object(auth, "verify_id_token", return_value=claims):
        reason = auth.rejection_reason(_with_token(post))

    assert reason == "unverified service account email"


@CONFIGURED
def test_a_genuine_cloud_tasks_dispatch_is_accepted(post):
    claims = {"email": SERVICE_ACCOUNT, "email_verified": True}

    with mock.patch.object(auth, "verify_id_token", return_value=claims) as verifier:
        reason = auth.rejection_reason(_with_token(post, "the-real-token"))

    assert reason is None
    verifier.assert_called_once_with("the-real-token", AUDIENCE)
