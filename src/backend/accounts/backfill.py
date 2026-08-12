"""E04 phase 2's back-fill, shared by two data migrations and their test.

Migrations receive *historical* model classes from ``apps.get_model``, so
everything here takes model classes as arguments rather than importing them.

The work is a bulk UPDATE per (user, model), not a row loop: production holds
thousands of entries and one user, so one statement per model is the whole
job. Rows that already have a household are never touched — re-running must
not move a row between households.
"""


def backfill_household_columns(Membership, models_by_label, apps):  # noqa: N803
    """Fill ``household`` (and ``created_by`` where present) from ``user``.

    Returns ``{label: rows_filled}``. A user with no owner membership is
    skipped and their rows stay NULL — failing closed, so phase 4's NOT NULL
    surfaces the gap instead of the back-fill inventing a tenant.
    """
    owners = Membership.objects.filter(role="owner").values_list("user_id", "household_id")

    counts = {}
    for label, model in models_by_label.items():
        has_created_by = any(f.name == "created_by" for f in model._meta.get_fields())
        filled = 0
        for user_id, household_id in owners:
            updates = {"household_id": household_id}
            if has_created_by:
                updates["created_by_id"] = user_id
            filled += model.objects.filter(user_id=user_id, household__isnull=True).update(
                **updates
            )
        counts[label] = filled
    return counts
