"""Beta feedback: easy to send, scoped, and never silently dropped."""

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db

URL = "/feedback/"


@pytest.fixture
def member(client, django_user_model):
    user = baker.make(django_user_model, username="familia")
    household = baker.make(Household, name="Casa de teste")
    baker.make(Membership, household=household, user=user, role=Role.OWNER)
    client.force_login(user)
    return user, household


def test_a_user_can_send_feedback(client, member):
    from core.models import Feedback

    user, household = member

    response = client.post(URL, {"message": "A foto do cupom não leu o desconto."})

    assert response.status_code in (200, 204, 302)
    row = Feedback.objects.get()
    assert row.household == household
    assert row.user == user
    assert "desconto" in row.message


def test_empty_feedback_is_rejected_rather_than_stored(client, member):
    from core.models import Feedback

    response = client.post(URL, {"message": "   "})

    assert Feedback.objects.count() == 0
    assert response.status_code in (200, 400)


def test_feedback_is_capped_in_length(client, member):
    """A 2 MB paste is not feedback. The cap is a storage bound, not a judgement."""
    from core.models import Feedback

    client.post(URL, {"message": "x" * 10_000})

    row = Feedback.objects.get()
    assert len(row.message) <= 4000


def test_anonymous_visitors_cannot_post(client):
    from core.models import Feedback

    client.post(URL, {"message": "olá"})

    assert Feedback.objects.count() == 0


def test_where_they_were_is_recorded_and_nothing_they_typed_elsewhere(client, member):
    """`context` exists so a report is actionable. It carries the path, and
    never anything the user wrote on another screen."""
    from core.models import Feedback

    client.post(URL, {"message": "o gráfico não bate"}, HTTP_REFERER="http://testserver/entries/")

    row = Feedback.objects.get()
    assert "/entries/" in row.context["path"]
    assert set(row.context) == {"path"}


def test_the_neighbours_feedback_is_not_visible(client, member, django_user_model):
    """The scoping test this codebase requires of every write: a row lands in the
    sender's household and is invisible from another."""
    from core.models import Feedback

    _, household = member
    other = baker.make(Household, name="Casa alheia")

    client.post(URL, {"message": "só nossa"})

    assert Feedback.objects.for_household(household).count() == 1
    assert Feedback.objects.for_household(other).count() == 0
