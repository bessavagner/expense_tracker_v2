from types import SimpleNamespace

import pytest

from assistant.services.transcription import transcribe_audio


class _FakeTranscriptions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text="  mercado 80 no pix  ")


class _FakeAudio:
    def __init__(self):
        self.transcriptions = _FakeTranscriptions()


class _FakeClient:
    def __init__(self):
        self.audio = _FakeAudio()


@pytest.mark.anyio
async def test_transcribe_returns_stripped_text():
    client = _FakeClient()
    text = await transcribe_audio(
        b"\x00\x01", "nota.webm", "audio/webm", client=client
    )
    assert text == "mercado 80 no pix"


@pytest.mark.anyio
async def test_transcribe_passes_model_and_language(settings):
    settings.LLM_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
    client = _FakeClient()
    await transcribe_audio(b"\x00", "nota.webm", "audio/webm", client=client)
    kwargs = client.audio.transcriptions.kwargs
    assert kwargs["model"] == "gpt-4o-mini-transcribe"
    assert kwargs["language"] == "pt"
    assert kwargs["file"] == ("nota.webm", b"\x00", "audio/webm")


class _FallbackTranscriptions:
    """Raises for a given model, succeeds for any other; records models tried."""

    def __init__(self, fail_model):
        self.fail_model = fail_model
        self.models_tried = []

    async def create(self, **kwargs):
        model = kwargs["model"]
        self.models_tried.append(model)
        if model == self.fail_model:
            raise RuntimeError("Audio file might be corrupted or unsupported")
        return SimpleNamespace(text="mercado 80 no pix")


class _FallbackClient:
    def __init__(self, fail_model):
        self.audio = SimpleNamespace(transcriptions=_FallbackTranscriptions(fail_model))


@pytest.mark.anyio
async def test_transcribe_falls_back_when_primary_model_fails(settings):
    settings.LLM_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
    settings.LLM_TRANSCRIBE_FALLBACK_MODEL = "whisper-1"
    client = _FallbackClient(fail_model="gpt-4o-mini-transcribe")
    text = await transcribe_audio(b"\x00\x01", "nota.webm", "audio/webm", client=client)
    assert text == "mercado 80 no pix"
    assert client.audio.transcriptions.models_tried == [
        "gpt-4o-mini-transcribe",
        "whisper-1",
    ]


class _AlwaysFailTranscriptions:
    async def create(self, **kwargs):
        raise RuntimeError("Audio file might be corrupted or unsupported")


@pytest.mark.anyio
async def test_transcribe_raises_when_all_models_fail(settings):
    settings.LLM_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
    settings.LLM_TRANSCRIBE_FALLBACK_MODEL = "whisper-1"
    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=_AlwaysFailTranscriptions())
    )
    with pytest.raises(RuntimeError):
        await transcribe_audio(b"\x00", "nota.webm", "audio/webm", client=client)
