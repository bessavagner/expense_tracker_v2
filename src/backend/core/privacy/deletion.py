"""Deleting a person without deleting the household they were part of.

Plan decision D1, which is E13's answer to the epic's open question 4 and to
E04's open question 3. In one sentence: *their* data goes, the *household's*
data stays for whoever is still using it, and a household nobody is left in
goes with them.

Almost nothing here is a `.delete()` call, because E04 already did most of the
work: `AuthoredHouseholdModel.created_by` is SET_NULL, so a person vanishing
from the ledger is already the database's default behaviour. What is left is
the part a foreign key cannot express — which rows are *theirs* rather than the
household's, who owns the household once the owner leaves, and the two tables
(`LoginAttempt`, `Session`) that name a person by string rather than by key.

GLOBAL CONSTRAINT 4, AND THE ONE EXCEPTION THIS EPIC TAKES TO IT.
`INDEX.md` §7.4 forbids `filter(user=...)` on a domain model: reads go through
the household-scoped manager, always. This module is the exception, and it has
to be — "delete the rows this person wrote" is a per-person query by
definition, and no household-scoped manager can express it. The exception is
this file and nothing else. It uses `_base_manager` rather than `objects` so
the scoped manager is bypassed deliberately and visibly, instead of being
quietly subverted.
"""

import logging
from dataclasses import dataclass, field

from django.contrib.sessions.models import Session
from django.db import transaction

from accounts.models import Membership, Role
from core.privacy.inventory import INVENTORY, Disposal, model_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletionReceipt:
    """What was actually removed. Shown to the person, and logged.

    A receipt rather than a bare success flag because deletion is irreversible
    and silent success is indistinguishable from silent failure. "3 mensagens,
    1 casa apagada" is a claim someone can check.
    """

    email: str
    households_deleted: list[str] = field(default_factory=list)
    households_kept: list[str] = field(default_factory=list)
    rows_deleted: dict[str, int] = field(default_factory=dict)
    owner_promoted_to: str | None = None


def delete_account(user) -> DeletionReceipt:
    """Remove ``user`` and everything that is theirs. Irreversible.

    One transaction: a deletion that half-happened leaves a person who cannot
    sign in and whose data is still there, which is the worst of both outcomes
    and the hardest to notice.

    The caller is responsible for offering an export first — that gate is a
    product decision and lives in the view (S13-1), not here, so that an
    operator fulfilling a request by hand can call this directly.
    """
    receipt_email = user.email
    households_deleted: list[str] = []
    households_kept: list[str] = []
    rows_deleted: dict[str, int] = {}
    promoted_to: str | None = None
    doomed_files: list[str] = []

    with transaction.atomic():
        memberships = list(Membership.objects.filter(user=user).select_related("household"))

        for membership in memberships:
            household = membership.household
            others = Membership.objects.filter(household=household).exclude(user=user)

            if not others.exists():
                # Nobody left. The household's CASCADE takes every
                # household-owned row with it — eighteen tables, discovered by
                # `accounts.household_owned_models()` rather than listed.
                #
                # Collected BEFORE the delete, because the rows carrying the
                # storage keys are about to cascade away with it.
                doomed_files.extend(_storage_keys_for(household))
                households_deleted.append(str(household.id))
                household.delete()
                continue

            households_kept.append(str(household.id))
            if membership.role == Role.OWNER and not others.filter(role=Role.OWNER).exists():
                # D1: the longest-standing member takes over. Deterministic
                # because `Membership.Meta.ordering` is `created_at`, and
                # `membership_household_age_idx` exists for this query.
                heir = others.select_related("user").order_by("created_at").first()
                heir.role = Role.OWNER
                heir.save(update_fields=["role"])
                promoted_to = heir.user.email
                logger.info(
                    "Household %s: %s left as sole owner; promoted %s.",
                    household.id,
                    receipt_email,
                    promoted_to,
                )

        # Once, and NOT inside the loop above: see the function's docstring.
        _delete_authored_rows(user, rows_deleted)

        _delete_login_attempts_for(user, rows_deleted)
        _delete_sessions_for(user, rows_deleted)

        # Last. CASCADE takes Membership, EmailAddress, EmailConfirmation,
        # Authenticator, LogEntry, PolicyAcceptance and Consent; SET_NULL
        # empties every `created_by` and every `user` column we chose to keep.
        user.delete()

    # After the commit, deliberately. Object storage is not transactional: if
    # the blobs went first and the transaction then rolled back, the rows would
    # survive pointing at files that no longer exist. This way the worst case is
    # a file the bucket's own 7-day lifecycle rule collects anyway.
    _delete_stored_files(doomed_files, rows_deleted)

    logger.info(
        "Account deleted: %s, %d household(s) removed, %d kept.",
        receipt_email,
        len(households_deleted),
        len(households_kept),
    )
    return DeletionReceipt(
        email=receipt_email,
        households_deleted=households_deleted,
        households_kept=households_kept,
        rows_deleted=rows_deleted,
        owner_promoted_to=promoted_to,
    )


