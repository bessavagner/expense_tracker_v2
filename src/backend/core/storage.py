"""Where a job's bytes live.

One function, so that the bucket name, the ACL posture and the local fallback
are decided in exactly one place. A second construction site is how a bucket
ends up public because someone copied the defaults.

Deliberately uncached. Constructing either backend is cheap, and an
``lru_cache`` here would make ``override_settings`` in a test silently
ineffective -- the worst kind of test, one that passes without exercising
anything.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage

# Uploads and exports share the bucket and never the prefix. The lifecycle
# rules differ (E12 decisions 2 and 4), and a rule cannot target a prefix that
# also holds the other kind.
JOB_UPLOAD_PREFIX = "imports"
JOB_EXPORT_PREFIX = "exports"


def job_storage() -> Storage:
    """The storage backing import uploads and export archives.

    ``GS_BUCKET_NAME`` unset is the entire local story: no credentials, no
    emulator, no network. That is the answer to the spec's "local development
    works without GCP credentials", and it is a default rather than a flag so
    that forgetting to set something fails safe.
    """
    if settings.GS_BUCKET_NAME:
        from storages.backends.gcloud import GoogleCloudStorage

        return GoogleCloudStorage(
            bucket_name=settings.GS_BUCKET_NAME,
            # Uniform bucket-level access is on (see docs/runbook.md), so a
            # per-object ACL is not merely unnecessary -- GCS rejects it.
            default_acl=None,
            # No credentials in a URL. Downloads go through
            # core.downloads + a household check, never a raw bucket link.
            querystring_auth=False,
            # Two jobs must never collide; the caller's key already carries a
            # UUID, and this makes an accidental collision a new name rather
            # than a silent overwrite of somebody's financial data.
            file_overwrite=False,
        )
    return FileSystemStorage(location=settings.JOB_STORAGE_ROOT)
