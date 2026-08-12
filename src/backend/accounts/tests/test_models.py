import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


def test_household_has_uuid_pk_and_str():
    household = baker.make(Household, name="Casa Bessa")
    assert str(household) == "Casa Bessa"
    # UUID pk, matching the convention in finances/models/category.py
    assert len(str(household.id)) == 36
