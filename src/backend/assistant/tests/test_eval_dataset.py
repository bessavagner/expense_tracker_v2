"""The golden dataset loads, and its arithmetic is self-consistent.

A wrong gabarito silently teaches the harness to prefer a worse model, so the
arithmetic check runs over EVERY committed case in the normal suite — it is the
only automatic defence against a transcription slip.
"""

from decimal import Decimal

import pytest

from assistant.eval.dataset import (
    DatasetError,
    ReceiptCase,
    arithmetic_error,
    available_receipt_cases,
    load_receipt_cases,
)


def test_every_committed_case_loads():
    cases = load_receipt_cases()
    assert len(cases) >= 7
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"


def test_the_set_covers_every_hard_case_it_claims_to():
    """The coverage the epic asks for, asserted rather than described.

    `already-registered` is deliberately absent: it is a BEHAVIOURAL case
    (`refuses-to-double-register-a-known-receipt`), not a receipt to read.
    """
    covered = {h for c in load_receipt_cases() for h in c.hard_cases}
    for required in (
        "thermal-print",
        "rotated",
        "low-contrast",
        "multi-category",
        "discount",
        "multi-unit-line",
        "long-receipt",
        "weighed-item",
    ):
        assert required in covered, required


def test_every_hard_case_tag_is_documented():
    """`docs/eval-dataset.md` claims this test asserts its table. Now it does.

    The older assertion only checked that a fixed list of tags was PRESENT, so a
    new tag could be invented in a case file and never explained anywhere. A tag
    nobody documented is a coverage claim nobody can check.
    """
    import pathlib

    doc = (
        pathlib.Path(__file__).resolve().parents[3].parent
        / "docs"
        / "eval-dataset.md"
    ).read_text(encoding="utf-8")
    used = {h for c in load_receipt_cases() for h in c.hard_cases}
    undocumented = sorted(tag for tag in used if f"`{tag}`" not in doc)
    assert not undocumented, (
        "hard-case tags used by a case but missing from the table in "
        f"docs/eval-dataset.md: {undocumented}"
    )


def test_every_committed_case_is_arithmetically_consistent():
    for case in load_receipt_cases():
        assert arithmetic_error(case) is None, f"{case.id}: {arithmetic_error(case)}"


def test_americanas_case_matches_the_known_gabarito():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    assert case.store_key == "americanas"
    assert case.date == "2026-06-12"
    assert case.amount_paid == Decimal("42.16")
    assert case.items_total == Decimal("46.15")
    assert len(case.items) == 5
    assert [i.category for i in case.items] == [
        "Roupa",
        "Lanche",
        "Lanche",
        "Lanche",
        "Lanche",
    ]


def test_hipermacional_case_matches_the_known_gabarito():
    (case,) = load_receipt_cases(["hipermacional-2026-06-15"])
    assert case.amount_paid == Decimal("376.70")
    assert case.items_total == Decimal("376.70")
    assert len(case.items) == 28
    assert len({i.category for i in case.items}) == 6


def make_case(**overrides) -> ReceiptCase:
    data = {
        "id": "broken",
        "images": ["x.jpg"],
        "image_source": "tracked",
        "media_type": "image/jpeg",
        "provenance": "synthetic",
        "categories": ["Lanche"],
        "payment_methods": [{"name": "Pix", "type": "pix"}],
        "store": "Loja",
        "store_key": "loja",
        "date": "2026-06-12",
        "discount": "0",
        "amount_paid": "10.00",
        "items": [{"description": "a", "line_total": "9.00", "category": "Lanche"}],
    }
    data.update(overrides)
    return ReceiptCase(**data)


def test_arithmetic_error_catches_a_wrong_total():
    assert "9.00" in arithmetic_error(make_case())


def test_a_case_with_no_printed_total_skips_reconciliation():
    """A marketplace order screen prints no total, and that is not a defect.

    `EXTRACTION_PROMPT` tells the model to leave `amount_paid` null when the
    document does not show one, so `None` is the expected answer rather than
    missing ground truth. There is simply nothing to reconcile against.
    """
    assert arithmetic_error(make_case(amount_paid=None)) is None


def test_a_discount_without_a_total_is_still_an_error():
    """Half an arithmetic claim is worse than none — it cannot be checked."""
    problem = arithmetic_error(make_case(amount_paid=None, discount="2.00"))
    assert problem is not None and "discount" in problem


def test_a_case_with_no_items_is_an_error():
    assert "no items" in arithmetic_error(make_case(items=[]))


def test_unknown_case_id_raises():
    with pytest.raises(DatasetError):
        load_receipt_cases(["does-not-exist"])


def test_tracked_images_resolve_inside_the_repo():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    paths = case.image_paths()
    assert paths is not None and len(paths) == 1 and paths[0].exists()
    assert paths[0].parts[-2:] == ("fixtures", "receipt_americanas.jpg")


def test_private_case_without_the_env_var_is_skipped_not_failed(settings, tmp_path):
    settings.EVAL_FIXTURES_DIR = str(tmp_path / "nowhere")
    cases, skipped = available_receipt_cases()
    assert all(c.image_paths() is not None for c in cases)
    assert skipped, "the private cases must be reported as skipped, not silently dropped"


def test_read_images_returns_bytes_and_media_type():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    ((data, media_type),) = case.read_images()
    assert isinstance(data, bytes) and len(data) > 1000
    assert media_type == "image/jpeg"


def test_a_two_page_receipt_carries_both_photos():
    """The 62-line Mateus receipt does not fit one frame.

    Production's `extract_receipt` already accepts a list of images and reads
    them as ONE document; a case that could hold only one photo could not
    represent the longest receipt in the set.
    """
    (case,) = load_receipt_cases(["mateus-2026-06-22"])
    assert len(case.images) == 2
    assert len(case.items) == 62
    assert case.amount_paid == Decimal("745.85")


def test_a_multi_page_case_is_all_or_nothing(settings, tmp_path):
    """Page 1 alone would score a perfect model as having missed half the items."""
    only_page_one = tmp_path / "partial"
    only_page_one.mkdir()
    (case,) = load_receipt_cases(["mateus-2026-06-22"])
    (only_page_one / case.images[0]).write_bytes(b"x")
    settings.EVAL_FIXTURES_DIR = str(only_page_one)
    assert case.image_paths() is None


def test_dataset_ground_truth_matches_the_regression_test_constants():
    """The two sources of gabarito must never drift apart.

    `test_image_extraction_regression.py` keeps its own literals because it is
    the record of two real production failures. This test is the ratchet that
    stops the dataset and the regression test from disagreeing about what the
    photo says.
    """
    from assistant.tests.test_image_extraction_regression import (
        AMERICANAS_ITEMS,
        HIPERMACIONAL_ITEMS,
    )

    pairs = [
        ("americanas-2026-06-12", AMERICANAS_ITEMS),
        ("hipermacional-2026-06-15", HIPERMACIONAL_ITEMS),
    ]
    for case_id, flat in pairs:
        (case,) = load_receipt_cases([case_id])
        assert len(case.items) == len(flat), case_id
        for item, (desc, value, cat) in zip(case.items, flat, strict=True):
            assert item.description == desc, case_id
            assert item.line_total == Decimal(value), case_id
            # The dataset writes category names without accents so a JSON file
            # stays diffable in any terminal; the regression test uses the
            # product's real names.
            assert item.category.lower()[:5] == cat.lower()[:5], (case_id, desc)
