"""How a person is named on screen.

The fallback is not an edge case: every account that exists on the day this
ships has a blank `first_name`, so `display_name` returns the email address
for all of them. It is the normal path, and the test says so.
"""

import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestDisplayName:
    def test_it_is_the_name_when_one_is_set(self):
        person = baker.make("core.CustomUser", email="vagner@example.com", first_name="Vagner")
        assert person.display_name == "Vagner"

    def test_it_falls_back_to_the_email_when_the_name_is_blank(self):
        person = baker.make("core.CustomUser", email="vagner@example.com", first_name="")
        assert person.display_name == "vagner@example.com"

    def test_whitespace_is_not_a_name(self):
        """Otherwise a user types a space and becomes invisible on the members list."""
        person = baker.make("core.CustomUser", email="vagner@example.com", first_name="   ")
        assert person.display_name == "vagner@example.com"

    def test_it_strips_the_name_it_returns(self):
        person = baker.make("core.CustomUser", email="vagner@example.com", first_name=" Vagner ")
        assert person.display_name == "Vagner"
