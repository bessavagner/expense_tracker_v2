"""Nothing personal survives a deletion, and nothing shared is destroyed by one.

Two halves, and they pull against each other on purpose:

  * the parameterized sweep proves no table was forgotten — it walks the
    inventory rather than a list somebody typed here, so a model added next
    year is covered without anyone remembering to cover it;
  * the household cases prove the sweep did not take the other member's
    ledger with it (plan decision D1).
"""

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from model_bakery import baker

from accounts.models import Household, Membership, Role
from core.privacy import INVENTORY, Disposal, delete_account, model_for

pytestmark = pytest.mark.django_db


AUTHORED = [record for record in INVENTORY if record.disposal is Disposal.AUTHOR]


@pytest.fixture
def two_person_household(household, user):
    """`user` owns it; `socia` is a plain member. The case D1 is about."""
    socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
    Membership.objects.create(user=socia, household=household, role=Role.MEMBER)
    return household, user, socia


class TestNothingPersonalSurvives:
    @pytest.mark.parametrize("record", AUTHORED, ids=lambda r: r.label)
    def test_the_rows_this_person_wrote_are_gone(self, record, two_person_household):
        """Parameterized over the inventory, not over a hand-written list. That
        is the whole reason the inventory exists."""
        household, owner, socia = two_person_household
        model = model_for(record)
        row = baker.make(model, household=household, **{record.subject_field: socia})

        delete_account(socia)

        assert not model.objects.filter(pk=row.pk).exists(), (
            f"{record.label} row written by the deleted person survived"
        )

    @pytest.mark.parametrize("record", AUTHORED, ids=lambda r: r.label)
    def test_the_other_members_rows_are_untouched(self, record, two_person_household):
        household, owner, socia = two_person_household
        model = model_for(record)
        theirs = baker.make(model, household=household, **{record.subject_field: owner})

        delete_account(socia)

        assert model.objects.filter(pk=theirs.pk).exists(), (
            f"deleting one person took another person's {record.label} with it"
        )

    def test_the_account_itself_is_gone(self, two_person_household):
        from core.models import CustomUser

        _, _, socia = two_person_household
        delete_account(socia)
        assert not CustomUser.objects.filter(email="socia@example.com").exists()

    def test_the_email_address_and_second_factor_go_with_the_account(self, two_person_household):
        from allauth.account.models import EmailAddress
        from allauth.mfa.models import Authenticator

        _, _, socia = two_person_household
        EmailAddress.objects.create(user=socia, email=socia.email, verified=True, primary=True)
        Authenticator.objects.create(user=socia, type=Authenticator.Type.TOTP, data={})

        delete_account(socia)

        assert not EmailAddress.objects.filter(email="socia@example.com").exists()
        assert not Authenticator.objects.exists()

    def test_the_consent_and_acceptance_records_go_too(self, two_person_household):
        """CASCADE by design (Task 2): a statement about a person has no meaning
        once the person is gone."""
        from core.models import Consent, PolicyAcceptance, PolicyDocument
        from core.privacy import set_ai_consent

        _, _, socia = two_person_household
        set_ai_consent(socia, granted=True)
        PolicyAcceptance.objects.create(
            user=socia, document=PolicyDocument.TERMS, version="2026-08-17"
        )

        delete_account(socia)

        assert not Consent.objects.exists()
        assert not PolicyAcceptance.objects.exists()

    def test_their_failed_login_attempts_are_gone(self, two_person_household):
        """`LoginAttempt` has no foreign key — it is keyed by the address
        string — so nothing deletes it unless this service does."""
        from core.models import LoginAttempt

        _, _, socia = two_person_household
        LoginAttempt.objects.create(username="socia@example.com", ip="203.0.113.7")
        LoginAttempt.objects.create(username="alguem@example.com", ip="203.0.113.7")

        delete_account(socia)

        assert not LoginAttempt.objects.filter(username="socia@example.com").exists()
        assert LoginAttempt.objects.filter(username="alguem@example.com").exists()

    def test_their_sessions_are_gone_so_an_open_tab_is_signed_out(self, two_person_household):
        """A session outliving its user is not a data leak — `get_user` returns
        AnonymousUser once the row is gone — but leaving it there means the
        person is 'signed in' to nothing, which reads as the deletion having
        failed."""
        _, _, socia = two_person_household
        client = Client()
        client.force_login(socia)
        assert Session.objects.count() == 1

        delete_account(socia)

        assert Session.objects.count() == 0

    def test_a_memory_rules_embedding_goes_with_the_rule(self, two_person_household):
        """`MemoryEmbedding` is household-owned and has no author column, so the
        sweep above cannot reach it. Its id is derived from the rule's, which is
        what makes this reachable at all."""
        from assistant.models import MemoryEmbedding, MemoryRule, MemorySource
        from assistant.tasks import embedding_id_for

        household, _, socia = two_person_household
        rule = MemoryRule.objects.create(
            household=household,
            created_by=socia,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source=MemorySource.USER_CORRECTION,
        )
        MemoryEmbedding.objects.create(
            id=embedding_id_for(rule.pk),
            household=household,
            text="cosmos → category=Alimentação",
            embedding=[0.0] * 1536,
        )

        delete_account(socia)

        assert not MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).exists()

    def test_what_they_wrote_in_a_household_they_left_goes_too(self, household, user):
        """Found by E13's security review, and it was real.

        `_delete_authored_rows` used to be called once per *current* membership
        and filtered on that household. A person removed from a household left
        their authored rows behind — and deleting their account then never
        looked there, so their chat messages survived, readable, with only
        `created_by` nulled by the FK. "Their own words go with them" has to
        mean wherever they wrote them.
        """
        from assistant.models import ChatMessage, MemoryRule, MemorySource, MessageRole

        socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
        Membership.objects.create(user=socia, household=household, role=Role.MEMBER)

        left_behind = Household.objects.create(name="Casa antiga")
        Membership.objects.create(user=user, household=left_behind, role=Role.OWNER)
        expired = Membership.objects.create(user=socia, household=left_behind, role=Role.MEMBER)

        message = baker.make(
            ChatMessage,
            household=left_behind,
            created_by=socia,
            role=MessageRole.USER,
            content="segredo da socia",
        )
        rule = MemoryRule.objects.create(
            household=left_behind,
            created_by=socia,
            trigger="x",
            field="category",
            value="Outros",
            source=MemorySource.INFERRED,
        )
        expired.delete()  # an owner removed her; her rows stayed behind

        delete_account(socia)

        assert not ChatMessage._base_manager.filter(pk=message.pk).exists()
        assert not MemoryRule._base_manager.filter(pk=rule.pk).exists()

    def test_the_address_itself_survives_nowhere_in_the_database(self, two_person_household):
        """A sweep rather than a list: every table, every row, one string.

        The per-model assertions above each name a table somebody thought of.
        This one names none, so a column that starts holding an address next
        year is covered by a test written this year.
        """
        from allauth.account.models import EmailAddress

        from assistant.models import ChatMessage, MessageRole
        from core.models import Feedback, LoginAttempt, ProductEvent
        from finances.models import Entry

        household, _, socia = two_person_household
        EmailAddress.objects.create(user=socia, email=socia.email, verified=True, primary=True)
        baker.make(ChatMessage, household=household, created_by=socia, role=MessageRole.USER)
        baker.make(Entry, household=household, created_by=socia)
        Feedback.objects.create(household=household, user=socia, message="oi")
        ProductEvent.objects.create(household=household, user=socia, name="signup")
        LoginAttempt.objects.create(username="socia@example.com", ip="203.0.113.7")

        delete_account(socia)

        from django.apps import apps

        survivors = [
            model._meta.label
            for model in apps.get_models()
            if ".tests." not in model.__module__
            for row in model._base_manager.all()[:500]
            if "socia@example.com" in str(row.__dict__)
        ]
        assert not survivors, f"the address survived in: {sorted(set(survivors))}"