def _delete_authored_rows(user, counts: dict[str, int]) -> None:
    """The rows this person wrote — wherever they wrote them.

    Driven by the inventory. A model added later with ``Disposal.AUTHOR`` is
    covered here without anyone editing this function, which is the point of
    the registry existing at all.

    DELIBERATELY NOT SCOPED TO A HOUSEHOLD, and called once rather than once per
    membership. An earlier version filtered on the households the person belongs
    to *now*, which quietly spared everything they had written in a household
    they were later removed from: an owner removes a member, and that member's
    chat messages sit there, readable, surviving their account deletion. E13's
    security review found it. "Their own words go with them" (plan decision D1)
    is a statement about the person, not about their current memberships, and
    `created_by` is the only handle that expresses it.

    Rows in a household this deletion just removed entirely are already gone by
    the time this runs — the household's CASCADE took them — so they simply do
    not match.
    """
    for record in INVENTORY:
        if record.disposal is not Disposal.AUTHOR:
            continue
        model = model_for(record)
        rows = model._base_manager.filter(**{record.subject_field: user})
        if record.label == "assistant.MemoryRule":
            _delete_embeddings_for(rows)
        deleted, _ = rows.delete()
        if deleted:
            counts[record.label] = counts.get(record.label, 0) + deleted


def _delete_embeddings_for(rules) -> None:
    """A memory rule's vector, which no foreign key points at.

    `MemoryEmbedding` is household-owned and carries no author column; its
    primary key is `uuid5(namespace, rule_id)` (`assistant/tasks.py:24-32`),
    which is the only handle there is. Missing this would leave a vector of
    someone's shopping habits in the database after they had been told it was
    gone.
    """
    from assistant.models import MemoryEmbedding
    from assistant.tasks import embedding_id_for

    ids = [embedding_id_for(pk) for pk in rules.values_list("pk", flat=True)]
    if ids:
        MemoryEmbedding._base_manager.filter(id__in=ids).delete()


def _storage_keys_for(household) -> list[str]:
    """Every blob this household owns, before its rows cascade away.

    Deleting the database is not deleting the data. The uploaded CSV is a
    household's whole transaction history and the export archive is the same
    thing zipped; both sit in object storage under keys that only these rows
    know. Without this, "your data is deleted" would be true of Postgres and
    false of the bucket for up to seven more days.
    """
    from finances.models import ExportJob, ImportJob

    keys = list(
        ImportJob._base_manager.filter(household=household)
        .exclude(storage_key="")
        .values_list("storage_key", flat=True)
    )
    keys += list(
        ExportJob._base_manager.filter(household=household)
        .exclude(storage_key="")
        .values_list("storage_key", flat=True)
    )
    return keys


def _delete_stored_files(keys: list[str], counts: dict[str, int]) -> None:
    """Remove the blobs, tolerating every way that can fail.

    Never raises. By the time this runs the database transaction has committed,
    so an exception here would report a failure for a deletion that already
    happened — and the bucket's 7-day lifecycle rule (E12 decision 2) collects
    anything missed. Belt and braces, in that order.
    """
    if not keys:
        return

    from core.storage import job_storage

    storage = job_storage()
    removed = 0
    for key in keys:
        try:
            storage.delete(key)
            removed += 1
        except Exception:
            logger.warning("Could not delete %s during account deletion.", key, exc_info=True)
    if removed:
        counts["storage.blobs"] = removed


def _delete_login_attempts_for(user, counts: dict[str, int]) -> None:
    """Keyed by the address string, not by a foreign key — so nothing else
    would ever remove these."""
    from core.models import LoginAttempt

    deleted, _ = LoginAttempt.objects.filter(
        username__in={user.email, user.get_username()}
    ).delete()
    if deleted:
        counts["core.LoginAttempt"] = deleted


def _delete_sessions_for(user, counts: dict[str, int]) -> None:
    """Every open session belonging to this person.

    Sessions hold `_auth_user_id` inside encoded data with no column to filter
    on, so they have to be decoded. That is affordable exactly here: this runs
    once per deletion, never per request, and the table is small because
    expired rows are swept daily by the purge job.

    Leaving them would not leak anything — `get_user` returns AnonymousUser
    once the row behind the id is gone — but it would leave the person's other
    tab believing it is signed in, which reads as the deletion not having
    worked.
    """
    target = str(user.pk)
    doomed = [
        session.session_key
        for session in Session.objects.iterator()
        if session.get_decoded().get("_auth_user_id") == target
    ]
    if doomed:
        deleted, _ = Session.objects.filter(session_key__in=doomed).delete()
        counts["sessions.Session"] = deleted
