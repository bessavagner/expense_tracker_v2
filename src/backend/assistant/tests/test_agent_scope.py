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


def test_scope_is_frozen(user, household, scope):
    """An LLM-driven tool must not be able to reassign its own scope."""
    scope = AgentScope(household=household, user=user)

    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.household = None


def test_for_request_reads_the_middlewares_household(rf, user, household, scope):
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


def test_memory_rules_are_household_scoped(user, household, other_user, other_household, scope):
    from assistant.agents.memory import find_matching_rules

    baker.make(
        "assistant.MemoryRule",
        household=other_household,
        trigger="cerveja",
        field="category",
        value="Álcool",
    )

    scope = AgentScope(household=household, user=user)

    assert find_matching_rules(scope, "comprei cerveja") == []


def test_list_categories_is_household_scoped(scope, user, household, other_user, other_household):

    from assistant.agents.tools import list_categories

    baker.make("finances.Category", household=household, name="Minha")
    baker.make("finances.Category", household=other_household, name="Do vizinho")

    assert list_categories(scope) == ["Minha"]


def test_create_entry_records_the_household_and_the_author(scope, user, household):
    """The plan called this tool `register_entry`; it is `create_entry`."""
    from assistant.agents.tools import create_entry
    from finances.models import Entry

    baker.make("finances.Category", household=household, name="Alimentação")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")

    create_entry(scope, "2026-03-10", "50.00", "Feira", "Alimentação", "Pix")

    entry = Entry.objects.get(description="Feira")
    assert entry.household == household
    assert entry.created_by == user


def test_a_tool_cannot_widen_its_scope_through_an_argument(
    scope, user, household, other_user, other_household
):
    """The DoD's argument-injection assertion. `category_name` is LLM-supplied;
    naming another household's category must fail to resolve, not reach it."""
    from assistant.agents.tools import create_entry
    from finances.models import Entry

    baker.make("finances.Category", household=other_household, name="Segredo")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")

    result = create_entry(scope, "2026-03-10", "50.00", "Feira", "Segredo", "Pix")

    assert not Entry.objects.filter(description="Feira").exists()
    assert "Segredo" in result
    assert "não encontrada" in result


def test_agent_deps_type_is_the_scope():
    """Pinned deliberately: if someone reverts deps to a User, every tool
    silently starts scoping by the actor again."""
    from assistant.agents.assistant import assistant_agent

    assert assistant_agent._deps_type is AgentScope


def test_chat_history_is_household_scoped(
    logged_client, user, household, other_user, other_household
):
    from django.urls import reverse

    baker.make(
        "assistant.ChatMessage",
        household=other_household,
        role="user",
        content="segredo do vizinho",
    )

    body = logged_client.get(reverse("assistant:chat")).content.decode()

    assert "segredo do vizinho" not in body
