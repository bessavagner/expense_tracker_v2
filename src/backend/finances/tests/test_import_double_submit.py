"""A double-tapped "Importar" must not import the file twice.

Found 2026-08-09 by double-tapping the real button in a browser against the dev
server: a 4000-row CSV produced 8000 rows and the result page still reported
"Importados 4000". The importer's four steps are plain ``<form method="post">``,
so htmx's in-flight drop — which does cover the app's other 18 POST forms — does
not apply to them.

The race is on the session: ``ImportExecuteView`` reads the row list from
``request.session`` and only clears it once every row is written, and Django
saves the session at *response* time. A second POST that arrives mid-import
therefore reads the same rows and imports the whole file again.

These tests run with ``transaction=True`` because the point is what two real,
concurrently committing connections do to each other; the default
transaction-wrapped fixture would hide exactly the effect under test.
"""

import io
import threading

import pytest
from django.db import connections
from django.test import Client
from model_bakery import baker

from accounts.resolution import household_for_user
from finances.models import Entry
from finances.views import importer as importer_views

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


def _walk_to_preview(client, household):
    """Upload and map ``_CSV`` so the session holds a ready-to-execute batch."""
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    csv_file = io.BytesIO(_CSV)
    csv_file.name = "test.csv"
    client.post("/import/", data={"file": csv_file, "import_type": "regular"})
    client.post("/import/map/", data=_MAPPING)


def _client_sharing_session_with(client):
    """A second client acting as a second tab/tap of the same logged-in session."""
    twin = Client()
    twin.cookies.update(client.cookies)
    return twin


@pytest.fixture
def stall_first_row(monkeypatch):
    """Hold the first import inside its transaction until released.

    Patches the per-row billing computation so the *first* row of the *first*
    request blocks. That puts the request inside its atomic block, past whatever
    guard the view has, with its row lock held — which is precisely the window a
    second tap lands in. Later rows and the second request run at full speed.
    """
    entered = threading.Event()
    release = threading.Event()
    seen = threading.Lock()
    stalled = []
    original = importer_views.compute_billing_month

    def stalling_compute(*args, **kwargs):
        with seen:
            first = not stalled
            if first:
                stalled.append(True)
        if first:
            entered.set()
            release.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(importer_views, "compute_billing_month", stalling_compute)
    yield entered, release
    release.set()


def _post_execute(client, results, key):
    """Run one execute POST on this thread's own DB connection.

    Closing it matters: a connection left open on a dead thread keeps a session
    on the test database and makes the suite's final teardown fail to drop it.
    """
    try:
        results[key] = client.post("/import/execute/")
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_two_overlapping_executes_import_the_file_once(stall_first_row):
    entered, release = stall_first_row
    user = baker.make("core.CustomUser", username="vagner")
    household = household_for_user(user)
    first = Client()
    first.force_login(user)
    _walk_to_preview(first, household)
    second = _client_sharing_session_with(first)

    results = {}
    thread_one = threading.Thread(target=_post_execute, args=(first, results, "first"))
    thread_two = threading.Thread(target=_post_execute, args=(second, results, "second"))

    thread_one.start()
    assert entered.wait(timeout=10), "the first import never reached its first row"

    # The second tap lands while the first is still inserting.
    thread_two.start()
    thread_two.join(timeout=2)
    assert thread_two.is_alive(), (
        "the second POST returned while the first still held the batch — it was "
        "not serialised against it, so this test would prove nothing"
    )

    release.set()
    thread_one.join(timeout=15)
    thread_two.join(timeout=15)
    assert not thread_one.is_alive() and not thread_two.is_alive()

    assert Entry.objects.for_household(household).count() == 2, (
        "the file was imported more than once"
    )
    assert results["first"].status_code == 200
    assert results["second"].status_code == 200
    # The loser renders the winner's numbers: the user is waiting on this
    # response, and "0 importados" would read as a failed import.
    assert results["second"].context["created_count"] == 2


@pytest.mark.django_db(transaction=True)
def test_replayed_execute_reports_the_first_run_instead_of_importing_again():
    """Sequential replay — a reload, a back-then-forward, a retried request.

    Distinct from the concurrent case: here the first import has fully finished
    and cleared the session, so this is about what the *second* request tells
    the user. It must not import again, and it must not claim zero.
    """
    user = baker.make("core.CustomUser", username="vagner")
    household = household_for_user(user)
    client = Client()
    client.force_login(user)
    _walk_to_preview(client, household)
    session_before = client.session["import_data"]

    first = client.post("/import/execute/")
    assert first.status_code == 200
    assert Entry.objects.for_household(household).count() == 2

    # Put the batch back the way the browser's own re-POST would find it if the
    # session had not yet been written — the token is what must stop it.
    session = client.session
    session["import_data"] = session_before
    session.save()

    second = client.post("/import/execute/")
    assert Entry.objects.for_household(household).count() == 2, "the replay imported again"
    assert second.status_code == 200
    assert second.context["created_count"] == 2, "the replay under-reported the import"


@pytest.mark.django_db
def test_entry_has_no_unique_constraint_on_its_natural_key():
    """Documents why the fix is a token and not a database constraint.

    Production holds two genuine R$ 20 fuel purchases on the same day with the
    same description; a ``UniqueConstraint`` on (user, date, amount,
    description) would reject the family's real data. If this test ever starts
    failing because someone added that constraint, read Finding 5 in
    ``.superpowers/sdd/HANDOFF-login-and-double-submit.md`` first.
    """
    constrained = {tuple(sorted(c.fields)) for c in Entry._meta.constraints if hasattr(c, "fields")}
    assert tuple(sorted(["user", "date", "amount", "description"])) not in constrained
