import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


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


class MemorySource(models.TextChoices):
    USER_CORRECTION = "user_correction", "Correção do usuário"
    INFERRED = "inferred", "Inferido"


class MemoryRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memory_rules",
    )
    trigger = models.CharField(max_length=255)
    field = models.CharField(max_length=50)
    value = models.CharField(max_length=255)
    confidence = models.FloatField(default=1.0)
    source = models.CharField(max_length=20, choices=MemorySource.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "regra de memória"
        verbose_name_plural = "regras de memória"
        unique_together = ("user", "trigger", "field")

    def __str__(self):
        return f"{self.trigger} → {self.field}={self.value}"


class ReceiptDraftStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    REGISTERED = "registered", "Registrado"
    DISCARDED = "discarded", "Descartado"


class ReceiptDraft(models.Model):
    """Recibo extraído de uma foto, persistido para sobreviver ao turno.

    Guardar a extração estruturada (itens + valores) permite que o turno de
    correção ("separe as categorias") tenha os dados por item — sem isto o
    registrador roda cego e não consegue ratear/repartir.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="receipt_drafts",
    )
    chat_message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="receipt_drafts",
        null=True,
        blank=True,
    )
    payload = models.JSONField()
    status = models.CharField(
        max_length=20,
        choices=ReceiptDraftStatus.choices,
        default=ReceiptDraftStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "rascunho de recibo"
        verbose_name_plural = "rascunhos de recibo"
        ordering = ["-created_at"]

    def __str__(self):
        store = (self.payload or {}).get("store", "?")
        return f"Recibo {store} ({self.status})"


class MemoryEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memory_embeddings",
    )
    text = models.TextField()
    embedding = VectorField(dimensions=1536)
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "embedding de memória"
        verbose_name_plural = "embeddings de memória"

    def __str__(self):
        return self.text[:50]
