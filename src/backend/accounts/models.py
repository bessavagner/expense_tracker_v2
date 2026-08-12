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
            models.Index(
                fields=["household", "created_at"], name="membership_household_age_idx"
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"
