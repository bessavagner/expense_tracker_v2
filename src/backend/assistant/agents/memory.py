from django.utils import timezone
from pgvector.django import CosineDistance

from assistant.models import MemoryEmbedding, MemoryRule

# Confidence thresholds
AUTO_APPLY = 0.9  # >= 0.9: apply silently
CONFIRM_APPLY = 0.7  # 0.7–0.9: apply with confirmation hint
# < 0.7: ask user before using


def find_matching_rules(scope, message: str) -> list[MemoryRule]:
    """Find memory rules whose trigger appears in the message (case-insensitive substring)."""
    rules = MemoryRule.objects.for_household(scope.household)
    matched = []
    message_lower = message.lower()
    for rule in rules:
        if rule.trigger.lower() in message_lower:
            matched.append(rule)
    if matched:
        MemoryRule.objects.filter(pk__in=[r.pk for r in matched]).update(
            last_used_at=timezone.now()
        )
    return matched


def find_semantic_matches(
    scope, query_vector: list[float], threshold: float = 0.8, limit: int = 5
) -> list:
    """Memory embeddings similar to ``query_vector``, nearest first.

    The threshold is applied in Python, deliberately. A ``WHERE distance < x``
    predicate makes Postgres compute the distance for every candidate row, which
    means a sequential scan no matter what index exists — pgvector's HNSW index
    answers "the k nearest", not "everything within a radius". Ordering and
    limiting in SQL, then filtering the small result set here, is what lets the
    index do its job.
    """
    max_distance = 1 - threshold
    nearest = (
        MemoryEmbedding.objects.for_household(scope.household)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")[:limit]
    )
    return [match for match in nearest if match.distance < max_distance]
