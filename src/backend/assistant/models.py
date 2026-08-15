import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from accounts.models import AuthoredHouseholdModel, HouseholdOwnedModel
from core.tiers import Tier


class MessageRole(models.TextChoices):
    USER = "user", "Usuário"
    ASSISTANT = "assistant", "Assistente"


class ChatMessage(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Redundant with chat_hh_recent_idx, whose leading column is household.
    # Measured at product scale: with this index present the planner picks it
    # over the composite and then sorts; without it, chat_hh_recent_idx serves
    # the query. See the note on finances.Entry.household.
    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
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
            models.Index(fields=["household", "-created_at"], name="chat_hh_recent_idx"),
        ]

    def __str__(self):
        preview = self.content[:50]
        return f"[{self.role}] {preview}"


class MemorySource(models.TextChoices):
    USER_CORRECTION = "user_correction", "Correção do usuário"
    INFERRED = "inferred", "Inferido"


class MemoryRule(AuthoredHouseholdModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    # Redundant with draft_hh_status_recent_idx, whose leading column is
    # household. See the note on finances.Entry.household.
    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
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
                fields=["household", "status", "-created_at"],
                name="draft_hh_status_recent_idx",
            ),
        ]

    def __str__(self):
        store = (self.payload or {}).get("store", "?")
        return f"Recibo {store} ({self.status})"


class MemoryEmbedding(HouseholdOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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


class InteractionKind(models.TextChoices):
    TEXT = "text", "Texto"
    IMAGE = "image", "Imagem"


class UsageInteraction(HouseholdOwnedModel):
    """One admitted user action — the unit credits are charged against.

    Written *before* the model call, so the counter records intent to spend
    rather than successful spend: a run that fails halfway still consumed the
    tokens. Audio turns count as ``TEXT``: transcription is roughly two orders
    of magnitude cheaper per turn than a vision call, so only the image path
    earns a budget of its own.

    This is deliberately NOT the cost ledger. One interaction fans out into
    several ``UsageRecord`` rows — a receipt photo costs an extraction, maybe a
    vision retry, and an agent run. The grains are different, which is why E07
    kept two tables (spec D1): a quota decision must happen *before* any call,
    and token counts do not exist until *after* it.

    ``household`` owns the credits; ``user`` is the acting member, which is
    what the per-user abuse ceiling counts (E04 decision 1). Append-only and
    cheap to write.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_usage_events",
    )
    kind = models.CharField(max_length=20, choices=InteractionKind.choices)
    # Which tier actually served this turn — not which one was asked for. The
    # operator report joins on it, and the UI uses it to tell a degraded user
    # what answered them.
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.ADVANCED)
    # Frozen at write time from CreditPrice, so retuning credit prices never
    # rewrites a household's spent balance. Zero for ESSENTIAL.
    credits_charged = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "interação com o assistente"
        verbose_name_plural = "interações com o assistente"
        indexes = [
            models.Index(
                fields=["user", "kind", "-created_at"],
                name="usage_user_kind_recent_idx",
            ),
            models.Index(
                fields=["household", "kind", "-created_at"],
                name="usage_hh_kind_recent_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.kind} {self.created_at:%Y-%m-%d %H:%M}"


class ModelPrice(models.Model):
    """What a provider charges for one model, per million tokens, in USD.

    A database row rather than a setting (E07 spec D4) because spec D3 requires
    prices to be re-checked against live provider docs rather than recalled —
    and a correction must not need a deploy.

    Not household-scoped: this is global product configuration, not tenant data.

    ``effective_from`` keeps history rather than overwriting: the row that
    applies is the newest one not after the date asked for. Note that a
    ``UsageRecord`` stores its computed cost at write time, so re-pricing never
    rewrites the past — this column exists so a *backfill* can be honest.

    Token pricing only. Transcription models are priced per minute of audio by
    the provider and deliberately have no row here; see the runbook.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_name = models.CharField(
        max_length=120,
        help_text="Exatamente como aparece em settings, incluindo o prefixo do provedor.",
    )
    input_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
    # Nullable, and NULL means "we have not read a cached rate for this model",
    # never "there is no discount". `cost_usd_for` falls back to the full input
    # rate, so an unfilled row keeps the old over-estimate — the safe direction
    # (E01's ceiling trips early) — instead of inventing a discount. D03.
    cached_input_per_mtok = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Tarifa de tokens de entrada já em cache. Vazio = cobra a tarifa cheia.",
    )
    output_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
    effective_from = models.DateField()
    source_url = models.URLField(
        max_length=500,
        help_text="A página de preços consultada. Obrigatória: preço sem fonte é palpite.",
    )
    checked_on = models.DateField(help_text="Quando esta linha foi conferida on-line.")

    class Meta:
        verbose_name = "preço de modelo"
        verbose_name_plural = "preços de modelo"
        ordering = ["model_name", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["model_name", "effective_from"],
                name="unique_model_price_per_date",
            )
        ]

    def __str__(self):
        return f"{self.model_name} @ {self.effective_from}"


