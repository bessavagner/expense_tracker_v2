"""Requesting a household export, and collecting it.

The download goes through this view rather than through a raw bucket URL. See
``core.downloads`` for why -- the short version is that a bucket link cannot
check ``request.household``, and a complete financial history is not something
to protect with URL secrecy alone.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views import View

from core.downloads import DownloadLinkInvalid, unsign_download
from core.storage import job_storage
from core.tasks import enqueue
from finances.models import ExportJob, ExportStatus
from finances.tasks import BUILD_EXPORT

# Bounded for the same reason as the import history: the page must not become a
# slow query for a household that exports every week.
EXPORT_LIMIT = 20


class ExportPageView(LoginRequiredMixin, View):
    """Request an export, and see the ones already made."""

    def get(self, request):
        return render(
            request,
            "exporter/export_page.html",
            {"jobs": ExportJob.objects.for_request(request)[:EXPORT_LIMIT]},
        )


class ExportRequestView(LoginRequiredMixin, View):
    """Ask for an archive, unless one is already being built.

    ``enqueue`` is idempotent by content hash, but the payload carries a fresh
    ExportJob id every time, so it can never collide here — a double-tapped
    button would walk every table in the household twice and write two zips.
    The guard has to be on the household's in-flight job instead.
    """

    def post(self, request):
        existing = (
            ExportJob.objects.for_request(request)
            .filter(status__in=[ExportStatus.PENDING, ExportStatus.RUNNING])
            .first()
        )
        if existing is not None:
            return redirect("finances:export_page")

        job = ExportJob.objects.create(
            household=request.household,
            created_by=request.user,
            status=ExportStatus.PENDING,
        )
        enqueue(BUILD_EXPORT, {"job_id": str(job.id)})
        return redirect("finances:export_page")


class ExportDownloadView(LoginRequiredMixin, View):
    """Serve the archive behind a signed, expiring token.

    Three gates, and all three are needed. The signature says the link was
    minted by us; the max-age says it was minted recently; ``for_request`` says
    the person holding it is in the household whose money is inside. A 404 for
    every failure, so a probe cannot tell "expired" from "not yours".
    """

    def get(self, request, token):
        try:
            job_id = unsign_download(token, kind="export")
        except DownloadLinkInvalid as exc:
            raise Http404("link inválido") from exc

        job = ExportJob.objects.for_request(request).filter(pk=job_id).first()
        if job is None or job.status != ExportStatus.DONE or not job.storage_key:
            raise Http404("exportação indisponível")

        storage = job_storage()
        if not storage.exists(job.storage_key):
            # The 7-day lifecycle rule deleted it. The row outlives the file on
            # purpose, so this is a knowable state rather than a mystery 404.
            raise Http404("exportação expirada")

        return FileResponse(
            storage.open(job.storage_key),
            as_attachment=True,
            filename=f"ledger-{job.created_at:%Y-%m-%d}.zip",
            content_type="application/zip",
        )
