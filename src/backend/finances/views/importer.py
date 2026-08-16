"""The CSV import wizard, driven by an ImportJob rather than by the session.

Every step is addressed by the job's id, and every step reads its state from
the job row plus the file in object storage. Nothing is kept in
``request.session``, which is what makes any step servable by any Cloud Run
instance -- E12's B4 fix.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from finances.models import Category, ImportJob, ImportStatus, PaymentMethod
from finances.services.import_rows import (
    detected_mapping,
    fields_for,
    headers_for,
    rows_for,
    unmatched_names,
)
from finances.services.import_storage import UploadTooLarge, store_upload


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
    """Step 4: execute the import. Task 5 moves this onto the task queue."""

    def post(self, request, job_id):
        job = get_job(request, job_id)
        from finances.services.import_runner import run_import

        run_import(job)
        return redirect("finances:import_preview", job_id=job.id)
