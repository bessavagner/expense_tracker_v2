"""The back-fill that lets pre-E05 accounts keep logging in.

Lives outside `migrations/` rather than inside it for two reasons: Django
treats every module in that package as a migration, and a rule kept in a
migration body can only ever run once per database, on rows a test cannot
construct beforehand. A function can be pointed at any queryset. Same shape as
`accounts/migrations_helpers.py`.

See ``0004_seed_email_addresses`` and
``core/tests/test_legacy_accounts_can_still_log_in.py``.
"""

#: Addresses `0003_customuser_email_unique` invented for accounts that had
#: none. RFC 2606 reserves `.invalid`, so these can never resolve.
PLACEHOLDER_SUFFIX = "@sem-email.invalid"


def backfill(EmailAddress, users) -> int:
    """Give each user in ``users`` a verified primary ``EmailAddress``.

    Verified, not pending: these accounts have been signing in for months and
    the addresses are the ones the operator entered. Sending them all a
    confirmation email at deploy time would be both a surprise and — for the
    address the operator typed themselves — a question nobody needs answered.

    Placeholder addresses are skipped deliberately. `<username>@sem-email.
    invalid` is a stand-in for an address nobody knows, so marking it verified
    would record a proof that was never obtained. Such an account cannot log in
    until an operator gives it a real address, which is the correct failure and
    is documented in the runbook.

    Returns the number of rows created, so the migration can log it.
    """
    created = 0
    for user in users.iterator():
        email = (user.email or "").strip()
        if not email or email.endswith(PLACEHOLDER_SUFFIX):
            continue
        if EmailAddress.objects.filter(user_id=user.pk).exists():
            continue
        EmailAddress.objects.create(user_id=user.pk, email=email, verified=True, primary=True)
        created += 1
    return created
