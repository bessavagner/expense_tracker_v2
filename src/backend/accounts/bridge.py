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

from accounts.models import household_owned_models
from accounts.resolution import household_for_user

_CACHE_ATTR = "_e04_bridge_household"


def household_for_writer(user):
    """The household a row written by ``user`` belongs to.

    Falls back to creating the user their own household — the same rule the
    seed migration applied — rather than returning None and letting the row
    land tenant-less. A user with no membership writing into their own new
    ledger is the fail-closed outcome; borrowing an existing household would
    be the leak.

    The rule itself lives in ``accounts.resolution.household_for_user``, which
    outlives this module: it takes the user's *oldest* membership, which
    diverges from ``accounts.middleware.resolve_active_household`` — that one
    honours the session-selected household. For a multi-household user an
    unconverted write would therefore land in the wrong household. Not
    reachable today: ``Membership.objects.create`` has a single, idempotent
    call site (``accounts/migrations_helpers.py``), so nobody holds two
    memberships. Phase 3 must convert writes to pass the *active* household
    explicitly rather than inherit this fallback.

    What this adds over the bare rule is memoisation on the user *instance*
    (``household_for_user`` does the ``select_related``). Without both, a bulk
    write path that saves N rows against one request user pays 2N queries — a
    lookup plus a lazy FK dereference each — which is the exact O(N) slope
    ``test_import_query_count`` exists to catch. The cache lives as long as the
    user object does, so a new request resolves afresh.
    """
    if user is None:
        return None
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    household = household_for_user(user)
    setattr(user, _CACHE_ATTR, household)
    return household


def fill_household(sender, instance, **kwargs):
    """Fill ``household`` — and ``created_by``, where the model has it.

    ``created_by_id is None`` is read as "not set yet", so a converted phase-3
    site cannot express "written by the system, not by a person". Harmless
    while the bridge exists; phase 4 deletes the module and the question with
    it.
    """
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
