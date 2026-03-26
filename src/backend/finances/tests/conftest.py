import pytest
from model_bakery import baker


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    return baker.make("core.CustomUser", username="amanda")