class TestWhatTheHouseholdKeeps:
    def test_the_ledger_survives_for_whoever_is_left(self, two_person_household):
        from finances.models import Entry

        household, owner, socia = two_person_household
        entry = baker.make(Entry, household=household, created_by=socia)

        delete_account(socia)

        entry.refresh_from_db()
        assert entry.created_by is None
        assert entry.household_id == household.id

    def test_the_household_itself_survives(self, two_person_household):
        household, owner, socia = two_person_household
        delete_account(socia)
        assert Household.objects.filter(pk=household.pk).exists()

    def test_the_remaining_member_can_still_get_in(self, two_person_household):
        household, owner, socia = two_person_household
        delete_account(socia)
        assert Membership.objects.filter(user=owner, household=household).exists()

    def test_the_usage_history_survives_with_the_person_removed_from_it(self, two_person_household):
        """Task 5's change, asserted from the deletion side."""
        from assistant.models import InteractionKind, UsageInteraction

        household, owner, socia = two_person_household
        interaction = baker.make(
            UsageInteraction, household=household, user=socia, kind=InteractionKind.TEXT
        )

        delete_account(socia)

        interaction.refresh_from_db()
        assert interaction.user is None


class TestTheLastOwnerLeaving:
    def test_the_longest_standing_member_is_promoted(self, two_person_household):
        """D1, and `accounts/models.py:109` says this is what E13 would do."""
        household, owner, socia = two_person_household

        receipt = delete_account(owner)

        promoted = Membership.objects.get(user=socia, household=household)
        assert promoted.role == Role.OWNER
        assert receipt.owner_promoted_to == "socia@example.com"

    def test_promotion_picks_the_oldest_membership_when_there_are_several(self, household, user):
        """Deterministic, because `Membership.Meta.ordering` is `created_at` and
        `membership_household_age_idx` exists for exactly this."""
        first = baker.make("core.CustomUser", username="a", email="primeira@example.com")
        second = baker.make("core.CustomUser", username="b", email="segunda@example.com")
        Membership.objects.create(user=first, household=household, role=Role.MEMBER)
        Membership.objects.create(user=second, household=household, role=Role.MEMBER)

        receipt = delete_account(user)

        assert receipt.owner_promoted_to == "primeira@example.com"
        assert Membership.objects.get(user=first).role == Role.OWNER
        assert Membership.objects.get(user=second).role == Role.MEMBER

    def test_nobody_is_promoted_when_an_owner_remains(self, household, user):
        co_owner = baker.make("core.CustomUser", username="c", email="co@example.com")
        Membership.objects.create(user=co_owner, household=household, role=Role.OWNER)

        receipt = delete_account(user)

        assert receipt.owner_promoted_to is None
        assert Membership.objects.get(user=co_owner).role == Role.OWNER


