"""The one documented command. Gated, and safe against any database."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command


@pytest.fixture
def llm_enabled(monkeypatch):
    monkeypatch.setenv("RUN_LLM_TESTS", "1")


@pytest.mark.django_db
def test_refuses_to_run_without_the_env_flag(monkeypatch):
    monkeypatch.delenv("RUN_LLM_TESTS", raising=False)
    with pytest.raises(CommandError, match="RUN_LLM_TESTS"):
        call_command("eval_models", "--models", "fake:model")


@pytest.mark.django_db
def test_requires_at_least_one_model(llm_enabled):
    with pytest.raises(CommandError, match="--models"):
        call_command("eval_models", "--models", "")


@pytest.mark.django_db
def test_an_unknown_case_id_fails_loudly(llm_enabled):
    with pytest.raises(CommandError, match="unknown case"):
        call_command("eval_models", "--models", "fake:m", "--cases", "nope")


@pytest.mark.django_db(transaction=True)
def test_a_dry_run_scores_the_stub_model_and_writes_the_report(llm_enabled, tmp_path):
    out = tmp_path / "report.md"
    buf = StringIO()
    call_command(
        "eval_models",
        "--models",
        "fake:model",
        "--suite",
        "both",
        "--stub",
        "--out",
        str(out),
        stdout=buf,
    )
    assert out.exists()
    text = out.read_text()
    assert "fake:model" in text and "Extraction" in text
    assert out.with_suffix(".json").exists()
    data = json.loads(out.with_suffix(".json").read_text())
    assert {r["suite"] for r in data["reports"]} == {"extraction", "behaviour"}


@pytest.mark.django_db(transaction=True)
def test_the_run_leaves_no_rows_behind(llm_enabled, tmp_path):
    """The throwaway household is rolled back on ANY database, always.

    Also the positive half of the `EXEMPT` entry in `test_metering.py`: the
    harness is excused from metering, so something has to prove it really does
    not meter. A `UsageRecord` from a run with no billable household would
    corrupt the operator cost report the pricing decisions are read from.
    """
    from accounts.models import Household
    from assistant.models import UsageRecord
    from finances.models import Entry

    before_h, before_e = Household.objects.count(), Entry.objects.count()
    before_u = UsageRecord.objects.count()
    call_command(
        "eval_models",
        "--models",
        "fake:model",
        "--suite",
        "both",
        "--stub",
        "--out",
        str(tmp_path / "r.md"),
        stdout=StringIO(),
    )
    assert Household.objects.count() == before_h
    assert Entry.objects.count() == before_e
    assert UsageRecord.objects.count() == before_u, "the harness must never meter"


@pytest.mark.django_db(transaction=True)
def test_missing_images_are_reported_as_skipped_not_as_failures(llm_enabled, tmp_path, settings):
    settings.EVAL_FIXTURES_DIR = str(tmp_path / "absent")
    buf = StringIO()
    call_command(
        "eval_models",
        "--models",
        "fake:model",
        "--suite",
        "extraction",
        "--stub",
        "--out",
        str(tmp_path / "r.md"),
        stdout=buf,
    )
    assert "skip" in buf.getvalue().lower()
