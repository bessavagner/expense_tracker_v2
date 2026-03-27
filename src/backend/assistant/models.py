import uuid

from django.conf import settings
from django.db import models


class MessageRole(models.TextChoices):
    USER = "user", "Usuário"
    ASSISTANT = "assistant", "Assistente"


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["created_at"]

    def __str__(self):
        preview = self.content[:50]
        return f"[{self.role}] {preview}"
