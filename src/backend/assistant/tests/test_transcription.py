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
