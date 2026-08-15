"""Extraction scoring — deterministic, no model, no database.

Binary assertions cannot compare two models that are both imperfect, which is
why this exists. The one non-graduated dimension is the money invariant: a read
whose items do not reconcile with the amount paid scores ZERO overall no matter
how good the rest looks.
"""

from decimal import Decimal

from assistant.agents.extraction import ReceiptExtraction, ReceiptItem
from assistant.eval.dataset import ReceiptCase
from assistant.eval.scoring import (
    aggregate_extraction,
    normalize_description,
    score_extraction,
)


def make_case(**overrides) -> ReceiptCase:
    data = {
        "id": "t",
        "images": ["x.jpg"],
        "image_source": "tracked",
        "media_type": "image/jpeg",
        "provenance": "synthetic",
        "categories": ["Lanche", "Roupa"],
        "payment_methods": [{"name": "Pix", "type": "pix"}],
        "store": "americanas sa - 1063",
        "store_key": "americanas",
        "date": "2026-06-12",
        "discount": "0",
        "amount_paid": "20.00",
        "items": [
            {
                "description": "BACONZITOS B&G ELMA CHIPS M",
                "line_total": "10.00",
                "category": "Lanche",
            },
            {
                "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
                "line_total": "10.00",
                "category": "Roupa",
            },
        ],
    }
    data.update(overrides)
    return ReceiptCase(**data)


def make_extraction(items, **overrides) -> ReceiptExtraction:
    data = {
        "store": "Lojas Americanas",
        "date": "2026-06-12",
        "items": [ReceiptItem(**i) for i in items],
        "discount": Decimal("0"),
        "amount_paid": Decimal("20.00"),
        "confidence": 0.9,
    }
    data.update(overrides)
    return ReceiptExtraction(**data)


PERFECT_ITEMS = [
    {
        "description": "BACONZITOS B&G ELMA CHIPS M",
        "line_total": "10.00",
        "category": "Lanche",
    },
    {
        "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
        "line_total": "10.00",
        "category": "Roupa",
    },
]


def test_a_perfect_read_scores_one():
    score = score_extraction(make_case(), make_extraction(PERFECT_ITEMS))
    assert score.money_ok is True
    assert score.item_recall == 1.0
    assert score.item_precision == 1.0
    assert score.amount_accuracy == 1.0
    assert score.category_accuracy == 1.0
    assert score.store_ok is True
    assert score.date_ok is True
    assert score.overall == 1.0


def test_money_invariant_failure_zeroes_the_whole_score():
    """The Mercado Livre bug: a multi-unit line counted twice."""
    doubled = [
        {
            "description": "BACONZITOS B&G ELMA CHIPS M",
            "line_total": "20.00",
            "category": "Lanche",
        },
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "10.00",
            "category": "Roupa",
        },
    ]
    score = score_extraction(make_case(), make_extraction(doubled))
    assert score.money_ok is False
    assert score.overall == 0.0
    # ...even though every other dimension is near-perfect:
    assert score.item_recall == 1.0
    assert score.category_accuracy == 1.0


def test_a_missing_amount_paid_fails_the_money_invariant():
    score = score_extraction(make_case(), make_extraction(PERFECT_ITEMS, amount_paid=None))
    assert score.money_ok is False
    assert score.overall == 0.0


def test_discount_is_subtracted_before_reconciling():
    case = make_case(amount_paid="18.00", discount="2.00")
    ext = make_extraction(PERFECT_ITEMS, discount=Decimal("2.00"), amount_paid=Decimal("18.00"))
    assert score_extraction(case, ext).money_ok is True


def test_when_no_total_is_printed_returning_none_is_the_right_answer():
    """A marketplace order screen shows per-line prices and no total.

    `EXTRACTION_PROMPT` forbids inventing one, so a model that answers `None`
    and whose lines add up to what was really charged has read it correctly.
    Scoring that as a money failure would mark the honest model down.
    """
    case = make_case(amount_paid=None)
    ext = make_extraction(PERFECT_ITEMS, amount_paid=None)
    assert score_extraction(case, ext).money_ok is True


def test_inventing_a_total_that_was_never_printed_fails_the_money_invariant():
    case = make_case(amount_paid=None)
    ext = make_extraction(PERFECT_ITEMS, amount_paid=Decimal("20.00"))
    score = score_extraction(case, ext)
    assert score.money_ok is False
    assert score.overall == 0.0


