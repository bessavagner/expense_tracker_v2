"""An account that predates allauth must survive the deploy that installs it.

`ACCOUNT_EMAIL_VERIFICATION = "mandatory"` is enforced against allauth's own
`EmailAddress` table, not against `CustomUser.email`. Every account created
before E05 has a `CustomUser` row and no `EmailAddress` row at all — so on the
morning of the deploy allauth would consider each of them unverified, refuse
the login it has always accepted, and send the family to a "confirme seu
e-mail" page for a message nobody sent.

There are three such accounts in production. This is the test that says they
still get in.
"""

import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from model_bakery import baker

SENHA = "senha-longa-de-antes-do-e05"


@pytest.mark.django_db
class TestAccountsThatPredateAllauth:
    def _legacy_account(self, email="antiga@example.com"):
        """A user row with no EmailAddress — exactly what production holds.

        The migration back-fills at deploy time, so a *new* row created in a
        test does not go through it; deleting the address allauth's signals
        create is what reproduces the pre-E05 shape.
        """
        user = baker.make("core.CustomUser", username="antiga", email=email)
        user.set_password(SENHA)
        user.save()
        EmailAddress.objects.filter(user=user).delete()
        return user

    def test_the_migration_gave_every_pre_existing_account_a_verified_address(self):
        """Asserted against the migration's rule, applied to a fresh row."""
        from core import migrations_helpers

        user = self._legacy_account()
        migrations_helpers.backfill(EmailAddress, type(user).objects.filter(pk=user.pk))

        address = EmailAddress.objects.get(user=user)
        assert address.email == "antiga@example.com"
        assert address.verified is True
        assert address.primary is True

    def test_a_back_filled_account_can_log_in(self):
        from core import migrations_helpers

        user = self._legacy_account()
        migrations_helpers.backfill(EmailAddress, type(user).objects.filter(pk=user.pk))

        client = Client()
        response = client.post(
            "/accounts/login/", {"login": "antiga@example.com", "password": SENHA}
        )
        assert response.status_code == 302
        assert response["Location"] == "/"
        assert "_auth_user_id" in client.session

    def test_without_the_back_fill_the_same_account_is_bounced(self):
        """The failure this migration exists to prevent, stated out loud."""
        self._legacy_account()

        client = Client()
        client.post("/accounts/login/", {"login": "antiga@example.com", "password": SENHA})
        assert "_auth_user_id" not in client.session

    def test_a_placeholder_address_is_not_marked_verified(self):
        """`<username>@sem-email.invalid` is a stand-in, not a proven address.

        Marking it verified would be a lie the system then relies on. The
        account cannot log in either way — the operator has to give it a real
        address first (docs/runbook.md) — so the honest record costs nothing.
        """
        from core import migrations_helpers

        user = self._legacy_account(email="ninguem@sem-email.invalid")
        migrations_helpers.backfill(EmailAddress, type(user).objects.filter(pk=user.pk))

        assert not EmailAddress.objects.filter(user=user).exists()
