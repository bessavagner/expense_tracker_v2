"""The CSV import wizard, driven by an ImportJob rather than by the session.

Every step is addressed by the job's id, and every step reads its state from
the job row plus the file in object storage. Nothing is kept in
``request.session``, which is what makes any step servable by any Cloud Run
instance -- E12's B4 fix.
"""

import csv

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from core.tasks import enqueue
from finances.models import Category, ImportJob, ImportStatus, PaymentMethod
from finances.services.import_rows import (
    detected_mapping,
    fields_for,
    headers_for,
    rows_for,
    unmatched_names,
)
from finances.services.import_storage import UploadTooLarge, store_upload
from finances.tasks import RUN_IMPORT


def get_job(request, job_id) -> ImportJob:
    """The job, or a 404 -- scoped to the request's household.

    ``for_request`` rather than a bare ``get``: global constraint 4, and it is
    what makes another household's job id a 404 instead of a data leak.
    """
    return get_object_or_404(ImportJob.objects.for_request(request), pk=job_id)


class ImportUploadView(LoginRequiredMixin, View):
    """Step 1: accept the CSV, put it in object storage, mint the job."""

    def get(self, request):
        return render(request, "importer/import_page.html", {"step": "upload"})

    def _error(self, request, message):
        return render(
            request,
            "importer/import_page.html",
            {"step": "upload", "error": message},
        )

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        import_type = request.POST.get("import_type", "regular")

        if not uploaded_file:
            return self._error(request, "Selecione um arquivo CSV.")

        household = request.household
        try:
            storage_key = store_upload(uploaded_file, household.id)
        except UploadTooLarge as exc:
            megabytes = exc.limit_bytes // (1024 * 1024)
            return self._error(
                request,
                f"Arquivo grande demais (máximo {megabytes} MB). "
                "Divida a planilha em partes e importe uma de cada vez.",
            )

        job = ImportJob.objects.create(
            household=household,
            created_by=request.user,
            import_type=import_type,
            storage_key=storage_key,
            original_filename=uploaded_file.name[:255],
            status=ImportStatus.UPLOADED,
        )

        # Read the header row now, so a file that is not UTF-8 is rejected here
        # -- on the step the user is looking at -- rather than two steps later
        # with the wizard already half committed.
        try:
            headers_for(job)
        except (UnicodeDecodeError, StopIteration):
            job.delete()
            return self._error(
                request,
                "Arquivo não está em formato UTF-8, ou está vazio. "
                "Re-exporte do Google Sheets como CSV.",
            )

        return redirect("finances:import_map", job_id=job.id)


class ImportMappingView(LoginRequiredMixin, View):
    """Step 2: review and confirm the column mapping."""

    def get(self, request, job_id):
        job = get_job(request, job_id)
        headers = headers_for(job)
        return render(
            request,
            "importer/import_page.html",
            {
                "step": "mapping",
                "job": job,
                "mapping": job.column_mapping or detected_mapping(job),
                "headers": headers,
                "headers_indexed": list(enumerate(headers)),
                "fields": fields_for(job.import_type),
                "import_type": job.import_type,
            },
        )

    def post(self, request, job_id):
        job = get_job(request, job_id)

        mapping = {}
        for field in fields_for(job.import_type):
            raw = request.POST.get(field)
            if raw is None:
                continue
            try:
                mapping[field] = int(raw)
            except ValueError:
                return redirect("finances:import_map", job_id=job.id)

        job.column_mapping = mapping
        job.status = ImportStatus.MAPPED
        # Counted once, here, so the progress bar has a denominator before the
        # runner starts rather than after its first save.
        job.total_rows = len(rows_for(job, mark_duplicates=False))
        job.save(update_fields=["column_mapping", "status", "total_rows", "updated_at"])

        return redirect("finances:import_preview", job_id=job.id)


