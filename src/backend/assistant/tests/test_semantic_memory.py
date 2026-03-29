import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from assistant.models import MemoryEmbedding

User = get_user_model()


class MemoryEmbeddingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_create_embedding(self):
        embedding = MemoryEmbedding.objects.create(
            user=self.user,
            text="compra no supermercado cosmos",
            embedding=[0.1] * 1536,
            metadata={"field": "category", "value": "Alimentação"},
        )
        self.assertIsInstance(embedding.id, uuid.UUID)
        self.assertEqual(embedding.text, "compra no supermercado cosmos")
        self.assertEqual(len(embedding.embedding), 1536)
        self.assertEqual(embedding.metadata["field"], "category")

    def test_embedding_str(self):
        embedding = MemoryEmbedding.objects.create(
            user=self.user,
            text="compra no supermercado cosmos que é muito bom e fica na esquina",
            embedding=[0.0] * 1536,
        )
        self.assertIn("compra no supermercado", str(embedding))

    def test_embedding_user_cascade_delete(self):
        MemoryEmbedding.objects.create(
            user=self.user,
            text="test",
            embedding=[0.0] * 1536,
        )
        self.user.delete()
        self.assertEqual(MemoryEmbedding.objects.count(), 0)


class SemanticSearchTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="searchuser", password="testpass")
        # Create embeddings with known vectors for cosine similarity testing
        self.emb1 = MemoryEmbedding.objects.create(
            user=self.user,
            text="supermercado cosmos",
            embedding=[1.0] + [0.0] * 1535,
            metadata={"field": "category", "value": "Alimentação"},
        )
        self.emb2 = MemoryEmbedding.objects.create(
            user=self.user,
            text="posto de gasolina",
            embedding=[0.0, 1.0] + [0.0] * 1534,
            metadata={"field": "category", "value": "Combustível"},
        )

    def test_find_semantic_matches_returns_similar(self):
        from assistant.agents.memory import find_semantic_matches

        query_vector = [0.9] + [0.1] + [0.0] * 1534
        matches = find_semantic_matches(self.user, query_vector, threshold=0.5)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text, "supermercado cosmos")

    def test_find_semantic_matches_respects_threshold(self):
        from assistant.agents.memory import find_semantic_matches

        query_vector = [0.5, 0.5] + [0.0] * 1534
        matches = find_semantic_matches(self.user, query_vector, threshold=0.95)
        self.assertEqual(len(matches), 0)

    def test_find_semantic_matches_filters_by_user(self):
        from assistant.agents.memory import find_semantic_matches

        other_user = User.objects.create_user(username="other", password="testpass")
        MemoryEmbedding.objects.create(
            user=other_user,
            text="other user embedding",
            embedding=[1.0] + [0.0] * 1535,
        )
        query_vector = [1.0] + [0.0] * 1535
        matches = find_semantic_matches(self.user, query_vector, threshold=0.5)
        self.assertTrue(all(m.user == self.user for m in matches))
