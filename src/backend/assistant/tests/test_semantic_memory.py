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
