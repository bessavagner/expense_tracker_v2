"""Memory rules become semantically searchable — off the request.

Finding F3 behind this epic: `create_memory_rule` never generated an embedding,
so `MemoryEmbedding` was empty outside the perf seed and the semantic fallback
in `lookup_memory_async` searched nothing. These tests pin both halves: the
vector now gets generated, and the feature still works while it has not.
"""

from unittest import mock

import pytest
from asgiref.sync import sync_to_async

from assistant.models import MemoryEmbedding, MemoryRule
from assistant.tasks import EMBED_MEMORY_RULE, embed_memory_rule, embedding_id_for
from core.models import TaskRun, TaskStatus

VECTOR = [0.05] * 1536


@pytest.fixture
def fake_embedding():
    """Patch where the handler looks it up, not where it is defined.

    `embed_memory_rule` imports `get_embedding` inside the function body
    precisely so this patch is total — and so the module keeps importing
    cleanly under the autouse `no_real_embedding_calls` guard.
    """

    async def _embed(text, *, scope=None):
        return VECTOR

    with mock.patch("assistant.services.embedding.get_embedding", side_effect=_embed) as patched:
        yield patched


@pytest.mark.django_db
class TestCreateMemoryRuleEnqueues:
    def test_creating_a_rule_generates_its_embedding(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        rule = MemoryRule.objects.get(trigger="cosmos")
        embedding = MemoryEmbedding.objects.get(id=embedding_id_for(rule.pk))
        assert embedding.household_id == scope.household.pk
        assert embedding.metadata["rule_id"] == str(rule.pk)
        assert embedding.metadata["field"] == "category"
        assert embedding.metadata["value"] == "Alimentação"
        assert "cosmos" in embedding.text

    def test_the_task_run_is_recorded_as_done(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        run = TaskRun.objects.get(name=EMBED_MEMORY_RULE)
        assert run.status == TaskStatus.DONE
        assert run.attempts == 1

    def test_re_saving_the_same_rule_and_value_does_not_re_embed(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")
        create_memory_rule(scope, "cosmos", "category", "Alimentação")

        assert TaskRun.objects.filter(name=EMBED_MEMORY_RULE).count() == 1
        assert fake_embedding.call_count == 1

    def test_changing_the_value_re_embeds_into_the_same_row(self, scope, fake_embedding):
        """The key is 'this rule, at this value'. A correction must produce a
        fresh vector, and must not leave the stale one behind."""
        from assistant.agents.tools import create_memory_rule

        create_memory_rule(scope, "cosmos", "category", "Alimentação")
        create_memory_rule(scope, "cosmos", "category", "Mercado")

        rule = MemoryRule.objects.get(trigger="cosmos")
        assert TaskRun.objects.filter(name=EMBED_MEMORY_RULE).count() == 2
        assert MemoryEmbedding.objects.count() == 1
        assert MemoryEmbedding.objects.get(id=embedding_id_for(rule.pk)).metadata["value"] == (
            "Mercado"
        )

    def test_an_unavailable_queue_does_not_break_teaching_a_rule(self, scope, fake_embedding):
        """A rule the user just taught us must survive an outage in the thing
        that indexes it. The substring matcher works either way."""
        from assistant.agents import tools

        with mock.patch.object(tools, "enqueue", side_effect=RuntimeError("queue is down")):
            result = tools.create_memory_rule(scope, "cosmos", "category", "Alimentação")

        assert MemoryRule.objects.filter(trigger="cosmos").exists()
        assert "criada" in result

    def test_an_invalid_field_still_enqueues_nothing(self, scope, fake_embedding):
        from assistant.agents.tools import create_memory_rule

        result = create_memory_rule(scope, "cosmos", "nao_existe", "x")

        assert "inválido" in result
        assert not TaskRun.objects.exists()


@pytest.mark.django_db
class TestHandler:
    def test_running_it_twice_leaves_one_embedding(self, scope, household, fake_embedding):
        """Cloud Tasks delivers at least once. The embedding id is derived from
        the rule id, so exactly-one-row is a property of the id rather than a
        convention someone has to keep."""
        rule = MemoryRule.objects.create(
            household=household, trigger="cosmos", field="category", value="Alimentação"
        )

        embed_memory_rule({"rule_id": str(rule.pk)})
        embed_memory_rule({"rule_id": str(rule.pk)})

        assert MemoryEmbedding.objects.count() == 1

    def test_a_rule_deleted_before_dispatch_is_not_an_error(self, db, fake_embedding):
        """Retrying will not bring it back, so this must not look like failure."""
        import uuid

        embed_memory_rule({"rule_id": str(uuid.uuid4())})

        assert MemoryEmbedding.objects.count() == 0

    def test_a_provider_failure_raises_so_the_rails_retry(self, scope, household):
        """Raising is the signal that earns a retry. Returning quietly would
        leave a rule permanently unsearchable with nothing in the tracker —
        the exact failure S10-4 names."""
        rule = MemoryRule.objects.create(
            household=household, trigger="cosmos", field="category", value="Alimentação"
        )

        async def _none(text, *, scope=None):
            return None

        with mock.patch("assistant.services.embedding.get_embedding", side_effect=_none):
            with pytest.raises(RuntimeError):
                embed_memory_rule({"rule_id": str(rule.pk)})


@pytest.mark.django_db
def test_a_rule_with_no_embedding_yet_is_still_matched_by_substring(scope, household):
    """The DoD box: a memory rule created while its embedding is pending is
    still matched by the substring path — so the feature degrades to
    'exact trigger only' rather than breaking."""
    from assistant.agents.tools import lookup_memory

    MemoryRule.objects.create(
        household=household, trigger="cosmos", field="category", value="Alimentação"
    )

    result = lookup_memory(scope, "comprei no cosmos hoje")

    assert MemoryEmbedding.objects.count() == 0
    assert "Alimentação" in result


@pytest.mark.anyio
@pytest.mark.django_db(transaction=True)
async def test_it_works_through_the_agent_s_sync_to_async_wrapper(fake_embedding):
    """`create_memory_rule` reaches the handler from inside `sync_to_async`
    (assistant/agents/assistant.py:369), and the handler calls back into async
    to reach the embeddings API. asgiref supports that nesting, but it is
    exactly the kind of thing that only breaks in the real call path.

    The user and household are built inside the test rather than taken from the
    `scope` fixture: those fixtures depend on pytest-django's `db`, which wraps
    the test in an atomic block on the main connection — and `sync_to_async`
    runs in a worker thread with a connection of its own that would not see any
    of it. `transaction=True` is what makes the rows visible across threads, and
    it cannot be combined with a fixture that requested `db`.
    """
    from model_bakery import baker

    from accounts.resolution import household_for_user
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import create_memory_rule

    def _build_scope():
        user = baker.make("core.CustomUser", username="vagner", email="vagner@example.com")
        return AgentScope(household=household_for_user(user), user=user)

    scope = await sync_to_async(_build_scope)()

    await sync_to_async(create_memory_rule)(scope, "cosmos", "category", "Alimentação")

    count = await sync_to_async(MemoryEmbedding.objects.count)()
    assert count == 1
