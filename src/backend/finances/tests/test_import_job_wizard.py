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


@pytest.mark.django_db
class TestThePreviewFormsDoNotClobberEachOther:
    """Review finding 2. `_step_preview.html` posts three separate forms to the
    same URL — categories, payment methods, and the skip checkboxes. Each one
    carries only its own fields, so a handler that reassigns all three pieces
    of state on every POST erases whatever the user did last.
    """

    @pytest.fixture
    def mapped_job(self, logged_client, seeded):
        _upload(logged_client)
        job = ImportJob.objects.for_household(seeded).get()
        logged_client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        return job

    def test_resolving_a_payment_method_keeps_the_category_resolution(
        self, logged_client, mapped_job
    ):
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "categories", "cat_resolve_Farmácia": "__new__"},
        )
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "payment_methods", "pm_resolve_Nubank": "__new__"},
        )
        mapped_job.refresh_from_db()

        assert mapped_job.category_resolutions == {"Farmácia": "__new__"}
        assert mapped_job.pm_resolutions == {"Nubank": "__new__"}

    def test_ticking_skips_keeps_both_resolutions(self, logged_client, mapped_job):
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "categories", "cat_resolve_Farmácia": "__new__"},
        )
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "skips", "skip_3": "on"},
        )
        mapped_job.refresh_from_db()

        assert mapped_job.category_resolutions == {"Farmácia": "__new__"}
        assert mapped_job.skip_lines == [3]

    def test_resolving_a_category_does_not_clear_the_skips(self, logged_client, mapped_job):
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "skips", "skip_2": "on", "skip_3": "on"},
        )
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "categories", "cat_resolve_Farmácia": "__new__"},
        )
        mapped_job.refresh_from_db()

        assert mapped_job.skip_lines == [2, 3]
        assert mapped_job.category_resolutions == {"Farmácia": "__new__"}

    def test_unticking_every_box_still_clears_the_skips(self, logged_client, mapped_job):
        """An empty skip form means "none", not "leave it alone" — otherwise a
        box could be ticked but never unticked."""
        logged_client.post(
            f"/import/{mapped_job.id}/preview/",
            data={"form_section": "skips", "skip_2": "on"},
        )
        logged_client.post(f"/import/{mapped_job.id}/preview/", data={"form_section": "skips"})
        mapped_job.refresh_from_db()

        assert mapped_job.skip_lines == []


@pytest.mark.django_db
class TestARejectedUploadLeavesNothingBehind:
    def test_a_non_utf8_upload_does_not_orphan_its_object(self, logged_client, seeded, settings):
        """Review finding 5. The file is stored before the header is read, so
        the rejection path has to remove it — otherwise a user re-exporting a
        Latin-1 file three times leaves three copies of their financial data in
        the bucket, referenced by no row, for the seven days the lifecycle rule
        takes to notice.
        """
        from core.storage import job_storage

        root = settings.JOB_STORAGE_ROOT
        before = {str(p) for p in root.rglob("*.csv")} if root.exists() else set()

        handle = io.BytesIO("data,valor,descrição\n01/03/2026,42,café\n".encode("latin-1"))
        handle.name = "latin.csv"
        response = logged_client.post("/import/", data={"file": handle, "import_type": "regular"})

        assert response.status_code == 200
        assert not ImportJob.objects.exists()
        after = {str(p) for p in root.rglob("*.csv")} if root.exists() else set()
        assert after == before, "the rejected upload was left in storage"
        assert job_storage() is not None
