"""TEMPORARY — delete in E04 phase 4, with accounts/tests/test_bridge.py.

Phases 2 and 3 run with both `user` and `household` on every domain model,
and with the app only partly converted: an unconverted view still writes rows
that set `user` alone, as do the ~1000 tests written before tenancy existed.

This receiver fills the gap so that no row is ever written tenant-less, which
is what lets phase 3 convert one surface per commit instead of all at once.

It fills only what is missing — a converted write site's explicit household
always wins. It cannot help `bulk_create` or `bulk_update`, which bypass
signals entirely; those call sites set household themselves.

Phase 4 makes `household` NOT NULL and drops `user`. At that point every write
path sets household explicitly, this module has nothing left to do, and
keeping it would only hide the next mistake.
"""

from django.db.models.signals import pre_save

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership, household_owned_models

_CACHE_ATTR = "_e04_bridge_household"


def household_for_writer(user):
    """The household a row written by ``user`` belongs to.

    Falls back to creating the user their own household — the same rule the
    seed migration applied — rather than returning None and letting the row
    land tenant-less. A user with no membership writing into their own new
    ledger is the fail-closed outcome; borrowing an existing household would
    be the leak.

    Memoised on the user *instance*, and ``select_related`` on the way in.
    Without both, a bulk write path that saves N rows against one request user
    pays 2N queries — a lookup plus a lazy FK dereference each — which is the
    exact O(N) slope ``test_import_query_count`` exists to catch. The cache
    lives as long as the user object does, so a new request resolves afresh.
    """
    if user is None:
        return None
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    membership = Membership.objects.select_related("household").filter(user=user).first()
    household = (
        membership.household
        if membership is not None
        else seed_household_for_user(Household, Membership, user)
    )
    setattr(user, _CACHE_ATTR, household)
    return household


def fill_household(sender, instance, **kwargs):
    if instance.household_id is not None:
        return
    # user_id, not user: on a non-nullable FK with nothing set, touching the
    # descriptor raises RelatedObjectDoesNotExist instead of returning None,
    # which would turn a would-be IntegrityError into a different exception.
    if instance.user_id is None:
        return
    instance.household = household_for_writer(instance.user)
    if hasattr(instance, "created_by_id") and instance.created_by_id is None:
        instance.created_by_id = instance.user_id


def connect(**kwargs):
    """Wire the receiver to every household-owned model. Idempotent via
    dispatch_uid, so a double ``ready()`` in tests is harmless."""
    for model in household_owned_models():
        pre_save.connect(
            fill_household,
            sender=model,
            dispatch_uid=f"e04_bridge_{model._meta.label_lower}",
        )
