"""A brand-new household must be able to record something without setup.

`Entry.category` and `Entry.payment_method` are required, so a household with
neither cannot write its first row — that is the wall S11-2 removes.
"""

import pytest
from django.urls import reverse

from accounts.starter_data import (
    STARTER_CATEGORIES,
    STARTER_PAYMENT_METHODS,
    seed_starter_data,
)
from assistant.models import MemoryRule
from assistant.starter_rules import DEFAULT_RULES
from core.events import EventName
from core.models import ProductEvent
from finances.models import Category, PaymentMethod


@pytest.mark.django_db
class TestSeeding:
    def test_it_creates_the_starter_catalogue(self, household, user):
        counts = seed_starter_data(household, user)

        assert counts["categories"] == len(STARTER_CATEGORIES)
        assert counts["payment_methods"] == len(STARTER_PAYMENT_METHODS)
        assert Category.objects.for_household(household).count() == len(STARTER_CATEGORIES)
        assert PaymentMethod.objects.for_household(household).count() == len(
            STARTER_PAYMENT_METHODS
        )

    def test_it_is_idempotent(self, household, user):
        seed_starter_data(household, user)
        second = seed_starter_data(household, user)

        assert second == {"categories": 0, "payment_methods": 0, "rules": 0}
        assert Category.objects.for_household(household).count() == len(STARTER_CATEGORIES)

    def test_it_never_touches_another_household(self, household, other_household, user):
        seed_starter_data(household, user)

        assert Category.objects.for_household(other_household).count() == 0

    def test_seeded_rows_are_attributed_to_the_seeding_user(self, household, user):
        seed_starter_data(household, user)

        assert Category.objects.for_household(household).exclude(created_by=user).count() == 0

    def test_it_emits_household_seeded_once(self, household, user):
        seed_starter_data(household, user)
        seed_starter_data(household, user)

        assert (
            ProductEvent.objects.for_household(household)
            .filter(name=EventName.HOUSEHOLD_SEEDED)
            .count()
            == 1
        )


@pytest.mark.django_db
class TestTheAssistantWorksImmediately:
    def test_every_starter_memory_rule_targets_a_starter_category(self):
        """S11-2: the AI works on day one rather than after manual setup.

        A pure-data assertion, so it fails at review time rather than the first
        time a real receipt is photographed by a real stranger.
        """
        starter_names = {name for name, _is_system in STARTER_CATEGORIES}
        missing = {
            category for _trigger, category in DEFAULT_RULES if category not in starter_names
        }

        assert missing == set()

    def test_seeding_installs_the_memory_rules(self, household, user):
        counts = seed_starter_data(household, user)

        assert counts["rules"] == len(DEFAULT_RULES)
        assert MemoryRule.objects.for_household(household).count() == len(DEFAULT_RULES)


@pytest.mark.django_db
class TestDefaultsAreAStartingPointNotACage:
    def test_non_system_starter_categories_can_be_deleted(self, household, user):
        seed_starter_data(household, user)
        category = Category.objects.for_household(household).get(name="Lanche")

        category.delete()

        assert not Category.objects.for_household(household).filter(name="Lanche").exists()

    def test_starter_categories_seed_with_no_invented_budget(self, household, user):
        """A ceiling copied from someone else's household is a made-up number."""
        seed_starter_data(household, user)

        assert Category.objects.for_household(household).exclude(budget_ceiling=0).count() == 0


@pytest.mark.django_db
class TestSignupSeeds:
    def test_a_brand_new_signup_can_record_an_entry_with_zero_setup(self, client):
        client.post(
            reverse("account_signup"),
            {
                "email": "estranho@example.com",
                "email2": "estranho@example.com",
                "password1": "uma-senha-bem-comprida",
                "password2": "uma-senha-bem-comprida",
                # E13: the signup form now carries a required acceptance checkbox.
                "accept_terms": "on",
            },
        )
        household = ProductEvent.objects.get(name=EventName.SIGNUP).household

        assert Category.objects.for_household(household).exists()
        assert PaymentMethod.objects.for_household(household).filter(is_active=True).exists()
