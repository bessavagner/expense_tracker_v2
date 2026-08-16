import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from accounts.models import HouseholdOwnedModel


class CustomUser(AbstractUser):
    # AbstractUser leaves this blank-able and non-unique. E05 makes the address
    # the login identifier, so it has to be exactly one account's. `username`
    # stays — ten models and every historical migration reference it — but
    # allauth derives it from the email and no screen shows it.
    email = models.EmailField("endereço de e-mail", unique=True)

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.username


class LoginAttempt(models.Model):
    """A failed authentication, kept only long enough to enforce a lockout.

    Not a security audit log — E17 owns that. Rows here exist to be counted
    inside a short rolling window and are deleted on a successful login.
    """

    username = models.CharField(max_length=254)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tentativa de login"
        verbose_name_plural = "tentativas de login"
        indexes = [
            models.Index(fields=["username", "-created_at"], name="login_username_recent_idx"),
            models.Index(fields=["ip", "-created_at"], name="login_ip_recent_idx"),
        ]

    def __str__(self):
        return f"{self.username}@{self.ip} {self.created_at:%Y-%m-%d %H:%M}"


class AdminAccessLog(models.Model):
    """One row per staff request that admin actually answered.

    S05-5: 'staff access to customer data is logged with actor, target, and
    timestamp'. Distinct from `LoginAttempt`, which is a lockout counter that
    gets deleted on success — these rows are kept.

    Refused requests are deliberately absent: a 404 for a non-staff user means
    nothing was disclosed, and logging those would drown the rows that record
    a human actually reading someone's money.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    path = models.CharField(max_length=500)
    method = models.CharField(max_length=10)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "acesso administrativo"
        verbose_name_plural = "acessos administrativos"
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="adminlog_actor_recent_idx"),
        ]

    def __str__(self):
        return f"{self.actor} {self.method} {self.path} @ {self.created_at:%Y-%m-%d %H:%M}"


class TaskStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    DONE = "done", "Concluída"
    DEAD = "dead", "Descartada"


class TaskRun(models.Model):
    """One unit of deferred work, and everything an operator needs about it.

    Cloud Tasks has no dead-letter queue: when a task exhausts its attempts the
    service simply drops it. So the attempt ceiling lives here, on a row that
    can be queried, listed in admin and replayed — rather than only in the
    queue's ``retryConfig``, where "it gave up" leaves no trace. It also makes
    the whole retry and dead-letter path testable without the cloud.

    ``idempotency_key`` is the at-least-once defence. Cloud Tasks may deliver
    the same task more than once; ``core.tasks.enqueue`` upserts on this column
    and the dispatch view refuses to re-run a row that already reached DONE.

    ``payload`` lives on the row rather than in the task body on purpose: only
    the row's id crosses the wire, so the fixed 1 MiB Cloud Tasks task ceiling
    stops being something every caller has to reason about.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    # The request that scheduled this work (E06, S10-5). Same 32-hex shape as
    # `core.request_id`, so one Cloud Logging filter finds the originating
    # request and the task it spawned.
    request_id = models.CharField(max_length=32, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "execução de tarefa"
        verbose_name_plural = "execuções de tarefa"
        ordering = ["-created_at"]
        indexes = [
            # The dead-letter sweep the runbook documents.
            models.Index(fields=["status", "-created_at"], name="taskrun_status_recent_idx"),
            # "How is this particular handler doing?"
            models.Index(fields=["name", "-created_at"], name="taskrun_name_recent_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.status}, {self.attempts}/{self.max_attempts})"


class ProductEvent(HouseholdOwnedModel):
    """One thing a person did that the product wants to count.

    Database-derived rather than shipped to an analytics vendor (E14 open
    question 1): it is cheaper, the numbers can be recomputed from history when
    a definition changes, and it keeps one more sub-processor off E13's
    inventory.

    ``metadata`` never carries user content — no descriptions, no store names,
    no chat text. Counts, ids and enum values only. Same discipline as
    ``core.observability.scrub_event``, and for the same reason: this table is
    read by operators and exported by E13.

    ``once`` marks the events that may happen at most once per household —
    activation above all. The partial unique constraint makes "the first
    receipt" a database fact rather than a convention, so two concurrent
    commits cannot both claim it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    once = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de produto"
        verbose_name_plural = "eventos de produto"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"],
                condition=models.Q(once=True),
                name="one_once_event_per_household",
            )
        ]
        indexes = [
            models.Index(fields=["name", "-created_at"], name="event_name_recent_idx"),
            models.Index(fields=["household", "-created_at"], name="event_hh_recent_idx"),
        ]

    def __str__(self):
        return f"{self.name} @ {self.household} ({self.created_at:%Y-%m-%d %H:%M})"


class Feedback(HouseholdOwnedModel):
    """What a beta user said, in their own words.

    The one place in E14 that stores user-authored text on purpose. It does NOT
    go in `ProductEvent.metadata`, whose PII rule forbids user content — which is
    the whole reason this is a separate table with its own entry on E13's
    processing inventory. See `docs/architecture/product-metrics.md`.

    `context` carries where they were when they wrote it, so a report is
    actionable, and never anything they typed on another screen.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    message = models.TextField(max_length=4000)
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "feedback"
        verbose_name_plural = "feedbacks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.household} @ {self.created_at:%Y-%m-%d %H:%M}"