class TestTheLastMemberLeaving:
    def test_the_household_and_everything_in_it_is_deleted(self, household, user):
        from assistant.models import ChatMessage, MessageRole
        from finances.models import Entry

        entry = baker.make(Entry, household=household, created_by=user)
        baker.make(ChatMessage, household=household, created_by=user, role=MessageRole.USER)
        household_id = household.id

        receipt = delete_account(user)

        assert not Household.objects.filter(pk=household_id).exists()
        assert not Entry.objects.filter(pk=entry.pk).exists()
        assert not ChatMessage.objects.exists()
        assert receipt.households_deleted == [str(household_id)]
        assert receipt.households_kept == []

    def test_the_uploaded_and_exported_files_go_too(self, household, user, tmp_path):
        """Deleting the database is not deleting the data.

        An uploaded CSV is the household's whole transaction history and an
        export archive is the same thing zipped. Without this they sit in the
        bucket for up to seven more days after the person was told everything
        was gone. The session-scoped `isolated_job_storage` fixture points
        storage at a temp dir, so this exercises the real code path.
        """
        from django.core.files.base import ContentFile

        from core.storage import job_storage
        from finances.models import ExportJob, ExportStatus, ImportJob

        storage = job_storage()
        upload = storage.save("imports/x.csv", ContentFile(b"data,valor\n01/01/2026,10,00\n"))
        archive = storage.save("exports/x.zip", ContentFile(b"PK\x03\x04"))
        baker.make(ImportJob, household=household, created_by=user, storage_key=upload)
        baker.make(
            ExportJob,
            household=household,
            created_by=user,
            status=ExportStatus.DONE,
            storage_key=archive,
        )

        delete_account(user)

        assert not storage.exists(upload)
        assert not storage.exists(archive)

    def test_a_missing_blob_does_not_fail_the_deletion(self, household, user):
        """The transaction has already committed by then. Raising here would
        report a failure for a deletion that actually happened."""
        from finances.models import ImportJob

        baker.make(ImportJob, household=household, created_by=user, storage_key="imports/gone.csv")

        receipt = delete_account(user)

        assert receipt.email == "vagner@example.com"

    def test_a_shared_households_files_are_kept(self, two_person_household):
        """The household survives, so its import history and its files do too."""
        from django.core.files.base import ContentFile

        from core.storage import job_storage
        from finances.models import ImportJob

        household, owner, socia = two_person_household
        storage = job_storage()
        key = storage.save("imports/shared.csv", ContentFile(b"x"))
        baker.make(ImportJob, household=household, created_by=socia, storage_key=key)

        delete_account(socia)

        assert storage.exists(key)

    def test_a_neighbouring_households_data_is_untouched(
        self, household, user, other_household, other_user
    ):
        """The whole of E04, restated as a deletion property."""
        from finances.models import Entry

        theirs = baker.make(Entry, household=other_household, created_by=other_user)

        delete_account(user)

        assert Entry.objects.filter(pk=theirs.pk).exists()
        assert Household.objects.filter(pk=other_household.pk).exists()


