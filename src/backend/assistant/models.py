import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from accounts.models import AuthoredHouseholdModel, HouseholdOwnedModel


class MessageRole(models.TextChoices):
    USER = "user", "Usuário"
    ASSISTANT = "assistant", "Assistente"


class ChatMessage(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
        # Redundant with chat_user_recent_idx, whose leading column is user.
        # See the note on finances.Entry.user.
        db_index=False,
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"
        ordering = ["created_at"]
        indexes = [
            # Every chat turn loads the last ASSISTANT_MAX_HISTORY messages
            # newest-first (assistant/views.py, `_load_history`), which is the
            # opposite of Meta.ordering — hence the explicit descending index.
            models.Index(fields=["user", "-created_at"], name="chat_user_recent_idx"),
        ]

    def __str__(self):
        preview = self.content[:50]
        return f"[{self.role}] {preview}"


class MemorySource(models.TextChoices):
    USER_CORRECTION = "user_correction", "Correção do usuário"
    INFERRED = "inferred", "Inferido"


class MemoryRule(AuthoredHouseholdModel):
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
        constraints = [
            models.UniqueConstraint(
                fields=["household", "trigger", "field"],
                name="unique_memory_rule_per_household",
            ),
        ]

    def __str__(self):
        return f"{self.trigger} → {self.field}={self.value}"


class ReceiptDraftStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    REGISTERED = "registered", "Registrado"
    DISCARDED = "discarded", "Descartado"


class ReceiptDraft(AuthoredHouseholdModel):
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
        # Redundant with draft_user_status_recent_idx, whose leading column is
        # user. See the note on finances.Entry.user.
        db_index=False,
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
        indexes = [
            # The pending-draft lookup that runs on every chat turn
            # (assistant/views.py, `_pending_receipt`).
            models.Index(
                fields=["user", "status", "-created_at"],
                name="draft_user_status_recent_idx",
            ),
        ]

    def __str__(self):
        store = (self.payload or {}).get("store", "?")
        return f"Recibo {store} ({self.status})"


class MemoryEmbedding(HouseholdOwnedModel):
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
        indexes = [
            # pgvector's own defaults. At this scale — thousands of vectors, not
            # millions — they give effectively exhaustive recall, and raising
            # them costs build time and index memory on a Supabase instance that
            # is not sized for it. vector_cosine_ops must match the distance
            # operator used by CosineDistance (<=>), or the index is ignored.
            HnswIndex(
                name="memory_embed_hnsw_cosine_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return self.text[:50]


class AssistantUsageKind(models.TextChoices):
    TEXT = "text", "Texto"
    IMAGE = "image", "Imagem"


class AssistantUsageEvent(HouseholdOwnedModel):
    """One admitted assistant turn.

    Written *before* the model call, so the counter records intent to spend
    rather than successful spend — a run that fails halfway still consumed the
    tokens. Audio turns count as ``TEXT``: transcription is roughly two orders of
    magnitude cheaper per turn than a vision call, so only the image path earns a
    budget of its own.

    E07 will extend this row with token counts. The household FK it wanted
    landed in E04 phase 2; `user` stays as the acting member, since a quota is
    charged to a household but attributed to a person. Keep it append-only and
    cheap to write.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_usage_events",
    )
    kind = models.CharField(max_length=20, choices=AssistantUsageKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de uso do assistente"
        verbose_name_plural = "eventos de uso do assistente"
        indexes = [
            models.Index(
                fields=["user", "kind", "-created_at"],
                name="usage_user_kind_recent_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.kind} {self.created_at:%Y-%m-%d %H:%M}"
