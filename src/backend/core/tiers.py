"""The three assistant model tiers.

Lives in ``core`` rather than ``assistant`` because both ``accounts``
(``Household.preferred_tier``) and ``assistant`` (``CreditPrice.tier``) need it,
and ``accounts`` importing ``assistant`` would be circular — ``assistant.models``
already imports ``accounts.models.HouseholdOwnedModel``.

The English names are the *product* names (E07 spec D2), so there is no
translation layer between what the code calls a tier and what a customer is
sold. pt-BR labels are the display layer, per global constraint 8.
"""

from django.db import models


class Tier(models.TextChoices):
    ADVANCED = "advanced", "Avançado"
    STANDARD = "standard", "Padrão"
    ESSENTIAL = "essential", "Essencial"


# Most expensive first. The quota cascade walks this in order, so the direction
# is load-bearing, not cosmetic.
TIER_ORDER: tuple[str, ...] = (Tier.ADVANCED, Tier.STANDARD, Tier.ESSENTIAL)
