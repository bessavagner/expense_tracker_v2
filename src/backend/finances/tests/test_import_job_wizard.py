"""The B4 fix, asserted the only way that means anything.

The old wizard wrote the uploaded file's local path into the session and
reopened it in a later request. On one warm instance that works. On Cloud Run
with more than one instance the second request lands somewhere the file does
not exist -- and the failure is invisible until traffic grows, which is exactly
when it is most expensive.

Two independent Client objects for the same user are two independent session
cookies, which is as close as the test suite gets to two processes. If any step
still depends on session state, the second client cannot complete the wizard.
"""

import io

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Entry, ImportJob, ImportStatus

_CSV = (
    b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
    b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
    b'05/03/2026,"R$ 14,00",Disk Bebida,\xc3\x81lcool,Pix\n'
)

_MAPPING = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


@pytest.fixture
def seeded(household, settings, tmp_path):
    settings.GS_BUCKET_NAME = ""
    settings.JOB_STORAGE_ROOT = tmp_path
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


@pytest.fixture
def second_client(user):
    """A second session for the same person -- the stand-in for a second
    instance. Must not share a cookie with `logged_client`."""
    client = Client()
    client.force_login(user)
    return client


def _upload(client):
    handle = io.BytesIO(_CSV)
    handle.name = "historico.csv"
    return client.post("/import/", data={"file": handle, "import_type": "regular"})


@pytest.mark.django_db
class TestTheWizardNeedsNoSession:
    def test_each_step_can_be_served_by_a_different_session(
        self, logged_client, second_client, seeded
    ):
        response = _upload(logged_client)
        job = ImportJob.objects.for_household(seeded).get()

        # Every subsequent step goes through the OTHER client.
        assert response.status_code == 302
        assert response.url == f"/import/{job.id}/mapear/"

        assert second_client.get(f"/import/{job.id}/mapear/").status_code == 200
        assert second_client.post(f"/import/{job.id}/mapear/", data=_MAPPING).status_code == 302
        assert second_client.get(f"/import/{job.id}/preview/").status_code == 200
        assert second_client.post(f"/import/{job.id}/executar/").status_code == 302

        assert Entry.objects.for_household(seeded).count() == 2

    def test_the_session_is_never_written(self, logged_client, seeded):
        """The narrower assertion, and the one that catches a partial fix: a
        wizard that still writes rows into the session has not stopped being
        the bug, it has only stopped reading them back."""
        _upload(logged_client)
        job = ImportJob.objects.for_household(seeded).get()
        logged_client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        logged_client.get(f"/import/{job.id}/preview/")

        assert "import_data" not in logged_client.session
        assert not any("import" in key for key in logged_client.session.keys())

    def test_a_job_survives_being_reloaded_from_scratch(self, logged_client, seeded):
        """No in-process cache: the whole state is columns and a stored file."""
        _upload(logged_client)
        job_id = ImportJob.objects.for_household(seeded).get().pk
        logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING)

        job = ImportJob.objects.get(pk=job_id)
        assert job.status == ImportStatus.MAPPED
        assert job.column_mapping == {
            "date": 0,
            "amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
        }
        assert job.storage_key
        assert job.total_rows == 2


@pytest.mark.django_db
class TestTenancy:
    def test_another_households_job_is_not_reachable(
        self, logged_client, seeded, other_household, other_user
    ):
        other_job = baker.make(ImportJob, household=other_household, created_by=other_user)
        for suffix in ("mapear/", "preview/"):
            assert logged_client.get(f"/import/{other_job.id}/{suffix}").status_code == 404
        assert logged_client.post(f"/import/{other_job.id}/executar/").status_code == 404

    def test_a_job_id_that_does_not_exist_is_a_404(self, logged_client, seeded):
        missing = "00000000-0000-4000-8000-000000000000"
        assert logged_client.get(f"/import/{missing}/preview/").status_code == 404


@pytest.mark.django_db
class TestUploadRejection:
    def test_an_oversized_upload_is_refused_in_ptbr_and_creates_no_job(
        self, logged_client, seeded, settings
    ):
        """A request that declares its length never reaches the view.

        ``core.middleware`` applies MAX_CSV_UPLOAD_BYTES to everything under
        ``/import/``, so this is a 413 with its own pt-BR body rather than the
        view's error page. Asserted at the layer that actually answers, because
        a test that expected the view here would be asserting a code path no
        declared-length request can reach.
        """
        settings.MAX_CSV_UPLOAD_BYTES = 32
        handle = io.BytesIO(b"x" * 5000)
        handle.name = "grande.csv"
        response = logged_client.post("/import/", data={"file": handle, "import_type": "regular"})
        assert response.status_code == 413
        assert "grande demais" in response.content.decode()
        assert not ImportJob.objects.exists()

    def test_the_views_own_cap_answers_in_ptbr_and_creates_no_job(self, rf, user, seeded, settings):
        """The other half: a chunked request declares no length, so the
        middleware has nothing to check and the streaming cap in
        ``store_upload`` is the only thing standing between a 2 MB ceiling and
        the instance's memory. Driven through the view directly, which is the
        only way to reach that branch -- the test client always sets
        Content-Length.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile

        from finances.views.importer import ImportUploadView

        settings.MAX_CSV_UPLOAD_BYTES = 32
        request = rf.post(
            "/import/",
            data={
                "file": SimpleUploadedFile("grande.csv", b"x" * 5000, "text/csv"),
                "import_type": "regular",
            },
        )
        request.user = user
        request.household = seeded

        response = ImportUploadView.as_view()(request)
        assert response.status_code == 200
        assert "grande demais" in response.content.decode()
        assert not ImportJob.objects.exists()

    def test_a_non_utf8_file_is_refused_and_the_job_is_discarded(self, logged_client, seeded):
        handle = io.BytesIO("data,valor,descrição\n01/03/2026,42,café\n".encode("latin-1"))
        handle.name = "latin.csv"
        response = logged_client.post("/import/", data={"file": handle, "import_type": "regular"})
        assert response.status_code == 200
        assert "UTF-8" in response.content.decode()
        assert not ImportJob.objects.exists()
