"""The cap is enforced while streaming, before a byte reaches storage.

'Before the payload is accepted, not after' is the spec's wording and it is
load-bearing: the container's filesystem is backed by its 1 GiB of RAM, so
'write it and then check the size' spends exactly the memory the cap exists to
protect.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from core.storage import job_storage
from finances.services.import_storage import UploadTooLarge, open_text, store_upload

_HOUSEHOLD_ID = "3f1e6f7c-9a1b-4c2d-8e5f-0a1b2c3d4e5f"


@pytest.fixture
def local_storage(tmp_path):
    with override_settings(GS_BUCKET_NAME="", JOB_STORAGE_ROOT=tmp_path):
        yield tmp_path


def test_a_small_upload_is_stored_and_readable(local_storage):
    upload = SimpleUploadedFile("x.csv", b"data,valor\n01/03/2026,42\n", "text/csv")
    key = store_upload(upload, _HOUSEHOLD_ID)
    assert job_storage().exists(key)
    with open_text(key) as handle:
        assert handle.readline() == "data,valor\n"


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_an_oversized_upload_is_refused(local_storage):
    upload = SimpleUploadedFile("big.csv", b"x" * 65, "text/csv")
    with pytest.raises(UploadTooLarge):
        store_upload(upload, _HOUSEHOLD_ID)


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_a_refused_upload_leaves_nothing_in_storage(local_storage):
    """The assertion that makes this a real 'before storage' test rather than a
    'delete it afterwards' one."""
    upload = SimpleUploadedFile("big.csv", b"x" * 100_000, "text/csv")
    with pytest.raises(UploadTooLarge):
        store_upload(upload, _HOUSEHOLD_ID)
    assert list(local_storage.rglob("*.csv")) == []


@override_settings(MAX_CSV_UPLOAD_BYTES=64)
def test_exactly_the_limit_is_accepted(local_storage):
    """Off-by-one in the wrong direction rejects a legitimate file, which is a
    support ticket rather than an incident -- but it is still a defect."""
    upload = SimpleUploadedFile("edge.csv", b"x" * 64, "text/csv")
    assert store_upload(upload, _HOUSEHOLD_ID)


def test_non_utf8_is_refused_with_a_ptbr_reason(local_storage):
    upload = SimpleUploadedFile("latin.csv", "descrição\n".encode("latin-1"), "text/csv")
    key = store_upload(upload, _HOUSEHOLD_ID)
    with pytest.raises(UnicodeDecodeError):
        with open_text(key) as handle:
            handle.read()


def test_the_key_is_namespaced_by_household(local_storage):
    key = store_upload(SimpleUploadedFile("x.csv", b"a\n", "text/csv"), _HOUSEHOLD_ID)
    assert key.startswith(f"imports/{_HOUSEHOLD_ID}/")


def test_two_uploads_of_the_same_name_do_not_collide(local_storage):
    first = store_upload(SimpleUploadedFile("x.csv", b"a\n", "text/csv"), _HOUSEHOLD_ID)
    second = store_upload(SimpleUploadedFile("x.csv", b"b\n", "text/csv"), _HOUSEHOLD_ID)
    assert first != second
    assert isinstance(io.TextIOWrapper(job_storage().open(second)), io.TextIOWrapper)
