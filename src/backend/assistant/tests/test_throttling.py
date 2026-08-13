"""Rolling-window counting for the assistant throttle.

The window is rolling rather than calendar-bucketed on purpose: a calendar hour
lets a caller spend the whole hourly budget at 10:59 and the whole next budget at
11:00, doubling the real ceiling at exactly the moment that matters.
"""

from datetime import UTC, datetime, timedelta

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from accounts.resolution import household_for_user
from assistant.models import AssistantUsageEvent, AssistantUsageKind
from assistant.throttling import exceeded_rule, rules_for

# Frozen so "N hours ago" is computed from a fixed instant rather than the real
# clock — a rolling-window test that reads the real clock is exactly the
# time-bomb this freeze exists to prevent.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN_NOW, tick=False)


def _burn(user, kind, count, *, age=timedelta(0)):
    """Create ``count`` usage events, backdated by ``age``.

    The event names both its actor and its tenant, and keeps them distinct.
    ``user`` is the *actor*: throttling is per person, so two members of one
    household each get their own budget (epic decision 1), and every call site
    below varies the actor rather than the household. ``household`` is set
    explicitly because Task 12 makes the column NOT NULL and deletes the write
    bridge that used to fill it.
    """
    stamp = timezone.now() - age
    household = household_for_user(user)
    for _ in range(count):
        event = AssistantUsageEvent.objects.create(user=user, household=household, kind=kind)
        AssistantUsageEvent.objects.filter(pk=event.pk).update(created_at=stamp)


@pytest.mark.django_db
class TestRulesFor:
    def test_image_rules_are_tighter_than_text_rules(self, settings):
        text_hourly = rules_for(AssistantUsageKind.TEXT)[0]
        image_hourly = rules_for(AssistantUsageKind.IMAGE)[0]
        assert image_hourly.limit < text_hourly.limit

    def test_rules_read_current_settings(self, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 7
        assert rules_for(AssistantUsageKind.TEXT)[0].limit == 7

    def test_each_kind_has_an_hourly_and_a_daily_rule(self):
        for kind in (AssistantUsageKind.TEXT, AssistantUsageKind.IMAGE):
            windows = {rule.window for rule in rules_for(kind)}
            assert windows == {timedelta(hours=1), timedelta(days=1)}


@pytest.mark.django_db
class TestExceededRule:
    def test_no_usage_is_never_throttled(self, user):
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_under_the_hourly_limit_is_allowed(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 4)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_at_the_hourly_limit_is_blocked(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 5)
        rule = async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT)
        assert rule is not None
        assert rule.limit == 5
        assert rule.label == "hora"

    def test_events_outside_the_window_do_not_count(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 5
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 5, age=timedelta(hours=2))
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_daily_limit_blocks_even_when_hourly_is_clear(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 6
        _burn(user, AssistantUsageKind.TEXT, 6, age=timedelta(hours=5))
        rule = async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT)
        assert rule is not None
        assert rule.label == "dia"

    def test_kinds_have_independent_budgets(self, user, settings):
        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 2
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.IMAGE, 2)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.IMAGE) is not None
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_other_users_usage_does_not_count(self, user, settings):
        from model_bakery import baker

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 2
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        stranger = baker.make("core.CustomUser", username="stranger")
        _burn(stranger, AssistantUsageKind.TEXT, 5)
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None

    def test_event_exactly_at_the_window_edge_still_counts(self, user, settings):
        """The window boundary is inclusive: an event exactly one hour old is
        still "this hour" for a caller who has been active for exactly an
        hour, not a loophole that lets the count reset a moment early.
        """
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 1, age=timedelta(hours=1))
        rule = async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT)
        assert rule is not None
        assert rule.label == "hora"

    def test_event_one_second_past_the_window_edge_does_not_count(self, user, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 1, age=timedelta(hours=1, seconds=1))
        assert async_to_sync(exceeded_rule)(user, AssistantUsageKind.TEXT) is None


