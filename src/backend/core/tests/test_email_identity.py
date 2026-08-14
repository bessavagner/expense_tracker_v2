"""Email is the identity. Two accounts may not share one.

Email-only login is only coherent if the address resolves to exactly one
account — otherwise `authenticate()` has to pick, and picking is a
vulnerability, not a feature.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

User = get_user_model()


@pytest.mark.django_db
class TestEmailUniqueness:
    def test_two_accounts_cannot_share_an_email(self):
        User.objects.create_user(
            username="primeiro", email="casa@example.com", password="senha-longa-o-bastante"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="segundo", email="casa@example.com", password="senha-longa-o-bastante"
            )

    def test_email_is_required(self):
        field = User._meta.get_field("email")
        assert field.unique is True
        assert field.blank is False


@pytest.mark.django_db
class TestExistingAccountsSurviveTheMigration:
    def test_fixtures_have_distinct_emails(self, user, other_user):
        """The suite's two tenants must not collide under the new constraint."""
        assert user.email
        assert other_user.email
        assert user.email != other_user.email
