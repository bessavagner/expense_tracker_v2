"""What the product knows about people, and what it does about that.

The public surface is deliberately small, the same discipline as
``core.tasks``: everything else in this package is internal, so the inventory
cannot be bypassed by importing something one layer down and writing a second
list of models.
"""

from core.privacy.consent import (
    AI_CONSENT_REQUIRED,
    ahas_ai_consent,
    has_ai_consent,
    set_ai_consent,
)
from core.privacy.deletion import DeletionReceipt, delete_account
from core.privacy.inventory import (
    INVENTORY,
    Basis,
    Disposal,
    Record,
    model_for,
    purgeable,
    record_for,
)
from core.privacy.retention import PURGE_EXPIRED_DATA, count_expired, purge_expired

__all__ = [
    "AI_CONSENT_REQUIRED",
    "INVENTORY",
    "PURGE_EXPIRED_DATA",
    "Basis",
    "DeletionReceipt",
    "Disposal",
    "Record",
    "ahas_ai_consent",
    "count_expired",
    "delete_account",
    "has_ai_consent",
    "model_for",
    "purgeable",
    "purge_expired",
    "record_for",
    "set_ai_consent",
]
