import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    return baker.make("core.CustomUser", username="amanda")


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client
