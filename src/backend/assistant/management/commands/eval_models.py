"""Score one or more models against the golden dataset. E08 S08-4.

    RUN_LLM_TESTS=1 uv run python src/backend/manage.py eval_models \\
        --models "openai:gpt-5.6-terra" --suite both \\
        --out docs/superpowers/evidence/eval/baseline.md

This command SPENDS MONEY. It is gated on ``RUN_LLM_TESTS=1`` for the same reason
the real-LLM tests are, and it never runs in normal CI.

Everything it writes to the database is rolled back. The behavioural suite needs
a household with a real catalogue, and a harness that leaves debris in whatever
database it was pointed at is a harness nobody dares run twice.
"""

import os
from datetime import UTC, datetime

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from assistant.eval.behaviour import load_behaviour_cases
from assistant.eval.behaviour_runner import build_world, run_behaviour_case
from assistant.eval.dataset import DatasetError, available_receipt_cases
from assistant.eval.extraction_runner import run_extraction_suite
from assistant.eval.report import (
    build_behaviour_report,
    build_extraction_report,
    render_json,
    render_markdown,
)

STUB_READ = {
    "store": "Loja Stub",
    "date": "2026-06-12",
    "discount": "0",
    "amount_paid": "1.00",
    "confidence": 0.5,
    "items": [{"description": "item", "line_total": "1.00", "category": None}],
}


class _Rollback(Exception):
    """Raised to unwind the atomic block. Never propagates out of `handle`."""


class Command(BaseCommand):
    help = "Score models against the E08 golden dataset. Costs money; needs RUN_LLM_TESTS=1."

    def add_arguments(self, parser):
        parser.add_argument("--models", required=True, help="Comma-separated model strings.")
        parser.add_argument("--suite", choices=["extraction", "behaviour", "both"], default="both")
        parser.add_argument("--cases", default="", help="Comma-separated case ids.")
        parser.add_argument("--out", default="", help="Markdown path; JSON gets the same stem.")
        parser.add_argument(
            "--stub",
            action="store_true",
            help="Use TestModel instead of a provider. For testing the harness itself.",
        )

    def handle(self, *args, **opts):
        if os.environ.get("RUN_LLM_TESTS") != "1":
            raise CommandError(
                "This command calls real models and costs money. "
                "Re-run with RUN_LLM_TESTS=1 once you mean it."
            )
        models = [m.strip() for m in opts["models"].split(",") if m.strip()]
        if not models:
            raise CommandError("--models needs at least one model string.")

        ids = [c.strip() for c in opts["cases"].split(",") if c.strip()] or None
        suite = opts["suite"]
        reports, skipped = [], []

        try:
            with transaction.atomic():
                reports, skipped = self._run(models, suite, ids, stub=opts["stub"])
                raise _Rollback
        except _Rollback:
            pass
        except DatasetError as exc:
            raise CommandError(str(exc)) from exc
        except ValueError as exc:  # unknown behaviour case id
            raise CommandError(f"unknown case: {exc}") from exc

        generated_at = timezone.localtime(datetime.now(UTC)).isoformat(timespec="seconds")
        markdown = render_markdown(reports, generated_at=generated_at, skipped=skipped)
        self.stdout.write(markdown)

        out = (opts["out"] or "").strip()
        if out:
            from pathlib import Path

            md_path = Path(out)
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(markdown, encoding="utf-8")
            json_path = md_path.with_suffix(".json")
            json_path.write_text(
                render_json(reports, generated_at=generated_at, skipped=skipped),
                encoding="utf-8",
            )
            self.stdout.write(f"\nWrote {md_path} and {json_path}")

    # ── internals ───────────────────────────────────────────────────────────

    def _model_for(self, name, stub):
        if not stub:
            return name
        from pydantic_ai.models.test import TestModel

        return TestModel(custom_output_args=STUB_READ, call_tools=[])

    def _run(self, models, suite, ids, *, stub):
        reports, skipped = [], []
        if suite in ("extraction", "both"):
            cases, skipped = available_receipt_cases(ids)
            if skipped:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {len(skipped)} case(s) with no image on disk: "
                        + ", ".join(skipped)
                        + "\nSet EVAL_FIXTURES_DIR — see docs/eval-dataset.md."
                    )
                )
            for name in models:
                self.stdout.write(f"extraction · {name} · {len(cases)} case(s)…")
                runs = async_to_sync(run_extraction_suite)(cases, self._model_for(name, stub))
                reports.append(build_extraction_report(name, cases, runs))

        if suite in ("behaviour", "both"):
            cases = load_behaviour_cases(ids)
            for name in models:
                self.stdout.write(f"behaviour · {name} · {len(cases)} case(s)…")
                runs = []
                for case in cases:
                    household, user = self._throwaway(case.id, name)
                    build_world(case, household, user)
                    runs.append(
                        async_to_sync(run_behaviour_case)(
                            case, self._model_for(name, stub), household, user
                        )
                    )
                reports.append(build_behaviour_report(name, cases, runs))

        return reports, skipped

    def _throwaway(self, case_id, model_name):
        """A fresh household per case, so one case cannot see another's rows.

        Rolled back with everything else. The suffix keeps the unique email
        constraint happy when the same case runs against several models.
        """
        from accounts.models import Household, Membership, Role
        from core.models import CustomUser

        slug = f"{case_id}-{abs(hash(model_name)) % 10**6}"
        household = Household.objects.create(name=f"eval-{slug}")
        user = CustomUser.objects.create(
            username=f"eval-{slug}", email=f"eval-{slug}@example.invalid"
        )
        Membership.objects.create(user=user, household=household, role=Role.OWNER)
        return household, user
