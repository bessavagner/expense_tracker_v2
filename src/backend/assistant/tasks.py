"""Deferred work the assistant schedules.

Discovered by ``core.tasks.registry.autodiscover()`` at startup, so the module
name is part of the contract: this file must stay ``assistant/tasks.py``.
"""

import logging
import uuid

from asgiref.sync import async_to_sync

from core.tasks import task_handler

logger = logging.getLogger(__name__)

EMBED_MEMORY_RULE = "assistant.embed_memory_rule"

# A fixed namespace, so `embedding_id_for` is stable across processes and
# deploys. Any UUID would do; this one is arbitrary and must never change,
# because changing it orphans every embedding already written.
EMBEDDING_NAMESPACE = uuid.UUID("6f8a1c02-3c2e-5f7a-9b4d-2a1f0e5c7d31")


def embedding_id_for(rule_id) -> uuid.UUID:
    """The one embedding row a rule is allowed to have.

    Derived from the rule id rather than stored alongside it: that makes
    exactly-one-row a property of the identifier itself, which cannot drift the
    way a nullable foreign key plus a uniqueness convention can. It is also
    what makes a redelivered task an update instead of a duplicate.
    """
    return uuid.uuid5(EMBEDDING_NAMESPACE, str(rule_id))


@task_handler(EMBED_MEMORY_RULE, max_attempts=4)
def embed_memory_rule(payload: dict) -> None:
    """Give a memory rule a vector, so semantic search can reach it.

    Raises on provider failure — that is the signal that earns a retry.
    Returning quietly would leave the rule permanently unsearchable with
    nothing in the error tracker, which is the exact failure S10-4 names.

    The imports are function-local so that this module stays importable at
    startup (``autodiscover`` runs inside ``AppConfig.ready``) and so that a
    test patching ``assistant.services.embedding.get_embedding`` is patching
    the object this function will actually reach.
    """
    from assistant.models import MemoryEmbedding, MemoryRule
    from assistant.services import embedding as embedding_service

    rule = MemoryRule.objects.filter(pk=payload["rule_id"]).first()
    if rule is None:
        # Deleted between enqueue and dispatch. Retrying will not bring it
        # back, so this is a completed task, not a failed one.
        logger.info("Memory rule %s is gone; skipping its embedding.", payload["rule_id"])
        return

    # The trigger alone is what the substring matcher already covers, so the
    # indexed text includes the conclusion too — that is what makes "onde eu
    # compro comida" reach a rule triggered by "cosmos".
    text = f"{rule.trigger} → {rule.field}={rule.value}"
    vector = async_to_sync(embedding_service.get_embedding)(text)
    if vector is None:
        raise RuntimeError(f"Embedding provider returned nothing for memory rule {rule.pk}.")

    MemoryEmbedding.objects.update_or_create(
        id=embedding_id_for(rule.pk),
        defaults={
            "household": rule.household,
            "text": text,
            "embedding": vector,
            # `lookup_memory_async` reads `field` and `value` straight off this
            # dict to render the match, so the shape is load-bearing.
            "metadata": {
                "rule_id": str(rule.pk),
                "field": rule.field,
                "value": rule.value,
            },
        },
    )
