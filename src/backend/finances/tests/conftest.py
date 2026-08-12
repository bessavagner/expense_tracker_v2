import pytest
from django.test import Client

# `user`, `other_user`, `household` and `other_household` live in the root
# `src/backend/conftest.py` — one definition, reachable from every app's tests.


@pytest.fixture
def logged_client(user, household):
    """A logged-in client whose user resolves to a household.

    `household` is requested for its side effect: the middleware reads
    `request.household` from a Membership, and a user without one makes every
    scoped queryset return none() — which would turn "the neighbour's row is
    absent" assertions into vacuous passes.
    """
    client = Client()
    client.force_login(user)
    return client