class TestAPersonInSeveralHouseholds:
    def test_each_household_is_decided_on_its_own(self, household, user):
        """One they share and one they are alone in: the first survives, the
        second does not, in a single call."""
        alone = Household.objects.create(name="Só minha")
        Membership.objects.create(user=user, household=alone, role=Role.OWNER)
        socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
        Membership.objects.create(user=socia, household=household, role=Role.MEMBER)

        receipt = delete_account(user)

        assert Household.objects.filter(pk=household.pk).exists()
        assert not Household.objects.filter(pk=alone.pk).exists()
        assert receipt.households_kept == [str(household.id)]
        assert receipt.households_deleted == [str(alone.id)]


class TestTheReceipt:
    def test_it_names_the_address_that_was_deleted(self, household, user):
        receipt = delete_account(user)
        assert receipt.email == "vagner@example.com"

    def test_it_counts_what_it_removed(self, two_person_household):
        from assistant.models import ChatMessage, MessageRole

        household, owner, socia = two_person_household
        baker.make(
            ChatMessage,
            household=household,
            created_by=socia,
            role=MessageRole.USER,
            _quantity=3,
        )

        receipt = delete_account(socia)

        assert receipt.rows_deleted["assistant.ChatMessage"] == 3

    def test_it_is_all_or_nothing(self, two_person_household, monkeypatch):
        """One transaction. A deletion that half-happened would leave a person
        who cannot sign in and whose data is still there — the worst of both."""
        from core.models import CustomUser
        from core.privacy import deletion

        household, owner, socia = two_person_household

        def explode(*args, **kwargs):
            raise RuntimeError("the database went away")

        # `_delete_sessions_for` runs INSIDE the atomic block, which is what
        # makes this a rollback test. `_delete_stored_files` deliberately runs
        # outside it and deliberately never raises — see its docstring.
        monkeypatch.setattr(deletion, "_delete_sessions_for", explode)

        with pytest.raises(RuntimeError):
            delete_account(socia)

        assert CustomUser.objects.filter(email="socia@example.com").exists()
        assert Membership.objects.filter(user=socia).exists()
