"""The metrics document must explain every event the funnel emits.

Not decoration: a funnel that grows an event nobody documented is how "activation
rate" quietly starts meaning something else. This test is the only thing that
makes the document a contract rather than a snapshot.
"""

from pathlib import Path

from core.events import EventName

# core/tests/test_metrics_doc.py → core/tests → core → backend → src → repo root
DOC = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "product-metrics.md"


def test_the_document_exists():
    assert DOC.is_file(), f"expected the metrics definitions at {DOC}"


def test_every_event_name_is_documented():
    text = DOC.read_text(encoding="utf-8")
    missing = [event.value for event in EventName if event.value not in text]
    assert not missing, f"undocumented events: {missing}"


def test_the_four_metrics_are_all_defined():
    text = DOC.read_text(encoding="utf-8").lower()
    for metric in ("exposição", "ativação", "time-to-value", "retenção"):
        assert metric in text, f"the document never defines {metric}"