class ImportPreviewView(LoginRequiredMixin, View):
    """Step 3: show what will happen, and let the user steer it."""

    def get(self, request, job_id):
        job = get_job(request, job_id)
        if not job.column_mapping:
            return redirect("finances:import_map", job_id=job.id)

        rows = rows_for(job)
        unmatched_categories, unmatched_pms = unmatched_names(job, rows)
        skip_lines = set(job.skip_lines)

        return render(
            request,
            "importer/import_page.html",
            {
                "step": "preview",
                "job": job,
                "rows": rows,
                "ok_count": sum(1 for row in rows if row["status"] == "ok"),
                "dup_count": sum(1 for row in rows if row["status"] == "duplicate"),
                "err_count": sum(1 for row in rows if row["status"] == "error"),
                "import_type": job.import_type,
                "unmatched_categories": unmatched_categories,
                "unmatched_pms": unmatched_pms,
                "categories": Category.objects.for_request(request).order_by("name"),
                "payment_methods": PaymentMethod.objects.for_request(request)
                .filter(is_active=True)
                .order_by("name"),
                "skip_lines": skip_lines,
            },
        )

    def post(self, request, job_id):
        """Record skips and conflict resolutions on the job.

        Keyed by CSV *line number* rather than by list index. An index only
        means anything relative to a particular parse; a line number is a fact
        about the file, and it is what a failure report has to name for the
        user to find the row in their spreadsheet.
        """
        job = get_job(request, job_id)

        skip_lines = []
        category_resolutions = {}
        pm_resolutions = {}
        for key, value in request.POST.items():
            if key.startswith("skip_") and value == "on":
                try:
                    skip_lines.append(int(key.removeprefix("skip_")))
                except ValueError:
                    continue
            elif key.startswith("cat_resolve_") and value:
                category_resolutions[key.removeprefix("cat_resolve_")] = value
            elif key.startswith("pm_resolve_") and value:
                pm_resolutions[key.removeprefix("pm_resolve_")] = value

        job.skip_lines = sorted(skip_lines)
        job.category_resolutions = category_resolutions
        job.pm_resolutions = pm_resolutions
        job.save(
            update_fields=[
                "skip_lines",
                "category_resolutions",
                "pm_resolutions",
                "updated_at",
            ]
        )
        return redirect("finances:import_preview", job_id=job.id)


class ImportExecuteView(LoginRequiredMixin, View):
    """Step 4: hand the job to a task and send the user to the status page.

    The old view did the whole import inside the request, wrapped in one
    ``@transaction.atomic`` -- which is where H5 lived, and which also meant a
    4000-row file held a request open for as long as it took. Enqueue is
    idempotent by content hash, so a double-tapped button produces one TaskRun
    and one import; the ``select_for_update`` dance the old view needed is now a
    property of ``core.tasks.enqueue`` plus ``import_runner._claim``.
    """

    def post(self, request, job_id):
        job = get_job(request, job_id)
        if not job.is_finished:
            enqueue(RUN_IMPORT, {"job_id": str(job.id)})
        return redirect("finances:import_status", job_id=job.id)


class ImportStatusView(LoginRequiredMixin, View):
    """Progress while it runs; counts when it is done; a reason when it is not.

    Serves the whole page normally and the progress fragment to HTMX, from one
    place, so the two cannot drift into disagreeing about the same job.
    """

    def get(self, request, job_id):
        job = get_job(request, job_id)
        context = {"step": "status", "job": job, "import_type": job.import_type}
        if request.headers.get("HX-Request"):
            return render(request, "importer/_progress.html", context)
        return render(request, "importer/import_page.html", context)


# Bounded so that a household with years of imports cannot turn the history
# page into a slow query. Old jobs stay in the database and in the admin; what
# is capped is the render, and the page says so.
HISTORY_LIMIT = 50


class ImportHistoryView(LoginRequiredMixin, View):
    """Past imports, and what each one did.

    The reason durable job state is worth having: before this, an import that
    finished was a page the user had to still be looking at.
    """

    def get(self, request):
        jobs = list(ImportJob.objects.for_request(request)[: HISTORY_LIMIT + 1])
        return render(
            request,
            "importer/import_history.html",
            {"jobs": jobs[:HISTORY_LIMIT], "truncated": len(jobs) > HISTORY_LIMIT},
        )


class ImportFailuresView(LoginRequiredMixin, View):
    """The failed rows, as a CSV the user can open next to their spreadsheet.

    Generated from the job rather than stored: the failures are already on the
    row, and writing a second artefact to the bucket would give the retention
    rule a second thing to reason about for no gain.

    UTF-8 BOM because the audience opens this in Excel, which reads a
    BOM-less UTF-8 file as Latin-1 and renders every accent as mojibake --
    on a report whose whole job is to be readable.

    No token on this one, unlike the export. It is reached from a page the user
    is already on, inside their own session, and it is scoped by
    ``for_request``; a token would add nothing.
    """

    def get(self, request, job_id):
        job = get_job(request, job_id)

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="erros-importacao-{job.id}.csv"'
        response.write("﻿")

        writer = csv.writer(response)
        writer.writerow(["linha", "motivo"])
        for failure in job.failures:
            writer.writerow([failure["line"], failure["reason"]])
        if job.failures_truncated:
            writer.writerow(
                ["", f"...e mais {job.failures_truncated} linha(s) com erro não listadas."]
            )
        return response
