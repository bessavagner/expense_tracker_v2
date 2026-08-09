"""Semantic memory search must use the HNSW index and keep finding the match.

An approximate index can reorder ties, so these tests assert that the expected
memory is returned — never that some exact list of five rows comes back in some
exact order.
"""

import random
import re

import pytest
from django.db import connection

from assistant.agents.memory import find_semantic_matches
from assistant.models import MemoryEmbedding

DIMENSIONS = 1536


def _vector(rng):
    return [rng.random() for _ in range(DIMENSIONS)]


def _readable(plan: str) -> str:
    """EXPLAIN echoes the whole 1536-dimension probe vector back in the Sort key.

    Printing that on failure buries the one line anybody needs in a screenful of
    floats, so collapse any long bracketed literal.
    """
    return re.sub(r"\[[-0-9.,e ]{80,}\]", "[…probe vector…]", plan)


@pytest.fixture
def haystack(user):
    """One known needle plus enough noise that a seq scan is the wrong plan."""
    rng = random.Random(20260808)  # noqa: S311 — synthetic vectors, not crypto
    needle_vector = _vector(rng)
    needle = MemoryEmbedding.objects.create(
        user=user, text="mercado cosmos é alimentação", embedding=needle_vector
    )
    MemoryEmbedding.objects.bulk_create(
        [
            MemoryEmbedding(user=user, text=f"ruído {i}", embedding=_vector(rng))
            for i in range(3000)
        ],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_memoryembedding;")
    return needle, needle_vector


@pytest.mark.django_db
def test_hnsw_index_exists():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'assistant_memoryembedding'"
        )
        rows = dict(cursor.fetchall())
    assert "memory_embed_hnsw_cosine_idx" in rows
    definition = rows["memory_embed_hnsw_cosine_idx"]
    assert "hnsw" in definition.lower()
    assert "vector_cosine_ops" in definition


@pytest.mark.django_db
def test_exact_match_is_found(user, haystack):
    needle, needle_vector = haystack
    matches = find_semantic_matches(user, needle_vector, threshold=0.8, limit=5)
    assert needle.id in [m.id for m in matches]


@pytest.mark.django_db
def test_threshold_still_excludes_distant_rows(user, haystack):
    """A near-orthogonal probe must return nothing, index or no index."""
    _, needle_vector = haystack
    orthogonal = [-value for value in needle_vector]
    assert find_semantic_matches(user, orthogonal, threshold=0.99, limit=5) == []


@pytest.mark.django_db
def test_limit_is_respected(user, haystack):
    _, needle_vector = haystack
    assert len(find_semantic_matches(user, needle_vector, threshold=0.0, limit=3)) <= 3


@pytest.mark.django_db
def test_results_are_scoped_to_the_user(user, other_user, haystack):
    _, needle_vector = haystack
    MemoryEmbedding.objects.create(user=other_user, text="vizinho", embedding=needle_vector)
    matches = find_semantic_matches(user, needle_vector, threshold=0.0, limit=50)
    assert all(m.user_id == user.id for m in matches)


@pytest.mark.django_db
def test_the_nearest_neighbour_query_uses_the_hnsw_index(user, haystack):
    """The ORDER BY … LIMIT shape is the only one HNSW can answer.

    Asserted on raw SQL rather than through find_semantic_matches so the test
    fails loudly if someone reintroduces a WHERE on the distance expression.
    """
    _, needle_vector = haystack
    literal = "[" + ",".join(str(v) for v in needle_vector) + "]"
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off;")
        cursor.execute(
            "EXPLAIN SELECT id FROM assistant_memoryembedding "
            "ORDER BY embedding <=> %s::vector LIMIT 5",
            [literal],
        )
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "memory_embed_hnsw_cosine_idx" in plan, _readable(plan)
