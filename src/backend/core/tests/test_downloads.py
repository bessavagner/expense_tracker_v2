"""A link that carries its own authority, and stops carrying it on time."""

import pytest
import time_machine
from django.test import override_settings

from core.downloads import DownloadLinkInvalid, sign_download, unsign_download

_ID = "6f8a1c02-3c2e-5f7a-9b4d-2a1f0e5c7d31"


def test_a_fresh_token_round_trips():
    token = sign_download("export", _ID)
    assert unsign_download(token, kind="export") == _ID


def test_a_tampered_token_is_refused():
    token = sign_download("export", _ID)
    with pytest.raises(DownloadLinkInvalid):
        unsign_download(token[:-1] + ("a" if token[-1] != "a" else "b"), kind="export")


def test_a_token_for_another_kind_is_refused():
    """Kind is inside the signed payload, not beside it. A token minted for an
    import file must not open an export archive, whatever the URL says."""
    token = sign_download("import", _ID)
    with pytest.raises(DownloadLinkInvalid):
        unsign_download(token, kind="export")


def test_garbage_is_refused_rather_than_raising_something_else():
    with pytest.raises(DownloadLinkInvalid):
        unsign_download("not-a-token", kind="export")


@override_settings(EXPORT_URL_MAX_AGE_SECONDS=3600)
def test_a_token_inside_its_window_is_accepted():
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        token = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 12:59:00+00:00", tick=False):
        assert unsign_download(token, kind="export") == _ID


@override_settings(EXPORT_URL_MAX_AGE_SECONDS=3600)
def test_a_token_past_its_window_is_refused():
    """The DoD's 'export URLs expire, verified by test'. Frozen clock on both
    sides -- global constraint 10 -- so this cannot rot into a flake."""
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        token = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 13:00:01+00:00", tick=False):
        with pytest.raises(DownloadLinkInvalid):
            unsign_download(token, kind="export")


def test_two_tokens_for_the_same_object_are_not_guessable_from_each_other():
    """Timestamped, so the same id does not always mint the same string, and
    neither string reveals the id without the signing key."""
    with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
        first = sign_download("export", _ID)
    with time_machine.travel("2026-08-16 12:00:05+00:00", tick=False):
        second = sign_download("export", _ID)
    assert first != second
    assert _ID not in first
