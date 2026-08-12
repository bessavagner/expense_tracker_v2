"""The agent's scope comes from deps, never from a tool argument.

This is the epic's DoD item: "a test asserts that a tool cannot be induced to
read another household's data by any tool argument". The discipline exists
today with `deps_type=User`; it must survive becoming a structure.
"""

import dataclasses

import pytest
from model_bakery import baker

from assistant.agents.scope import AgentScope

pytestmark = pytest.mark.django_db


def test_scope_is_frozen(user, household):
    """An LLM-driven tool must not be able to reassign its own scope."""
    scope = AgentScope(household=household, user=user)

    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.household = None


def test_for_request_reads_the_middlewares_household(rf, user, household):
    request = rf.get("/")
    request.user = user
    request.household = household

    scope = AgentScope.for_request(request)

    assert scope.household == household
    assert scope.user == user


def test_for_request_without_middleware_fails_closed(rf, user):
    """A request built without the middleware has no `household` attribute.
    It must yield None — which every scoped queryset turns into none() —
    rather than raising or defaulting to something."""
    request = rf.get("/")
    request.user = user

    assert AgentScope.for_request(request).household is None


def test_memory_rules_are_household_scoped(user, household, other_user, other_household):
    from assistant.agents.memory import find_matching_rules

    baker.make(
        "assistant.MemoryRule",
        user=other_user,
        household=other_household,
        trigger="cerveja",
        field="category",
        value="Álcool",
    )

    scope = AgentScope(household=household, user=user)

    assert find_matching_rules(scope, "comprei cerveja") == []