@pytest.mark.django_db
class TestChatEndpointThrottle:
    """The endpoint must refuse an over-limit turn before spending anything."""

    def _post_text(self, client, monkeypatch):
        """POST a text turn with ``_sse_response`` replaced by a call recorder.

        Replacing ``_sse_response`` is the cheapest place to prove "zero model
        calls" *for the JSON path*: ``_handle_json`` has exactly one route to a
        model, through ``_sse_response``. This does not hold for the multipart
        path — ``transcribe_audio`` and ``extract_receipt`` reach models directly,
        without going through ``_sse_response`` — so this stub only covers text
        turns. The stub must return a real ``HttpResponse`` — ``_handle_json``
        returns its result straight to Django, which raises on ``None``.
        """
        import json

        from django.http import HttpResponse

        calls = []

        def _stub_sse(*args, **kwargs):
            calls.append("call")
            return HttpResponse("stubbed", content_type="text/event-stream")

        monkeypatch.setattr("assistant.views._sse_response", _stub_sse)
        response = client.post(
            "/api/assistant/chat/",
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        return response, calls

    def test_under_the_limit_reaches_the_model(self, logged_client, user, monkeypatch, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 2)
        response, calls = self._post_text(logged_client, monkeypatch)
        assert response.status_code == 200
        assert len(calls) == 1

    def test_over_the_limit_makes_zero_model_calls(
        self, logged_client, user, monkeypatch, settings
    ):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        response, calls = self._post_text(logged_client, monkeypatch)
        assert response.status_code == 429
        assert calls == []

    def test_rejection_message_is_pt_br_and_names_the_window(
        self, logged_client, user, monkeypatch, settings
    ):
        import json as _json

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        response, _ = self._post_text(logged_client, monkeypatch)
        body = _json.loads(response.content)
        assert "Limite" in body["error"]
        assert "hora" in body["error"]

    def test_rejected_turn_writes_no_chat_message(
        self, logged_client, user, monkeypatch, settings, household
    ):
        from assistant.models import ChatMessage

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        self._post_text(logged_client, monkeypatch)
        assert not ChatMessage.objects.for_household(household).exists()

    def test_admitted_turn_records_one_usage_event(
        self, logged_client, user, monkeypatch, settings
    ):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 10
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        self._post_text(logged_client, monkeypatch)
        assert (
            AssistantUsageEvent.objects.filter(user=user, kind=AssistantUsageKind.TEXT).count() == 1
        )

    def test_rejected_turn_records_no_usage_event(self, logged_client, user, monkeypatch, settings):
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 3
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 3)
        self._post_text(logged_client, monkeypatch)
        assert (
            AssistantUsageEvent.objects.filter(user=user, kind=AssistantUsageKind.TEXT).count() == 3
        )

    def test_image_turn_spends_the_image_budget_not_the_text_one(
        self, logged_client, user, monkeypatch, settings
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        _burn(user, AssistantUsageKind.IMAGE, 1)

        calls = []

        async def _stub_multipart(*args, **kwargs):
            # async, because chat_view awaits it — a plain lambda would raise a
            # confusing TypeError instead of failing this test cleanly.
            from django.http import HttpResponse

            calls.append("call")
            return HttpResponse("stubbed", content_type="text/event-stream")

        monkeypatch.setattr("assistant.views._handle_multipart", _stub_multipart)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
            b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
            b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("recibo.png", png, content_type="image/png")
        response = logged_client.post("/api/assistant/chat/", data={"image": image})
        assert response.status_code == 429
        assert calls == []
        assert "fotos" in response.content.decode()

    def test_audio_turn_spends_the_text_budget(self, logged_client, user, monkeypatch, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR = 1
        settings.ASSISTANT_THROTTLE_TEXT_PER_DAY = 100
        settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR = 100
        settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY = 100
        _burn(user, AssistantUsageKind.TEXT, 1)

        calls = []

        async def _stub_multipart(*args, **kwargs):
            # Stubbed so a regression that lets this turn through cannot reach
            # transcribe_audio, which would make a real outbound call to
            # api.openai.com with whatever credentials the environment holds.
            from django.http import HttpResponse

            calls.append("call")
            return HttpResponse("stubbed", content_type="text/event-stream")

        monkeypatch.setattr("assistant.views._handle_multipart", _stub_multipart)
        audio = SimpleUploadedFile("nota.webm", b"\x00\x01\x02", content_type="audio/webm")
        response = logged_client.post("/api/assistant/chat/", data={"audio": audio})
        assert response.status_code == 429
        assert calls == []


@pytest.mark.django_db
def test_an_admitted_turn_records_its_household(user, household):
    """The usage event is household-owned even though it counts per person.

    Written against the still-present write bridge on purpose: the assertion is
    that `throttle_denial` names the tenant itself, not that something else
    fills it in. E04 decision 1 keeps `user` here — the throttle counts per
    person, so two members of one household each get their own budget.
    """
    from assistant.agents.scope import AgentScope
    from assistant.views import throttle_denial

    scope = AgentScope(household=household, user=user)

    assert async_to_sync(throttle_denial)(scope, AssistantUsageKind.TEXT) is None

    event = AssistantUsageEvent.objects.get(user=user)
    assert event.household == household
