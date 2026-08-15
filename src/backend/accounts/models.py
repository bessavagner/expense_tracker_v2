import uuid

from django.conf import settings
from django.db import models

from accounts.scoping import HouseholdScopedManager
from core.tiers import Tier


class Plan(models.Model):
    """What a household is entitled to per month.

    Credits are a product currency, deliberately NOT real tokens (E07 spec D2).
    They are a stable unit a customer can reason about and we can reprice
    without changing what they were promised. Real token counts live in
    ``assistant.UsageRecord``.

    E15 extends this with money. Today nothing is charged (PD-3: free capped
    beta, paid at GA), so there is no price column yet.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=40, unique=True)
    monthly_credits = models.PositiveIntegerField(
        help_text="Créditos concedidos no início de cada mês civil."
    )
    # A household with no plan falls back to this one, so `balance_for` never
    # has to decide what "no plan" means. The partial unique constraint below
    # makes "exactly one default" a database fact rather than a convention.
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="only_one_default_plan",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.monthly_credits} créditos/mês)"


class Household(models.Model):
    """The tenant. A ledger belongs to a household, not to a person."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    # Nullable: E15 assigns paid plans later without backfilling every beta
    # household. `None` resolves to the default plan at read time.
    plan = models.ForeignKey(
        "accounts.Plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="households",
    )
    # The tier the household WANTS. The chokepoint may override it downward
    # when credits run out; it never overrides upward (E07 spec D2).
    preferred_tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.ADVANCED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "casa"
        verbose_name_plural = "casas"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    OWNER = "owner", "Dono"
    MEMBER = "member", "Membro"


class Membership(models.Model):
    """Links a user to a household. Two roles, deliberately — an owner may
    invite and remove people, a member may only edit the ledger. Anything
    finer-grained is a separate epic (see the epic's decision 2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    # Indexed and ordered on: E13 promotes the longest-standing member when the
    # last owner deletes their account, and the active-household fallback picks
    # the oldest membership so it is deterministic across requests.
    created_at = models.DateTimeField(auto_now_add=True)

    objects = HouseholdScopedManager()

    class Meta:
        verbose_name = "vínculo"
        verbose_name_plural = "vínculos"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "household"], name="unique_membership_per_household"
            )
        ]
        indexes = [
            models.Index(fields=["household", "created_at"], name="membership_household_age_idx"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"


class HouseholdOwnedModel(models.Model):
    """A domain row that belongs to a household.

    Abstract on purpose: re-tenanting a model is a change to its base class,
    so there is exactly one definition of the tenant column and phase 4 can
    enumerate the models instead of trusting a hand-maintained list.

    ``household`` was nullable through E04 phases 2 and 3, while the back-fill
    ran and while write sites still set only ``user``. Phase 4 made it NOT
    NULL: every write path now names its household explicitly, and from here
    the database is what enforces tenancy — not a signal, not a convention. A
    row with no household is impossible rather than merely unintended.
    """

    household = models.ForeignKey(
        "accounts.Household",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s",
    )

    objects = HouseholdScopedManager()

    class Meta:
        abstract = True


class AuthoredHouseholdModel(HouseholdOwnedModel):
    """A household row a person wrote.

    ``created_by`` is not decoration — it delivers review finding M5 (no audit
    trail) as a side effect of work we are doing anyway, and E17 surfaces it.

    SET_NULL rather than CASCADE: when a member leaves or deletes their
    account, the household's financial history must survive. That distinction
    is the entire reason ``user`` splits into two columns instead of being
    renamed.
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True


def household_owned_models():
    """Every concrete model carrying a household column.

    Discovered, not listed. A model added later that inherits the base is
    covered by phase 4's isolation test automatically; a model added later
    that *forgets* to inherit it is caught by the same test's counterpart.
    """
    from django.apps import apps

    return [
        model
        for model in apps.get_models()
        if issubclass(model, HouseholdOwnedModel) and not model._meta.abstract
    ]


class Invitation(AuthoredHouseholdModel):
    """A pending offer to join a household.

    Inherits ``AuthoredHouseholdModel`` rather than ``models.Model`` so the
    tenant column is the same one every other domain row carries: E04's
    ratchet test enumerates by base class, so this model is covered by the
    cross-household isolation suite the moment it exists, without anyone
    adding it to a list.

    ``created_by`` is the inviter. SET_NULL, like everywhere else — an owner
    who deletes their account must not take the household's invitation history
    with them.

    The raw token is never stored. ``token_hash`` holds its SHA-256, so a
    database read — a leaked backup, an over-broad admin query — yields
    nothing redeemable. See ``accounts.invitations``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("e-mail convidado")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "convite"
        verbose_name_plural = "convites"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["household", "-created_at"], name="invite_household_recent_idx"),
        ]

    def __str__(self):
        return f"{self.email} → {self.household}"

    def is_expired(self, now=None) -> bool:
        """Clock injected: `docs/testing-conventions.md` — a boundary test must
        not have to straddle two reads of `timezone.now()`."""
        from django.utils import timezone

        return self.expires_at <= (now or timezone.now())

    @property
    def is_pending(self) -> bool:
        """Redeemable right now: not accepted, not revoked, not expired."""
        return self.accepted_at is None and self.revoked_at is None and not self.is_expired()


class OnboardingStep(models.TextChoices):
    """The guided setup, in order.

    Three, against S11-3's ceiling of five. Each one removes a wall a stranger
    would otherwise hit silently: no income means an empty projection, no card
    means every credit purchase lands in the wrong billing month, and no photo
    means they never see what this product is for.
    """

    INCOME = "income", "Renda"
    CARDS = "cards", "Cartões"
    CAPTURE = "capture", "Primeira foto"


class OnboardingState(models.Model):
    """How far through the guided setup a household is.

    On the household rather than the user: a second person joining a household
    that is already set up must not be walked through setting it up again.

    A step is "done" whether the user filled it in or skipped it. That is
    deliberate — S11-3 requires every step to be skippable and skipping not to
    break anything, so the flow only needs to know it has *asked*.
    """

    household = models.OneToOneField(
        Household,
        on_delete=models.CASCADE,
        related_name="onboarding",
        primary_key=True,
    )
    steps_done = models.JSONField(default=list, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "início de uso"
        verbose_name_plural = "inícios de uso"

    def __str__(self):
        return f"{self.household}: {len(self.steps_done)}/{len(OnboardingStep)}"

    @classmethod
    def for_household(cls, household):
        """This household's progress, creating the row on first sight."""
        state, _ = cls.objects.get_or_create(household=household)
        return state

    def next_step(self):
        """The first step not yet asked, or ``None`` when the flow is over."""
        done = set(self.steps_done or [])
        for step in OnboardingStep:
            if step.value not in done:
                return step.value
        return None

    @property
    def is_complete(self) -> bool:
        return self.next_step() is None

    def mark(self, step) -> None:
        """Record that ``step`` has been asked. Idempotent."""
        from django.utils import timezone

        value = str(step)
        steps = list(self.steps_done or [])
        if value not in steps:
            steps.append(value)
            self.steps_done = steps
        # Stamped once. A user who walks back through a finished flow has not
        # re-onboarded, and moving this timestamp would move E14's cohort.
        if self.completed_at is None and self.next_step() is None:
            self.completed_at = timezone.now()
        self.save(update_fields=["steps_done", "completed_at", "updated_at"])