class UsageKind(models.TextChoices):
    """What kind of provider call this was — NOT what kind of turn it served.

    `InteractionKind` (text/image) describes the user's action. This describes
    one billable call inside it. A single image interaction fans out into
    EXTRACTION, possibly a second EXTRACTION (the vision retry), and a CHAT.
    """

    CHAT = "chat", "Conversa"
    EXTRACTION = "extraction", "Extração de recibo"
    TRANSCRIPTION = "transcription", "Transcrição"
    EMBEDDING = "embedding", "Embedding"


class UsageRecord(HouseholdOwnedModel):
    """One provider call, with what it cost. The cost ledger.

    Written *after* the call, because token counts do not exist before it. That
    is precisely why this is not the same table as ``UsageInteraction``, which
    must be written *before* the call to gate it (E07 spec D1).

    ``interaction`` is nullable: an embedding or a transcription can be
    triggered outside a chat turn, and a record with no interaction is still a
    real cost that must appear in the operator's report.

    ``cost_usd`` is nullable and means "not priceable", never "free". It is
    computed and frozen at write time, so re-pricing a model never rewrites
    history. USD, not BRL: providers price in USD and an FX rate is E15's
    problem, not this table's.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    interaction = models.ForeignKey(
        "assistant.UsageInteraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=20, choices=UsageKind.choices)
    model = models.CharField(max_length=120)
    input_tokens = models.IntegerField(null=True, blank=True)
    # A SUBSET of input_tokens, not an addition — the provider reports cache
    # reads as part of the prompt. NULL means the provider reported nothing;
    # 0 means nothing was cached. Recorded so the discount `cost_usd` already
    # applied is auditable months later (D03), rather than only visible on the
    # provider's own dashboard.
    cache_read_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    ok = models.BooleanField(default=True)
    # Blank means "not an escalation", never "unknown". Two EXTRACTION records on
    # one interaction could equally be a quality escalation or a retry after a
    # transient 500, and the DoD needs the escalation RATE; a count cannot tell
    # those apart. The reason is also what tunes
    # ASSISTANT_ESCALATE_MIN_CONFIDENCE — "we escalated 40% of the time" is not
    # actionable until you know whether it was confidence or reconciliation.
    escalation_reason = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro de uso"
        verbose_name_plural = "registros de uso"
        indexes = [
            # The operator report's access pattern: one household, one period.
            models.Index(
                fields=["household", "-created_at"],
                name="usagerec_hh_recent_idx",
            ),
            # "What does receipt OCR cost relative to text chat?" — S07-5.
            models.Index(fields=["kind", "-created_at"], name="usagerec_kind_recent_idx"),
        ]

    def __str__(self):
        return f"{self.kind} {self.model} {self.cost_usd}"


class CreditPrice(models.Model):
    """How many credits one interaction costs, by tier and kind.

    A database row (E07 spec D4) so the beta's economics can be retuned from
    the admin once Task 10's report shows what things actually cost.

    ESSENTIAL is zero by definition — it is the free floor a household lands on
    when its credits run out, and charging for it would defeat the whole point.

    Not household-scoped: this is global product configuration, like
    ``ModelPrice``. Per-tenant pricing is E15's problem, and would be a
    different column here rather than a household FK on every row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tier = models.CharField(max_length=20, choices=Tier.choices)
    kind = models.CharField(max_length=20, choices=InteractionKind.choices)
    credits = models.PositiveIntegerField()

    class Meta:
        verbose_name = "preço em créditos"
        verbose_name_plural = "preços em créditos"
        ordering = ["tier", "kind"]
        constraints = [models.UniqueConstraint(fields=["tier", "kind"], name="unique_credit_price")]

    def __str__(self):
        return f"{self.tier}/{self.kind} = {self.credits}"
