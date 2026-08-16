"""Links that expire, without a cloud round trip.

The alternative is a GCS signed URL, and it was rejected for three reasons.
Signing one from Cloud Run needs either a service-account key file on disk --
a secret we would then own -- or an IAM SignBlob call per download. A raw
bucket link cannot check ``request.household``, so tenancy would rest on URL
secrecy alone. And it would only work in production, which means the DoD's
"export URLs expire, verified by test" could never be asserted locally.

Django's TimestampSigner gives expiry from the SECRET_KEY we already rotate,
in-process, identically on a laptop and on Cloud Run.
"""

from django.conf import settings
from django.core import signing


class DownloadLinkInvalid(Exception):
    """The token was tampered with, minted for another kind, or has expired."""


def sign_download(kind: str, object_id) -> str:
    """A URL-safe token standing for "this object, from now".

    ``kind`` travels *inside* the signed payload rather than as a salt beside
    it, so that a token minted for one kind cannot be replayed against another
    by editing the path.
    """
    return signing.dumps({"kind": kind, "id": str(object_id)}, salt="core.downloads")


def unsign_download(token: str, *, kind: str, max_age: int | None = None) -> str:
    """The object id behind ``token``, or ``DownloadLinkInvalid``.

    One exception type for every failure mode on purpose: the caller answers
    404 either way, and distinguishing "expired" from "forged" in a response
    tells an attacker which half of the token to keep working on.
    """
    if max_age is None:
        max_age = settings.EXPORT_URL_MAX_AGE_SECONDS
    try:
        payload = signing.loads(token, salt="core.downloads", max_age=max_age)
    except signing.BadSignature as exc:
        raise DownloadLinkInvalid(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        raise DownloadLinkInvalid("token is for a different kind of object")
    return payload["id"]
