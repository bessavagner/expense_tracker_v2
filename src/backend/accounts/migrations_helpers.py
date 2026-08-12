"""Helpers shared by data migrations and their tests.

Migrations receive *historical* model classes from ``apps.get_model``, so
these take the model classes as arguments rather than importing them.
"""


def _username_of(user):
    """The user's login name, on a live *or* historical model instance.

    ``apps.get_model`` rebuilds a model from migration state with its fields
    but none of ``AbstractBaseUser``'s methods, so ``get_username()`` exists
    only on the live class.
    """
    get_username = getattr(user, "get_username", None)
    return get_username() if callable(get_username) else user.username


def _household_name_for(user, max_length=120):
    """``Casa de <username>``, clipped to fit ``Household.name``.

    A username may be up to 150 characters, so the naive f-string overflows a
    ``varchar(120)`` and the insert dies with StringDataRightTruncation. The
    name is a label, not an identifier — clipping it is strictly better than
    failing a seed or a write.
    """
    prefix = "Casa de "
    return f"{prefix}{_username_of(user)}"[:max_length]


def seed_household_for_user(Household, Membership, user):  # noqa: N803
    """Give ``user`` their own household, as its owner. Idempotent."""
    existing = Membership.objects.filter(user=user).first()
    if existing is not None:
        return existing.household

    name_field = Household._meta.get_field("name")
    household = Household.objects.create(
        name=_household_name_for(user, name_field.max_length or 120)
    )
    Membership.objects.create(user=user, household=household, role="owner")
    return household