def test_with_no_printed_total_the_lines_must_still_add_up():
    """The Mercado Livre double-count: a 2-unit line multiplied a second time."""
    case = make_case(amount_paid=None)
    doubled = [
        {
            "description": "BACONZITOS B&G ELMA CHIPS M",
            "line_total": "20.00",
            "category": "Lanche",
        },
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "10.00",
            "category": "Roupa",
        },
    ]
    assert score_extraction(case, make_extraction(doubled, amount_paid=None)).money_ok is False


def test_a_case_with_no_printed_date_expects_none_back():
    case = make_case(date=None)
    assert score_extraction(case, make_extraction(PERFECT_ITEMS, date=None)).date_ok is True
    assert (
        score_extraction(case, make_extraction(PERFECT_ITEMS, date="2026-06-12")).date_ok is False
    )


def test_a_missed_item_lowers_recall_and_is_named():
    partial = [
        PERFECT_ITEMS[0],
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "10.00",
            "category": "Roupa",
        },
    ]
    del partial[1]
    score = score_extraction(make_case(), make_extraction(partial, amount_paid=Decimal("20.00")))
    assert score.item_recall == 0.5
    assert score.item_precision == 1.0
    assert "SOUTIEN TOP B+ TAF21 BRANCO GG" in score.missed


def test_a_hallucinated_item_lowers_precision_and_is_named():
    extra = PERFECT_ITEMS + [
        {"description": "PRODUTO QUE NAO EXISTE", "line_total": "0.00", "category": "Lanche"}
    ]
    score = score_extraction(make_case(), make_extraction(extra))
    assert score.item_recall == 1.0
    assert round(score.item_precision, 4) == round(2 / 3, 4)
    assert "PRODUTO QUE NAO EXISTE" in score.spurious


def test_a_wrong_category_is_scored_separately_from_recall():
    miscategorised = [
        {
            "description": "BACONZITOS B&G ELMA CHIPS M",
            "line_total": "10.00",
            "category": "Roupa",
        },
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "10.00",
            "category": "Roupa",
        },
    ]
    score = score_extraction(make_case(), make_extraction(miscategorised))
    assert score.item_recall == 1.0
    assert score.category_accuracy == 0.5
    assert 0.0 < score.overall < 1.0


def test_a_null_category_counts_as_wrong():
    nulled = [
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "10.00", "category": None},
        {
            "description": "SOUTIEN TOP B+ TAF21 BRANCO GG",
            "line_total": "10.00",
            "category": "Roupa",
        },
    ]
    assert score_extraction(make_case(), make_extraction(nulled)).category_accuracy == 0.5


def test_store_is_matched_by_key_not_by_equality():
    assert score_extraction(make_case(), make_extraction(PERFECT_ITEMS)).store_ok is True
    wrong = make_extraction(PERFECT_ITEMS, store="Supermercado Pague Menos")
    assert score_extraction(make_case(), wrong).store_ok is False


def test_a_wrong_date_is_scored_but_not_fatal():
    ext = make_extraction(PERFECT_ITEMS, date="2026-06-13")
    score = score_extraction(make_case(), ext)
    assert score.date_ok is False
    assert score.overall > 0.9


def test_scoring_is_deterministic_for_the_same_input():
    case, ext = make_case(), make_extraction(PERFECT_ITEMS)
    assert score_extraction(case, ext) == score_extraction(case, ext)


def test_normalize_description_is_case_and_punctuation_insensitive():
    assert normalize_description("LAYS  CLASSICA, B&G") == normalize_description(
        "lays classica b g"
    )


def test_aggregate_averages_each_dimension_and_counts_money_failures():
    good = score_extraction(make_case(), make_extraction(PERFECT_ITEMS))
    bad = score_extraction(make_case(), make_extraction(PERFECT_ITEMS, amount_paid=None))
    agg = aggregate_extraction([good, bad])
    assert agg.n == 2
    assert agg.money_ok_rate == 0.5
    assert agg.item_recall == 1.0
    assert agg.overall == 0.5


def test_aggregate_of_nothing_is_zero_not_a_crash():
    agg = aggregate_extraction([])
    assert agg.n == 0 and agg.overall == 0.0
