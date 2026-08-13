import uuid

from django.conf import settings
from django.db import models

from accounts.scoping import HouseholdScopedManager


class Household(models.Model):
    """The tenant. A ledger belongs to a household, not to a person."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
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
