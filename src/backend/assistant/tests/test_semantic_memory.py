import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.resolution import household_for_user
from assistant.agents.scope import AgentScope
from assistant.models import MemoryEmbedding

User = get_user_model()


class MemoryEmbeddingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="testuser@example.com", password="testpass"
        )

    def test_create_embedding(self):
        embedding = MemoryEmbedding.objects.create(
            household=household_for_user(self.user),
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
            household=household_for_user(self.user),
            text="compra no supermercado cosmos que é muito bom e fica na esquina",
            embedding=[0.0] * 1536,
        )
        self.assertIn("compra no supermercado", str(embedding))

    def test_embedding_household_cascade_delete(self):
        """The embedding belongs to the household, so the household is what takes
        it away. It used to hang off the user, and deleting a member would have
        destroyed memories the rest of the household still relies on."""
        household = household_for_user(self.user)
        MemoryEmbedding.objects.create(
            household=household,
            text="test",
            embedding=[0.0] * 1536,
        )

        self.user.delete()
        self.assertEqual(MemoryEmbedding.objects.count(), 1)

        household.delete()
        self.assertEqual(MemoryEmbedding.objects.count(), 0)


class SemanticSearchTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="searchuser", email="searchuser@example.com", password="testpass"
        )
        self.household = household_for_user(self.user)
        self.scope = AgentScope(household=self.household, user=self.user)
        # Create embeddings with known vectors for cosine similarity testing
        self.emb1 = MemoryEmbedding.objects.create(
            household=self.household,
            text="supermercado cosmos",
            embedding=[1.0] + [0.0] * 1535,
            metadata={"field": "category", "value": "Alimentação"},
        )
        self.emb2 = MemoryEmbedding.objects.create(
            household=self.household,
            text="posto de gasolina",
            embedding=[0.0, 1.0] + [0.0] * 1534,
            metadata={"field": "category", "value": "Combustível"},
        )

    def test_find_semantic_matches_returns_similar(self):
        from assistant.agents.memory import find_semantic_matches

        query_vector = [0.9] + [0.1] + [0.0] * 1534
        matches = find_semantic_matches(self.scope, query_vector, threshold=0.5)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text, "supermercado cosmos")

    def test_find_semantic_matches_respects_threshold(self):
        from assistant.agents.memory import find_semantic_matches

        query_vector = [0.5, 0.5] + [0.0] * 1534
        matches = find_semantic_matches(self.scope, query_vector, threshold=0.95)
        self.assertEqual(len(matches), 0)

    def test_find_semantic_matches_filters_by_household(self):
        from assistant.agents.memory import find_semantic_matches

        other_user = User.objects.create_user(
            username="other", email="other@example.com", password="testpass"
        )
        MemoryEmbedding.objects.create(
            household=household_for_user(other_user),
            text="other user embedding",
            embedding=[1.0] + [0.0] * 1535,
        )
        query_vector = [1.0] + [0.0] * 1535
        matches = find_semantic_matches(self.scope, query_vector, threshold=0.5)
        self.assertTrue(all(m.household == self.household for m in matches))
