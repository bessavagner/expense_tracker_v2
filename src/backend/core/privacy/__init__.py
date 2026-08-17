"""What the product knows about people, and what it does about that.

The public surface is deliberately small, the same discipline as
``core.tasks``: everything else in this package is internal, so the inventory
cannot be bypassed by importing something one layer down and writing a second
list of models.
"""

from core.privacy.inventory import (
    INVENTORY,
    Basis,
    Disposal,
    Record,
    model_for,
    purgeable,
    record_for,
)

__all__ = [
    "INVENTORY",
    "Basis",
    "Disposal",
    "Record",
    "model_for",
    "purgeable",
    "record_for",
]
