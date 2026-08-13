import pytest
from django.core.management import call_command

from assistant.models import MemoryRule

pytestmark = pytest.mark.django_db


def test_seed_creates_nf_token_rules(seeded_user, household):
    call_command("seed_category_rules", "--user", seeded_user.username)
    rules = {
        (r.trigger, r.value)
        for r in MemoryRule.objects.for_household(household).filter(field="category")
    }
    assert ("energ", "Lanche") in rules
    assert ("refrig", "Lanche") in rules
    assert ("monster", "Lanche") in rules


def test_seed_is_idempotent(seeded_user, household):
    call_command("seed_category_rules", "--user", seeded_user.username)
    call_command("seed_category_rules", "--user", seeded_user.username)
    assert (
        MemoryRule.objects.for_household(household)
        .filter(field="category", trigger="energ")
        .count()
        == 1
    )


def test_seed_skips_missing_category(user, household):
    # `user` fixture has NO categories → every rule is skipped, none created.
    call_command("seed_category_rules", "--user", user.username)
    assert MemoryRule.objects.for_household(household).filter(field="category").count() == 0
