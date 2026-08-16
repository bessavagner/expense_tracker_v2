"""Every entry records how it was captured, so the wedge ratio is computable.

The ratio S14-3 calls the most important number: AI-captured against
manually-typed. If users are typing entries rather than photographing receipts,
the wedge is not landing.
"""

import pytest
from model_bakery import baker

from accounts.models import Household
from core.events import ONCE_PER_HOUSEHOLD, EventName, emit
from core.models import ProductEvent

pytestmark = pytest.mark.django_db


def test_entry_created_is_not_a_once_event():
    """Once-per-household events cannot count anything. This one has to count."""
    assert EventName.ENTRY_CREATED not in ONCE_PER_HOUSEHOLD


def test_the_event_survives_many_writes_in_one_household():
    """The partial unique index must not apply here — two entries, two rows."""
    household = baker.make(Household, name="Casa de teste")

    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "form"})
    emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "receipt"})

    assert ProductEvent.objects.filter(name=EventName.ENTRY_CREATED).count() == 2


def test_the_metadata_carries_a_source_and_nothing_else():
    """Constraint 11: counts and enum values, never user content. A description
    leaking into metadata is a PII incident, not a bug."""
    household = baker.make(Household, name="Casa de teste")

    row = emit(EventName.ENTRY_CREATED, household=household, metadata={"source": "chat"})

    assert set(row.metadata) == {"source"}
