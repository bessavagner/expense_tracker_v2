"""The guided setup end to end: three steps, all skippable, ending at the wedge."""

import pytest
from django.urls import reverse

from accounts.models import OnboardingState, OnboardingStep
from core.events import EventName
from core.models import ProductEvent
from finances.models import Income, PaymentMethod


@pytest.mark.django_db
class TestTheFlow:
    def test_it_opens_on_the_income_step(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.get(reverse("onboarding"))

        assert response.status_code == 200
        assertion = response.content.decode()
        assert "Quanto entra por mês" in assertion

    def test_submitting_income_records_it_and_advances(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.post(
            reverse("onboarding_step", args=[OnboardingStep.INCOME]),
            {"name": "Salário", "amount": "4500.00"},
        )

        assert response.status_code == 302
        assert Income.objects.for_household(household).get().amount == 4500
        assert OnboardingState.for_household(household).next_step() == OnboardingStep.CARDS

    def test_submitting_a_card_records_its_closing_day(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        logged_client.post(
            reverse("onboarding_step", args=[OnboardingStep.CARDS]),
            {"name": "Nubank", "closing_day": "25"},
        )

        card = PaymentMethod.objects.for_household(household).get(name="Nubank")
        assert card.type == "credit_card"
        assert card.closing_day == 25

    def test_the_last_step_hands_the_user_to_the_chat_not_the_dashboard(
        self, logged_client, household
    ):
        OnboardingState.objects.filter(household=household).delete()
        state = OnboardingState.for_household(household)
        state.mark(OnboardingStep.INCOME)
        state.mark(OnboardingStep.CARDS)

        response = logged_client.post(reverse("onboarding_step", args=[OnboardingStep.CAPTURE]))

        assert response["Location"] == "/?comecar=foto"


@pytest.mark.django_db
class TestSkipping:
    @pytest.mark.parametrize("step", list(OnboardingStep))
    def test_every_step_can_be_skipped(self, logged_client, household, step):
        OnboardingState.objects.filter(household=household).delete()

        response = logged_client.post(reverse("onboarding_skip", args=[step]))

        assert response.status_code == 302
        assert step.value in OnboardingState.for_household(household).steps_done

    def test_skipping_everything_leaves_a_working_product(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        for step in OnboardingStep:
            logged_client.post(reverse("onboarding_skip", args=[step]))

        assert logged_client.get("/").status_code == 200
        assert Income.objects.for_household(household).count() == 0


@pytest.mark.django_db
class TestResumability:
    def test_an_interrupted_setup_resumes_where_it_stopped(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        logged_client.post(reverse("onboarding_skip", args=[OnboardingStep.INCOME]))

        response = logged_client.get(reverse("onboarding"))

        assert "fecha a fatura" in response.content.decode()


@pytest.mark.django_db
class TestCopy:
    def test_the_closing_day_is_explained_in_one_sentence(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        OnboardingState.for_household(household).mark(OnboardingStep.INCOME)

        body = logged_client.get(reverse("onboarding")).content.decode()

        assert "fecha a fatura" in body
        assert "mês seguinte" in body

    def test_the_importer_is_offered_during_setup_and_marked_optional(
        self, logged_client, household
    ):
        OnboardingState.objects.filter(household=household).delete()

        body = logged_client.get(reverse("onboarding")).content.decode()

        assert reverse("finances:import_upload") in body
        assert "opcional" in body.lower()


@pytest.mark.django_db
class TestInstrumentation:
    def test_each_step_emits_an_event_with_its_outcome(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()

        logged_client.post(reverse("onboarding_skip", args=[OnboardingStep.INCOME]))

        event = ProductEvent.objects.for_household(household).get(name=EventName.ONBOARDING_STEP)
        assert event.metadata == {"step": "income", "action": "skipped"}

    def test_finishing_emits_onboarding_done_once(self, logged_client, household):
        OnboardingState.objects.filter(household=household).delete()
        for step in OnboardingStep:
            logged_client.post(reverse("onboarding_skip", args=[step]))

        assert (
            ProductEvent.objects.for_household(household)
            .filter(name=EventName.ONBOARDING_DONE)
            .count()
            == 1
        )
