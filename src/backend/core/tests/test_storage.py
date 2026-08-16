"""One place names a bucket, and with no bucket the app is still complete."""

from pathlib import Path

from django.core.files.storage import FileSystemStorage
from django.test import override_settings

from core.storage import JOB_EXPORT_PREFIX, JOB_UPLOAD_PREFIX, job_storage


@override_settings(GS_BUCKET_NAME="")
def test_no_bucket_falls_back_to_the_filesystem(tmp_path):
    with override_settings(JOB_STORAGE_ROOT=tmp_path):
        storage = job_storage()
    assert isinstance(storage, FileSystemStorage)
    assert Path(storage.location) == tmp_path


@override_settings(GS_BUCKET_NAME="")
def test_the_fallback_round_trips_bytes(tmp_path):
    from django.core.files.base import ContentFile

    with override_settings(JOB_STORAGE_ROOT=tmp_path):
        storage = job_storage()
        key = storage.save("imports/x.csv", ContentFile(b"data,valor\n"))
        with storage.open(key) as handle:
            assert handle.read() == b"data,valor\n"


@override_settings(GS_BUCKET_NAME="ledger-jobs-test")
def test_the_gcs_backend_is_constructed_privately():
    """The one branch that never runs locally, and the one where a mistake is
    a public bucket full of other people's bank statements.

    Asserted on the constructor rather than against a real bucket, because the
    value here is the *posture*: no per-object ACL (uniform bucket-level access
    rejects it), no credentials in a URL (downloads go through core.downloads
    and a household check), and no silent overwrite of an existing object.
    """
    storage = job_storage()

    assert storage.bucket_name == "ledger-jobs-test"
    assert storage.default_acl is None
    assert storage.querystring_auth is False
    assert storage.file_overwrite is False


def test_the_prefixes_are_distinct():
    """Uploads and exports share a bucket but never a namespace: the retention
    rule and the audit story differ, and a shared prefix makes both ambiguous."""
    assert JOB_UPLOAD_PREFIX != JOB_EXPORT_PREFIX
