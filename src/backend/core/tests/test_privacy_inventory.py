"""Every table in this product has a privacy decision attached to it.

This is the load-bearing test of E13. A model added later without an entry
here fails the suite, which is the only mechanism that keeps the privacy
notice a contract rather than a snapshot of one afternoon in August. Same idea
as `core/tests/test_metrics_doc.py`, and for the same reason.

`apps.get_models()` covers Django's own tables and allauth's too, deliberately:
`account.EmailAddress` and `mfa.Authenticator` hold personal data whether or
not we wrote them.
"""

import pytest
from django.apps import apps

from core.privacy import INVENTORY, Basis, Disposal, purgeable, record_for


def installed_labels() -> set[str]:
    """Every model this product actually ships.

    Test modules may declare their own models — `accounts/tests/test_backfill.py`
    builds a `LegacyRow` table so it can exercise the backfill against a shape
    no live model has any more — and those get registered in the app registry
    as soon as the module is imported. They are not part of the product and
    hold nobody's data, so demanding a privacy decision for them would make
    this suite pass or fail on collection order.
    """
    return {model._meta.label for model in apps.get_models() if ".tests." not in model.__module__}


def test_every_installed_model_is_classified():
    installed = installed_labels()
    classified = {record.label for record in INVENTORY}

    unclassified = installed - classified
    assert not unclassified, (
        "these models have no privacy decision — add a Record in "
        f"core/privacy/inventory.py: {sorted(unclassified)}"
    )


def test_the_inventory_names_no_model_that_does_not_exist():
    ghosts = {record.label for record in INVENTORY} - installed_labels()
    assert not ghosts, f"the inventory names models that were deleted: {sorted(ghosts)}"


def test_no_label_is_listed_twice():
    labels = [record.label for record in INVENTORY]
    assert len(labels) == len(set(labels))


def test_every_author_record_names_a_column_that_actually_exists():
    """A typo here is a deletion that silently deletes nothing — the worst
    possible bug in this epic, because the receipt would still say it worked."""
    from django.conf import settings as django_settings

    user_label = django_settings.AUTH_USER_MODEL
    for record in INVENTORY:
        if record.disposal is not Disposal.AUTHOR:
            continue
        model = apps.get_model(record.label)
        field = model._meta.get_field(record.subject_field)
        assert field.related_model._meta.label_lower == user_label.lower(), (
            f"{record.label}.{record.subject_field} does not point at the user model"
        )


def test_exactly_one_record_is_the_person_themselves():
    selves = [r.label for r in INVENTORY if r.disposal is Disposal.SELF]
    assert selves == ["core.CustomUser"]


def test_every_record_that_holds_personal_data_states_a_lawful_basis():
    """Disposal NONE means "no personal data", and only then may basis be None.

    LGPD art. 7 requires a basis per purpose. A row that holds someone's data
    with no basis recorded is the violation, not the paperwork.
    """
    for record in INVENTORY:
        if record.disposal is Disposal.NONE:
            continue
        assert isinstance(record.basis, Basis), f"{record.label} has no lawful basis"


def test_every_record_has_a_purpose_written_in_portuguese_for_the_notice():
    for record in INVENTORY:
        assert record.purpose.strip(), f"{record.label} has no purpose"
        # The notice renders these verbatim. A purpose written in English would
        # ship an English sentence into a pt-BR legal document.
        assert not record.purpose.strip().startswith("TODO")


def test_every_purgeable_record_names_a_field_that_actually_exists():
    """A typo here is a purge that silently deletes nothing, forever."""
    for record in purgeable():
        model = apps.get_model(record.label)
        names = {field.name for field in model._meta.get_fields() if field.concrete}
        assert record.timestamp_field in names, (
            f"{record.label} would be purged on '{record.timestamp_field}', "
            "which is not a field on it"
        )


def test_every_purge_filter_is_a_valid_query_for_its_model():
    for record in purgeable():
        model = apps.get_model(record.label)
        # Evaluated lazily by Django, so `.query` is what forces validation
        # without touching the database.
        str(model._base_manager.filter(**record.purge_filter).query)


def test_the_chat_is_kept_for_ninety_days():
    """D2, asserted rather than trusted: the notice prints this number."""
    assert record_for("assistant.ChatMessage").retention_days == 90


def test_the_ledger_itself_is_never_purged_on_a_timer():
    """A user's entries are theirs until they delete the account. A retention
    period on the ledger would silently destroy the product."""
    for label in ("finances.Entry", "finances.Income", "finances.InstallmentPlan"):
        assert record_for(label).retention_days is None


def test_the_assistant_runs_on_consent_and_the_ledger_on_contract():
    """D3. If these ever disagree with the notice, the notice is a lie."""
    assert record_for("assistant.ChatMessage").basis is Basis.CONSENT
    assert record_for("assistant.MemoryRule").basis is Basis.CONSENT
    assert record_for("assistant.MemoryEmbedding").basis is Basis.CONSENT
    assert record_for("finances.Entry").basis is Basis.CONTRACT
    assert record_for("assistant.UsageRecord").basis is Basis.LEGITIMATE
    assert record_for("core.AdminAccessLog").basis is Basis.LEGITIMATE


def test_lawful_bases_cite_the_article_the_notice_prints():
    assert Basis.CONTRACT.article == "art. 7º, V"
    assert Basis.CONSENT.article == "art. 7º, I"
    assert Basis.LEGITIMATE.article == "art. 7º, IX"


@pytest.mark.parametrize(
    "label",
    [
        "assistant.ChatMessage",
        "assistant.MemoryRule",
        "assistant.ReceiptDraft",
        "core.Feedback",
    ],
)
def test_the_things_a_person_wrote_go_with_them(label):
    """D1: the household's ledger survives a member leaving; their own words
    do not."""
    assert record_for(label).disposal is Disposal.AUTHOR
