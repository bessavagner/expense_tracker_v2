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
    assert len(cases) >= 2
    assert len({c.id for c in cases}) == len(cases), "case ids must be unique"


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


def test_arithmetic_error_catches_a_wrong_total():
    case = ReceiptCase(
        id="broken",
        image="x.jpg",
        image_source="tracked",
        media_type="image/jpeg",
        provenance="synthetic",
        categories=["Lanche"],
        payment_methods=[{"name": "Pix", "type": "pix"}],
        store="Loja",
        store_key="loja",
        date="2026-06-12",
        discount="0",
        amount_paid="10.00",
        items=[{"description": "a", "line_total": "9.00", "category": "Lanche"}],
    )
    assert "9.00" in arithmetic_error(case)


def test_unknown_case_id_raises():
    with pytest.raises(DatasetError):
        load_receipt_cases(["does-not-exist"])


def test_tracked_images_resolve_inside_the_repo():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    path = case.image_path()
    assert path is not None and path.exists()
    assert path.parts[-2:] == ("fixtures", "receipt_americanas.jpg")


def test_private_case_without_the_env_var_is_skipped_not_failed(settings, tmp_path):
    settings.EVAL_FIXTURES_DIR = str(tmp_path / "nowhere")
    cases, skipped = available_receipt_cases()
    assert all(c.image_path() is not None for c in cases)
    assert isinstance(skipped, list)


def test_read_image_returns_bytes_and_media_type():
    (case,) = load_receipt_cases(["americanas-2026-06-12"])
    data, media_type = case.read_image()
    assert isinstance(data, bytes) and len(data) > 1000
    assert media_type == "image/jpeg"


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
