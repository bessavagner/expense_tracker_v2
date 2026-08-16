"""Getting an uploaded CSV into object storage, and back out as text.

The cap is counted here rather than trusted from a header. ``Content-Length``
is what ``core.middleware`` and ``core.asgi_body_limit`` check, and both are
right to -- but a chunked request declares no length, and multipart overhead
means a legal declared length can still wrap an illegal file. Counting the
chunks as they arrive is the check that cannot be lied to.
"""

import io
import uuid

from django.conf import settings
from django.core.files.base import ContentFile

from core.storage import JOB_UPLOAD_PREFIX, job_storage


class UploadTooLarge(ValueError):
    """The upload exceeded ``MAX_CSV_UPLOAD_BYTES`` and was never stored."""

    def __init__(self, limit_bytes: int):
        self.limit_bytes = limit_bytes
        super().__init__(f"Upload exceeds {limit_bytes} bytes.")


def store_upload(uploaded_file, household_id) -> str:
    """Stream ``uploaded_file`` into object storage. Returns its key.

    Buffered in memory on purpose: the ceiling is 2 MB, which is smaller than
    the multipart body Django has already accepted, so this adds nothing to the
    peak. Streaming straight to the backend would be worse, not better -- it
    would mean a rejected upload had already written partial bytes to a bucket
    the caller then has to remember to clean up.
    """
    limit = settings.MAX_CSV_UPLOAD_BYTES
    buffer = io.BytesIO()
    total = 0
    for chunk in uploaded_file.chunks():
        total += len(chunk)
        if total > limit:
            # Nothing has been written to storage at this point, and nothing
            # will be. That is the property test_a_refused_upload_leaves_
            # nothing_in_storage asserts.
            raise UploadTooLarge(limit)
        buffer.write(chunk)

    key = f"{JOB_UPLOAD_PREFIX}/{household_id}/{uuid.uuid4()}.csv"
    return job_storage().save(key, ContentFile(buffer.getvalue()))


def open_text(key: str) -> io.TextIOWrapper:
    """The stored CSV as a UTF-8 text stream.

    ``newline=""`` because ``csv.reader`` does its own newline handling; without
    it a quoted field containing a line break is split into two rows, which in
    this product means one entry's description becoming a second, malformed
    entry.
    """
    return io.TextIOWrapper(job_storage().open(key), encoding="utf-8", newline="")
